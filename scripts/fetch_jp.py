"""日本财政数据抓取 (data/jp)。稳定源自动; Excel/PDF源为对话锚。金额单位: 兆円(T¥)除注明外。"""
import json, sys, time, os
from pathlib import Path
from datetime import date, datetime, timedelta

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "jp"
OUT.mkdir(parents=True, exist_ok=True)
TODAY = date.today()


def _write(name, obj):
    obj["fetched_at"] = datetime.utcnow().isoformat(timespec="seconds")
    (OUT / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    print(f"  data/jp/{name}.json")


def _mnum(m): return int(m[:4])*12 + int(m[5:7])


def _interp(knots):
    out = []
    for (m0, v0), (m1, v1) in zip(knots, knots[1:]):
        a, b = _mnum(m0), _mnum(m1)
        for k in range(a, b):
            y, mm = divmod(k-1, 12)
            out.append((f"{y}-{mm+1:02d}", v0 + (v1-v0)*(k-a)/(b-a)))
    out.append(knots[-1]); return out


def _era_to_iso(s):
    """和暦(S/H/R+年.月.日)→ISO; 已是西暦则原样。"""
    s = s.strip()
    if not s: return None
    if s[0] in "SHR":
        base = {"S": 1925, "H": 1988, "R": 2018}[s[0]]
        parts = s[1:].split(".")
        if len(parts) == 3:
            return f"{base+int(parts[0])}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d"):
        try: return datetime.strptime(s, fmt).date().isoformat()
        except ValueError: pass
    return None


# ---------------------------------------------------------------- 真实抓取
def fetch_jgb_yields():
    """財務省 国債金利情報 CSV(Shift-JIS, 和暦): 当年+全史。日频, 1974+。"""
    import requests, csv, io
    urls = ["https://www.mof.go.jp/jgbs/reference/interest_rate/historical/jgbcme_all.csv",
            "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv"]
    TEN = {"1年": "1y", "2年": "2y", "5年": "5y", "10年": "10y", "20年": "20y", "30年": "30y", "40年": "40y"}
    byd = {}
    got = 0
    for u in urls:
        try:
            r = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=90)
            if r.status_code != 200: continue
            text = r.content.decode("shift_jis", "ignore")
            rows = list(csv.reader(io.StringIO(text)))
            hdr_i = next((i for i, row in enumerate(rows) if any("10年" in c for c in row)), None)
            if hdr_i is None: continue
            hdr = [c.strip() for c in rows[hdr_i]]
            idx = {TEN[h]: i for i, h in enumerate(hdr) if h in TEN}
            for row in rows[hdr_i+1:]:
                if not row or not row[0].strip(): continue
                d = _era_to_iso(row[0])
                if not d: continue
                rec = {}
                for k, i in idx.items():
                    try: rec[k] = float(row[i])
                    except (ValueError, IndexError): pass
                if rec: byd[d] = rec; got += 1
        except Exception as e:
            print(f"  jgb csv 失败 {u.rsplit('/',1)[-1]}: {e}")
    if len(byd) < 500:
        print(f"  !! JGB利率不足({len(byd)}), 保留上一版"); return
    ds = sorted(byd)
    _write("jgb_yields", {"sample": False, "dates": ds,
                          "series": {k: [byd[d].get(k) for d in ds] for k in TEN.values()}})


def _fred_csv(sid):
    import requests, csv, io
    r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": sid}, timeout=60)
    r.raise_for_status()
    out = []
    for row in csv.DictReader(io.StringIO(r.text)):
        d = row.get("DATE") or row.get("observation_date"); v = row.get(sid)
        if d and v and v != ".": out.append((d, float(v)))
    return out


def fetch_macro_jp():
    """FRED镜像 + IMF WEO: 名目GDP, 债务/GDP, 财政收支, BOJ总资产 (weekly)。"""
    import requests
    out = {"sample": False}
    try:
        g = _fred_csv("JPNNGDP")           # 季度SAAR, 十亿円
        byy = {}
        for d, v in g: byy.setdefault(int(d[:4]), []).append(v)
        out["ngdp"] = {str(y): round(sum(v)/len(v)/1000, 1) for y, v in byy.items()}   # →兆円
    except Exception as e: print(f"  JPNNGDP失败: {e}")
    try:
        out["boj_assets"] = [{"month": d[:7], "t_yen": round(v/10000, 1)} for d, v in _fred_csv("JPNASSETS")]  # 億→兆
    except Exception as e: print(f"  JPNASSETS失败: {e}")
    try:
        out["jgb10y_m"] = [{"month": d[:7], "rate": round(v, 3)} for d, v in _fred_csv("IRLTLT01JPM156N")]
    except Exception as e: print(f"  IRLTLT失败: {e}")
    for key, ind in (("debt_gdp", "GGXWDG_NGDP"), ("bal_gdp", "GGXCNL_NGDP"), ("pb_gdp", "GGXONLB_NGDP")):
        try:
            r = requests.get(f"https://www.imf.org/external/datamapper/api/v1/{ind}/JPN", timeout=60)
            vals = (r.json().get("values") or {}).get(ind, {}).get("JPN", {})
            out[key] = {y: round(v, 1) for y, v in vals.items()}
        except Exception as e: print(f"  IMF {ind}失败: {e}")
    if len(out) < 4:
        print("  !! macro_jp不足, 保留上一版"); return
    _write("macro_jp", out)


def ensure_seeds_jp():
    """锚文件缺失自动播种(不覆盖)。"""
    missing = [n for n in SEEDS if not (OUT / f"{n}.json").exists()]
    for n in missing:
        SEEDS[n](); print(f"  播种: {n}")


# ---------------------------------------------------------------- 锚/样例生成器
def seed_budget():
    _write("budget_jp", {"sample": True, "fy": 2026, "as_of": "2025-12-26 政府案(3月成立)",
        "total": 122.3, "revenue": [
            ("税收(租税及印花收入)", 83.7), ("所得税", 25.3), ("法人税", 20.7), ("消费税", 26.7), ("其他税", 11.0),
            ("其他收入", 9.0), ("公债金(新规国债)", 29.6), ("建设国债", 6.7), ("特例国债", 22.9)],
        "outlay": [("一般歳出(政策支出)", 70.2), ("社会保障", 39.1), ("防卫", 9.0), ("公共事业", 6.1),
                   ("文教科技", 6.0), ("其他政策支出", 10.0), ("国债费", 31.3), ("债务偿还费", 18.2),
                   ("利息支付等", 13.1), ("地方交付税等", 20.9)],
        "pb_initial": 0.2, "note": "当初预算口径一般会计基本财政收支28年来首次转正(+0.2兆); 预算假定利率2.6%"})


def seed_supplementary():
    _write("supplementary", {"sample": True, "rows": [
        {"fy": 2019, "amount": 4.5, "count": 1}, {"fy": 2020, "amount": 73.0, "count": 3},
        {"fy": 2021, "amount": 36.0, "count": 1}, {"fy": 2022, "amount": 31.6, "count": 2},
        {"fy": 2023, "amount": 13.2, "count": 1}, {"fy": 2024, "amount": 13.9, "count": 1},
        {"fy": 2025, "amount": 17.7, "count": 1}, {"fy": 2026, "amount": None, "count": 0, "note": "秋季补充预算待观察"}],
        "reserve": [{"fy": 2020, "t": 11.5}, {"fy": 2021, "t": 5.0}, {"fy": 2022, "t": 5.5}, {"fy": 2023, "t": 5.0},
                    {"fy": 2024, "t": 1.0}, {"fy": 2025, "t": 1.0}, {"fy": 2026, "t": 1.0}]})


def seed_mlt():
    yrs = list(range(2025, 2036))
    _write("mlt_projection", {"sample": True, "years": yrs,
        "versions": [{"id": "2026-01", "name": "2026年1月版"}, {"id": "2026-07", "name": "2026年7月版"}],
        "data": {"2026-01": {"pb_growth": [-0.4, 0.5, 0.9, 1.2, 1.6, 2.0, 2.3, 2.6, 2.8, 3.0, 3.2],
                             "pb_base": [-0.4, 0.1, 0.2, 0.1, 0.0, -0.1, -0.3, -0.5, -0.7, -0.9, -1.1],
                             "debt_growth": [205, 201, 197, 193, 189, 185, 181, 177, 173, 169, 165],
                             "debt_base": [205, 204, 203, 203, 203, 203, 204, 205, 206, 207, 208]},
                 "2026-07": {"pb_growth": [-0.3, 0.8, 1.1, 1.4, 1.8, 2.2, 2.5, 2.8, 3.0, 3.2, 3.4],
                             "pb_base": [-0.3, 0.3, 0.3, 0.2, 0.1, 0.0, -0.2, -0.4, -0.6, -0.8, -1.0],
                             "debt_growth": [204, 199, 195, 191, 186, 182, 178, 174, 170, 166, 162],
                             "debt_base": [204, 203, 202, 202, 202, 202, 203, 204, 205, 206, 207]}},
        "note": "内阁府中长期经济财政测算(1月/7月); pb=中央+地方基本财政收支/GDP%, debt=公债等残高/GDP%; 成长实现/基线两场景"})


def seed_issuance_plan():
    _write("issuance_plan", {"sample": True, "fy": 2026, "as_of": "2025-12-26",
        "table": [("新规财源债", 29.6, 28.6), ("其中 建设国债", 6.7, 6.8), ("其中 特例国债", 22.9, 21.9),
                  ("再融资国债", 130.0, 128.5), ("财投债", 13.0, 12.0), ("复兴债", 0.1, 0.1),
                  ("GX经济转型债", 1.8, 1.4), ("儿童特例债", 0.3, 0.3), ("发行总额", 175.0, 171.0),
                  ("其中 日历基准市中发行额", 172.3, 172.3), ("提前发行债限额", 50.0, 50.0)],
        "calendar": [("2年", 2.6, 12), ("5年", 2.4, 12), ("10年", 2.6, 12), ("20年", 0.9, 12),
                     ("30年", 0.7, 12), ("40年", 0.5, 6), ("物价联动10年", 0.25, 4), ("流动性供给", 0.6, 24),
                     ("1年贴现", 3.5, 12), ("6个月贴现", 3.5, 12)],
        "note": "日历基准=预先定额定期招标的4月-次年3月发行预定额面; 2025年6月改定后超长端缩减延续"})


def seed_tenor_history():
    """月度各期限单次招标规模 2010+ (锚)。"""
    knots = {"2y": [("2010-04", 2.6), ("2013-04", 2.7), ("2016-04", 2.2), ("2020-04", 2.5), ("2020-07", 3.0), ("2022-04", 2.9), ("2024-04", 2.6), ("2026-03", 2.6)],
             "5y": [("2010-04", 2.4), ("2013-04", 2.7), ("2016-04", 2.4), ("2020-07", 2.5), ("2022-04", 2.5), ("2024-04", 2.4), ("2026-03", 2.4)],
             "10y": [("2010-04", 2.2), ("2013-04", 2.4), ("2016-04", 2.4), ("2020-07", 2.6), ("2022-04", 2.7), ("2024-04", 2.6), ("2026-03", 2.6)],
             "20y": [("2010-04", 1.1), ("2013-04", 1.2), ("2016-04", 1.1), ("2020-07", 1.2), ("2022-04", 1.2), ("2024-04", 1.0), ("2025-07", 0.9), ("2026-03", 0.9)],
             "30y": [("2010-04", 0.6), ("2013-04", 0.6), ("2016-04", 0.8), ("2020-07", 0.9), ("2022-04", 0.9), ("2024-04", 0.9), ("2025-07", 0.7), ("2026-03", 0.7)],
             "40y": [("2010-04", 0.3), ("2013-04", 0.4), ("2016-04", 0.4), ("2020-07", 0.6), ("2022-04", 0.7), ("2024-04", 0.7), ("2025-07", 0.5), ("2026-03", 0.5)]}
    allm = [m for m, _ in _interp([("2010-04", 0), ("2026-03", 0)])]
    ser = {}
    for t, kn in knots.items():
        d = dict(_interp(kn)); ser[t] = [round(d[m], 2) if m in d else None for m in allm]
    _write("tenor_history", {"sample": True, "months": allm, "tenors": ser})


def seed_tax():
    """月度税收累计: FY2023决算/FY2024决算/FY2025决算(预估)/FY2026当初; 4月起累计。"""
    prof = [0.03, 0.10, 0.17, 0.24, 0.30, 0.36, 0.43, 0.50, 0.58, 0.68, 0.78, 1.00]  # 月度累计占比(含3月集中)
    def path(total, n=12): return [round(total*p, 1) for p in prof[:n]]
    _write("tax_progress", {"sample": True, "months": ["4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月", "1月", "2月", "3月"],
        "fys": {"FY2023(决算)": path(72.1), "FY2024(决算)": path(75.2), "FY2025(决算见込)": path(80.3), "FY2026(当初预算)": path(83.7),
                "FY2026(实绩)": path(83.7, 4)},
        "by_tax": [("所得税", 25.3, 23.8), ("法人税", 20.7, 19.5), ("消费税", 26.7, 25.6), ("其他", 11.0, 11.4)],
        "as_of": "2026-07实绩(9月上旬公布)", "note": "税收超收=决算-当初; 近年连续超收, 决算剩余金回流补充预算/防卫财源"})


def seed_flows():
    knots = [("2016-04", 8), ("2019-04", 9), ("2020-04", 14), ("2022-04", 11), ("2024-04", 11), ("2026-08", 12)]
    ms = _interp(knots)
    import random; random.seed(3)
    _write("treasury_flows", {"sample": True, "series": [
        {"month": m, "receipts": round(v*(1.9 if m[5:7] in ("05", "11", "03") else 1.0), 1),
         "payments": round(v*1.05 + random.uniform(-1, 1), 1)} for m, v in ms],
        "note": "国库对民间收支月度(受入/支払), 财务省; 5月/11月/3月为法人税·所得税集中缴纳月"})


def seed_local_jp():
    yrs = list(range(2016, 2027))
    _write("local_jp", {"sample": True, "years": yrs,
        "series": {"plan_total": [85.8, 86.6, 86.9, 89.6, 90.7, 89.8, 90.6, 92.0, 93.6, 96.5, 102.4],
                   "local_tax": [39.4, 39.0, 39.5, 40.2, 40.8, 38.3, 41.2, 42.9, 44.1, 46.2, 48.0],
                   "lat": [16.7, 16.3, 16.0, 16.2, 16.6, 17.4, 18.1, 18.4, 18.7, 19.0, 20.9],
                   "grants": [13.5, 13.4, 13.6, 13.9, 14.4, 15.4, 15.2, 15.3, 15.6, 16.2, 17.5],
                   "local_bond": [9.2, 9.2, 9.2, 9.4, 9.3, 11.2, 7.6, 6.8, 6.3, 6.5, 6.4]},
        "note": "地方财政计划(通常收支分): 地方税/地方交付税/国库支出金/地方债; 央地划分=交付税+国库支出金"})


def seed_debt_long():
    yrs = list(range(1965, 2027))
    import math
    debt = [round(0.2 * math.exp(0.113*(y-1965)) if y < 1990 else 0, 1) for y in yrs]
    kn = [(1965, 0.2), (1975, 15), (1985, 134), (1990, 166), (1995, 225), (2000, 368), (2005, 527), (2010, 636),
          (2015, 805), (2020, 947), (2023, 1027), (2026, 1112)]
    def ik(y):
        for (y0, v0), (y1, v1) in zip(kn, kn[1:]):
            if y0 <= y <= y1: return v0 + (v1-v0)*(y-y0)/(y1-y0)
        return kn[-1][1]
    gk = [(1965, 33), (1975, 152), (1985, 330), (1990, 451), (1995, 521), (2000, 535), (2005, 532), (2010, 505),
          (2015, 540), (2020, 539), (2023, 597), (2026, 640)]
    def ig(y):
        for (y0, v0), (y1, v1) in zip(gk, gk[1:]):
            if y0 <= y <= y1: return v0 + (v1-v0)*(y-y0)/(y1-y0)
        return gk[-1][1]
    _write("debt_long_jp", {"sample": True, "years": yrs, "jgb": [round(ik(y), 0) for y in yrs],
                            "ngdp": [round(ig(y), 0) for y in yrs],
                            "note": "普通国债残高(年度末, 兆円) 与 名目GDP; 2026为年度末见込"})


def seed_holders_jp():
    qs = [f"{y}Q{q}" for y in range(2012, 2027) for q in (1, 2, 3, 4)][:58]
    n = len(qs)
    def ramp(a, b): return [round(a + (b-a)*i/(n-1), 1) for i in range(n)]
    boj = [round(v, 1) for v in ramp(11, 53)]
    for i in range(n-8, n): boj[i] = round(53 - (i-(n-9))*0.9, 1)   # 2024后减持
    _write("holders_jp", {"sample": True, "quarters": qs,
        "shares": {"日本银行": boj, "银行等": ramp(40, 12), "保险·年金": ramp(23, 20), "海外": ramp(8, 13),
                   "公的年金": ramp(8, 4), "家庭·其他": [round(100-a-b-c-d-e, 1) for a, b, c, d, e in
                                                   zip(boj, ramp(40, 12), ramp(23, 20), ramp(8, 13), ramp(8, 4))]},
        "total_t": ramp(950, 1250), "note": "资金循环统计(BOJ季度): 国债·国库短期证券合计持有者份额%"})


def seed_interest_jp():
    yrs = list(range(2001, 2027))
    _write("interest_jp", {"sample": True, "years": yrs,
        "interest_t": [10.0, 9.4, 8.0, 7.5, 7.3, 7.6, 8.0, 8.1, 7.6, 7.9, 8.1, 8.0, 8.0, 8.1, 8.2, 8.1, 8.0, 7.9, 7.8, 7.5, 7.3, 7.2, 7.5, 8.4, 10.5, 13.1],
        "avg_rate": [2.7, 2.4, 2.0, 1.7, 1.5, 1.5, 1.5, 1.5, 1.4, 1.3, 1.3, 1.2, 1.1, 1.1, 1.0, 0.9, 0.9, 0.9, 0.9, 0.8, 0.8, 0.8, 0.9, 1.0, 1.1, 1.2],
        "assumed_rate": [2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.3, 2.3, 2.0, 2.0, 2.0, 2.0, 1.8, 1.8, 1.8, 1.6, 1.1, 1.1, 1.1, 1.1, 1.1, 1.1, 1.1, 1.9, 2.0, 2.6],
        "wam_yr": [5.3, 5.6, 5.8, 6.0, 6.3, 6.6, 6.8, 7.0, 7.3, 7.5, 7.7, 7.9, 8.1, 8.3, 8.5, 8.8, 9.0, 9.1, 9.1, 9.2, 9.2, 9.2, 9.2, 9.2, 9.3, 9.3],
        "note": "利息支付等(一般会计国债费, 兆円)/存量加权利率%/预算假定利率%/平均剩余期限(年)"})


def seed_boj_plan():
    _write("boj_plan", {"sample": True, "as_of": "2025-06-17决定; 2026-06中期评估(维持, 待核)",
        "path": [("2024Q3", 5.7), ("2024Q4", 5.3), ("2025Q1", 4.9), ("2025Q2", 4.5), ("2025Q3", 4.1), ("2025Q4", 3.7),
                 ("2026Q1", 3.3), ("2026Q2", 2.9), ("2026Q3", 2.7), ("2026Q4", 2.5), ("2027Q1", 2.1)],
        "note": "月度长期国债购入预定额(兆円): 2026Q1前每季减0.4兆, 2026Q2起每季减0.2兆, 2027Q1约2兆; 持有份额约48%→减持中"})


def seed_auctions_jp():
    import random; random.seed(5)
    rows = []
    d = TODAY - timedelta(days=60)
    tenors = ["10年", "30年", "5年", "20年", "2年", "40年", "流动性供给"]
    while d <= TODAY + timedelta(days=30):
        if d.weekday() in (1, 3):
            t = tenors[(d.toordinal()) % len(tenors)]
            rows.append({"date": d.isoformat(), "tenor": t, "size_t": {"10年": 2.6, "30年": 0.7, "5年": 2.4, "20年": 0.9, "2年": 2.6, "40年": 0.5, "流动性供给": 0.6}[t],
                         "btc": round(random.uniform(2.6, 3.9), 2) if d <= TODAY else None,
                         "tail_bp": round(random.uniform(0.1, 3.5), 1) if d <= TODAY else None})
        d += timedelta(days=1)
    _write("auctions_jp", {"sample": True, "records": rows, "note": "招标结果(財務省逐场页面, 尽力解析待接入); btc=倍数, tail=平均-最低价差"})


SEEDS = {"budget_jp": seed_budget, "supplementary": seed_supplementary, "mlt_projection": seed_mlt,
         "issuance_plan": seed_issuance_plan, "tenor_history": seed_tenor_history, "tax_progress": seed_tax,
         "treasury_flows": seed_flows, "local_jp": seed_local_jp, "debt_long_jp": seed_debt_long,
         "holders_jp": seed_holders_jp, "interest_jp": seed_interest_jp, "boj_plan": seed_boj_plan,
         "auctions_jp": seed_auctions_jp}


def write_sample():
    for n, fn in SEEDS.items(): fn()
    # 利率样例: 2000+日频三期限
    kn = {"2y": [("2000-01", 0.5), ("2006-06", 0.9), ("2010-01", 0.15), ("2016-06", -0.3), ("2021-01", -0.13), ("2023-12", 0.05), ("2025-06", 0.75), ("2026-08", 1.05)],
          "10y": [("2000-01", 1.7), ("2006-06", 1.9), ("2010-01", 1.3), ("2016-06", -0.2), ("2021-01", 0.03), ("2023-12", 0.65), ("2025-06", 1.45), ("2026-08", 1.62)],
          "30y": [("2000-01", 2.4), ("2006-06", 2.5), ("2010-01", 2.2), ("2016-06", 0.3), ("2021-01", 0.65), ("2023-12", 1.65), ("2025-06", 2.95), ("2026-08", 3.25)]}
    ms = {t: dict(_interp(k)) for t, k in kn.items()}
    dates, ser = [], {t: [] for t in kn}
    d = date(2000, 1, 4)
    while d <= TODAY:
        if d.weekday() < 5:
            m = d.strftime("%Y-%m"); dates.append(d.isoformat())
            for t in kn: ser[t].append(round(ms[t].get(m, list(ms[t].values())[-1]) + 0.02*((d.day % 7) - 3)/3, 3))
        d += timedelta(days=1)
    _write("jgb_yields", {"sample": True, "dates": dates, "series": ser})
    _write("macro_jp", {"sample": True, "ngdp": {str(y): v for y, v in zip(range(2015, 2027), [540, 545, 553, 556, 558, 539, 553, 562, 597, 610, 628, 640])},
                        "debt_gdp": {str(y): v for y, v in zip(range(2015, 2027), [228, 232, 231, 232, 236, 258, 253, 248, 240, 237, 234, 232])},
                        "pb_gdp": {str(y): v for y, v in zip(range(2015, 2027), [-3.6, -3.4, -2.8, -2.2, -2.9, -8.6, -5.6, -3.6, -2.1, -1.5, -0.9, -0.5])}})
    print("日本示例完成")


GROUPS = {"daily": [ensure_seeds_jp, fetch_jgb_yields],
          "weekly": [ensure_seeds_jp, fetch_jgb_yields, fetch_macro_jp],
          "intraday": [ensure_seeds_jp]}


def run_group(mode):
    for fn in GROUPS.get(mode, []):
        print(f"- [jp:{mode}] {fn.__name__}")
        try: fn()
        except Exception as e: print(f"  !! {fn.__name__} 失败: {e} (保留上次数据)")


if __name__ == "__main__":
    if "--sample" in sys.argv: write_sample()
    else: run_group(sys.argv[1] if len(sys.argv) > 1 else "daily")
