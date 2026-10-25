# cryptocasinolist.io

Static comparison site. `python3 build.py` renders `content/*.html` (front-matter + body) through `layout.html` into `dist/`, plus `sitemap.xml` and `robots.txt`. No dependencies.

Referral links are generated from `{{REF}}` in content: `https://stakebet.gg/ref/QQ6Z5TTZ?c=ccl&s=<page-slug>` (no `lp`, so the click goes straight to registration with the code applied).

## How the SEO system works

| Piece | What it does |
| --- | --- |
| `data/casinos.json` | Every casino fact the site prints, with `verified_at` dates and a `test_log` per casino. Change a fact here and every page that shows it follows. |
| Shortcodes in `content/*.html` | `{{TABLE:<preset>}}`, `{{VERSUS:a,b}}`, `{{FACT:id.path}}`, `{{TESTLOG:id}}`, `{{MONTH}}`, `{{DATA_MONTH}}`, `{{CTA}}`, `{{RELATED}}`. Documented at the top of `build.py`. |
| `build.py` | Pulls the live StakeBet welcome bonus (falls back to the data file if the API is unreachable), expands shortcodes, generates BreadcrumbList / Article / ItemList / FAQPage / WebSite JSON-LD, related-page links, hreflang, and a sitemap whose `lastmod` is each page's real last change (git), not the build date. |
| `seo/check.py` | Quality gate: duplicate titles/descriptions, title and description length, thin content, broken internal links, unknown shortcodes, stale facts, empty test logs. New pages must pass fully; existing pages only warn. |
| `seo/indexnow.py` | Pings Bing/Yandex (IndexNow) with the URLs that changed today. |
| `seo/draft.py` | Drafts the next planned keyword from `data/keywords.json` with Claude (`claude-opus-5`) into a new content file. Never publishes. |
| `data/keywords.json` | The keyword plan: query, language, tier, target slug, status (`live`, `planned`, `drafted`, `skip`), priority. |

## Schedules (`.github/workflows/`)

- **pages.yml**: on every push to `main` and daily at 05:17 UTC: build, gate, deploy, IndexNow. The daily run rolls month-dated titles over on the 1st and re-reads the StakeBet offer.
- **draft.yml**: Mondays 06:00 UTC (or run by hand with a slug): drafts one page and opens a PR with the gate result and a review checklist. Merging publishes it.
- **facts-review.yml**: 1st of each month: opens an issue listing every casino fact to re-verify.

Setup the drafter needs once: a repo secret `ANTHROPIC_API_KEY`, and Settings → Actions → General → "Allow GitHub Actions to create and approve pull requests".

## Rules

- Only add a `test_log` entry for a test that really happened, with its real date and numbers.
- Competitor facts are re-checked by hand; anything older than a month is labelled "not verified this month" automatically.
- No fabricated ratings, reviews or testimonials, and keep the ownership disclosure in the footer.

Local preview: `python3 build.py && python3 seo/check.py && python3 -m http.server -d dist 8000`.
