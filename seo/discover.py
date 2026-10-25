#!/usr/bin/env python3
"""Find what to write next and what to improve, from real search data.

Sources (each optional; missing credentials just skip that source):
  - Bing Webmaster keyword research (BING_WEBMASTER_API_KEY): related queries
    with monthly impressions for our seed topics, per market.
  - Google Search Console (GSC_SERVICE_ACCOUNT_JSON): what we already show up
    for, and pages ranking on page 2-3 that a rewrite could push up.

Output:
  - new keyword rows (status 'planned', with impressions and related queries)
    in data/keywords.json, after Claude groups queries into pages so related
    searches share one strong page instead of many thin ones;
  - data/opportunities.json with refresh targets for the autopilot.

  python3 seo/discover.py [--dry-run]
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://cryptocasinolist.io/"
GSC_PROPERTY = os.environ.get("GSC_PROPERTY", "sc-domain:cryptocasinolist.io")
MARKETS = [("us", "en-US", "en"), ("gb", "en-GB", "en"), ("ru", "ru-RU", "ru"), ("br", "pt-BR", "pt"), ("es", "es-ES", "es")]
SEEDS = {
    "en": ["crypto casino", "bitcoin casino", "crypto casino bonus", "no kyc casino", "usdt casino",
           "provably fair", "crash gambling", "stake alternative", "crypto gambling", "plinko", "mines game"],
    "ru": ["крипто казино", "биткоин казино", "казино без верификации", "краш игра"],
    "pt": ["cassino cripto", "cassino bitcoin", "crash aposta"],
    "es": ["casino cripto", "casino bitcoin", "juego crash"],
}
RELEVANT = re.compile(r"casino|cassino|казино|gambl|bet|slot|crash|plinko|mines|dice|limbo|keno|poker|roulette|blackjack|"
                      r"bonus|bônus|бонус|kyc|provably|stake|usdt|bitcoin|btc|crypto|cripto|крипто|wager|rtp|jackpot", re.I)


def load_json(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(os.path.join(ROOT, path), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ── Bing ────────────────────────────────────────────────────────────────────

def bing_related(key, q, country, language):
    end = datetime.date.today() - datetime.timedelta(days=3)
    start = end - datetime.timedelta(days=30)
    params = urllib.parse.urlencode({"apikey": key, "q": q, "country": country, "language": language,
                                     "startDate": start.isoformat(), "endDate": end.isoformat()})
    url = f"https://ssl.bing.com/webmaster/api.svc/json/GetRelatedKeywords?{params}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Content-Type": "application/json"}), timeout=30) as r:
        return json.load(r).get("d") or []


def from_bing():
    key = os.environ.get("BING_WEBMASTER_API_KEY")
    if not key:
        print("bing: no BING_WEBMASTER_API_KEY, skipped")
        return []
    found = {}
    for country, language, lang in MARKETS:
        for seed in SEEDS[lang]:
            try:
                rows = bing_related(key, seed, country, language)
            except Exception as e:  # noqa: BLE001 - one bad market must not stop the run
                print(f"bing: {seed!r} {country}: {type(e).__name__} {e}")
                continue
            for r in rows:
                q = (r.get("Query") or "").strip().lower()
                imp = int(r.get("Impressions") or r.get("BroadImpressions") or 0)
                if q and RELEVANT.search(q):
                    k = (q, lang)
                    found[k] = max(found.get(k, 0), imp)
    print(f"bing: {len(found)} relevant queries")
    return [{"q": q, "lang": lang, "impressions": imp, "source": "bing"} for (q, lang), imp in found.items()]


# ── Google Search Console ──────────────────────────────────────────────────

def gsc_rows():
    raw = os.environ.get("GSC_SERVICE_ACCOUNT_JSON")
    if not raw:
        print("gsc: no GSC_SERVICE_ACCOUNT_JSON, skipped")
        return []
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    creds = service_account.Credentials.from_service_account_info(
        json.loads(raw), scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
    end = datetime.date.today() - datetime.timedelta(days=3)
    body = {"startDate": (end - datetime.timedelta(days=28)).isoformat(), "endDate": end.isoformat(),
            "dimensions": ["query", "page"], "rowLimit": 5000}
    url = f"https://www.googleapis.com/webmasters/v3/sites/{urllib.parse.quote(GSC_PROPERTY, safe='')}/searchAnalytics/query"
    resp = AuthorizedSession(creds).post(url, json=body, timeout=60)
    resp.raise_for_status()
    rows = resp.json().get("rows", [])
    print(f"gsc: {len(rows)} query/page rows")
    return [{"q": r["keys"][0], "page": r["keys"][1], "impressions": r["impressions"], "clicks": r["clicks"],
             "position": r["position"]} for r in rows]


def refresh_targets(rows, manifest):
    """Pages on positions 5-30 with real impressions: the cheapest traffic to win."""
    by_url = {p["url"]: p for p in manifest["pages"]}
    agg = {}
    for r in rows:
        if 5 <= r["position"] <= 30 and r["page"] in by_url:
            a = agg.setdefault(r["page"], {"impressions": 0, "queries": []})
            a["impressions"] += r["impressions"]
            a["queries"].append(f"{r['q']} (pos {r['position']:.0f}, {r['impressions']} impr.)")
    out = []
    for url, a in sorted(agg.items(), key=lambda kv: -kv[1]["impressions"]):
        if a["impressions"] >= 20:
            out.append({"file": by_url[url]["file"], "impressions": a["impressions"],
                        "reason": "ranks on page 2-3 for: " + "; ".join(a["queries"][:8])})
    return out


# ── Grouping new queries into pages ─────────────────────────────────────────

TRIAGE_SYSTEM = """You plan pages for cryptocasinolist.io, a crypto casino comparison and guides site (EN, RU, PT, ES).
Group the candidate search queries into pages. One page per distinct search intent; near-duplicates and
reformulations go into the same page as 'related'. Prefer extending an existing page (merge_into) when it already
covers the intent. Drop queries that are navigational for another brand's login, illegal, about sports betting
odds (we have no sportsbook), adult, or would need facts we cannot verify (e.g. a named casino we do not list,
country-specific law). Slugs: lowercase, hyphens, prefixed by language for non-English (ru/, pt/, es/), with
guides/ for how-to and explainer topics and compare/ for X vs Y."""

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {"pages": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "q": {"type": "string"}, "lang": {"type": "string"}, "slug": {"type": "string"},
            "tier": {"type": "string", "enum": ["head", "mid", "long"]},
            "merge_into": {"type": "string"}, "related": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["q", "lang", "slug", "tier", "merge_into", "related"],
        "additionalProperties": False}}},
    "required": ["pages"], "additionalProperties": False,
}


def triage(candidates, keywords, pages):
    known = {k["q"].lower() for k in keywords["keywords"]}
    fresh = [c for c in candidates if c["q"].lower() not in known]
    fresh.sort(key=lambda c: -c.get("impressions", 0))
    fresh = fresh[:150]
    if not fresh:
        return [], []
    listing = "\n".join(f"{c['q']} [{c['lang']}] {c.get('impressions', '?')} impr." for c in fresh)
    existing = "\n".join(f"/{s}/ - {t}" for _, s, t in pages)
    result = llm.call(TRIAGE_SYSTEM, ["Existing pages:\n" + existing,
                                      "Candidate queries (impressions are monthly):\n" + listing + "\n\nGroup them."],
                      effort="medium", schema=TRIAGE_SCHEMA, max_tokens=32000)
    imp = {c["q"].lower(): c.get("impressions", 0) for c in fresh}
    new_rows, merges = [], []
    have_slugs = {k["slug"] for k in keywords["keywords"]} | {s for _, s, _ in pages}
    for p in result["pages"]:
        total = imp.get(p["q"].lower(), 0) + sum(imp.get(r.lower(), 0) for r in p["related"])
        if p["merge_into"]:
            merges.append({"slug": p["merge_into"].strip("/"), "queries": [p["q"]] + p["related"], "impressions": total})
        elif p["slug"].strip("/") not in have_slugs:
            new_rows.append({"q": p["q"], "lang": p["lang"], "tier": p["tier"], "slug": p["slug"].strip("/"),
                             "status": "planned", "priority": 40, "impressions": total, "related": p["related"],
                             "found": datetime.date.today().isoformat()})
    return new_rows, merges


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from draft import existing_pages
    keywords = load_json("data/keywords.json")
    pages = existing_pages()
    manifest = load_json("build-manifest.json")

    gsc = gsc_rows()
    candidates = from_bing() + [{"q": r["q"], "lang": "en", "impressions": r["impressions"], "source": "gsc"}
                                for r in gsc if r["position"] > 10]
    new_rows, merges = triage(candidates, keywords, pages) if candidates else ([], [])

    by_file = {p["slug"]: p["file"] for p in manifest["pages"]}
    opportunities = {"updated": datetime.date.today().isoformat(), "refresh": refresh_targets(gsc, manifest)}
    for m in merges:
        if m["slug"] in by_file:
            opportunities["refresh"].append({"file": by_file[m["slug"]], "impressions": m["impressions"],
                                             "reason": "also cover these searches: " + "; ".join(m["queries"][:10])})
    print(f"discover: {len(new_rows)} new page ideas, {len(opportunities['refresh'])} refresh targets")
    for r in new_rows[:10]:
        print(f"  + {r['q']} [{r['lang']}] -> /{r['slug']}/ ({r['impressions']} impr.)")
    if args.dry_run:
        return
    keywords["keywords"].extend(new_rows)
    save_json("data/keywords.json", keywords)
    save_json("data/opportunities.json", opportunities)


if __name__ == "__main__":
    main()
