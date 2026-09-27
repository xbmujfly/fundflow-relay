#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""历史回补的汇总：跨轮累积 → 目标日台账 → （抓全后）落正式产物

· 累加器 relay/data/_accum_hist.json.gz：row = [code,date,main,small,mid,big,super,main_pct,close,pct]
· 目标日（--target）的股票集合 vs universe → 缺哪些股票 → 写 _hist_progress.json
· 缺 0 只（或已达 --min-rows 且缺 ≤ --tolerance）→ 写 fundflow_<target>.json.gz（与快照同一格式，可被 pull_relay_data.py 入库）
"""
import argparse
import glob
import gzip
import json
import os
import sys
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))


def load_accum(path):
    if os.path.exists(path):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"rows": []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", default="parts")
    ap.add_argument("--out", default="relay/data")
    ap.add_argument("--target", required=True, help="目标交易日 2026-09-23")
    ap.add_argument("--universe", default="relay/gha/universe.txt")
    ap.add_argument("--min-rows", type=int, default=3800)
    ap.add_argument("--tolerance", type=int, default=0)
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    accum_path = os.path.join(a.out, "_accum_hist.json.gz")

    files = sorted(glob.glob(os.path.join(a.parts, "**", "hist_*.json.gz"), recursive=True))
    new_rows = []
    for p in files:
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            print(f"  ✗ {os.path.basename(p)} 读取失败 {e}")
            continue
        new_rows += d.get("rows") or []
    print(f"本轮 {len(files)} 个分片｜{len(new_rows)} 行")

    acc = load_accum(accum_path)
    have = {(r[0], r[1]) for r in acc.get("rows") or []}
    added = 0
    for r in new_rows:
        key = (r[0], r[1])
        if key not in have:
            have.add(key)
            acc["rows"].append(r)
            added += 1
    acc["updated_at"] = datetime.now(CST).isoformat(timespec="seconds")
    with gzip.open(accum_path, "wt", encoding="utf-8") as f:
        json.dump(acc, f, ensure_ascii=False, separators=(",", ":"))

    tgt = [r for r in acc["rows"] if r[1] == a.target]
    codes_ok = {r[0] for r in tgt}
    universe = []
    if os.path.exists(a.universe):
        universe = [l.strip().zfill(6) for l in open(a.universe, encoding="utf-8") if l.strip()]
    missing = [c for c in universe if c not in codes_ok] if universe else []
    dates = sorted({r[1] for r in acc["rows"]})

    print(f"累积：{len(acc['rows'])} 行｜{len(dates)} 个交易日 {dates[:3]}…{dates[-3:] if len(dates)>3 else ''}")
    print(f"目标 {a.target}：{len(tgt)} 行 / {len(codes_ok)} 只｜universe {len(universe)}｜缺 {len(missing)} 只")

    prog = dict(target=a.target, rows=len(tgt), codes_ok=len(codes_ok),
                universe=len(universe), codes_missing=len(missing),
                miss_sample=missing[:20], accum_rows=len(acc["rows"]),
                parts=len(files), built_at=datetime.now(CST).isoformat(timespec="seconds"))
    with open(os.path.join(a.out, "_hist_progress.json"), "w", encoding="utf-8") as f:
        json.dump(prog, f, ensure_ascii=False, indent=1)

    if len(tgt) < a.min_rows:
        print(f"❌ 目标日数据不足（{len(tgt)} < {a.min_rows}）→ 只写台账")
        return 3
    if len(missing) > a.tolerance:
        print(f"⚠️ 还缺 {len(missing)} 只（> {a.tolerance}）→ 只写台账，等下一轮")
        return 3

    # 转成与快照一致的 payload：data 行 = [code, main, super, big, mid, small, close, pct]
    # 历史行 = [code,date,main,small,mid,big,super,main_pct,close,pct]
    packed = [[r[0], r[2], r[6], r[5], r[4], r[3], r[8], r[9]] for r in tgt]
    fpath = os.path.join(a.out, f"fundflow_{a.target}.json.gz")
    payload = dict(date=a.target, rows=len(packed),
                   fetched_at=datetime.now(CST).isoformat(timespec="seconds"),
                   source="eastmoney.push2his.fflow.daykline", data=packed)
    with gzip.open(fpath, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"🎉 已写 {os.path.basename(fpath)}（{os.path.getsize(fpath)/1024:.0f}KB，{len(packed)} 只）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
