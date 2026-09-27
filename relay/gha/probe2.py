#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针 2：push2delay 上的 fflow/daykline 是否给逐日历史？单 IP 能吃几发？

背景：探针 1 发现
  · clist 带 date 参数被忽略（返回的仍是 9-24 快照）→ 拿不到历史
  · push2his 的 fflow/daykline 在 Azure IP 上通过率极低（~3%）→ 全市场回补不可行
  · **但 push2delay 上也有 fflow/daykline 且返回 200** ← 若它给逐日历史且通过率正常，回补就有救
"""
import json
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
F1 = "f1,f2,f3,f7"
F2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63"
HOSTS = ["push2delay.eastmoney.com", "push2his.eastmoney.com"]


def egress():
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=8) as r:
            return r.read().decode().strip()
    except Exception:
        return "?"


def one(host, secid, lmt=10, timeout=18):
    url = (f"https://{host}/api/qt/stock/fflow/daykline/get"
           f"?lmt={lmt}&klt=101&secid={secid}&fields1={F1}&fields2={F2}")
    try:
        with urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}), timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:120]
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:70]}"


def main():
    print(f"== 探针2（出口 IP={egress()}）==", flush=True)
    for host in HOSTS:
        st, body = one(host, "1.600519", lmt=10)
        print(f"\n--- {host} / 600519 ---", flush=True)
        print(f"  HTTP {st}｜{body[:400]}", flush=True)
        try:
            d = (json.loads(body).get("data") or {})
            kl = d.get("klines") or []
            print(f"  klines 条数={len(kl)}｜列数={len(kl[0].split(',')) if kl else 0}", flush=True)
            for line in kl[:3] + kl[-3:]:
                print(f"    {line}", flush=True)
        except Exception as e:
            print(f"  解析失败 {type(e).__name__}", flush=True)

    # 单 IP 能吃几发（同一 host 连发 12 只，看第几发开始挂）
    host = "push2delay.eastmoney.com"
    print(f"\n--- 单 IP 连续请求预算测试（{host}，最多 12 发）---", flush=True)
    codes = ["1.600519", "0.000001", "0.300750", "1.601318", "0.002415", "1.600036",
             "0.000002", "0.000063", "1.601988", "0.002594", "1.600030", "0.300059"]
    okn = 0
    for i, sec in enumerate(codes, 1):
        t0 = time.time()
        st, body = one(host, sec, lmt=3)
        good = st == 200 and '"klines"' in body
        okn += 1 if good else 0
        print(f"  {i:>2}/{len(codes)} {sec}: {'✅' if good else '❌'} {st} ({time.time()-t0:.1f}s)", flush=True)
        if not good:
            print(f"     → 第 {i} 发开始被拒（本 IP 预算 ≈ {i-1} 发）", flush=True)
            break
        time.sleep(0.3)
    print(f"\n结论：本 IP 在 {host} 上成功 {okn} 发", flush=True)


if __name__ == "__main__":
    main()
