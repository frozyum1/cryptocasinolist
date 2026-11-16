#!/usr/bin/env python3
"""SEO autopilot for cryptocasinolist.io: runs daily in GitHub Actions, no human needed.

Each run:
  1. (Mondays, or --discover) find new queries and refresh targets from Bing / Search Console.
  2. Write one new page for the best planned keyword.
  3. Rewrite one existing page: a page-2 ranking from Search Console first, else the thinnest page.
  4. Every page goes through seo/review.py, with up to three drafts, each given the reviewer's
     findings on the one before. Publishable pages are committed to main and deployed. A page
     that still fails is thrown away and its findings are kept, so the next try starts from them;
     nothing waits for a person. A topic that fails on two days, or is rejected, is marked 'skip'.
  5. Once a week, measure the results (seo/metrics.py): clicks, impressions, indexed pages.
  6. (Mondays) open a weekly report issue: results first, then activity and what needs attention.

Discovery also runs when fewer than a week of planned topics is left, so the queue cannot run dry
between Mondays.

Controls (repo variables): AUTOPILOT=on | pr-only | off, AUTOPILOT_NEW_PER_RUN (default 1),
AUTOPILOT_REFRESH_PER_RUN (default 1), AUTOPILOT_MIN_SCORE (default 8). Not wired into the
workflow file, so they take their defaults unless added there: AUTOPILOT_ON_FAIL=retry | pr
(pr opens a pull request for a failed page, the old behaviour), AUTOPILOT_ATTEMPTS (default 3).

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
ON_FAIL = os.environ.get("AUTOPILOT_ON_FAIL", "retry")
MAX_ATTEMPTS = max(1, int(os.environ.get("AUTOPILOT_ATTEMPTS", "3")))
MAX_TOPIC_FAILS = 2           # days a new topic may fail review before it is skipped
REFRESH_COOLDOWN_DAYS = 45    # after a published refresh
REFRESH_RETRY_DAYS = 7        # after a failed one
REFRESH_MAX_FAILS = 3         # failed tries inside the cooldown window before the page is left alone
MIN_QUEUE = 7                 # planned topics; fewer than this triggers discovery on any day
DISCOVERY_MIN_GAP_DAYS = 3
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

def findings(report, limit=6):
    """The reviewer's objections, short enough to keep in the log and feed to the next draft."""
    items = report.get("problems") or (report.get("unsupported_claims", []) + report.get("rule_violations", [])
                                       + report.get("quality_issues", []))
    return [str(x)[:400] for x in items[:limit]]


def produce(kind, path, make, original=None, feedback=None):
    """make(feedback) returns page text. Returns (publishable, report, attempts).

    feedback: findings from an earlier day's failed try, so the first draft already avoids them.
    """
    report = {}
    for attempt in range(1, MAX_ATTEMPTS + 1):
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
    return False, report, MAX_ATTEMPTS


def ship(kind, path, title, ok, report):
    """Publish to main or open a PR. Returns a short outcome string."""
    if not USE_GIT:
        return "local only (--no-git)"
    if ok and MODE == "on":
        sh("git", "add", path)
        sh("git", "commit", "-m", f"autopilot {kind}: {title}\n\nReviewer score {report.get('score')}: {report.get('summary', '')}")
        return "published"
    if not ok and ON_FAIL != "pr":
        # Nobody merges these by hand, so a pull request is a dead end. The caller discards
        # the draft and keeps the findings for the next try.
        return "held back"
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
        ok, rep, attempts = produce("page", path, lambda fb: draft.write_new(row, pages, fb),
                                    feedback=row.get("feedback"))
        if rep.get("stage") == "llm":
            # The API failed (bad key, no credit, outage): nothing is wrong with
            # the topic, so it stays planned and is tried again next run.
            discard(path, existed=False)
            outcome = "llm error"
            print(f"::warning::Claude call failed, '{row['q']}' stays planned: {'; '.join(rep.get('problems', []))[:200]}")
            log.append({"date": TODAY, "action": "new", "q": row["q"], "file": path, "outcome": outcome,
                        "score": None, "attempts": attempts})
            return
        if rep.get("verdict") == "reject":
            discard(path, existed=False)
            row["status"] = "skip"
            row["note"] = f"autopilot {TODAY}: {rep.get('summary') or '; '.join(rep.get('problems', []))}"[:300]
            outcome = "skipped"
        else:
            title = re.search(r"^title:\s*(.*)$", open(os.path.join(ROOT, path), encoding="utf-8").read(), re.M).group(1)
            outcome = ship("page", path, title, ok, rep)
            if outcome == "published":
                row["status"] = "live"
                row.pop("fails", None)
                row.pop("feedback", None)
            elif outcome == "held back":
                discard(path, existed=False)
                row["fails"] = row.get("fails", 0) + 1
                row["feedback"] = "\n".join("- " + f for f in findings(rep))
                if row["fails"] >= MAX_TOPIC_FAILS:
                    row["status"] = "skip"
                    row["note"] = f"autopilot {TODAY}: failed review on {row['fails']} days; last: {rep.get('summary') or row['feedback']}"[:300]
            else:
                row["status"] = "drafted"
        jsave("data/keywords.json", keywords)
        entry = {"date": TODAY, "action": "new", "q": row["q"], "file": path, "outcome": outcome,
                 "score": rep.get("score"), "attempts": attempts}
        if outcome != "published":
            entry["findings"] = findings(rep)
        log.append(entry)
        done += 1


def reason_queries(entry):
    """The searches a refresh was asked to cover (from the entry, or parsed from an old log reason)."""
    if entry.get("queries"):
        return [q.lower() for q in entry["queries"]]
    reason = entry.get("reason", "")
    if not reason.startswith("also cover"):
        return []
    return [q.strip().lower() for q in reason.split(": ", 1)[-1].split(";") if q.strip()]


def refresh_candidates(log, opps, thin_warnings, slug_of, today):
    """[(file, reason, queries)] in the order to try them.

    A page is left alone for 45 days after a published refresh. A failed try (discarded, held
    back, or an unmerged pull request) only blocks it for a week, up to three failures: until
    2026-11-16 a failure counted like a success, which locked the four thinnest pages out for
    45 days each and stopped refreshes altogether. A target is also dropped when a published
    refresh of the same page already covered every search it lists.
    """
    def days_ago(e):
        return (today - datetime.date.fromisoformat(e["date"])).days

    blocked, covered = set(), {}
    by_file = {}
    for e in log:
        if e["action"] == "refresh":
            by_file.setdefault(e["file"], []).append(e)
    for f, entries in by_file.items():
        published = [e for e in entries if e["outcome"] == "published"]
        failed = [e for e in entries if e["outcome"] != "published" and days_ago(e) <= REFRESH_COOLDOWN_DAYS]
        covered[f] = {q for e in published for q in reason_queries(e)}
        if any(days_ago(e) <= REFRESH_COOLDOWN_DAYS for e in published):
            blocked.add(f)
        elif failed and (len(failed) >= REFRESH_MAX_FAILS or min(days_ago(e) for e in failed) < REFRESH_RETRY_DAYS):
            blocked.add(f)

    out = []
    for o in opps:
        queries = [q.lower() for q in (o.get("queries") or reason_queries(o))]
        already = queries and set(queries) <= covered.get(o["file"], set())
        if o["file"] not in blocked and not already:
            out.append((o["file"], o["reason"], queries))
    thin = []
    for w in thin_warnings:
        m = re.match(r"(content/\S+\.html): (\d+) words, below", w)
        if m and m.group(1) not in blocked and slug_of.get(m.group(1)) not in NEVER_REFRESH:
            thin.append((int(m.group(2)), m.group(1), f"thin content: {m.group(2)} words"))
    seen = {f for f, _, _ in out}
    out += [(f, r, []) for _, f, r in sorted(thin) if f not in seen]
    return out


def last_findings(log, path):
    """Findings from the most recent failed refresh of this page, for the next draft to avoid."""
    for e in reversed(log):
        if e["action"] == "refresh" and e["file"] == path:
            return "\n".join("- " + f for f in e.get("findings", [])) or None
    return None


def step_refresh(log):
    opps = jload("data/opportunities.json", {"refresh": []})["refresh"]
    gate = json.loads(sh(sys.executable, "seo/check.py", "--json", check=False))
    slug_of = {p["file"]: p["slug"] for p in jload("build-manifest.json", {"pages": []})["pages"]}
    todo = refresh_candidates(log, opps, gate["warnings"], slug_of, datetime.date.today())
    for path, reason, queries in todo[:REFRESH_PER_RUN]:
        original = open(os.path.join(ROOT, path), encoding="utf-8").read()
        print(f"refresh: {path} ({reason[:80]})")
        ok, rep, attempts = produce("refresh", path, lambda fb: draft.refresh(path, reason, draft.existing_pages(), fb),
                                    original, feedback=last_findings(log, path))
        if rep.get("stage") == "llm" or rep.get("verdict") == "reject":
            discard(path, existed=True)
            outcome = "llm error" if rep.get("stage") == "llm" else "discarded"
        else:
            title = re.search(r"^title:\s*(.*)$", open(os.path.join(ROOT, path), encoding="utf-8").read(), re.M).group(1)
            outcome = ship("refresh", path, title, ok, rep)
            if outcome != "published":
                discard(path, existed=True)
        entry = {"date": TODAY, "action": "refresh", "file": path, "reason": reason[:200], "outcome": outcome,
                 "score": rep.get("score"), "attempts": attempts}
        if queries:
            entry["queries"] = queries
        if outcome != "published":
            entry["findings"] = findings(rep)
        log.append(entry)


def needs_attention(keywords, gate_warnings):
    """What the autopilot cannot fix itself, for the weekly report."""
    lines = []
    planned = sum(1 for k in keywords if k["status"] == "planned")
    if planned < MIN_QUEUE:
        lines.append(f"Only {planned} planned topics are left (about {planned // max(NEW_PER_RUN, 1)} days of new pages). "
                     "Discovery runs every few days, not only on Mondays, until the queue is refilled.")
    stale = [w.split("data: ", 1)[1] for w in gate_warnings if w.startswith("data:") and "last verified" in w]
    if stale:
        lines.append("Casino facts past the 60-day check, printed as 'not verified this month' on the site: "
                     + "; ".join(s.split(" facts last verified ")[0] + " (" + s.split(" facts last verified ")[1].split(";")[0] + ")" for s in stale))
    untested = [w.split("data: ", 1)[1].split(" has no test_log")[0] for w in gate_warnings if "has no test_log" in w]
    if untested:
        lines.append("No real deposit/withdrawal test is recorded for: " + ", ".join(untested)
                     + ". Reviews cannot claim hands-on testing until `test_log` has entries.")
    claims = sorted({w.split(":", 1)[0] for w in gate_warnings if "hands-on claim" in w})
    if claims:
        lines.append("Pages that claim hands-on testing with nothing in the data behind it: " + ", ".join(claims))
    return lines


def weekly_report(log):
    import metrics
    since = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    week = [e for e in log if e["date"] >= since]
    kw = jload("data/keywords.json", {"keywords": []})["keywords"]
    planned = sum(1 for k in kw if k["status"] == "planned")
    gate = json.loads(sh(sys.executable, "seo/check.py", "--json", check=False))
    lines = metrics.report_lines(jload(metrics.HISTORY, []))
    attention = needs_attention(kw, gate["warnings"])
    if attention:
        lines += ["", "## Needs a person", ""] + [f"- {a}" for a in attention]
    lines += ["", f"## Autopilot activity {since} to {TODAY}", "",
              f"- Published: {sum(1 for e in week if e['outcome'] == 'published')}",
              f"- Failed review and held back for another try: {sum(1 for e in week if e['outcome'] == 'held back' or str(e['outcome']).startswith('PR'))}",
              f"- Skipped or discarded: {sum(1 for e in week if e['outcome'] in ('skipped', 'discarded'))}",
              f"- Keywords still planned: {planned}", "", "| Date | Action | Page | Outcome | Score | Drafts |", "| --- | --- | --- | --- | --- | --- |"]
    lines += [f"| {e['date']} | {e['action']} | {e.get('q') or e['file']} | {e['outcome']} | {e.get('score') or '-'} | {e.get('attempts') or '-'} |" for e in week]
    failed = [e for e in week if e.get("findings")]
    if failed:
        lines += ["", "Why pages were held back:", ""]
        for e in failed:
            lines.append(f"- **{e.get('q') or e['file']}** ({e['date']}): " + " / ".join(f[:200] for f in e["findings"][:3]))
    if USE_GIT:
        with open(os.path.join(ROOT, ".report.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        sh("gh", "issue", "create", "--title", f"SEO autopilot weekly report {TODAY}", "--body-file", ".report.md")
        os.remove(os.path.join(ROOT, ".report.md"))
    else:
        print("\n".join(lines))


def discovery_due(args, monday):
    if args.discover or monday:
        return True
    planned = sum(1 for k in jload("data/keywords.json", {"keywords": []})["keywords"] if k["status"] == "planned")
    last = jload("data/opportunities.json", {}).get("updated", "2000-01-01")
    gap = (datetime.date.today() - datetime.date.fromisoformat(last)).days
    return planned < MIN_QUEUE and gap >= DISCOVERY_MIN_GAP_DAYS


def measure(force=False):
    """Take the results snapshot when one is due (weekly, and always before a report). Never stops the run."""
    import metrics
    history = jload(metrics.HISTORY, [])
    if not (force or metrics.due(history)):
        return
    try:
        snap = metrics.collect(jload("build-manifest.json", {"pages": []}))
    except Exception as e:  # noqa: BLE001
        print(f"metrics failed: {type(e).__name__}: {e}")
        return
    jsave(metrics.HISTORY, metrics.record(history, snap))
    g, b, idx = snap.get("google") or {}, snap.get("bing") or {}, snap.get("index") or {}
    print(f"metrics: google {g.get('clicks', '-')} clicks / {g.get('impressions', '-')} impressions, "
          f"bing {b.get('clicks', '-')} / {b.get('impressions', '-')}, "
          f"indexed {idx.get('indexed', '-')} of {idx.get('checked', '-')}, sitemap {snap.get('sitemap', '-')}"
          + (f"; notes: {'; '.join(snap['notes'])}" if snap.get("notes") else ""))


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

    if discovery_due(args, monday):
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
    measure(force=monday)

    build()
    gate = subprocess.run([sys.executable, "seo/check.py"], cwd=ROOT)
    if gate.returncode != 0:
        raise SystemExit("final quality gate failed; nothing pushed")
    if USE_GIT:
        sh("git", "add", "data/keywords.json", "data/autopilot-log.json")
        for extra in ("data/opportunities.json", "data/seen-queries.json", "data/metrics.json"):
            if os.path.exists(os.path.join(ROOT, extra)):
                sh("git", "add", extra)
        if sh("git", "status", "--porcelain", "--", "data", check=False):
            sh("git", "commit", "-m", f"autopilot: keyword plan and log {TODAY}")
        sh("git", "push", "origin", "main")
        if any(e["date"] == TODAY and e["outcome"] == "published" for e in log):
            sh("gh", "workflow", "run", "pages.yml", "--ref", "main")
    if monday:
        weekly_report(log)


if __name__ == "__main__":
    main()
