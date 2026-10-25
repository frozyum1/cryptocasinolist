#!/usr/bin/env python3
"""Draft one new page for cryptocasinolist.io with Claude, for a human to review in a PR.

Picks the highest-priority 'planned' keyword in data/keywords.json whose slug has
no page yet (or the one passed with --slug), writes content/NN-<slug>.html, and
marks the keyword 'drafted'. The weekly workflow then builds, runs the quality
gate and opens a pull request. Nothing here publishes: a draft goes live only
when someone merges the PR.

  ANTHROPIC_API_KEY=... python3 seo/draft.py [--slug guides/plinko-odds] [--dry-run]

Requires `pip install anthropic` (CI installs it; build.py itself stays dependency-free).
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.environ.get("DRAFT_MODEL", "claude-opus-5")
EXAMPLE_PAGE = "content/41-no-kyc.html"

STYLE = """You write pages for cryptocasinolist.io, a crypto casino comparison site openly run by the team behind StakeBet.

Non-negotiable rules:
- Never invent facts. Casino facts come only from the JSON data provided; print them through shortcodes, never as typed numbers: {{TABLE:<preset>}} (presets: home, bonuses, nokyc, withdrawal, usdt, fair, alternatives), {{VERSUS:<id>,<id>}}, {{FACT:<id>.<path>}} (e.g. {{FACT:stakebet.bonus.summary}}), {{TESTLOG:<id>}}.
- Never claim tests, deposits, screenshots, quotes, user reviews, statistics or dates that are not in the data. If a fact you would need is missing, write around it or say it is not verified.
- General, widely known mechanics (how wagering works, how provably fair hashing works, blockchain confirmation times, house edge maths) are fine to explain without a source. StakeBet's published house edges: Coinflip 1%; Dice, Mines, Plinko, Limbo 2%; Crash 3%.
- Be honest about StakeBet's weaknesses where relevant: no gambling licence, no sportsbook, launched 2026, every withdrawal approved by a person, withdrawals paused while a welcome bonus has wagering left. Say that the site is run by StakeBet's team whenever you recommend StakeBet.
- No promises of winnings, no "guaranteed", no "risk-free". Responsible tone; mention that gambling can be addictive when the topic is strategy or bankroll.
- Write for a reader who searched the target query: answer it in the first two sentences, then go deeper. Plain words, short paragraphs, specific numbers only where they are general maths or come from shortcodes.
- Use {{CTA}} at most twice. Link to existing pages from the list given (relative URLs like /bonuses/). End the page with {{RELATED}}.
- Write the whole page in the target language.

Output format: exactly one page file, nothing before or after it, in this shape:
---
slug: <slug>
lang: <lang, omit for English>
cluster: <lists|guides|reviews|compare|stakebet>
type: <article|list>
title: <25-65 characters, contains the target query naturally>
description: <80-160 characters>
---
<body HTML using the same tags and classes as the example page: div.eyebrow, h1, p.lede, h2, p, ul/ol, div.tbl>table, div.faq with <details><summary>Q</summary><p>A</p></details>>

Length: 800-1300 words of body text. Include an FAQ with 3-4 questions."""


def load(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def existing_pages():
    pages = []
    for name in sorted(os.listdir(os.path.join(ROOT, "content"))):
        src = load(os.path.join("content", name))
        slug = re.search(r"^slug:\s*(.*)$", src, re.M).group(1).strip()
        title = re.search(r"^title:\s*(.*)$", src, re.M).group(1).strip()
        pages.append((name, slug.strip("/"), title))
    return pages


def pick(keywords, pages, slug=None):
    have = {s for _, s, _ in pages}
    rows = keywords["keywords"]
    if slug:
        row = next((k for k in rows if k["slug"] == slug), None)
        if not row:
            sys.exit(f"no keyword row with slug {slug}")
        return row
    todo = sorted((k for k in rows if k["status"] == "planned" and k["slug"] not in have), key=lambda k: k["priority"])
    return todo[0] if todo else None


def next_filename(pages, slug):
    used = [int(n.split("-", 1)[0]) for n, _, _ in pages if n[:2].isdigit()]
    num = max([n for n in used if n < 99] + [49]) + 1
    return f"content/{num:02d}-{slug.replace('/', '-')}.html"


def draft(row, pages):
    import anthropic  # imported here so --dry-run works without the SDK

    page_list = "\n".join(f"/{s}/ - {t}" if s else f"/ - {t}" for _, s, t in pages)
    brief = (f"Target query: {row['q']}\nLanguage: {row['lang']}\nSlug: {row['slug']}\nTier: {row['tier']}\n"
             f"Notes: {row.get('note', 'none')}\n\nExisting pages you may link to:\n{page_list}")
    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=[{"type": "text", "text": STYLE, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "Casino data (the only source of casino facts):\n" + load("data/casinos.json")},
            {"type": "text", "text": "Example page for format and tone:\n" + load(EXAMPLE_PAGE)},
            {"type": "text", "text": brief + "\n\nWrite the page now."},
        ]}],
    ) as stream:
        msg = stream.get_final_message()

    if msg.stop_reason == "refusal":
        sys.exit(f"model refused: {getattr(msg.stop_details, 'category', None)}")
    if msg.stop_reason == "max_tokens":
        sys.exit("draft was cut off at max_tokens")
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    m = re.search(r"^---\n.*?\n---\n.*", text, re.S | re.M)
    if not m:
        sys.exit("model output had no front-matter page:\n" + text[:500])
    out = m.group(0).rstrip() + "\n"
    got_slug = re.search(r"^slug:\s*(.*)$", out, re.M).group(1).strip().strip("/")
    if got_slug != row["slug"]:
        out = re.sub(r"^slug:.*$", f"slug: {row['slug']}", out, count=1, flags=re.M)
    print(f"model={msg.model} in={msg.usage.input_tokens} out={msg.usage.output_tokens} "
          f"cache_read={msg.usage.cache_read_input_tokens}", file=sys.stderr)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--dry-run", action="store_true", help="print the pick and target file, call nothing")
    args = ap.parse_args()

    keywords = json.loads(load("data/keywords.json"))
    pages = existing_pages()
    row = pick(keywords, pages, args.slug)
    if not row:
        print("nothing planned: every planned keyword already has a page")
        return
    target = next_filename(pages, row["slug"])
    print(f"drafting '{row['q']}' ({row['lang']}) -> /{row['slug']}/ in {target}")
    if args.dry_run:
        return

    page = draft(row, pages)
    with open(os.path.join(ROOT, target), "w", encoding="utf-8") as f:
        f.write(page)
    row["status"] = "drafted"
    with open(os.path.join(ROOT, "data", "keywords.json"), "w", encoding="utf-8") as f:
        json.dump(keywords, f, ensure_ascii=False, indent=2)
        f.write("\n")
    # Outputs for the workflow's PR step.
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"query={row['q']}\nslug={row['slug']}\nfile={target}\n")


if __name__ == "__main__":
    main()
