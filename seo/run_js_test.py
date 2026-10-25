#!/usr/bin/env python3
"""Run seo/test_pf.js with macOS JavaScriptCore (osascript) when node is not installed."""
import json, os, subprocess, sys
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
files = {p: open(os.path.join(root, p), encoding="utf-8").read() for p in ("static/js/pf.js", "static/js/wager.js", "seo/pf-golden.json")}
src = ("var console = {log: function (m) { LOG.push(String(m)); }}; var LOG = [];\n"
       f"var FILES = {json.dumps(files)};\nfunction LOAD(p) {{ return FILES[p]; }}\n"
       + open(os.path.join(root, "seo/test_pf.js"), encoding="utf-8").read() + "\nLOG.join('\\n');")
out = subprocess.run(["osascript", "-l", "JavaScript", "-e", src], capture_output=True, text=True)
print(out.stdout.strip() or out.stderr.strip())
sys.exit(0 if " 0 failed" in out.stdout else 1)
