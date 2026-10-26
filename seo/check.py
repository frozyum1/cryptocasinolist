#!/usr/bin/env python3
"""Quality gate for cryptocasinolist.io. Run after build.py; exits 1 on any error.

Errors block a deploy or a drafted PR. Warnings are printed and do not block,
so an existing thin page can be fixed over time without freezing the site.
New pages (not yet committed) are held to the full bar.

  python3 seo/check.py            # gate
  python3 seo/check.py --json     # machine-readable, used by the weekly drafter
"""
import datetime
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIN_WORDS = {"article": 600, "list": 500, "page": 120}
STALE_DAYS = 60
EXEMPT_THIN = {"privacy", "404", "responsible-gambling", "about"}


def committed(path):
    r = subprocess.run(["git", "log", "--follow", "-1", "--format=%H", "--", path], cwd=ROOT, capture_output=True, text=True)
    return bool(r.stdout.strip())


def main():
    manifest = json.load(open(os.path.join(ROOT, "build-manifest.json"), encoding="utf-8"))
    data = json.load(open(os.path.join(ROOT, "data", "casinos.json"), encoding="utf-8"))
    pages = manifest["pages"]
    errors, warnings = [], []
    known = {"/" + p["slug"] + "/" if p["slug"] else "/" for p in pages}
    for p in pages:
        if p.get("redirect"):
            target = "/" + p["redirect"].strip("/") + "/"
            if target not in known:
                errors.append(f"{p['file']}: redirect target {target} does not exist")
    static_files = set()
    for base, _, files in os.walk(os.path.join(ROOT, "static")):
        for f in files:
            static_files.add("/" + os.path.relpath(os.path.join(base, f), os.path.join(ROOT, "static")))

    seen_titles, seen_desc = {}, {}
    for p in pages:
        if not p["indexable"]:
            continue
        where = p["file"]
        new = not committed(where)
        add = errors.append if new else warnings.append

        if p["unexpanded"]:
            errors.append(f"{where}: unknown shortcode(s) {p['unexpanded']}")
        if p["title"] in seen_titles:
            errors.append(f"{where}: duplicate title with {seen_titles[p['title']]}")
        seen_titles[p["title"]] = where
        if p["description"] in seen_desc:
            errors.append(f"{where}: duplicate description with {seen_desc[p['description']]}")
        seen_desc[p["description"]] = where
        if not 25 <= len(p["title"]) <= 70:
            add(f"{where}: title is {len(p['title'])} chars (aim 25-70)")
        if not 70 <= len(p["description"]) <= 165:
            add(f"{where}: description is {len(p['description'])} chars (aim 70-165)")
        need = MIN_WORDS.get(p["type"], MIN_WORDS["page"])
        if p["slug"] not in EXEMPT_THIN and p["words"] < need:
            add(f"{where}: {p['words']} words, below {need} for a {p['type']} page (thin content)")
        for link in p["links"]:
            if link not in known and link not in static_files and not link.rstrip("/") + "/" in known:
                errors.append(f"{where}: broken internal link {link}")

    today = datetime.date.today()
    for c in data["casinos"]:
        v = c.get("verified_at")
        if not v or (today - datetime.date.fromisoformat(v)).days > STALE_DAYS:
            warnings.append(f"data: {c['name']} facts last verified {v or 'never'}; re-check on the casino itself")
        if not c.get("test_log"):
            warnings.append(f"data: {c['name']} has no test_log entries, but the site says every casino was tested")

    if "--json" in sys.argv:
        print(json.dumps({"errors": errors, "warnings": warnings}, ensure_ascii=False, indent=1))
    else:
        for w in warnings:
            print("warning:", w)
        for e in errors:
            print("ERROR:", e)
        print(f"{len(errors)} error(s), {len(warnings)} warning(s) across {sum(p['indexable'] for p in pages)} pages")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
