#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""缺页则自动再触发一轮（在 workflow 的 merge job 里跑）

GitHub Actions 一个 run 只能看到自己的 artifacts，而东财对海外 IP 只放行一半，
一轮必然缺页 → 由本脚本用 workflow 自带的 GITHUB_TOKEN 再派发一轮，只抓缺的页。
累积由 merge_parts.py 的累加器负责（仓库里的 _accum.json.gz），所以重跑不浪费。

环境变量（workflow 里注入）：GITHUB_TOKEN / GITHUB_REPOSITORY / ROUND / MAX_ROUND
"""
import json
import os
import sys
import urllib.error
import urllib.request

ROUND = int(os.environ.get("ROUND", "1"))
MAX_ROUND = int(os.environ.get("MAX_ROUND", "6"))
MODE = os.environ.get("MODE", "snapshot")          # snapshot | history
TARGET = os.environ.get("TARGET", "")
PROG = os.environ.get("PROGRESS",
                      "relay/data/_hist_progress.json" if MODE == "history"
                      else "relay/data/_progress.json")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOK = os.environ.get("GITHUB_TOKEN", "")
WF = os.environ.get("WF", "history.yml" if MODE == "history" else "fundflow.yml")


def main():
    if not os.path.exists(PROG):
        print("没有台账文件 → 跳过")
        return 0
    p = json.load(open(PROG, encoding="utf-8"))
    if MODE == "history":
        miss_n = p.get("codes_missing") or 0
        miss = p.get("miss_sample") or []
    else:
        miss = p.get("pages_missing") or []
        miss_n = len(miss)
    print(f"[{MODE}] 台账：{p.get('rows')}/{p.get('total') or p.get('universe')}"
          f"｜缺 {miss_n}｜当前第 {ROUND} 轮")
    if not miss_n:
        print("✅ 已抓全，无需补跑")
        return 0
    if ROUND >= MAX_ROUND:
        print(f"⛔ 已达最大轮次 {MAX_ROUND}，停止补跑")
        return 0
    if not (REPO and TOK):
        print("缺 GITHUB_REPOSITORY / GITHUB_TOKEN → 跳过")
        return 0
    if MODE == "history":
        inputs = {"round": str(ROUND + 1), "target": TARGET}
    else:
        inputs = {"round": str(ROUND + 1), "pages_list": ",".join(str(x) for x in miss)}
    body = json.dumps({"ref": "main", "inputs": inputs}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/workflows/{WF}/dispatches",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {TOK}",
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json",
                 "User-Agent": "relay-next-round"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"▶ 已触发第 {ROUND+1} 轮补缺页 {miss}: HTTP {r.status}")
    except urllib.error.HTTPError as e:
        print(f"✗ 触发失败 HTTP {e.code}: {e.read().decode()[:200]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
