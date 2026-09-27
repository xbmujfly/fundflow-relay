#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""等 GitHub relay 出正式产物（供后台挂机用）

轮询仓库的 relay/data/_progress.json 看进展；一旦 latest.json 出现即完成退出。
退出码：0 完成 / 4 超时
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

API = "https://api.github.com"
REPO = os.environ.get("RELAY_REPO", "xbmujfly/fundflow-relay")


def token():
    t = os.environ.get("GITHUB_TOKEN", "")
    if t:
        return t
    for p in (Path.home() / "AppData/Local/hermes/.env", Path.home() / ".qclaw/.env"):
        if p.exists():
            for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
                if ln.strip().startswith("GITHUB_TOKEN="):
                    return ln.split("=", 1)[1].strip()
    return ""


H = {"Authorization": f"Bearer {token()}", "Accept": "application/vnd.github+json",
     "User-Agent": "relay-wait"}


def fetch(path):
    try:
        req = urllib.request.Request(f"{API}/repos/{REPO}/contents/{path}?ref=main", headers=H)
        with urllib.request.urlopen(req, timeout=25) as r:
            return base64.b64decode(json.load(r)["content"])
    except urllib.error.HTTPError as e:
        return None if e.code == 404 else f"__HTTP {e.code}__".encode()
    except Exception:
        return b"__net__"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=25)
    ap.add_argument("--interval", type=int, default=45)
    ap.add_argument("--file", default="latest.json", help="等哪个产物（历史回补用 fundflow_2026-09-23.json.gz）")
    ap.add_argument("--progress", default="_progress.json")
    a = ap.parse_args()
    t0 = time.time()
    last = None
    while time.time() - t0 < a.minutes * 60:
        b = fetch("relay/data/" + a.file)
        if isinstance(b, bytes) and b and not b.startswith(b"__"):
            m = json.loads(b.decode("utf-8"))
            print(f"[{datetime.now():%H:%M:%S}] 🎉 正式产物已就绪：{m['file']}｜{m['date']}｜{m['rows']} 行"
                  f"｜缺页 {m.get('pages_missing')}", flush=True)
            return 0
        p = fetch("relay/data/" + a.progress)
        if isinstance(p, bytes) and p and not p.startswith(b"__"):
            d = json.loads(p.decode("utf-8"))
            if "codes_missing" in d:      # 历史回补台账
                cur = (d.get("rows"), d.get("codes_missing"), d.get("accum_rows"))
                if cur != last:
                    print(f"[{datetime.now():%H:%M:%S}] 历史回补台账：目标日 {d.get('rows')} 行 / {d.get('codes_ok')} 只"
                          f"｜universe {d.get('universe')}｜缺 {d.get('codes_missing')} 只"
                          f"｜累加器共 {d.get('accum_rows')} 行", flush=True)
                    last = cur
            else:
                cur = (d.get("rows"), len(d.get("pages_ok") or []), tuple(d.get("pages_missing") or []))
                if cur != last:
                    print(f"[{datetime.now():%H:%M:%S}] 台账：{d.get('rows')}/{d.get('total')} 只"
                          f"｜页 {len(d.get('pages_ok') or [])}/{d.get('pages_total')}"
                          f"｜缺 {d.get('pages_missing')}", flush=True)
                    last = cur
        time.sleep(a.interval)
    print("超时：还没有正式产物", flush=True)
    return 4


if __name__ == "__main__":
    sys.exit(main())
