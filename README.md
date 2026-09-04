# cryptocasinolist.io

Static comparison site. `python3 build.py` renders `content/*.html` (front-matter + body) through `layout.html` into `dist/`, plus `sitemap.xml` and `robots.txt`. Deployed to GitHub Pages by `.github/workflows/pages.yml` on every push to `main`.

Referral links are generated from `{{REF}}` in content: `https://stakebet.gg/ref/QQ6Z5TTZ?c=ccl&lp=crypto&s=<page-slug>`.
