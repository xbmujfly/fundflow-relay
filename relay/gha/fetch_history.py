#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐股历史资金流回补（push2his daykline）—— 补历史缺口日（如 2026-09-23）

为什么需要它
==========
东财 clist 只能拿「最新快照」，所以**只有当天能抓到当天**。一旦某天没抓到（9-23/9-24 就是这样），
clist 再也拿不到。而 push2his 的 **daykline 接口能逐股给出历史日序列**，同属东财 push2 族
→ **与 clist 同口径**（新浪那种跨源口径不一致的问题不存在）。

代价：每股一次请求（全市场约 5200 次）。所以放到 GitHub Actions 矩阵里摊：
· 每个 job 独立 runner = 独立 IP（实测 Azure IP 约 43% 可用、可用者只吃得下几发）
· 每个 job 只抓少量股票（--limit），连续失败 --max-fail 次就收工（IP 已死，别浪费）
· **已抓过的股票由 merge 累积在仓库里**，下一轮 job 自己读累加器跳过 → 自动收敛到抓全

用法（runner 上）
====
    python3 fetch_history.py --job 3 --jobs 120 --target 2026-09-23 --limit 8 --out parts
    python3 fetch_history.py --codes "600519,000001" --out parts      # 定向补
产出：parts/hist_<job>.json.gz = {job, target, rows:[[code,date,main,small,mid,big,super,main_pct,close,pct],...]}
"""
import argparse
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
BASE = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
F1 = "f1,f2,f3,f7"
F2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63"


def secid(code):
    code = str(code).zfill(6)
    if code[0] == "6":
        return "1." + code
    if code[0] in "03":
        return "0." + code
    return "0." + code          # 北交所(4/8)在东财也走 0.


def egress_ip():
    for u in ("https://api.ipify.org", "http://ip.3322.net"):
        try:
            with urllib.request.urlopen(u, timeout=8) as r:
                return r.read().decode("utf-8", "replace").strip()[:40]
        except Exception:
            continue
    return "?"


def fetch_one(code, lmt=15, tries=2):
    """取单只股票的历史资金流。返回 [[code,date,main,small,mid,big,super,main_pct,close,pct], ...]"""
    url = f"{BASE}?lmt={lmt}&klt=101&secid={secid(code)}&fields1={F1}&fields2={F2}"
    code6 = str(code).zfill(6)
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                      "Referer": "https://quote.eastmoney.com/"})
            with urllib.request.urlopen(req, timeout=18) as r:
                j = json.loads(r.read().decode("utf-8", "replace"))
            d = j.get("data") or {}
            kl = d.get("klines") or []
            out = []
            for line in kl:
                p = line.split(",")
                if len(p) < 13:
                    continue
                out.append([code6, p[0], float(p[1]), float(p[2]), float(p[3]), float(p[4]),
                            float(p[5]), float(p[6]), float(p[11]), float(p[12])])
            if out:
                return out
            return []          # 有响应但没数据（停牌/退市）→ 不算失败
        except urllib.error.HTTPError as e:
            if k + 1 < tries:
                time.sleep(1.5)
            last = f"HTTP {e.code}"
        except Exception as e:
            last = type(e).__name__
            if k + 1 < tries:
                time.sleep(1.5)
    raise RuntimeError(last)


def load_done(path, target):
    """累加器里 target 日已有的股票代码（下一轮跳过，不重复抓）"""
    if not path or not os.path.exists(path):
        return set()
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            acc = json.load(f)
        return {r[0] for r in acc.get("rows", []) if r[1] == target}
    except Exception:
        return set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=120)
    ap.add_argument("--target", default=None, help="目标交易日（如 2026-09-23）")
    ap.add_argument("--universe", default="relay/gha/universe.txt")
    ap.add_argument("--codes", default=None, help="显式代码列表（逗号分隔），优先于 universe")
    ap.add_argument("--skip-file", default="relay/data/_accum_hist.json.gz")
    ap.add_argument("--limit", type=int, default=8, help="本 job 最多抓几只（省 IP 配额）")
    ap.add_argument("--max-fail", type=int, default=3, help="连续失败几次就收工（IP 已死）")
    ap.add_argument("--lmt", type=int, default=15, help="每股取多少天历史")
    ap.add_argument("--out", default="parts")
    a = ap.parse_args()

    if a.codes:
        universe = [c.strip() for c in a.codes.split(",") if c.strip()]
    else:
        if not os.path.exists(a.universe):
            print(f"缺 universe 文件 {a.universe}", flush=True)
            return 0
        universe = [l.strip() for l in open(a.universe, encoding="utf-8") if l.strip()]
    done = load_done(a.skip_file, a.target) if a.target else set()
    todo = [c for c in universe if str(c).zfill(6) not in done]
    # 分片轮换：所有 job 用同一个 seed（由「目标日 + 已完成数量」决定）→ 分片仍互不重叠，
    # 但每轮重新划分 → 某个 IP 反复死的 job 不会一直压着同一小片股票（否则收敛很慢）。
    if todo:
        import hashlib
        import random as _rnd
        seed = int(hashlib.md5(f"{a.target}|{len(done)}".encode()).hexdigest()[:8], 16)
        _rnd.Random(seed).shuffle(todo)
    mine = todo[a.job::a.jobs][:a.limit]
    print(f"== job={a.job}/{a.jobs} 目标={a.target}｜universe {len(universe)}｜已完成 {len(done)}"
          f"｜本 job 待抓 {len(mine)} 只｜出口 IP={egress_ip()} ==", flush=True)
    if not mine:
        print("本 job 没有要抓的（已完成或用例为空）→ 跳过", flush=True)
        return 0

    rows, ok, fails, streak = [], [], 0, 0
    for c in mine:
        try:
            r = fetch_one(c, a.lmt)
            rows += r
            ok.append(str(c).zfill(6))
            streak = 0
            print(f"  {c}: ok {len(r)} 天", flush=True)
        except Exception as e:
            fails += 1
            streak += 1
            print(f"  {c}: FAIL {e}", flush=True)
            if streak >= a.max_fail:
                print(f"  连续失败 {streak} 次 → 本 IP 大概已死，收工", flush=True)
                break
        time.sleep(0.5)

    if a.out != "-":
        os.makedirs(a.out, exist_ok=True)
        p = os.path.join(a.out, f"hist_{a.job}.json.gz")
        with gzip.open(p, "wt", encoding="utf-8") as f:
            json.dump(dict(job=a.job, target=a.target, ok_codes=ok, fail=fails, rows=rows),
                      f, ensure_ascii=False, separators=(",", ":"))
        print(f"✅ 写 {p}（{len(ok)} 只成功 / {len(rows)} 行）", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
