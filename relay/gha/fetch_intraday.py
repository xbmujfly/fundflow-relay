#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""【抓取端·盘中】东财「当日主力累计曲线」→ relay/data/intraday_<date>.json

为什么单独一条链路（2026-09-27 定）：
  · 本机（校园网出口）被东财 push2 整族拒连 → 盘中实时资金本机取不到
  · 本仓 GHA runner = 海外 IP，实测约 43% 可吃 → 由 runner 抓、本机取（同 relay 其余链路）
  · 只抓**监控名单**（relay/intraday_watch.json = 持仓 + 分层池 T1-T4 + 观察池），
    且**只抓一条 fflow 分时资金**（现价/涨跌幅/流通市值由本机走腾讯行情补，见 common/local_quote.py）
    → 每只是一次 HTTP，8 线程并发，一轮 63 只 ≈ 20-40 秒（v1 串行 2 请求/只 ≈ 12 分钟被卡，
      2026-09-27 实测后改）

产出（本机消费：common/intraday_relay.py → intraday_weak_watch.py）
  relay/data/intraday_<date>.json
    {"date","fetch_ts","last_bar","n_bars","total_bars","src","count","missing","items":{...}}
    每只：cum(当日主力累计,元) / peak / peak_t / fall_pct(从日内峰值回落%) / low / n_bars / last_bar
       → 本机据此判：折算全天主力、峰值回落%、盘中强度（近3日累计+当日 ÷ 流通市值）

用法（runner 上）: python3 fetch_intraday.py [--watch relay/intraday_watch.json] [--out relay/data]
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
BASE_FFLOW = ("https://push2delay.eastmoney.com/api/qt/stock/fflow/kline/get"
              "?lmt=0&klt=1&secid={secid}&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56")
TOTAL_BARS = 241          # 9:30-11:30 + 13:00-15:00 的 1 分钟 bar 数


def secid(code):
    return ("1." if code[0] in "659" else "0.") + code


def get_json(url, tries=2, timeout=8):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                       "Referer": "https://data.eastmoney.com/"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(0.6)
    return None


def one(code):
    """只拉 fflow 分时资金（一次 HTTP）→ dict 或 None"""
    js = get_json(BASE_FFLOW.format(secid=secid(code)))
    kl = ((js or {}).get("data") or {}).get("klines") or []
    if not kl:
        return None
    series = []
    for k in kl:
        p = k.split(",")
        try:
            series.append((p[0], float(p[1])))     # (时间, 主力累计净额)
        except Exception:
            continue
    if not series:
        return None
    cums = [v for _, v in series]
    cum, peak = cums[-1], max(cums)
    fall = ((peak - cum) / peak * 100) if peak > 0 else None
    return {"cum": cum, "peak": peak, "peak_t": series[cums.index(peak)][0],
            "low": min(cums), "fall_pct": (round(fall, 1) if fall is not None else None),
            "n_bars": len(series), "last_bar": series[-1][0]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", default="relay/intraday_watch.json")
    ap.add_argument("--out", default="relay/data")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    now = datetime.now(CST)
    if not os.path.exists(a.watch):
        print(f"⚠️ 监控名单不存在: {a.watch}（本机 relay/push_intraday_watch.py 会推它）")
        return 0
    w = json.loads(open(a.watch, encoding="utf-8").read())
    codes = []
    for c in (w.get("codes") or []):
        c = str(c).zfill(6)
        if c not in codes:
            codes.append(c)
    if not codes:
        print("⚠️ 名单为空，跳过")
        return 0
    print(f"名单 {len(codes)} 只｜抓取 {now:%Y-%m-%d %H:%M} CST｜并发 {a.workers}", flush=True)

    items, miss = {}, []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(one, c): c for c in codes}
        for fu in futs:
            pass
        for fu, c in list(futs.items()):
            try:
                r = fu.result(timeout=60)
            except Exception:
                r = None
            if r:
                items[c] = r
                print(f"  {c} cum={r['cum']/1e8:+.3f}亿 fall={r['fall_pct']}% "
                      f"bars={r['n_bars']} last={r['last_bar']}", flush=True)
            else:
                miss.append(c)
    print(f"耗时 {time.time()-t0:.0f}s｜成功 {len(items)}｜失败 {len(miss)}")
    # 多轮补抓（最多 3 轮，总预算 480s）——目标是**抓全**：
    #   2026-09-27 用户"确定这样不会漏吧？不保险就按前面" → 名单回退全量 + 这里把"抓全"做成机制。
    #   东财对同一出口偶发限流（实测首轮 43/63），间隔重试能追回（一轮 → 62/63，再轮可望全）。
    #   ⚠️ 宁可多花 1-2 分钟，也不要结构性漏票。
    _rnd, _t_start = 0, time.time()
    while miss and _rnd < 3 and (time.time() - _t_start) < 480:
        _rnd += 1
        print(f"补抓第 {_rnd} 轮（{len(miss)} 只，间隔 1.2s）…", flush=True)
        still = []
        for c in miss:
            r = one(c)
            if r:
                items[c] = r
                print(f"  ✔ {c} cum={r['cum']/1e8:+.3f}亿", flush=True)
            else:
                still.append(c)
            time.sleep(1.2)
        miss = still
        print(f"第 {_rnd} 轮后：成功 {len(items)}｜仍缺 {len(miss)}", flush=True)
    if miss:
        print(f"⚠️ 仍有 {len(miss)} 只未抓到（东财对本 runner 拒连）→ 下一轮 cron（10 分钟后）换 IP 重试")
    if not items:
        print("❌ 全部失败（东财对本 runner IP 拒连）→ 非零退出，让工作流重跑换 IP")
        return 2
    _lb = max(v["last_bar"] for v in items.values())
    _nb = max(v["n_bars"] for v in items.values())
    out = {"date": now.strftime("%Y-%m-%d"), "fetch_ts": now.strftime("%Y-%m-%d %H:%M:%S"),
           "last_bar": _lb, "n_bars": _nb, "total_bars": TOTAL_BARS,
           "src": "eastmoney-fflow(klt=1 主力累计)", "count": len(items),
           "missing": miss, "items": items}
    os.makedirs(a.out, exist_ok=True)
    dst = os.path.join(a.out, f"intraday_{now:%Y-%m-%d}.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"✅ 写出 {dst}｜成功 {len(items)} / 失败 {len(miss)}｜最新 bar {_lb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
