#!/usr/bin/env python3
"""Decide whether an AI-written page may publish without a human.

A page publishes only when every deterministic check passes AND an independent
Claude review (which never saw the drafting prompt) finds no unsupported claim
and scores it 8/10 or more. Anything else goes to a pull request.

  python3 seo/review.py content/52-guides-plinko-odds.html [--original <old file>]
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIN_SCORE = int(os.environ.get("AUTOPILOT_MIN_SCORE", "8"))
MAX_SIMILARITY = 0.30
BANNED = [r"\bguarantee[ds]? (you |a |to )?(win|wins|profit|profits|returns|payouts?|money)\b", r"\bguaranteed (win|profit|returns?)\b",
          r"\brisk[- ]free (bet|bonus|play|money)", r"\bsure win\b", r"\bfoolproof\b",
          r"\bnever lose\b", r"\bsure[- ]fire\b", r"гарантированн\w* (выигрыш|прибыл)", r"\bбез риска\b"]
FIRST_PERSON_TEST = r"\b(we|our team) (tested|deposited|withdrew|played|signed up|claimed|verified)\b|\bмы (протестировали|внесли|вывели)\b"

REVIEW_SYSTEM = """You are the last check before a page on a gambling comparison site goes live with no human review. Be strict: a false claim here can mislead players and get the site penalised by Google.

You receive the casino data file (the only allowed source of casino-specific facts) and a page. Shortcodes like {{TABLE:...}}, {{FACT:...}}, {{VERSUS:...}} are filled from that data at build time and are always fine.

Flag as unsupported: any casino-specific fact typed in prose that is not in the data or contradicts it (bonus sizes, licences, coin counts, game counts, withdrawal times, KYC rules, dates, rankings by others, awards, user counts); any claim of testing, deposits or screenshots; any invented statistic, quote, testimonial or study; any promise of winning or strategy claimed to beat the house edge.
Allowed without data: general explanations of how gambling, wagering, provably fair hashing, blockchains and house edge work, and StakeBet's published house edges (Coinflip 1%; Dice, Mines, Plinko, Limbo 2%; Crash 3%; Keno 4%).

Score 0-10 for how well the page serves someone who searched its title's topic (depth, accuracy, clarity, honesty about StakeBet's weaknesses where relevant, disclosure that the site is run by StakeBet's team when it recommends StakeBet). verdict: publish only if there is nothing unsupported and the score is 8 or more; revise if fixable; reject if the topic itself is a problem."""

SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "verdict": {"type": "string", "enum": ["publish", "revise", "reject"]},
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
        "rule_violations": {"type": "array", "items": {"type": "string"}},
        "quality_issues": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["score", "verdict", "unsupported_claims", "rule_violations", "quality_issues", "summary"],
    "additionalProperties": False,
}


def body_text(src):
    body = src.split("\n---\n", 1)[-1]
    body = re.sub(r"(?s)<script.*?</script>", " ", body)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>|\{\{[^}]*\}\}", " ", body)).strip().lower()


def shingles(text, n=5):
    words = re.findall(r"\w+", text)
    return {" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def deterministic(path, original=None):
    problems = []
    src = open(os.path.join(ROOT, path), encoding="utf-8").read()
    text = body_text(src)

    for pat in BANNED:
        if re.search(pat, text):
            problems.append(f"banned phrase matching /{pat}/")
    old_tests = len(re.findall(FIRST_PERSON_TEST, body_text(original))) if original else 0
    if len(re.findall(FIRST_PERSON_TEST, text)) > old_tests:
        problems.append("claims first-person testing that the data does not record")

    mine = shingles(text)
    for name in os.listdir(os.path.join(ROOT, "content")):
        other = os.path.join("content", name)
        if other == path:
            continue
        theirs = shingles(body_text(open(os.path.join(ROOT, other), encoding="utf-8").read()))
        if mine and theirs:
            sim = len(mine & theirs) / len(mine | theirs)
            if sim > MAX_SIMILARITY:
                problems.append(f"{sim:.0%} similar to {other} (duplicate content)")

    subprocess.run([sys.executable, "build.py"], cwd=ROOT, check=True, capture_output=True)
    gate = json.loads(subprocess.run([sys.executable, "seo/check.py", "--json"], cwd=ROOT,
                                     capture_output=True, text=True).stdout)
    problems += [e for e in gate["errors"] if e.startswith(path)]
    # A refreshed page is held to the new-page bar too: thin or over-long titles are not "existing" debt any more.
    problems += [w for w in gate["warnings"] if w.startswith(path) and "words" in w]
    return problems


def ai_review(path):
    page = open(os.path.join(ROOT, path), encoding="utf-8").read()
    data = open(os.path.join(ROOT, "data", "casinos.json"), encoding="utf-8").read()
    return llm.call(REVIEW_SYSTEM, ["Casino data:\n" + data, "Page to review:\n" + page + "\n\nReview it."],
                    effort="high", schema=SCHEMA, max_tokens=32000)


def review(path, original=None):
    """Returns (publishable: bool, report: dict)."""
    det = deterministic(path, original)
    if det:
        return False, {"stage": "deterministic", "problems": det, "feedback": "\n".join("- " + p for p in det)}
    r = ai_review(path)
    ok = r["verdict"] == "publish" and r["score"] >= MIN_SCORE and not r["unsupported_claims"] and not r["rule_violations"]
    fb = "\n".join("- " + x for x in r["unsupported_claims"] + r["rule_violations"] + r["quality_issues"])
    return ok, {"stage": "ai", **r, "feedback": fb}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--original")
    a = ap.parse_args()
    orig = open(a.original, encoding="utf-8").read() if a.original else None
    ok, rep = review(a.path, orig)
    print(json.dumps({"publishable": ok, **rep}, ensure_ascii=False, indent=1))
    sys.exit(0 if ok else 1)
