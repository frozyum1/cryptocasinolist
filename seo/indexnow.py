#!/usr/bin/env python3
"""Tell IndexNow (Bing, Yandex, Seznam, Naver; Google ignores it) which URLs changed.

Pings pages whose lastmod is today, or every indexable page with --all.
Run after a deploy, never before: the engines fetch the URL straight away.
"""
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = "cryptocasinolist.io"
KEY = "6661975c36214dd9d805032349fc9fda"  # served at /<KEY>.txt from static/


def main():
    manifest = json.load(open(os.path.join(ROOT, "build-manifest.json"), encoding="utf-8"))
    built = manifest["built"]
    urls = [p["url"] for p in manifest["pages"] if p["indexable"] and ("--all" in sys.argv or p["lastmod"] == built)]
    if not urls:
        print("indexnow: nothing changed today")
        return
    body = json.dumps({"host": HOST, "key": KEY, "keyLocation": f"https://{HOST}/{KEY}.txt", "urlList": urls}).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"indexnow: {r.status} for {len(urls)} url(s)")
    except urllib.error.HTTPError as e:
        # 202 = accepted, 200 = ok; 4xx is worth seeing in the log but must not fail the deploy.
        print(f"indexnow: HTTP {e.code} for {len(urls)} url(s): {e.read()[:200]!r}")


if __name__ == "__main__":
    main()
