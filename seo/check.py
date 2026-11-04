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
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIN_WORDS = {"article": 600, "list": 500, "page": 120}
STALE_DAYS = 60
EXEMPT_THIN = {"privacy", "404", "responsible-gambling", "about"}

# A first-person claim that we put money through a casino. review.py already
# stops the autopilot ADDING one; nothing ever audited the pages that were
# written by hand, which is how the homepage came to say "we deposited USDT
# at each casino" while every test_log in the data file was empty and the
# Roobet review said the opposite on the same site.
FIRST_PERSON_TEST = re.compile(
    r"\b(we|our team) (tested|deposited|withdrew|played|signed up|claimed|verified)\b"
    r"|\bмы (протестировали|внесли|вывели)\b",
    re.I,
)
# The same claim stretched over the whole list. Unprovable by construction:
# it asserts something about casinos the page never names.
BLANKET = re.compile(
    r"\b(each|every|all (five|of the)) casino|\bat each\b"
    r"|\b(кажд\w+|все) казино|\bem cada cassino\b|\ben cada casino\b",
    re.I,
)


def sentences(text):
    return [t.strip() for t in re.split(r"(?<=[.!?])\s+", text) if t.strip()]


def audit_testing_claims(pages, data, errors, warnings):
    """Every hands-on claim must name a casino whose test_log backs it."""
    tested = {c["name"].lower() for c in data["casinos"] if c.get("test_log")}
    names = {c["name"].lower() for c in data["casinos"]}
    for p in pages:
        src = os.path.join(ROOT, "content", os.path.basename(p["file"]))
        body = open(src, encoding="utf-8").read() if os.path.exists(src) else ""
        # The claim that shipped lived in the front-matter description as much
        # as in the prose, so both are audited.
        # The embedded JSON-LD is machine data, not prose, and it has no
        # sentence punctuation — left in, it swallows the line after it.
        body = "\n".join(l for l in body.splitlines() if not l.startswith("jsonld:"))
        text = re.sub(r"<[^>]+>", " ", body)
        text = " ".join([text, p.get("title") or "", p.get("description") or ""])
        for sent in sentences(text):
            m = FIRST_PERSON_TEST.search(sent)
            if not m:
                continue
            # Quote around the claim itself, not the start of a long sentence.
            a, b = max(0, m.start() - 40), min(len(sent), m.end() + 50)
            quote = ("…" if a else "") + " ".join(sent[a:b].split()) + ("…" if b < len(sent) else "")
            where = f"{p['file']}: \"{quote}\""
            if BLANKET.search(sent):
                errors.append(f"{where} — claims hands-on testing across the whole list; no page can support that")
                continue
            named = [n for n in names if n in sent.lower()]
            unbacked = [n for n in named if n not in tested]
            if unbacked:
                errors.append(f"{where} — claims testing of {', '.join(sorted(unbacked))}, which has no test_log")
            elif not named:
                warnings.append(f"{where} — hands-on claim that names no casino; say which one")


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
            warnings.append(f"data: {c['name']} has no test_log entries, so no page may claim we deposited or withdrew there")

    audit_testing_claims(pages, data, errors, warnings)

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
