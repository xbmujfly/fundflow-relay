#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并矩阵各 job 的 parts/*.json.gz → 正式产物 fundflow_<date>.json.gz

产物格式与 relay/fetch_fundflow.py 完全一致，可直接被 common/pull_relay_data.py 入库。
"""
import argparse
import glob
import gzip
import json
import os
import sys
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
MIN_ROWS = 3800


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", default="parts")
    ap.add_argument("--out", default="relay/data")
    ap.add_argument("--min-rows", type=int, default=MIN_ROWS)
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.parts, "**", "part_*.json.gz"), recursive=True))
    print(f"发现 {len(files)} 个 part 文件")
    rows, dates, per = [], set(), []
    for p in files:
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            print(f"  ✗ {os.path.basename(p)} 读取失败 {e}")
            continue
        r = d.get("rows") or []
        rows += r
        if d.get("date"):
            dates.add(d["date"])
        per.append((os.path.basename(p), len(r), d.get("date")))
        print(f"  ✓ {os.path.basename(p):22s} {len(r):5d} 行  日期={d.get('date')}")

    # 去重（同一只票可能被两个 job 抓到）
    seen, uniq = set(), []
    for r in rows:
        c = str(r.get("f12"))
        if c and c not in seen:
            seen.add(c)
            uniq.append(r)

    ts = [r.get("f124") for r in uniq if isinstance(r.get("f124"), (int, float)) and r.get("f124")]
    date = datetime.fromtimestamp(max(ts), CST).strftime("%Y-%m-%d") if ts else (sorted(dates)[-1] if dates else None)
    print(f"\n合并后：{len(uniq)} 只（去重前 {len(rows)}）｜交易日={date}｜各 job 日期={sorted(dates)}")
    if not date or len(uniq) < a.min_rows:
        print(f"❌ 数据不足（{len(uniq)} < {a.min_rows}）→ 不落盘，避免污染")
        return 3

    os.makedirs(a.out, exist_ok=True)
    fpath = os.path.join(a.out, f"fundflow_{date}.json.gz")
    packed = [[str(r.get("f12")), r.get("f62"), r.get("f66"), r.get("f72"),
               r.get("f78"), r.get("f84"), r.get("f2"), r.get("f3")] for r in uniq]
    payload = dict(date=date, rows=len(packed),
                   fetched_at=datetime.now(CST).isoformat(timespec="seconds"),
                   source="eastmoney.push2delay.clist.gha", data=packed)
    with gzip.open(fpath, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"✅ 已写 {fpath}（{os.path.getsize(fpath)/1024:.0f}KB）")

    lj = os.path.join(a.out, "latest.json")
    meta = dict(date=date, file=os.path.basename(fpath), rows=len(packed),
                fetched_at=datetime.now(CST).isoformat(timespec="seconds"))
    old = {}
    if os.path.exists(lj):
        try:
            old = json.load(open(lj, encoding="utf-8"))
        except Exception:
            pass
    if old.get("date") and old["date"] > date:
        print(f"⏭ latest.json 已指向更新的 {old['date']}，不回退")
    else:
        json.dump(meta, open(lj, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    idx_path = os.path.join(a.out, "index.json")
    try:
        idx = json.load(open(idx_path, encoding="utf-8")).get("dates", [])
    except Exception:
        idx = []
    if date not in idx:
        idx.append(date)
    json.dump(dict(dates=sorted(idx)), open(idx_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ latest.json → {date}｜index {len(idx)} 天")
    return 0


if __name__ == "__main__":
    sys.exit(main())
