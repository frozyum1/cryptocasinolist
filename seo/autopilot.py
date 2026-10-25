#!/usr/bin/env python3
"""SEO autopilot for cryptocasinolist.io: runs daily in GitHub Actions, no human needed.

Each run:
  1. (Mondays, or --discover) find new queries and refresh targets from Bing / Search Console.
  2. Write one new page for the best planned keyword.
  3. Rewrite one existing page: a page-2 ranking from Search Console first, else the thinnest page.
  4. Every page goes through seo/review.py. Publishable pages are committed to main and deployed;
     the rest become pull requests with the reviewer's findings. Rejected topics are marked 'skip'.
  5. (Mondays) open a weekly report issue.

Controls (repo variables): AUTOPILOT=on | pr-only | off, AUTOPILOT_NEW_PER_RUN (default 1),
AUTOPILOT_REFRESH_PER_RUN (default 1), AUTOPILOT_MIN_SCORE (default 8).

  python3 seo/autopilot.py [--discover] [--no-git]
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import draft  # noqa: E402
import llm  # noqa: E402
import review  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODE = os.environ.get("AUTOPILOT", "on")
NEW_PER_RUN = int(os.environ.get("AUTOPILOT_NEW_PER_RUN", "1"))
REFRESH_PER_RUN = int(os.environ.get("AUTOPILOT_REFRESH_PER_RUN", "1"))
REFRESH_COOLDOWN_DAYS = 45
NEVER_REFRESH = {"privacy", "404", "responsible-gambling", "about"}
TODAY = datetime.date.today().isoformat()
USE_GIT = True


def sh(*cmd, check=True):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()


def jload(path, default):
    p = os.path.join(ROOT, path)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def jsave(path, data):
    with open(os.path.join(ROOT, path), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def build():
    sh(sys.executable, "build.py")


# ── One unit of work: write, review (one retry with feedback), then ship ─────

def produce(kind, path, make, original=None):
    """make(feedback) returns page text. Returns (publishable, report, attempts)."""
    feedback, report = None, {}
    for attempt in (1, 2):
        try:
            text = make(feedback)
        except llm.LLMError as e:
            return False, {"stage": "llm", "problems": [str(e)], "feedback": str(e)}, attempt
        with open(os.path.join(ROOT, path), "w", encoding="utf-8") as f:
            f.write(text)
        try:
            ok, report = review.review(path, original)
        except llm.LLMError as e:
            return False, {"stage": "llm", "problems": [f"review failed: {e}"], "feedback": str(e)}, attempt
        print(f"  {kind} attempt {attempt}: {'PUBLISHABLE' if ok else 'not publishable'} "
              f"({report.get('stage')} score={report.get('score', '-')})")
        if ok or report.get("verdict") == "reject":
            return ok, report, attempt
        feedback = report.get("feedback")
    return False, report, 2


def ship(kind, path, title, ok, report):
    """Publish to main or open a PR. Returns a short outcome string."""
    if not USE_GIT:
        return "local only (--no-git)"
    if ok and MODE == "on":
        sh("git", "add", path)
        sh("git", "commit", "-m", f"autopilot {kind}: {title}\n\nReviewer score {report.get('score')}: {report.get('summary', '')}")
        return "published"
    branch = f"autopilot/{kind}-{re.sub(r'[^a-z0-9-]+', '-', os.path.basename(path)[:-5])}-{TODAY}"
    sh("git", "checkout", "-b", branch)
    sh("git", "add", path)
    sh("git", "commit", "-m", f"autopilot {kind} (needs review): {title}")
    sh("git", "push", "-u", "origin", branch)
    findings = report.get("problems") or (report.get("unsupported_claims", []) + report.get("rule_violations", []) + report.get("quality_issues", []))
    body = (f"The autopilot wrote this {kind} but did not publish it.\n\n"
            f"**Why:** {'autopilot is in pr-only mode' if ok else 'the review did not pass'} "
            f"(stage: {report.get('stage')}, score: {report.get('score', '-')}).\n\n"
            + "\n".join(f"- {x}" for x in findings[:20])
            + f"\n\n{report.get('summary', '')}\n\nMerge to publish, or close to discard.")
    url = sh("gh", "pr", "create", "--title", f"Autopilot {kind}: {title}", "--body", body, "--base", "main", "--head", branch)
    sh("git", "checkout", "main")
    return f"PR {url}"


def discard(path, existed):
    if existed:
        sh("git", "checkout", "--", path)
    elif os.path.exists(os.path.join(ROOT, path)):
        os.remove(os.path.join(ROOT, path))


# ── Steps ────────────────────────────────────────────────────────────────────

def step_new(log):
    keywords = jload("data/keywords.json", {"keywords": []})
    done = 0
    while done < NEW_PER_RUN:
        pages = draft.existing_pages()
        row = draft.pick(keywords, pages)
        if not row:
            print("new: nothing planned")
            return
        path = draft.next_filename(pages, row["slug"])
        print(f"new: '{row['q']}' -> {path}")
        ok, rep, attempts = produce("page", path, lambda fb: draft.write_new(row, pages, fb))
        if rep.get("stage") == "llm" or rep.get("verdict") == "reject":
            discard(path, existed=False)
            row["status"] = "skip"
            row["note"] = f"autopilot {TODAY}: {rep.get('summary') or '; '.join(rep.get('problems', []))}"[:300]
            outcome = "skipped"
        else:
            title = re.search(r"^title:\s*(.*)$", open(os.path.join(ROOT, path), encoding="utf-8").read(), re.M).group(1)
            outcome = ship("page", path, title, ok, rep)
            row["status"] = "live" if outcome == "published" else "drafted"
        jsave("data/keywords.json", keywords)
        log.append({"date": TODAY, "action": "new", "q": row["q"], "file": path, "outcome": outcome,
                    "score": rep.get("score"), "attempts": attempts})
        done += 1


def refresh_candidates(log):
    recent = {e["file"] for e in log if e["action"] == "refresh" and e["date"] >= (
        datetime.date.today() - datetime.timedelta(days=REFRESH_COOLDOWN_DAYS)).isoformat()}
    opps = jload("data/opportunities.json", {"refresh": []})["refresh"]
    out = [(o["file"], o["reason"]) for o in opps if o["file"] not in recent]
    gate = json.loads(sh(sys.executable, "seo/check.py", "--json", check=False))
    manifest = jload("build-manifest.json", {"pages": []})
    slug_of = {p["file"]: p["slug"] for p in manifest["pages"]}
    thin = []
    for w in gate["warnings"]:
        m = re.match(r"(content/\S+\.html): (\d+) words, below", w)
        if m and m.group(1) not in recent and slug_of.get(m.group(1)) not in NEVER_REFRESH:
            thin.append((int(m.group(2)), m.group(1), f"thin content: {m.group(2)} words"))
    out += [(f, r) for _, f, r in sorted(thin)]
    return out


def step_refresh(log):
    for path, reason in refresh_candidates(log)[:REFRESH_PER_RUN]:
        original = open(os.path.join(ROOT, path), encoding="utf-8").read()
        print(f"refresh: {path} ({reason[:80]})")
        ok, rep, attempts = produce("refresh", path, lambda fb: draft.refresh(path, reason, draft.existing_pages(), fb), original)
        if rep.get("stage") == "llm" or rep.get("verdict") == "reject":
            discard(path, existed=True)
            outcome = "discarded"
        else:
            title = re.search(r"^title:\s*(.*)$", open(os.path.join(ROOT, path), encoding="utf-8").read(), re.M).group(1)
            outcome = ship("refresh", path, title, ok, rep)
            if outcome != "published":
                discard(path, existed=True)
        log.append({"date": TODAY, "action": "refresh", "file": path, "reason": reason[:200], "outcome": outcome,
                    "score": rep.get("score"), "attempts": attempts})


def weekly_report(log):
    since = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    week = [e for e in log if e["date"] >= since]
    kw = jload("data/keywords.json", {"keywords": []})["keywords"]
    planned = sum(1 for k in kw if k["status"] == "planned")
    lines = [f"Autopilot activity {since} to {TODAY}.", "",
             f"- Published: {sum(1 for e in week if e['outcome'] == 'published')}",
             f"- Sent for review (PR): {sum(1 for e in week if str(e['outcome']).startswith('PR'))}",
             f"- Skipped or discarded: {sum(1 for e in week if e['outcome'] in ('skipped', 'discarded'))}",
             f"- Keywords still planned: {planned}", "", "| Date | Action | Page | Outcome | Score |", "| --- | --- | --- | --- | --- |"]
    lines += [f"| {e['date']} | {e['action']} | {e.get('q') or e['file']} | {e['outcome']} | {e.get('score') or '-'} |" for e in week]
    if USE_GIT:
        sh("gh", "issue", "create", "--title", f"SEO autopilot weekly report {TODAY}", "--body", "\n".join(lines))
    else:
        print("\n".join(lines))


def main():
    global USE_GIT
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--no-git", action="store_true", help="write files locally, no commits, PRs or issues")
    args = ap.parse_args()
    USE_GIT = not args.no_git
    if MODE == "off":
        print("autopilot is off (repo variable AUTOPILOT=off)")
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("::warning::ANTHROPIC_API_KEY secret is not set; autopilot skipped")
        return
    monday = datetime.date.today().weekday() == 0
    log = jload("data/autopilot-log.json", [])
    build()

    if args.discover or monday:
        import discover
        sys.argv = ["discover.py"]
        try:
            discover.main()
        except Exception as e:  # noqa: BLE001 - a failed discovery must not stop writing
            print(f"discover failed: {type(e).__name__}: {e}")
        build()
    step_new(log)
    build()
    step_refresh(log)
    jsave("data/autopilot-log.json", log)

    build()
    gate = subprocess.run([sys.executable, "seo/check.py"], cwd=ROOT)
    if gate.returncode != 0:
        raise SystemExit("final quality gate failed; nothing pushed")
    if USE_GIT:
        sh("git", "add", "data/keywords.json", "data/autopilot-log.json")
        if os.path.exists(os.path.join(ROOT, "data/opportunities.json")):
            sh("git", "add", "data/opportunities.json")
        if sh("git", "status", "--porcelain", "--", "data", check=False):
            sh("git", "commit", "-m", f"autopilot: keyword plan and log {TODAY}")
        sh("git", "push", "origin", "main")
        if any(e["date"] == TODAY and e["outcome"] == "published" for e in log):
            sh("gh", "workflow", "run", "pages.yml", "--ref", "main")
    if monday:
        weekly_report(log)


if __name__ == "__main__":
    main()
