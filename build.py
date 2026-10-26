#!/usr/bin/env python3
"""Static build for cryptocasinolist.io. No dependencies: python3 build.py -> dist/

Content pages live in content/*.html (front-matter + body). Casino facts live in
data/casinos.json and reach pages through shortcodes, so a fact changes in one
place and every page that prints it follows on the next build:

  {{MONTH}} {{YEAR}} {{UPDATED}}   localised month ("October 2026"), year, build date
  {{DATA_MONTH}}                   localised month the casino data last changed (honest "updated" label)
  {{TABLE:<preset>}}               data table (home, bonuses, nokyc, withdrawal, usdt, fair, alternatives)
  {{VERSUS:<id>,<id>}}             two-casino fact comparison
  {{FACT:<id>.<path>}}             one fact, e.g. {{FACT:lumenbet.bonus.summary}}
  {{TESTLOG:<id>}}                 the casino's dated test log (renders nothing when empty)
  {{CTA}}                          Lumenbet referral button
  {{RELATED}}                      links to other pages in the same cluster and language
  {{REF}}                          Lumenbet referral URL tagged with this page's slug

Front-matter keys: slug, title, description, lang, i18n (translation group),
cluster (related-links group), type (article|list|page), date (fixed lastmod),
noindex, jsonld (extra JSON-LD, raw).
"""
import datetime
import html
import json
import os
import re
import shutil
import subprocess
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
SITE = "https://cryptocasinolist.io"
SITE_NAME = "Crypto Casino List"
REF = "https://lumenbet.io/ref/QQ6Z5TTZ?c=ccl&s="
LUMENBET_BONUS_API = "https://api.lumenbet.io/api/public/promotions/welcome-bonus/active"
TODAY = datetime.date.today()

MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    "ru": ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"],
    "pt": ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
}

L = {
    "en": {"casino": "Casino", "rating": "Rating", "coins": "Coins", "originals": "Provably fair originals", "slots": "Slots",
           "sportsbook": "Sportsbook", "kyc": "KYC to withdraw", "withdrawal": "Withdrawal speed", "licence": "Licence",
           "offer": "Current offer", "wagering": "Wagering", "min_dep": "Min. deposit", "checked": "Last checked",
           "usdt": "USDT on TRON", "launched": "Launched", "pm": "Prediction markets", "yes": "Yes", "no": "No",
           "unverified": "not verified this month", "play": "Play at Lumenbet", "review": "Review", "related": "Related",
           "spots": "{r} of {t} spots left", "test": "Our tests", "test_date": "Date", "test_dep": "Deposit",
           "test_wd": "Withdrawal", "test_time": "Time to arrive", "test_kyc": "ID asked?", "home": "Rankings", "fact": "Fact"},
    "ru": {"casino": "Казино", "rating": "Оценка", "coins": "Монеты", "originals": "Provably fair игры", "slots": "Слоты",
           "sportsbook": "Ставки на спорт", "kyc": "KYC для вывода", "withdrawal": "Скорость вывода", "licence": "Лицензия",
           "offer": "Текущее предложение", "wagering": "Вейджер", "min_dep": "Мин. депозит", "checked": "Проверено",
           "usdt": "USDT в сети TRON", "launched": "Запуск", "pm": "Рынки предсказаний", "yes": "Да", "no": "Нет",
           "unverified": "не проверено в этом месяце", "play": "Играть в Lumenbet", "review": "Обзор", "related": "Читайте также",
           "spots": "осталось {r} из {t} мест", "test": "Наши тесты", "test_date": "Дата", "test_dep": "Депозит",
           "test_wd": "Вывод", "test_time": "Время зачисления", "test_kyc": "Просили документы?", "home": "Рейтинг", "fact": "Параметр"},
    "pt": {"casino": "Cassino", "rating": "Nota", "coins": "Moedas", "originals": "Originais provably fair", "slots": "Slots",
           "sportsbook": "Apostas esportivas", "kyc": "KYC para sacar", "withdrawal": "Velocidade de saque", "licence": "Licença",
           "offer": "Oferta atual", "wagering": "Rollover", "min_dep": "Depósito mín.", "checked": "Verificado em",
           "usdt": "USDT na TRON", "launched": "Lançamento", "pm": "Mercados de previsão", "yes": "Sim", "no": "Não",
           "unverified": "não verificado este mês", "play": "Jogar no Lumenbet", "review": "Análise", "related": "Veja também",
           "spots": "restam {r} de {t} vagas", "test": "Nossos testes", "test_date": "Data", "test_dep": "Depósito",
           "test_wd": "Saque", "test_time": "Tempo até chegar", "test_kyc": "Pediram documento?", "home": "Ranking", "fact": "Item"},
    "es": {"casino": "Casino", "rating": "Nota", "coins": "Monedas", "originals": "Originales provably fair", "slots": "Slots",
           "sportsbook": "Apuestas deportivas", "kyc": "KYC para retirar", "withdrawal": "Velocidad de retiro", "licence": "Licencia",
           "offer": "Oferta actual", "wagering": "Rollover", "min_dep": "Depósito mín.", "checked": "Verificado",
           "usdt": "USDT en TRON", "launched": "Lanzamiento", "pm": "Mercados de predicción", "yes": "Sí", "no": "No",
           "unverified": "no verificado este mes", "play": "Jugar en Lumenbet", "review": "Reseña", "related": "Ver también",
           "spots": "quedan {r} de {t} plazas", "test": "Nuestras pruebas", "test_date": "Fecha", "test_dep": "Depósito",
           "test_wd": "Retiro", "test_time": "Tiempo de llegada", "test_kyc": "¿Pidieron ID?", "home": "Ranking", "fact": "Dato"},
}

KYC_ORDER = {"none": 0, "level": 1, "often": 2, "required": 3}


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def parse(src):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", src, re.S)
    meta = dict(l.split(":", 1) for l in m.group(1).splitlines() if ":" in l)
    meta = {k.strip(): v.strip() for k, v in meta.items()}
    return meta, m.group(2)


def git_date(*paths):
    """Last commit date touching any of paths (ISO), or None outside git / for new files."""
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cs", "--", *paths], cwd=ROOT,
                             capture_output=True, text=True, timeout=10).stdout.strip()
        return out or None
    except (OSError, subprocess.SubprocessError):
        return None


# ── Data ─────────────────────────────────────────────────────────────────

DATA = json.loads(read(os.path.join(ROOT, "data", "casinos.json")))
CASINOS = {c["id"]: c for c in DATA["casinos"]}
DATA_DATE = git_date("data/casinos.json") or TODAY.isoformat()


def refresh_lumenbet_bonus():
    """Pull the live welcome bonus. Falls back silently: CI runners in some regions are geo-blocked."""
    b = CASINOS["lumenbet"]["bonus"]
    if b.get("source") != "lumenbet-api":
        return "manual"
    try:
        req = urllib.request.Request(LUMENBET_BONUS_API, headers={"User-Agent": "cryptocasinolist-build"})
        with urllib.request.urlopen(req, timeout=8) as r:
            live = json.load(r)
    except Exception as e:  # noqa: BLE001 - any failure means "use the data file"
        b.pop("limited", None)  # a stale "spots left" count is worse than none
        return f"fallback ({type(e).__name__})"
    pct, wag = live.get("bonusPercent"), live.get("wageringMultiplier")
    mx, mn = live.get("maxBonusAtomic"), live.get("minDepositAtomic")
    if not (pct and wag and mx and mn):
        return "fallback (incomplete response)"
    b.update(percent=pct, wagering=wag, max=mx // 100, min_deposit=mn // 100, verified_at=TODAY.isoformat())
    if live.get("maxRedemptions"):
        b["limited"] = {"total": live["maxRedemptions"], "remaining": live.get("spotsRemaining", 0)}
    b["summary"] = {
        "en": f"{pct}% up to {b['max']} USDT, {wag}x wagering",
        "ru": f"{pct}% до {b['max']} USDT, вейджер x{wag}",
        "pt": f"{pct}% até {b['max']} USDT, rollover {wag}x",
        "es": f"{pct}% hasta {b['max']} USDT, rollover {wag}x",
    }
    return "live"


BONUS_STATUS = refresh_lumenbet_bonus()


def t(value, lang):
    """A data value in the page language: plain strings pass through, dicts pick lang then en."""
    if isinstance(value, dict):
        return value.get(lang) or value.get("en") or ""
    return "" if value is None else str(value)


def yn(v, lang):
    return f'<span class="yes">{L[lang]["yes"]}</span>' if v else f'<span class="no">{L[lang]["no"]}</span>'


def month_label(lang, d=TODAY):
    m = MONTHS.get(lang, MONTHS["en"])[d.month - 1]
    return f"{m} de {d.year}" if lang in ("pt", "es") else f"{m} {d.year}"


def stale(iso):
    if not iso:
        return True
    return (TODAY - datetime.date.fromisoformat(iso)).days > 31


# ── Shortcodes ───────────────────────────────────────────────────────────

def casino_link(c, lang):
    return f'<a href="{c["review"]}">{html.escape(c["name"])}</a>' if c.get("review") else html.escape(c["name"])


def bonus_cell(c, lang):
    b = c.get("bonus") or {}
    text = html.escape(t(b.get("summary"), lang))
    lim = b.get("limited")
    if lim and lim.get("remaining") is not None:
        text += f'<br><span class="updated">{L[lang]["spots"].format(r=lim["remaining"], t=lim["total"])}</span>'
    if stale(b.get("verified_at")):
        text += f' <span class="updated">({L[lang]["unverified"]})</span>'
    return text


PRESETS = {
    # preset: (columns, sort key, filter)
    "home": (["rank", "casino", "rating", "coins", "originals", "slots", "sportsbook", "kyc", "withdrawal"], lambda c: -c["rating"], None),
    "bonuses": (["casino", "offer", "wagering", "min_dep", "checked"], lambda c: -c["rating"], None),
    "nokyc": (["casino", "kyc", "licence", "withdrawal"], lambda c: (KYC_ORDER[c["kyc"]], -c["rating"]), None),
    "withdrawal": (["casino", "withdrawal", "kyc", "coins"], lambda c: c["withdrawal_rank"], None),
    "usdt": (["casino", "usdt", "coins", "withdrawal"], lambda c: -c["rating"], lambda c: c.get("usdt_trc20")),
    "fair": (["casino", "originals", "slots", "pm"], lambda c: -c["rating"], lambda c: c.get("provably_fair")),
    "alternatives": (["casino", "licence", "kyc", "sportsbook", "pm", "withdrawal"], lambda c: -c["rating"], lambda c: c["id"] != "stake"),
}


def cell(col, c, lang, rank):
    b = c.get("bonus") or {}
    return {
        "rank": str(rank),
        "casino": casino_link(c, lang),
        "rating": f'<span class="score">{c["rating"]}</span>',
        "coins": html.escape(t(c["coins"], lang)),
        "originals": (f'<span class="yes">{c["originals"]}</span>' if c.get("originals") else yn(c.get("provably_fair"), lang)),
        "slots": html.escape(c["slots"]),
        "sportsbook": yn(c["sportsbook"], lang),
        "kyc": html.escape(t(c["kyc_note"], lang)),
        "withdrawal": html.escape(t(c["withdrawal"], lang)),
        "licence": html.escape(t(c["licence"], lang)),
        "offer": bonus_cell(c, lang),
        "wagering": f'{b["wagering"]}x' if b.get("wagering") else "–",
        "min_dep": f'{b["min_deposit"]} {b.get("currency", "USDT")}' if b.get("min_deposit") else "–",
        "checked": html.escape(b.get("verified_at") or "–"),
        "usdt": yn(c.get("usdt_trc20"), lang),
        "pm": yn(c.get("prediction_markets"), lang),
    }[col]


def render_table(preset, lang):
    cols, key, flt = PRESETS[preset]
    rows = sorted((c for c in DATA["casinos"] if flt is None or flt(c)), key=key)
    heads = {"rank": "#", "casino": L[lang]["casino"], "rating": L[lang]["rating"], "coins": L[lang]["coins"],
             "originals": L[lang]["originals"], "slots": L[lang]["slots"], "sportsbook": L[lang]["sportsbook"],
             "kyc": L[lang]["kyc"], "withdrawal": L[lang]["withdrawal"], "licence": L[lang]["licence"],
             "offer": L[lang]["offer"], "wagering": L[lang]["wagering"], "min_dep": L[lang]["min_dep"],
             "checked": L[lang]["checked"], "usdt": L[lang]["usdt"], "pm": L[lang]["pm"]}
    num = {"rank", "rating"}
    cls = lambda col: ' class="n"' if col in num else ""
    out = ['<div class="tbl"><table>', "  <tr>" + "".join(f"<th{cls(c)}>{heads[c]}</th>" for c in cols) + "</tr>"]
    for i, c in enumerate(rows, 1):
        out.append("  <tr>" + "".join(f"<td{cls(col)}>{cell(col, c, lang, i)}</td>" for col in cols) + "</tr>")
    out.append("</table></div>")
    return "\n".join(out), [c["name"] for c in rows]


def render_versus(a_id, b_id, lang):
    a, b = CASINOS[a_id], CASINOS[b_id]
    rows = [("launched", str(a["launched"]), str(b["launched"])),
            ("licence", t(a["licence"], lang), t(b["licence"], lang)),
            ("coins", t(a["coins"], lang), t(b["coins"], lang)),
            ("originals", str(a["originals"] or L[lang]["yes"]), str(b["originals"] or L[lang]["yes"])),
            ("slots", a["slots"], b["slots"]),
            ("sportsbook", L[lang]["yes" if a["sportsbook"] else "no"], L[lang]["yes" if b["sportsbook"] else "no"]),
            ("pm", L[lang]["yes" if a["prediction_markets"] else "no"], L[lang]["yes" if b["prediction_markets"] else "no"]),
            ("kyc", t(a["kyc_note"], lang), t(b["kyc_note"], lang)),
            ("withdrawal", t(a["withdrawal"], lang), t(b["withdrawal"], lang)),
            ("offer", t(a["bonus"]["summary"], lang), t(b["bonus"]["summary"], lang))]
    heads = {"launched": L[lang]["launched"], "licence": L[lang]["licence"], "coins": L[lang]["coins"],
             "originals": L[lang]["originals"], "slots": L[lang]["slots"], "sportsbook": L[lang]["sportsbook"],
             "pm": L[lang]["pm"], "kyc": L[lang]["kyc"], "withdrawal": L[lang]["withdrawal"], "offer": L[lang]["offer"]}
    out = ['<div class="tbl"><table>',
           f'  <tr><th>{L[lang]["fact"]}</th><th>{casino_link(a, lang)}</th><th>{casino_link(b, lang)}</th></tr>']
    for k, x, y in rows:
        out.append(f"  <tr><td>{heads[k]}</td><td>{html.escape(x)}</td><td>{html.escape(y)}</td></tr>")
    out.append("</table></div>")
    return "\n".join(out)


def render_fact(path, lang):
    cid, *keys = path.split(".")
    v = CASINOS[cid]
    for k in keys:
        v = v[k] if isinstance(v, dict) and k in v else None
        if v is None:
            raise KeyError(f"unknown fact {path}")
    return html.escape(t(v, lang))


def render_testlog(cid, lang):
    log = CASINOS[cid].get("test_log") or []
    if not log:
        return ""
    lab = L[lang]
    rows = "\n".join(
        f'  <tr><td>{html.escape(e["date"])}</td><td>{html.escape(e.get("deposit", "–"))}</td>'
        f'<td>{html.escape(e.get("withdrawal", "–"))}</td><td>{html.escape(e.get("withdrawal_time", "–"))}</td>'
        f'<td>{lab["yes"] if e.get("kyc_asked") else lab["no"]}</td></tr>' for e in log)
    return (f'<h2>{lab["test"]}</h2>\n<div class="tbl"><table>\n  <tr><th>{lab["test_date"]}</th><th>{lab["test_dep"]}</th>'
            f'<th>{lab["test_wd"]}</th><th>{lab["test_time"]}</th><th>{lab["test_kyc"]}</th></tr>\n{rows}\n</table></div>')


def expand(text, meta, lang, slug, ctx):
    ref = REF + (slug.replace("/", "-") or "home")
    text = text.replace("{{MONTH}}", month_label(lang)).replace("{{YEAR}}", str(TODAY.year))
    text = text.replace("{{UPDATED}}", TODAY.isoformat()).replace("{{REF}}", ref)
    if "{{DATA_MONTH}}" in text:
        ctx["data"] = True
        text = text.replace("{{DATA_MONTH}}", month_label(lang, datetime.date.fromisoformat(DATA_DATE)))
    text = text.replace("{{CTA}}", f'<p><a class="btn" href="{ref}" rel="sponsored nofollow">{L[lang]["play"]}</a></p>')

    def table(m):
        body, names = render_table(m.group(1), lang)
        ctx["list"] = ctx.get("list") or names
        ctx["data"] = True
        return body

    def versus(m):
        ctx["data"] = True
        a, b = [x.strip() for x in m.group(1).split(",")]
        return render_versus(a, b, lang)

    def fact(m):
        ctx["data"] = True
        return render_fact(m.group(1), lang)

    def testlog(m):
        ctx["data"] = True
        return render_testlog(m.group(1), lang)

    text = re.sub(r"\{\{TABLE:([a-z]+)\}\}", table, text)
    text = re.sub(r"\{\{VERSUS:([a-z0-9\-, ]+)\}\}", versus, text)
    text = re.sub(r"\{\{FACT:([a-z0-9_\-\.]+)\}\}", fact, text)
    text = re.sub(r"\{\{TESTLOG:([a-z0-9\-]+)\}\}", testlog, text)
    return text


# ── Pages ────────────────────────────────────────────────────────────────

def url_of(slug):
    slug = slug.strip("/")
    return SITE + ("/" if not slug else f"/{slug}/")


def jsonld_blocks(meta, body, lang, slug, ctx, lastmod):
    blocks = []
    if slug and slug != "404":
        root = lang if lang != "en" and slug.split("/")[0] == lang else ""
        parts = [p for p in slug[len(root):].strip("/").split("/") if p]
        items = [{"@type": "ListItem", "position": 1, "name": L.get(lang, L["en"])["home"], "item": url_of(root)}]
        for i in range(len(parts)):
            sub = "/".join(([root] if root else []) + parts[: i + 1])
            name = meta["title"] if i == len(parts) - 1 else parts[i].replace("-", " ").title()
            items.append({"@type": "ListItem", "position": len(items) + 1, "name": name, "item": url_of(sub)})
        if len(items) > 1:
            blocks.append({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items})
    if meta.get("type") == "article":
        blocks.append({"@context": "https://schema.org", "@type": "Article", "headline": meta["title"],
                       "description": meta["description"], "inLanguage": lang, "dateModified": lastmod,
                       "datePublished": meta.get("published", lastmod), "mainEntityOfPage": url_of(slug),
                       "author": {"@type": "Organization", "name": f"{SITE_NAME} team", "url": url_of("about")},
                       "publisher": {"@type": "Organization", "name": SITE_NAME, "url": SITE}})
    if ctx.get("list") and "ItemList" not in meta.get("jsonld", ""):
        blocks.append({"@context": "https://schema.org", "@type": "ItemList", "name": meta["title"],
                       "itemListElement": [{"@type": "ListItem", "position": i, "name": n} for i, n in enumerate(ctx["list"], 1)]})
    if "FAQPage" not in meta.get("jsonld", ""):
        qa = re.findall(r"<details><summary>(.*?)</summary>\s*<p>(.*?)</p>\s*</details>", body, re.S)
        if qa:
            strip = lambda s: re.sub(r"<[^>]+>", "", s).strip()
            blocks.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
                {"@type": "Question", "name": strip(q), "acceptedAnswer": {"@type": "Answer", "text": strip(a)}} for q, a in qa]})
    if not slug:
        blocks.append({"@context": "https://schema.org", "@type": "WebSite", "name": SITE_NAME, "url": SITE, "inLanguage": "en"})
        blocks.append({"@context": "https://schema.org", "@type": "Organization", "name": SITE_NAME, "url": SITE,
                       "logo": SITE + "/favicon.svg"})
    return "\n".join(f'<script type="application/ld+json">{json.dumps(b, ensure_ascii=False)}</script>' for b in blocks)


def main():
    layout = read(os.path.join(ROOT, "layout.html"))
    entries = []
    for name in sorted(os.listdir(os.path.join(ROOT, "content"))):
        if name.endswith(".html"):
            meta, body = parse(read(os.path.join(ROOT, "content", name)))
            meta["_file"] = os.path.join("content", name)
            entries.append((meta, body))

    groups = {}
    for meta, _ in entries:
        if meta.get("i18n") and not meta.get("redirect"):
            groups.setdefault(meta["i18n"], []).append((meta.get("lang", "en"), url_of(meta["slug"])))

    clusters = {}
    for meta, _ in entries:
        if meta.get("cluster") and meta.get("noindex") != "true" and not meta.get("redirect"):
            clusters.setdefault((meta["cluster"], meta.get("lang", "en")), []).append(meta)

    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    manifest = []
    for meta, body in entries:
        slug = meta["slug"].strip("/")
        lang = meta.get("lang", "en")
        if meta.get("redirect"):
            # A moved page. GitHub Pages cannot send a 301, so the old URL serves
            # an instant meta refresh plus a canonical to the new one, which
            # Google treats as a permanent redirect. Never listed in the sitemap.
            target = url_of(meta["redirect"])
            out = os.path.join(DIST, slug, "index.html")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                f.write(f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{html.escape(meta.get("title", "Moved"))}</title>'
                        f'<link rel="canonical" href="{target}"><meta http-equiv="refresh" content="0; url={target}"></head>'
                        f'<body><p>This page has moved to <a href="{target}">{target}</a>.</p></body></html>')
            manifest.append({"slug": slug, "url": url_of(slug), "file": meta["_file"], "lang": lang, "title": meta.get("title", ""),
                             "description": "", "lastmod": TODAY.isoformat(), "words": 0, "cluster": None, "type": "redirect",
                             "indexable": False, "links": [], "unexpanded": [], "redirect": meta["redirect"]})
            continue
        ctx = {}
        title = expand(meta["title"], meta, lang, slug, ctx)
        desc = expand(meta["description"], meta, lang, slug, ctx)
        body = expand(body, meta, lang, slug, ctx)
        meta = {**meta, "title": title, "description": desc}

        if "{{RELATED}}" in body:
            peers = [m for m in clusters.get((meta.get("cluster"), lang), []) if m["slug"].strip("/") != slug]
            links = "".join(f'<a href="{url_of(m["slug"])}"><b>{html.escape(expand(m["title"], m, lang, m["slug"], {}))}</b>'
                            f'{html.escape(expand(m["description"], m, lang, m["slug"], {}))}</a>' for m in peers)
            body = body.replace("{{RELATED}}", f'<h2>{L[lang]["related"]}</h2>\n<div class="guides">{links}</div>' if peers else "")

        # lastmod: fixed date > newest of (file commit, data commit when data-driven, month start when month-dated)
        candidates = [git_date(meta["_file"]) or TODAY.isoformat()]
        if ctx.get("data"):
            candidates.append(DATA_DATE)
        if "{{MONTH}}" in read(os.path.join(ROOT, meta["_file"])):
            candidates.append(TODAY.replace(day=1).isoformat())
        lastmod = meta.get("date") or max(candidates)

        hreflang = ""
        g = meta.get("i18n")
        if g and len(groups[g]) > 1:
            links = [f'<link rel="alternate" hreflang="{l}" href="{u}">' for l, u in groups[g]]
            default = next((u for l, u in groups[g] if l == "en"), groups[g][0][1])
            links.append(f'<link rel="alternate" hreflang="x-default" href="{default}">')
            hreflang = "\n".join(links)

        jsonld = "\n".join(x for x in [meta.get("jsonld", ""), jsonld_blocks(meta, body, lang, slug, ctx, lastmod)] if x)
        robots = '<meta name="robots" content="noindex">' if meta.get("noindex") == "true" else ""
        page = layout
        for k, v in {"TITLE": html.escape(title, quote=False), "DESC": html.escape(desc), "BODY": body, "LANG": lang,
                     "HREFLANG": hreflang + robots, "URL": url_of(slug), "DATE": lastmod, "JSONLD": jsonld,
                     "YEAR": str(TODAY.year)}.items():
            page = page.replace("{{" + k + "}}", v)

        out = os.path.join(DIST, slug, "index.html") if slug else os.path.join(DIST, "index.html")
        if slug == "404":
            out = os.path.join(DIST, "404.html")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(page)

        text = re.sub(r"<[^>]+>", " ", body)
        manifest.append({
            "slug": slug, "url": url_of(slug), "file": meta["_file"], "lang": lang, "title": title, "description": desc,
            "lastmod": lastmod, "words": len(text.split()), "cluster": meta.get("cluster"), "type": meta.get("type", "page"),
            "indexable": slug != "404" and meta.get("noindex") != "true",
            "links": sorted(set(re.findall(r'href="(/[^"#?]*)', body))), "unexpanded": re.findall(r"\{\{[A-Z]+[^}]*\}\}", body),
        })

    shutil.copytree(os.path.join(ROOT, "static"), DIST, dirs_exist_ok=True)
    with open(os.path.join(DIST, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for p in manifest:
            if p["indexable"]:
                f.write(f'  <url><loc>{p["url"]}</loc><lastmod>{p["lastmod"]}</lastmod></url>\n')
        f.write("</urlset>\n")
    with open(os.path.join(DIST, "robots.txt"), "w") as f:
        f.write(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    with open(os.path.join(ROOT, "build-manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"built": TODAY.isoformat(), "lumenbet_bonus": BONUS_STATUS, "pages": manifest}, f, ensure_ascii=False, indent=1)
    print(f"built {sum(p['indexable'] for p in manifest)} indexable pages -> dist/ (Lumenbet bonus: {BONUS_STATUS})")


if __name__ == "__main__":
    main()
