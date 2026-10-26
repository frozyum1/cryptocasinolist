#!/usr/bin/env python3
"""Write new pages and refresh existing ones with Claude.

Library for seo/autopilot.py, also usable by hand:
  python3 seo/draft.py new [--slug guides/plinko-odds] [--dry-run]
  python3 seo/draft.py refresh content/11-review-stake.html --reason "thin: 327 words"
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE_PAGE = "content/41-no-kyc.html"

RULES = """You write pages for cryptocasinolist.io, a crypto casino comparison site openly run by the team behind Lumenbet.

Non-negotiable rules:
- Never invent facts. Casino facts come only from the JSON data provided; print them through shortcodes, never as typed numbers: {{TABLE:<preset>}} (presets: home, bonuses, nokyc, withdrawal, usdt, fair, alternatives), {{VERSUS:<id>,<id>}}, {{FACT:<id>.<path>}} (e.g. {{FACT:lumenbet.bonus.summary}}), {{TESTLOG:<id>}}.
- Never claim tests, deposits, screenshots, quotes, user reviews, statistics, awards, rankings by others or dates that are not in the data. If a fact you would need is missing, write around it or say it is not verified.
- General, widely known mechanics (how wagering works, how provably fair hashing works, blockchain confirmation times, house edge maths, how a game is played) are fine to explain without a source. Lumenbet's published house edges: Coinflip 1%; Dice, Mines, Plinko, Limbo 2%; Crash 3%; Keno 4%.
- Be honest about Lumenbet's weaknesses where relevant: no gambling licence, no sportsbook, launched 2026, every withdrawal approved by a person, withdrawals paused while a welcome bonus has wagering left. Say that the site is run by Lumenbet's team whenever you recommend Lumenbet.
- No promises of winnings, no "guaranteed", no "risk-free", no strategy that claims to beat the house edge. Mention that gambling can be addictive when the topic is strategy, bonuses or bankroll.
- Write for a reader who searched the target query: answer it in the first two sentences, then go deeper with sections a competitor's page would have. Plain words, short paragraphs.
- Use {{CTA}} at most twice. Link to 3-6 existing pages from the list given (relative URLs like /bonuses/). Tools exist at /tools/wagering-calculator/ and /tools/provably-fair-verifier/. End the page with {{RELATED}}.
- Write the whole page in the target language.

Output format: exactly one page file, nothing before or after it:
---
slug: <slug>
lang: <lang; omit the line for English>
cluster: <lists|guides|reviews|compare|lumenbet|tools>
type: <article|list>
title: <25-65 characters, contains the target query naturally>
description: <80-160 characters>
---
<body HTML using the same tags and classes as the example page: div.eyebrow, h1, p.lede, h2, p, ul/ol, div.tbl>table, div.faq with <details><summary>Q</summary><p>A</p></details>>

Length: 900-1500 words of body text with an FAQ of 3-5 questions."""


def load(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def existing_pages():
    pages = []
    for name in sorted(os.listdir(os.path.join(ROOT, "content"))):
        src = load(os.path.join("content", name))
        slug = re.search(r"^slug:\s*(.*)$", src, re.M).group(1).strip().strip("/")
        title = re.search(r"^title:\s*(.*)$", src, re.M).group(1).strip()
        pages.append((name, slug, title))
    return pages


def page_list(pages):
    return "\n".join(f"/{s}/ - {t}" if s else f"/ - {t}" for _, s, t in pages)


def pick(keywords, pages, slug=None):
    have = {s for _, s, _ in pages}
    rows = keywords["keywords"]
    if slug:
        return next((k for k in rows if k["slug"] == slug), None)
    todo = sorted((k for k in rows if k["status"] == "planned" and k["slug"] not in have),
                  key=lambda k: (-(k.get("impressions") or 0), k["priority"]))
    return todo[0] if todo else None


def next_filename(pages, slug):
    used = [int(n.split("-", 1)[0]) for n, _, _ in pages if n[:2].isdigit()]
    num = max([n for n in used if n < 99] + [49]) + 1
    return f"content/{num:02d}-{slug.replace('/', '-')}.html"


def extract_page(text, slug):
    m = re.search(r"^---\n.*?\n---\n.*", text, re.S | re.M)
    if not m:
        raise llm.LLMError("model output had no front-matter page: " + text[:300])
    out = m.group(0).rstrip() + "\n"
    if not re.search(r"^slug:", out, re.M):
        raise llm.LLMError("page has no slug line")
    return re.sub(r"^slug:.*$", f"slug: {slug}", out, count=1, flags=re.M)


def write_new(row, pages, feedback=None):
    brief = (f"Target query: {row['q']}\nLanguage: {row['lang']}\nSlug: {row['slug']}\nTier: {row['tier']}\n"
             f"Search impressions (Bing, monthly, if known): {row.get('impressions', 'unknown')}\n"
             f"Related queries to cover in the same page: {', '.join(row.get('related', [])) or 'none'}\n"
             f"Notes: {row.get('note', 'none')}\n\nExisting pages you may link to:\n{page_list(pages)}")
    ask = brief + ("\n\nA reviewer rejected the previous draft. Fix every point:\n" + feedback if feedback else "") + "\n\nWrite the page now."
    text = llm.call(RULES, ["Casino data (the only source of casino facts):\n" + load("data/casinos.json"),
                            "Example page for format and tone:\n" + load(EXAMPLE_PAGE), ask])
    return extract_page(text, row["slug"])


def refresh(path, reason, pages, feedback=None):
    current = load(path)
    slug = re.search(r"^slug:\s*(.*)$", current, re.M).group(1).strip().strip("/")
    ask = (f"Improve this existing page. Reason it was selected: {reason}\n"
           "Keep its slug, language, cluster and every true statement, keep all shortcodes, keep the author's "
           "own test descriptions exactly as they are, and keep the URL's topic. Expand it to the length in the rules "
           "with the sections a searcher expects, fix anything thin or vague, and improve title and description for "
           "click-through without clickbait.\n\nExisting pages you may link to:\n" + page_list(pages)
           + ("\n\nA reviewer rejected the previous rewrite. Fix every point:\n" + feedback if feedback else "")
           + "\n\nCurrent page:\n" + current + "\n\nReturn the full improved page.")
    text = llm.call(RULES, ["Casino data (the only source of casino facts):\n" + load("data/casinos.json"),
                            "Example page for format and tone:\n" + load(EXAMPLE_PAGE), ask])
    return extract_page(text, slug)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("--slug")
    n.add_argument("--dry-run", action="store_true")
    r = sub.add_parser("refresh")
    r.add_argument("path")
    r.add_argument("--reason", default="manual refresh")
    args = ap.parse_args()

    pages = existing_pages()
    if args.cmd == "new":
        keywords = json.loads(load("data/keywords.json"))
        row = pick(keywords, pages, args.slug)
        if not row:
            print("nothing planned")
            return
        target = next_filename(pages, row["slug"])
        print(f"new: '{row['q']}' ({row['lang']}) -> /{row['slug']}/ in {target}")
        if args.dry_run:
            return
        with open(os.path.join(ROOT, target), "w", encoding="utf-8") as f:
            f.write(write_new(row, pages))
    else:
        page = refresh(args.path, args.reason, pages)
        with open(os.path.join(ROOT, args.path), "w", encoding="utf-8") as f:
            f.write(page)
        print(f"refreshed {args.path}")


if __name__ == "__main__":
    main()
