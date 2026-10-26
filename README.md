# cryptocasinolist.io

Static comparison site. `python3 build.py` renders `content/*.html` (front-matter + body) through `layout.html` into `dist/`, plus `sitemap.xml` and `robots.txt`. No dependencies.

Referral links are generated from `{{REF}}` in content: `https://lumenbet.io/ref/QQ6Z5TTZ?c=ccl&s=<page-slug>` (no `lp`, so the click goes straight to registration with the code applied).

## How the SEO system works

| Piece | What it does |
| --- | --- |
| `data/casinos.json` | Every casino fact the site prints, with `verified_at` dates and a `test_log` per casino. Change a fact here and every page that shows it follows. |
| Shortcodes in `content/*.html` | `{{TABLE:<preset>}}`, `{{VERSUS:a,b}}`, `{{FACT:id.path}}`, `{{TESTLOG:id}}`, `{{MONTH}}`, `{{DATA_MONTH}}`, `{{CTA}}`, `{{RELATED}}`. Documented at the top of `build.py`. |
| `build.py` | Pulls the live Lumenbet welcome bonus (falls back to the data file if the API is unreachable), expands shortcodes, generates BreadcrumbList / Article / ItemList / FAQPage / WebSite JSON-LD, related-page links, hreflang, and a sitemap whose `lastmod` is each page's real last change (git), not the build date. |
| `seo/check.py` | Quality gate: duplicate titles/descriptions, title and description length, thin content, broken internal links, unknown shortcodes, stale facts, empty test logs. New pages must pass fully; existing pages only warn. |
| `seo/indexnow.py` | Pings Bing/Yandex (IndexNow) with the URLs that changed today. |
| `seo/autopilot.py` | Daily orchestrator: discovery (Mondays), one new page, one refreshed page, review, publish or PR, weekly report issue. |
| `seo/discover.py` | Keyword research from Bing Webmaster (related queries with impressions, 5 markets) and Google Search Console (page-2 rankings). Claude groups queries into pages. |
| `seo/draft.py` | Writes new pages and rewrites existing ones with Claude (`claude-opus-5`), facts only via shortcodes. |
| `seo/review.py` | Publish gate: banned claims, invented first-person tests, duplicate content (5-gram similarity), the quality gate, then an independent Claude fact-check against `data/casinos.json` (score 8/10 or more to publish). |
| `seo/llm.py` | Shared Claude call: streaming, adaptive thinking, refusal fallback, prompt caching. |
| `data/keywords.json` | The keyword plan: query, language, tier, target slug, status (`live`, `planned`, `drafted`, `skip`), priority. |

## Schedules (`.github/workflows/`)

- **pages.yml**: on every push to `main` and daily at 05:17 UTC: build, gate, deploy, IndexNow. The daily run rolls month-dated titles over on the 1st and re-reads the Lumenbet offer.
- **autopilot.yml**: daily 03:30 UTC. Publishes pages that pass review straight to `main` and triggers a deploy; anything that fails review becomes a PR. Repo variable `AUTOPILOT` = `on` (default), `pr-only` (every page waits for a merge) or `off`. `AUTOPILOT_NEW_PER_RUN` / `AUTOPILOT_REFRESH_PER_RUN` (default 1 each), `AUTOPILOT_MIN_SCORE` (default 8).
- **facts-review.yml**: 1st of each month: opens an issue listing every casino fact to re-verify.

Setup once: secrets `ANTHROPIC_API_KEY` (required), `BING_WEBMASTER_API_KEY` and `GSC_SERVICE_ACCOUNT_JSON` (optional, for discovery; add the service account's email as a user on the Search Console property), and Settings → Actions → General → "Allow GitHub Actions to create and approve pull requests".

## Rules

- Only add a `test_log` entry for a test that really happened, with its real date and numbers.
- Competitor facts are re-checked by hand; anything older than a month is labelled "not verified this month" automatically.
- No fabricated ratings, reviews or testimonials, and keep the ownership disclosure in the footer.

Local preview: `python3 build.py && python3 seo/check.py && python3 -m http.server -d dist 8000`.
