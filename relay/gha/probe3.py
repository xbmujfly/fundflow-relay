#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针 3：是「配额」还是「限速」？

背景（probe1/2 实测）
==================
· 单个出口 IP 连发 2-3 次就被 RemoteDisconnected 秒断（clist / fflow 都一样）
· 但**快发**与**慢发**没区分过 —— 如果是**限速**（如 N 发/分钟），放慢就能无限取；
  如果是**配额**（每 IP 总量封顶），那就必须换 IP。
这个结论决定两件事：
  ① 9-23 能不能用 push2his 补（只有它给历史，但每 IP 只给 2-3 发）
  ② 每日快照能不能从「240 个 job 抢配额」简化成「1 个 job 慢慢抓」

做法：单 IP 按固定间隔连发，统计成功率随时间的变化。
"""
import json
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
F1, F2 = "f1,f2,f3,f7", "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63"
STOCKS = ["1.600519", "0.000001", "0.300750", "1.601318", "0.002415", "1.600036",
          "0.000002", "0.000063", "1.601988", "0.002594", "1.600030", "0.300059",
          "1.600887", "0.000858", "1.601166", "0.002304", "1.600276", "0.300124"]


def egress():
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=8) as r:
            return r.read().decode().strip()
    except Exception:
        return "?"


def his(secid, timeout=15):
    u = (f"https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
         f"?lmt=3&klt=101&secid={secid}&fields1={F1}&fields2={F2}")
    try:
        with urllib.request.urlopen(urllib.request.Request(
                u, headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}), timeout=timeout) as r:
            b = r.read().decode("utf-8", "replace")
        return (r.status, '"klines"' in b and len(b) > 300)
    except urllib.error.HTTPError as e:
        return (e.code, False)
    except Exception:
        return (None, False)


def clist(pn, timeout=15):
    u = ("https://push2delay.eastmoney.com/api/qt/clist/get?pn=%d&pz=5&po=1&np=1&fltt=2&invt=2"
         "&fid=f62&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12,f62,f124" % pn)
    try:
        with urllib.request.urlopen(urllib.request.Request(
                u, headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}), timeout=timeout) as r:
            b = r.read().decode("utf-8", "replace")
        return (r.status, '"diff"' in b)
    except urllib.error.HTTPError as e:
        return (e.code, False)
    except Exception:
        return (None, False)


def main():
    print(f"== 探针3 节奏测试（出口 IP={egress()}）==", flush=True)

    for label, gap, n in [("push2his fflow · 间隔 12 秒", 12, 10),
                          ("push2his fflow · 间隔 3 秒", 3, 6)]:
        print(f"\n--- {label} ---", flush=True)
        ok = 0
        for i in range(n):
            st, good = his(STOCKS[i % len(STOCKS)])
            ok += 1 if good else 0
            print(f"  {i+1:>2}/{n}: {'✅' if good else '❌'} HTTP {st}", flush=True)
            if not good and i >= 1:
                print(f"     → 连续失败，停止本组（成功 {ok} 发）", flush=True)
                break
            if i + 1 < n:
                time.sleep(gap)
        print(f"  小结：{label} 成功 {ok} 发", flush=True)

    print("\n--- push2delay clist · 间隔 12 秒（快照路径同样测）---", flush=True)
    ok = 0
    for i in range(8):
        st, good = clist(i + 1)
        ok += 1 if good else 0
        print(f"  {i+1:>2}/8: {'✅' if good else '❌'} HTTP {st}", flush=True)
        if i + 1 < 8:
            time.sleep(12)
    print(f"  小结：clist 成功 {ok} 发", flush=True)


if __name__ == "__main__":
    main()
