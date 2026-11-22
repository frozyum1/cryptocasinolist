#!/usr/bin/env python3
"""Unit tests for the autopilot's decisions. No network, no API keys.

  python3 -m unittest discover -s seo -p 'test_*.py'
"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build  # noqa: E402
import autopilot  # noqa: E402
import discover  # noqa: E402
import draft  # noqa: E402
import intent  # noqa: E402
import metrics  # noqa: E402

D = datetime.date(2026, 11, 16)


def ago(days):
    return (D - datetime.timedelta(days=days)).isoformat()


class Intent(unittest.TestCase):
    def test_navigational_searches_are_worth_nothing(self):
        for q in ("usdt0 official website", "stake login", "stake.us", "usdt0 usdt0.today", "bc game app download"):
            self.assertEqual(intent.classify(q), "navigational", q)
            self.assertEqual(intent.score({"q": q, "impressions": 20000}), 0)

    def test_bare_crypto_is_not_casino_payment_intent(self):
        for q in ("usdt0", "bitcoin price", "crypto wallet", "what is bitcoin"):
            self.assertEqual(intent.classify(q), "general_crypto", q)

    def test_casino_searches_keep_their_intent(self):
        self.assertEqual(intent.classify("usdt casino"), "choose_casino")
        self.assertEqual(intent.classify("crypto casino no deposit bonus"), "bonus")
        self.assertEqual(intent.classify("how to withdraw usdt"), "play")
        self.assertEqual(intent.classify("plinko odds"), "game_guide")
        self.assertEqual(intent.classify("best crypto wallet for casino deposits"), "choose_casino")
        self.assertEqual(intent.classify("minesweeper online free"), "other")

    def test_worth_covering_drops_what_no_page_can_answer(self):
        self.assertEqual(intent.worth_covering(["usdt0", "usdt0 website", "usdt casino"]), ["usdt casino"])
        self.assertEqual(intent.worth_covering(["usdt0", "usdt0 official website"]), [])


class Discovery(unittest.TestCase):
    KEYWORDS = {"keywords": [{"q": "mines game", "related": ["mines casino game"], "status": "live", "slug": "g"}]}

    def cands(self, *qs):
        return [{"q": q, "lang": "en", "impressions": 100 - i} for i, q in enumerate(qs)]

    def test_known_and_related_queries_are_not_sent_again(self):
        fresh = discover.fresh_candidates(self.cands("mines game", "mines casino game", "keno odds"), self.KEYWORDS, {}, D)
        self.assertEqual([c["q"] for c in fresh], ["keno odds"])

    def test_recently_triaged_queries_wait_out_the_window(self):
        seen = {"keno odds|en": ago(10), "limbo strategy|en": ago(discover.SEEN_DAYS + 1)}
        fresh = discover.fresh_candidates(self.cands("keno odds", "limbo strategy", "dice odds"), self.KEYWORDS, seen, D)
        self.assertEqual(sorted(c["q"] for c in fresh), ["dice odds", "limbo strategy"])

    def test_same_query_in_another_language_is_separate(self):
        seen = {"casino bitcoin|es": ago(1)}
        c = [{"q": "casino bitcoin", "lang": "pt", "impressions": 50}]
        self.assertEqual(len(discover.fresh_candidates(c, self.KEYWORDS, seen, D)), 1)

    def test_junk_never_reaches_triage_and_batch_is_capped(self):
        many = self.cands("stake login", "bitcoin price", *[f"casino topic {i}" for i in range(300)])
        fresh = discover.fresh_candidates(many, self.KEYWORDS, {}, D)
        self.assertEqual(len(fresh), discover.TRIAGE_BATCH)
        self.assertNotIn("stake login", [c["q"] for c in fresh])
        self.assertNotIn("bitcoin price", [c["q"] for c in fresh])


class DiscoveryBatches(unittest.TestCase):
    def test_each_batch_sees_new_queries_and_results_are_combined(self):
        calls = []

        def fake_call(system, blocks, **kw):
            listing = blocks[1].split("\n")[1:-2]
            calls.append(len([l for l in listing if l.strip()]))
            first = listing[0].split(" [")[0]
            return {"pages": [{"q": first, "lang": "en", "slug": "guides/" + first.replace(" ", "-"), "tier": "long",
                               "intent": "game_guide", "merge_into": "", "related": []}]}
        cands = [{"q": f"casino topic {i:03d}", "lang": "en", "impressions": 1000 - i} for i in range(discover.TRIAGE_BATCH * 2 + 10)]
        seen, keywords, real = {}, {"keywords": []}, discover.llm.call
        discover.llm.call = fake_call
        try:
            found = []
            for _ in range(3):
                rows, _m = discover.triage(cands, {"keywords": keywords["keywords"] + found}, [], seen, D)
                found += rows
        finally:
            discover.llm.call = real
        self.assertEqual(calls, [discover.TRIAGE_BATCH, discover.TRIAGE_BATCH, 10])
        self.assertEqual([r["q"] for r in found], ["casino topic 000", "casino topic 150", "casino topic 300"])
        self.assertEqual(len(seen), len(cands))


class Drafting(unittest.TestCase):
    def test_failed_topics_wait_behind_untried_ones(self):
        kw = {"keywords": [
            {"q": "a", "slug": "a", "status": "planned", "priority": 40, "impressions": 900, "intent": "bonus", "fails": 1},
            {"q": "b", "slug": "b", "status": "planned", "priority": 40, "impressions": 10, "intent": "bonus"},
        ]}
        self.assertEqual(draft.pick(kw, [])["q"], "b")


def refresh(file, days, outcome, reason="thin content: 300 words", **extra):
    return dict({"date": ago(days), "action": "refresh", "file": file, "reason": reason, "outcome": outcome}, **extra)


class RefreshQueue(unittest.TestCase):
    THIN = ["content/a.html: 292 words, below 600 for a article page (thin content)",
            "content/b.html: 347 words, below 600 for a article page (thin content)",
            "content/about.html: 100 words, below 120 for a page page (thin content)"]
    SLUGS = {"content/a.html": "reviews/a", "content/b.html": "reviews/b", "content/about.html": "about"}

    def files(self, log, opps=()):
        return [f for f, _, _ in autopilot.refresh_candidates(log, list(opps), self.THIN, self.SLUGS, D)]

    def test_thinnest_first_and_exempt_pages_never(self):
        self.assertEqual(self.files([]), ["content/a.html", "content/b.html"])

    def test_published_refresh_blocks_for_the_cooldown(self):
        self.assertEqual(self.files([refresh("content/a.html", 44, "published")]), ["content/b.html"])
        self.assertEqual(self.files([refresh("content/a.html", 46, "published")]), ["content/a.html", "content/b.html"])

    def test_failed_refresh_blocks_for_a_week_only(self):
        # The bug this replaces: a discarded try on 31 Oct kept the page out until mid-December.
        for outcome in ("discarded", "held back", "llm error", "PR https://example.invalid/pull/2"):
            self.assertEqual(self.files([refresh("content/a.html", 3, outcome)]), ["content/b.html"], outcome)
            self.assertEqual(self.files([refresh("content/a.html", 16, outcome)]), ["content/a.html", "content/b.html"], outcome)

    def test_three_failures_leave_the_page_alone(self):
        log = [refresh("content/a.html", d, "held back") for d in (30, 20, 10)]
        self.assertEqual(self.files(log), ["content/b.html"])

    def test_target_already_covered_by_a_published_refresh_is_dropped(self):
        log = [refresh("content/c.html", 60, "published", reason="also cover these searches: stake.us; stake us; stake usa")]
        again = {"file": "content/c.html", "impressions": 9000, "reason": "also cover these searches: stake us; stake usa"}
        new = {"file": "content/c.html", "impressions": 9000, "reason": "also cover these searches: stake us; stake sweepstakes"}
        self.assertNotIn("content/c.html", self.files(log, [again]))
        self.assertEqual(self.files(log, [new])[0], "content/c.html")

    def test_discovery_targets_come_before_thin_pages_without_duplicates(self):
        opp = {"file": "content/b.html", "impressions": 500, "reason": "also cover these searches: x casino", "queries": ["x casino"]}
        self.assertEqual(self.files([], [opp]), ["content/b.html", "content/a.html"])

    def test_next_draft_starts_from_the_last_findings(self):
        log = [refresh("content/a.html", 9, "held back", findings=["names games not in the data"])]
        self.assertEqual(autopilot.last_findings(log, "content/a.html"), "- names games not in the data")
        self.assertIsNone(autopilot.last_findings(log, "content/b.html"))


class Report(unittest.TestCase):
    def test_findings_are_capped(self):
        rep = {"unsupported_claims": ["x" * 900], "rule_violations": ["r"], "quality_issues": ["q"] * 10}
        out = autopilot.findings(rep)
        self.assertEqual(len(out), 6)
        self.assertEqual(len(out[0]), 400)
        self.assertEqual(autopilot.findings({"problems": ["build fails"]}), ["build fails"])

    def test_needs_attention_names_what_only_a_person_can_fix(self):
        warnings = ["data: Stake facts last verified 2026-09-05; re-check on the casino itself",
                    "data: Stake has no test_log entries, so no page may claim we deposited or withdrew there",
                    'content/10-review-lumenbet.html: "We deposited USDT…" — hands-on claim that names no casino; say which one']
        text = "\n".join(autopilot.needs_attention([{"status": "planned"}] * 2, warnings))
        self.assertIn("Only 2 planned topics", text)
        self.assertIn("Stake (2026-09-05)", text)
        self.assertIn("No real deposit/withdrawal test is recorded for: Stake", text)
        self.assertIn("content/10-review-lumenbet.html", text)
        self.assertEqual(autopilot.needs_attention([{"status": "planned"}] * 9, []), [])


class Metrics(unittest.TestCase):
    def test_index_summary(self):
        s = metrics.summarise_index([("/", "Submitted and indexed", "PASS"),
                                     ("/a/", "Crawled - currently not indexed", "NEUTRAL"),
                                     ("/b/", "Discovered - currently not indexed", "NEUTRAL")])
        self.assertEqual((s["checked"], s["indexed"]), (3, 1))
        self.assertEqual(s["not_indexed"], ["/a/", "/b/"])
        self.assertEqual(s["states"]["Submitted and indexed"], 1)

    def test_bing_summary_uses_the_window_and_merges_days(self):
        def day(n):
            ms = int(datetime.datetime(2026, 11, 16).timestamp() * 1000) - n * 86400000
            return "/Date(%d-0700)/" % ms
        traffic = [{"Date": day(2), "Clicks": 1, "Impressions": 10}, {"Date": day(40), "Clicks": 9, "Impressions": 90}]
        queries = [{"Date": day(2), "Query": "Mines Game", "Clicks": 1, "Impressions": 4, "AvgImpressionPosition": 12},
                   {"Date": day(5), "Query": "mines game", "Clicks": 0, "Impressions": 3, "AvgImpressionPosition": 9},
                   {"Date": day(50), "Query": "old", "Clicks": 5, "Impressions": 50, "AvgImpressionPosition": 1}]
        s = metrics.summarise_bing(traffic, queries, D)
        self.assertEqual((s["clicks"], s["impressions"]), (1, 10))
        self.assertEqual(s["queries"], [{"key": "mines game", "clicks": 1, "impressions": 7, "position": 9}])

    def test_snapshot_is_weekly_and_replaces_same_day(self):
        self.assertTrue(metrics.due([], D))
        self.assertFalse(metrics.due([{"date": ago(6)}], D))
        self.assertTrue(metrics.due([{"date": ago(7)}], D))
        h = metrics.record([{"date": "2026-11-16", "pages": 1}], {"date": "2026-11-16", "pages": 2})
        self.assertEqual(h, [{"date": "2026-11-16", "pages": 2}])

    def test_report_shows_change_and_what_was_not_measured(self):
        prev = {"date": "2026-11-09", "google": {"clicks": 0, "impressions": 3, "position": 40.0},
                "index": {"checked": 50, "indexed": 4, "states": {}, "not_indexed": []}}
        cur = {"date": "2026-11-16", "window_days": 28, "pages": 51,
               "google": {"clicks": 2, "impressions": 30, "position": 31.5,
                          "queries": [{"key": "mines game", "clicks": 1, "impressions": 20, "position": 18.0}], "pages": []},
               "index": {"checked": 51, "indexed": 9, "states": {"Submitted and indexed": 9, "Discovered - currently not indexed": 42},
                         "not_indexed": ["/x/"]},
               "sitemap": "submitted", "notes": ["bing: HTTPError"]}
        text = "\n".join(metrics.report_lines([prev, cur]))
        self.assertIn("| Google | 2 (+2) | 30 (+27) | 31.5 |", text)
        self.assertIn("| Bing | not measured | | |", text)
        self.assertIn("indexed **9 of 51** pages (+5)", text)
        self.assertIn("Discovered - currently not indexed: 42", text)
        self.assertIn("| mines game | 20 | 1 | 18.0 |", text)
        self.assertIn("Not measured: bing: HTTPError", text)
        self.assertIn("No snapshot yet", "\n".join(metrics.report_lines([])))

    def test_sitemap_line(self):
        entry = {"path": metrics.SITEMAP, "lastDownloaded": "2026-11-10T04:12:00.000Z", "errors": "0", "warnings": "0"}
        self.assertEqual(metrics.describe_sitemap(entry, True), "submitted, last read by Google 2026-11-10, re-read requested")
        self.assertIn("needs Full permission", metrics.describe_sitemap(entry, False))
        self.assertIn("2 errors", metrics.describe_sitemap(dict(entry, errors="2"), True))
        self.assertEqual(metrics.describe_sitemap(None, True), "NOT submitted (submitted now)")
        self.assertIn("could not be submitted", metrics.describe_sitemap(None, False))

    def test_missing_credentials_are_noted_not_fatal(self):
        saved = {k: os.environ.pop(k, None) for k in ("GSC_SERVICE_ACCOUNT_JSON", "BING_WEBMASTER_API_KEY")}
        try:
            snap = metrics.collect({"pages": [{"indexable": True, "url": "https://cryptocasinolist.io/"}]}, D)
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
        self.assertEqual(snap["pages"], 1)
        self.assertEqual(len(snap["notes"]), 2)
        self.assertNotIn("google", snap)

    def test_bing_site_status(self):
        self.assertEqual(metrics.bing_site_status([{"Url": "https://cryptocasinolist.io/", "IsVerified": True}]), "verified")
        self.assertEqual(metrics.bing_site_status([{"Url": "http://www.cryptocasinolist.io", "IsVerified": False}]),
                         "added but NOT verified")
        self.assertIn("NOT added", metrics.bing_site_status([{"Url": "https://example.com/", "IsVerified": True}]))
        self.assertIn("NOT added", metrics.bing_site_status([]))
        text = "\n".join(metrics.report_lines([{"date": "2026-11-16", "bing": {"clicks": 0, "impressions": 0, "site": "verified"}}]))
        self.assertIn("Site in Bing Webmaster Tools: verified.", text)


class Site(unittest.TestCase):
    def page(self, slug, **kw):
        return ({"slug": slug, "title": "T " + slug, "description": "D " + slug, **kw}, "")

    def test_hub_lists_every_page_under_it(self):
        entries = [self.page("reviews/a"), self.page("reviews/b"), self.page("reviews/old", redirect="reviews/a"),
                   self.page("reviews/hidden", noindex="true"), self.page("es/reviews/c", lang="es")]
        hubs = build.hub_entries(entries)
        self.assertEqual([m["slug"] for m, _ in hubs], ["reviews"])
        meta, body = hubs[0]
        self.assertEqual(meta["type"], "hub")
        self.assertIn('href="/reviews/a/"', body)
        self.assertIn('href="/reviews/b/"', body)
        for absent in ("old", "hidden", "/es/"):
            self.assertNotIn(absent, body)

    def test_no_hub_for_one_page_or_a_taken_url(self):
        self.assertEqual(build.hub_entries([self.page("guides/a")]), [])
        self.assertEqual(build.hub_entries([self.page("guides"), self.page("guides/a"), self.page("guides/b")]), [])

    def test_breadcrumb_only_names_urls_that_exist(self):
        meta = {"title": "Stake review"}
        with_hub = build.breadcrumb(meta, "en", "reviews/stake", {"reviews", "reviews/stake"})
        self.assertEqual([i["item"] for i in with_hub], [build.SITE + "/", build.SITE + "/reviews/", build.SITE + "/reviews/stake/"])
        self.assertEqual([i["position"] for i in with_hub], [1, 2, 3])
        without = build.breadcrumb({"title": "Ruleta"}, "es", "es/guides/ruleta", {"es", "es/guides/ruleta"})
        self.assertEqual([i["item"] for i in without], [build.SITE + "/es/", build.SITE + "/es/guides/ruleta/"])
        self.assertEqual([i["position"] for i in without], [1, 2])

    def test_feed_is_newest_first_without_hubs_or_hidden_pages(self):
        def p(slug, published, **kw):
            return {"slug": slug, "url": build.url_of(slug), "title": "A & B " + slug, "description": "d", "lastmod": published,
                    "published": published, "type": "article", "indexable": True, **kw}
        feed = build.atom_feed([p("old", "2026-09-04"), p("new", "2026-11-16"), p("guides", "2026-11-16", type="hub"),
                                p("secret", "2026-11-16", indexable=False), p("", "2026-11-16")])
        self.assertLess(feed.index("/new/"), feed.index("/old/"))
        self.assertEqual(feed.count("<entry>"), 2)
        self.assertIn("A &amp; B new", feed)
        self.assertNotIn("secret", feed)


if __name__ == "__main__":
    unittest.main()


class EmptySlugRead(unittest.TestCase):
    """The homepage's slug is empty. Reading it must not swallow the next front-matter line."""

    def test_refresh_reads_empty_slug_as_empty(self):
        import re as _re
        page = "---\nslug:\ni18n: home\ntitle: T\n---\nbody\n"
        self.assertEqual(_re.search(r"^slug:[ \t]*(.*)$", page, _re.M).group(1).strip().strip("/"), "")

    def test_extract_page_keeps_root_slug(self):
        import draft
        out = draft.extract_page("---\nslug: whatever\ni18n: home\n---\nbody\n", "")
        self.assertIn("\nslug: \ni18n: home\n", out)
