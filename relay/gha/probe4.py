# 探针4：验证「用 3/5/10 日累计净额反推缺失交易日」的算术是否成立
import json, time, urllib.request, ssl, sys
ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
UA = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36",
      "Referer":"https://data.eastmoney.com/zjlx/"}
UT = "b2884a393a59ad64002292a3e90d46a5"
FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
FIELDS = "f12,f14,f62,f184,f267,f164,f174,f127,f2,f3"
HOSTS = ["push2delay.eastmoney.com", "push2.eastmoney.com"]

def fetch_page(pn, pz=100):
    last = None
    for h in HOSTS:
        for att in range(5):
            u = (f"https://{h}/api/qt/clist/get?pn={pn}&pz={pz}&po=1&np=1&fltt=2&invt=2&fid=f62"
                 f"&fs={FS}&fields={FIELDS}&ut={UT}")
            try:
                with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=15, context=ctx) as r:
                    j = json.loads(r.read().decode("utf-8","replace"))
                d = (j.get("data") or {}).get("diff") or []
                if d: return h, d
                last = f"empty@try{att}"
            except Exception as e:
                last = f"{h}:{type(e).__name__}"
            time.sleep(1.5)
    return None, last

print("== 探针4：3/5/10日累计净额字段验证 ==", flush=True)
rows = []
for pn in (1, 2):
    h, d = fetch_page(pn)
    if not isinstance(d, list):
        print(f"  page{pn} 失败：{d}", flush=True); continue
    print(f"  page{pn} ✅ {h} 拿到 {len(d)} 只", flush=True)
    rows += d
print(f"共 {len(rows)} 只", flush=True)
print("CODE,MAIN1,SUM3,SUM5,SUM10,PCT1", flush=True)
for it in rows[:60]:
    print(f"{it.get('f12')},{it.get('f62')},{it.get('f267')},{it.get('f164')},{it.get('f174')},{it.get('f184')}", flush=True)
print("== 探针4 结束 ==", flush=True)
