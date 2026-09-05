#!/usr/bin/env python3
"""Static build for cryptocasinolist.io. No dependencies: python3 build.py -> dist/"""
import os, re, shutil, json, datetime
ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
SITE = "https://cryptocasinolist.io"
REF = "https://stakebet.gg/ref/QQ6Z5TTZ?c=ccl&s="
TODAY = datetime.date.today().isoformat()

def read(p):
    with open(p, encoding="utf-8") as f: return f.read()

def parse(src):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", src, re.S)
    meta = dict(l.split(":", 1) for l in m.group(1).splitlines() if ":" in l)
    meta = {k.strip(): v.strip() for k, v in meta.items()}
    return meta, m.group(2)

LAYOUT = read(os.path.join(ROOT, "layout.html"))
entries = []
for name in sorted(os.listdir(os.path.join(ROOT, "content"))):
    if not name.endswith(".html"): continue
    meta, body = parse(read(os.path.join(ROOT, "content", name)))
    entries.append((meta, body))

def url_of(slug):
    slug = slug.strip("/")
    return SITE + ("/" if not slug else f"/{slug}/")

# hreflang groups: pages sharing an `i18n:` key are translations of each other
groups = {}
for meta, _ in entries:
    g = meta.get("i18n")
    if g: groups.setdefault(g, []).append((meta.get("lang", "en"), url_of(meta["slug"])))

pages = []
for meta, body in entries:
    slug = meta["slug"].strip("/")
    body = body.replace("{{REF}}", REF + (slug.replace("/", "-") or "home"))
    hreflang = ""
    g = meta.get("i18n")
    if g and len(groups[g]) > 1:
        links = [f'<link rel="alternate" hreflang="{l}" href="{u}">' for l, u in groups[g]]
        default = next((u for l, u in groups[g] if l == "en"), groups[g][0][1])
        links.append(f'<link rel="alternate" hreflang="x-default" href="{default}">')
        hreflang = "\n".join(links)
    html = LAYOUT
    for k, v in {"TITLE": meta["title"], "DESC": meta["description"], "BODY": body, "LANG": meta.get("lang", "en"), "HREFLANG": hreflang,
                 "URL": url_of(slug), "DATE": meta.get("date", TODAY),
                 "JSONLD": meta.get("jsonld", ""), "YEAR": str(datetime.date.today().year)}.items():
        html = html.replace("{{" + k + "}}", v)
    out = os.path.join(DIST, slug, "index.html") if slug else os.path.join(DIST, "index.html")
    if slug == "404": out = os.path.join(DIST, "404.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f: f.write(html)
    if slug != "404" and meta.get("noindex") != "true":
        pages.append((url_of(slug), meta.get("date", TODAY)))

shutil.copytree(os.path.join(ROOT, "static"), DIST, dirs_exist_ok=True)
with open(os.path.join(DIST, "sitemap.xml"), "w") as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
    for url, d in pages: f.write(f"  <url><loc>{url}</loc><lastmod>{d}</lastmod></url>\n")
    f.write("</urlset>\n")
with open(os.path.join(DIST, "robots.txt"), "w") as f:
    f.write(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
print(f"built {len(pages)} pages -> dist/")
