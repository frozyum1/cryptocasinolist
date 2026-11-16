#!/usr/bin/env python3
"""What the site actually earns in search, so the autopilot is judged on results, not page counts.

Each snapshot records, from the sources whose credentials are present:
  - Google Search Console: clicks, impressions, CTR and average position for the last 28 days,
    the top queries and pages, whether the sitemap is submitted, and how many pages Google has
    indexed (URL Inspection API, one call per page).
  - Bing Webmaster: clicks and impressions for the last 28 days and the top queries.

Snapshots are appended to data/metrics.json (one per week is enough) and the weekly report
prints the latest one next to the previous one. A missing credential or a failing API call
skips that source and is noted in the snapshot; it never stops the autopilot.

  python3 seo/metrics.py            # print a snapshot, write nothing
  python3 seo/metrics.py --save     # also append it to data/metrics.json

API shapes checked 2026-11-16 against:
  https://developers.google.com/webmaster-tools/v1/searchanalytics/query
  https://developers.google.com/webmaster-tools/v1/urlInspection.index/inspect  (webmasters.readonly is enough)
  https://developers.google.com/webmaster-tools/v1/sitemaps/submit              (needs the full webmasters scope)
  https://learn.microsoft.com/en-us/dotnet/api/microsoft.bing.webmaster.api.interfaces.iwebmasterapi.getrankandtrafficstats
"""
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://cryptocasinolist.io/"
SITEMAP = SITE + "sitemap.xml"
GSC_PROPERTY = os.environ.get("GSC_PROPERTY", "sc-domain:cryptocasinolist.io")
GSC_API = "https://www.googleapis.com/webmasters/v3/sites/"
INSPECT_API = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
BING_API = "https://ssl.bing.com/webmaster/api.svc/json/"
WINDOW_DAYS = 28
SNAPSHOT_EVERY_DAYS = 7
HISTORY = "data/metrics.json"
KEEP_SNAPSHOTS = 104  # two years of weekly rows


# ── Google Search Console ──────────────────────────────────────────────────

def _gsc_session(scope="webmasters.readonly"):
    raw = os.environ.get("GSC_SERVICE_ACCOUNT_JSON")
    if not raw:
        return None
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    creds = service_account.Credentials.from_service_account_info(
        json.loads(raw), scopes=["https://www.googleapis.com/auth/" + scope])
    return AuthorizedSession(creds)


def _site_path():
    return GSC_API + urllib.parse.quote(GSC_PROPERTY, safe="")


def _gsc_query(session, dimensions, limit, today):
    end = today - datetime.timedelta(days=3)  # Search Console data lags about three days
    body = {"startDate": (end - datetime.timedelta(days=WINDOW_DAYS)).isoformat(), "endDate": end.isoformat(),
            "dimensions": dimensions, "rowLimit": limit}
    resp = session.post(_site_path() + "/searchAnalytics/query", json=body, timeout=60)
    resp.raise_for_status()
    return resp.json().get("rows", [])


def gsc_performance(session, today):
    total = (_gsc_query(session, [], 1, today) or [{}])[0]
    out = {"clicks": int(total.get("clicks", 0)), "impressions": int(total.get("impressions", 0)),
           "ctr": round(total.get("ctr", 0.0), 4), "position": round(total.get("position", 0.0), 1)}
    for name, dim in (("queries", "query"), ("pages", "page")):
        rows = sorted(_gsc_query(session, [dim], 25, today), key=lambda r: -r.get("impressions", 0))[:10]
        out[name] = [{"key": r["keys"][0].replace(SITE.rstrip("/"), "") if dim == "page" else r["keys"][0],
                      "clicks": int(r.get("clicks", 0)), "impressions": int(r.get("impressions", 0)),
                      "position": round(r.get("position", 0.0), 1)} for r in rows]
    return out


def gsc_sitemap(session):
    """'submitted', 'submitted now', or the reason it is not. Google never learns of new pages from IndexNow."""
    resp = session.get(_site_path() + "/sitemaps", timeout=60)
    resp.raise_for_status()
    if any(s.get("path") == SITEMAP for s in resp.json().get("sitemap", [])):
        return "submitted"
    try:  # submitting needs the full scope and at least "Full" permission on the property
        full = _gsc_session("webmasters")
        r = full.put(_site_path() + "/sitemaps/" + urllib.parse.quote(SITEMAP, safe=""), timeout=60)
        r.raise_for_status()
        return "submitted now"
    except Exception as e:  # noqa: BLE001
        return "NOT submitted (could not submit it: %s)" % type(e).__name__


def summarise_index(results):
    """results: [(path, coverageState, verdict)] -> counts and the pages Google has not indexed."""
    indexed = [p for p, _, verdict in results if verdict == "PASS"]
    states = {}
    for _, state, _ in results:
        states[state] = states.get(state, 0) + 1
    return {"checked": len(results), "indexed": len(indexed), "states": states,
            "not_indexed": sorted(p for p, _, verdict in results if verdict != "PASS")[:60]}


def gsc_index(session, urls):
    results = []
    for url in urls:
        try:
            resp = session.post(INSPECT_API, json={"inspectionUrl": url, "siteUrl": GSC_PROPERTY}, timeout=60)
            resp.raise_for_status()
            status = resp.json().get("inspectionResult", {}).get("indexStatusResult", {})
            results.append((url.replace(SITE.rstrip("/"), ""), status.get("coverageState") or "unknown",
                            status.get("verdict") or "unknown"))
        except Exception as e:  # noqa: BLE001 - one page failing must not lose the rest
            results.append((url.replace(SITE.rstrip("/"), ""), "inspection failed: " + type(e).__name__, "unknown"))
    return summarise_index(results)


# ── Bing Webmaster ─────────────────────────────────────────────────────────

def _bing(method, key, **params):
    params.update(apikey=key, siteUrl=SITE)
    req = urllib.request.Request(BING_API + method + "?" + urllib.parse.urlencode(params),
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("d") or []


def bing_date(value):
    """Bing dates look like '/Date(1316156400000-0700)/'."""
    m = re.search(r"\((-?\d+)", str(value))
    return datetime.datetime.utcfromtimestamp(int(m.group(1)) / 1000).date() if m else None


def summarise_bing(traffic, queries, today):
    since = today - datetime.timedelta(days=WINDOW_DAYS)
    recent = [r for r in traffic if (bing_date(r.get("Date")) or datetime.date.min) >= since]
    agg = {}
    for r in queries:
        if (bing_date(r.get("Date")) or today) < since:
            continue
        q = (r.get("Query") or "").strip().lower()
        if not q:
            continue
        a = agg.setdefault(q, {"key": q, "clicks": 0, "impressions": 0, "position": None})
        a["clicks"] += int(r.get("Clicks") or 0)
        a["impressions"] += int(r.get("Impressions") or 0)
        pos = r.get("AvgImpressionPosition")
        if pos and pos > 0:
            a["position"] = round(min(a["position"] or pos, pos), 1)
    return {"clicks": sum(int(r.get("Clicks") or 0) for r in recent),
            "impressions": sum(int(r.get("Impressions") or 0) for r in recent),
            "queries": sorted(agg.values(), key=lambda a: -a["impressions"])[:10]}


def bing_performance(key, today):
    return summarise_bing(_bing("GetRankAndTrafficStats", key), _bing("GetQueryStats", key), today)


# ── Snapshots ──────────────────────────────────────────────────────────────

def collect(manifest, today=None):
    today = today or datetime.date.today()
    snap = {"date": today.isoformat(), "window_days": WINDOW_DAYS,
            "pages": sum(1 for p in manifest["pages"] if p["indexable"])}
    notes = []
    session = None
    try:
        session = _gsc_session()
    except Exception as e:  # noqa: BLE001
        notes.append("google: credentials unusable (%s)" % type(e).__name__)
    if session is None and not notes:
        notes.append("google: no GSC_SERVICE_ACCOUNT_JSON")
    if session is not None:
        for name, fn in (("google", lambda: gsc_performance(session, today)),
                         ("sitemap", lambda: gsc_sitemap(session)),
                         ("index", lambda: gsc_index(session, [p["url"] for p in manifest["pages"] if p["indexable"]]))):
            try:
                snap[name] = fn()
            except Exception as e:  # noqa: BLE001
                notes.append("%s: %s %s" % (name, type(e).__name__, str(e)[:160]))
    key = os.environ.get("BING_WEBMASTER_API_KEY")
    if not key:
        notes.append("bing: no BING_WEBMASTER_API_KEY")
    else:
        try:
            snap["bing"] = bing_performance(key, today)
        except Exception as e:  # noqa: BLE001
            notes.append("bing: %s %s" % (type(e).__name__, str(e)[:160].replace(key, "***")))
    if notes:
        snap["notes"] = notes
    return snap


def due(history, today=None):
    today = today or datetime.date.today()
    if not history:
        return True
    return (today - datetime.date.fromisoformat(history[-1]["date"])).days >= SNAPSHOT_EVERY_DAYS


def record(history, snap):
    history = [h for h in history if h["date"] != snap["date"]] + [snap]
    return history[-KEEP_SNAPSHOTS:]


def _delta(now, before):
    if before is None:
        return ""
    d = now - before
    return " (%s%d)" % ("+" if d >= 0 else "", d)


def report_lines(history):
    """Markdown for the weekly report: the latest snapshot against the one before it."""
    if not history:
        return ["## Search results", "", "No snapshot yet."]
    cur, prev = history[-1], (history[-2] if len(history) > 1 else {})
    lines = ["## Search results (last %d days, measured %s)" % (cur.get("window_days", WINDOW_DAYS), cur["date"]), ""]
    if prev:
        lines.append("Change is against the snapshot of %s." % prev["date"])
        lines.append("")
    lines += ["| Source | Clicks | Impressions | Avg. position |", "| --- | --- | --- | --- |"]
    for name, label in (("google", "Google"), ("bing", "Bing")):
        c, p = cur.get(name), prev.get(name) or {}
        if c is None:
            lines.append("| %s | not measured | | |" % label)
            continue
        lines.append("| %s | %d%s | %d%s | %s |" % (
            label, c["clicks"], _delta(c["clicks"], p.get("clicks")),
            c["impressions"], _delta(c["impressions"], p.get("impressions")), c.get("position") or "-"))
    lines.append("")
    idx = cur.get("index")
    if idx:
        lines.append("- Google has indexed **%d of %d** pages%s." % (
            idx["indexed"], idx["checked"], _delta(idx["indexed"], (prev.get("index") or {}).get("indexed"))))
        for state, n in sorted(idx["states"].items(), key=lambda kv: -kv[1]):
            lines.append("  - %s: %d" % (state, n))
        if idx["not_indexed"]:
            lines.append("  - Not indexed: " + ", ".join(idx["not_indexed"][:15])
                         + (" and %d more" % (len(idx["not_indexed"]) - 15) if len(idx["not_indexed"]) > 15 else ""))
    if cur.get("sitemap"):
        lines.append("- Sitemap in Search Console: %s." % cur["sitemap"])
    for name, label in (("google", "Google"), ("bing", "Bing")):
        top = (cur.get(name) or {}).get("queries") or []
        if top:
            lines += ["", "Top %s queries:" % label, "", "| Query | Impressions | Clicks | Position |", "| --- | --- | --- | --- |"]
            lines += ["| %s | %d | %d | %s |" % (q["key"].replace("|", "/"), q["impressions"], q["clicks"], q.get("position") or "-")
                      for q in top]
    top_pages = (cur.get("google") or {}).get("pages") or []
    if top_pages:
        lines += ["", "Top pages on Google:", "", "| Page | Impressions | Clicks | Position |", "| --- | --- | --- | --- |"]
        lines += ["| %s | %d | %d | %s |" % (p["key"] or "/", p["impressions"], p["clicks"], p.get("position") or "-") for p in top_pages]
    for n in cur.get("notes", []):
        lines.append("- Not measured: %s" % n)
    return lines


def main():
    manifest = json.load(open(os.path.join(ROOT, "build-manifest.json"), encoding="utf-8"))
    snap = collect(manifest)
    path = os.path.join(ROOT, HISTORY)
    history = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []
    history = record(history, snap)
    print("\n".join(report_lines(history)))
    if "--save" in sys.argv:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=1)
            f.write("\n")


if __name__ == "__main__":
    main()
