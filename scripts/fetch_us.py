#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_us.py — 定量数据抓取 (FiscalData为主)
输出 data/us/*.json, 全部金额 USD bn。
用法: python scripts/fetch_us.py [--sample]
字段候选防御: 未命中落盘 _debug_*.json 供一次校正。
"""
import json, math, re, sys, time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "us"
BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
TODAY = date.today()


def _write(name, payload):
    OUT.mkdir(parents=True, exist_ok=True)
    payload.setdefault("fetched_at", datetime.utcnow().isoformat() + "Z")
    (OUT / f"{name}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  data/us/{name}.json")


def _debug(name, records):
    (OUT / f"_debug_{name}.json").write_text(
        json.dumps(records[:20], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  !! 字段未命中, 样本 -> _debug_{name}.json")


def _pick(rec, cands, cast=float):
    for c in cands:
        v = rec.get(c)
        if v not in (None, "", "null"):
            try:
                return cast(v)
            except (ValueError, TypeError):
                continue
    return None


def api_get(endpoint, params, max_pages=6):
    import requests
    out, page = [], 1
    while page <= max_pages:
        q = dict(params); q["page[number]"] = page; q.setdefault("page[size]", 1000)
        r = requests.get(BASE + endpoint, params=q, timeout=60)
        r.raise_for_status()
        body = r.json(); out.extend(body.get("data", []))
        if page >= int(body.get("meta", {}).get("total-pages", 1)):
            break
        page += 1; time.sleep(0.4)
    return out


def ago(n):
    return (TODAY - timedelta(days=n)).isoformat()


# ---------------------------------------------------------------- 真实抓取

def fetch_debt():
    recs = api_get("/v2/accounting/od/debt_to_penny",
                   {"filter": f"record_date:gte:{ago(560)}", "sort": "record_date"})
    s = []
    for r in recs:
        t = _pick(r, ["tot_pub_debt_out_amt"])
        if t is None: continue
        s.append({"date": r["record_date"], "total": round(t/1e9, 1),
                  "public": round((_pick(r, ["debt_held_public_amt"]) or 0)/1e9, 1),
                  "intragov": round((_pick(r, ["intragov_hold_amt"]) or 0)/1e9, 1)})
    if not s and recs: _debug("debt", recs)
    _write("debt", {"sample": False, "series": s})


REV_MAP = {
    "individual income taxes": "rev_ind",
    "total -- individual income taxes": "rev_ind",
    "corporation income taxes": "rev_corp",
    "total -- corporation income taxes": "rev_corp",
    "total -- social insurance and retirement receipts": "rev_pay",
    "customs duties": "rev_tariff",
    "total -- excise taxes": "rev_other",
    "estate and gift taxes": "rev_other",
    "total -- miscellaneous receipts": "rev_other",
}
OUT_MAP = {
    "social security": "out_ss",
    "medicare": "out_med",
    "health": "out_mcd",
    "income security": "out_incsec",
    "national defense": "out_def",
    "net interest": "out_int",
    # 其余支出职能 → out_ndd (t9收支同表, 不可用兜底)
    "international affairs": "out_ndd", "general science": "out_ndd",
    "energy": "out_ndd", "natural resources": "out_ndd", "agriculture": "out_ndd",
    "commerce and housing": "out_ndd", "transportation": "out_ndd",
    "community and regional": "out_ndd", "education": "out_ndd",
    "veterans benefits": "out_ndd", "administration of justice": "out_ndd",
    "general government": "out_ndd", "allowances": "out_ndd",
    "undistributed offsetting": "out_ndd",
}
REV_LABEL = {"rev_ind": "个人所得税", "rev_pay": "Payroll(社保税)", "rev_corp": "企业所得税",
             "rev_tariff": "关税", "rev_other": "其他收入"}
OUT_LABEL = {"out_ss": "社会保障", "out_med": "Medicare", "out_mcd": "Health(含Medicaid)",
             "out_incsec": "收入保障", "out_def": "国防", "out_ndd": "其余职能合计",
             "out_int": "净利息"}
MONTHS_EN = {"January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"}

def _cls_match(cls, mapping):
    c = (cls or "").strip().lower().rstrip(":")
    for k, v in mapping.items():
        if c == k or c.startswith(k):
            return v
    return None


def _fytd(r):
    return (_pick(r, ["current_fytd_net_rcpt_amt", "current_fytd_gross_rcpt_amt",
                      "current_fytd_net_outly_amt", "current_fytd_gross_outly_amt",
                      "current_fytd_outly_amt", "current_fytd_rcpt_outly_amt"]),
            _pick(r, ["prior_fytd_net_rcpt_amt", "prior_fytd_gross_rcpt_amt",
                      "prior_fytd_net_outly_amt", "prior_fytd_gross_outly_amt",
                      "prior_fytd_outly_amt", "prior_fytd_rcpt_outly_amt"]))


def fetch_debt_limit():
    """限额内 = 公众 + 政府间 - 不计入 + 其他计入 (表IIIC无合计行)。"""
    recs = api_get("/v1/accounting/dts/debt_subject_to_limit",
                   {"filter": f"record_date:gte:{ago(400)}", "sort": "record_date"}, max_pages=6)
    byd = {}
    for r in recs:
        v = _pick(r, ["close_today_bal"])
        if v is not None:
            byd.setdefault(r["record_date"], {})[(r.get("debt_catg") or "")] = v/1e3
    s = []
    NEED = ("Debt Held by the Public", "Intragovernmental Holdings", "Debt Not Subject to Limit")
    for d in sorted(byd):
        c = byd[d]
        if all(k in c for k in NEED):
            subj = c[NEED[0]] + c[NEED[1]] - c[NEED[2]] + c.get("Other Debt Subject to Limit", 0)
            s.append({"date": d, "subj_limit": round(subj, 1)})
    if not s:
        if recs: _debug("debt_limit", recs)
        print("  !! debt_limit零命中, 保留上一版")
        return
    _write("debt_limit", {"sample": False, "series": s})


def fetch_tga():
    recs = api_get("/v1/accounting/dts/operating_cash_balance",
                   {"filter": f"record_date:gte:{ago(220)}", "sort": "record_date"})
    dedup = {}
    for r in recs:
        acct = (r.get("account_type") or "")
        if "TGA" not in acct and "Federal Reserve Account" not in acct: continue
        v = _pick(r, ["close_today_bal", "closing_balance_today", "open_today_bal"])
        if v is not None:
            dedup[r["record_date"]] = {"date": r["record_date"], "close": round(v/1e3, 1)}
    s = [dedup[k] for k in sorted(dedup)]
    if not s and recs: _debug("tga", recs)
    _write("tga", {"sample": False, "series": s})


def fetch_mts():
    """MTS表1: classification=月份名 + MTH/D; dfct_sur赤字为正取负。"""
    recs = api_get("/v1/accounting/mts/mts_table_1",
                   {"filter": f"record_date:gte:{ago(2950)}", "sort": "record_date"}, max_pages=8)
    bym = {}
    for r in recs:
        if (r.get("record_type_cd"), r.get("data_type_cd")) != ("MTH", "D"): continue
        if (r.get("classification_desc") or "") not in MONTHS_EN: continue
        rcpt = _pick(r, ["current_month_gross_rcpt_amt"])
        outl = _pick(r, ["current_month_gross_outly_amt"])
        dfct = _pick(r, ["current_month_dfct_sur_amt"])
        if rcpt is None or outl is None: continue
        bym[r["record_date"][:7]] = {
            "receipts": round(rcpt/1e9, 1), "outlays": round(outl/1e9, 1),
            "balance": round((-dfct if dfct is not None else rcpt-outl)/1e9, 1)}
    s = [{"month": m, **v} for m, v in sorted(bym.items())]
    if not s:
        if recs: _debug("mts", recs)
        print("  !! mts零命中, 保留上一版")
        return
    _write("mts", {"sample": False, "series": s})


def _fetch_cat(table, name, mapping, labels, rest_id=None):
    recs = api_get(f"/v1/accounting/mts/mts_table_{table}",
                   {"filter": f"record_date:gte:{ago(70)}", "sort": "-record_date"}, max_pages=3)
    latest = max((r["record_date"] for r in recs), default=None)
    agg = {}
    for r in recs:
        if r["record_date"] != latest: continue
        if (r.get("data_type_cd") or "") not in ("D", "T"): continue
        cls_low = (r.get("classification_desc") or "").lower()
        cid = _cls_match(r.get("classification_desc"), mapping)
        if cid is None and rest_id and r.get("data_type_cd") == "D" and "total" not in cls_low:
            cid = rest_id
        if cid is None: continue
        cur, py = _fytd(r)
        if cur is None: continue
        a = agg.setdefault(cid, [0.0, 0.0])
        a[0] += cur/1e9
        a[1] += (py or 0)/1e9
    rows = [{"id": cid, "cat": labels.get(cid, cid), "fytd": round(v[0], 0),
             "fytd_prior": round(v[1], 0)} for cid, v in agg.items()]
    rows.sort(key=lambda x: -x["fytd"])
    if not rows:
        if recs: _debug(name, recs)
        print(f"  !! {name}零命中, 保留上一版")
        return
    _write(name, {"sample": False, "as_of": latest[:7] if latest else None, "rows": rows})


def fetch_auctions():
    recs = api_get("/v1/accounting/od/auctions_query",
                   {"filter": f"auction_date:gte:{ago(95)}", "sort": "-auction_date"})
    rows = []
    for r in recs:
        off = _pick(r, ["offering_amt", "total_accepted"])
        rows.append({"auction_date": r.get("auction_date"), "type": r.get("security_type"),
                     "term": r.get("security_term"), "cusip": r.get("cusip"),
                     "offering_bn": round(off/1e9, 1) if off else None,
                     "high_yield": _pick(r, ["high_yield", "high_investment_rate", "high_discnt_rate"]),
                     "btc": _pick(r, ["bid_to_cover_ratio"]),
                     "pd_pct": _pick(r, ["primary_dealer_accepted_pct"]),
                     "indirect_pct": _pick(r, ["indirect_bidder_accepted_pct"]),
                     "tail_bp": None})   # 空置接口: 需WI snap(BBG)
    if not rows and recs: _debug("auctions", recs)
    _write("auctions", {"sample": False, "records": rows})


def fetch_upcoming():
    recs = api_get("/v1/accounting/od/upcoming_auctions", {"sort": "auction_date"})
    rows = [{"announce": r.get("announcemt_date") or r.get("announcement_date"),
             "auction_date": r.get("auction_date"), "issue_date": r.get("issue_date"),
             "type": r.get("security_type"), "term": r.get("security_term"),
             "offering_bn": round(_pick(r, ["offering_amt"])/1e9, 1) if _pick(r, ["offering_amt"]) else None}
            for r in recs]
    _write("upcoming", {"sample": False, "records": rows})


BUYBACK_ENDPOINTS = ["/v1/accounting/od/treasury_securities_buybacks_operations",
                     "/v1/accounting/od/buybacks_operations",
                     "/v1/accounting/od/tsb_operations",
                     "/v1/accounting/od/buybacks_security_details",
                     "/v1/accounting/od/buybacks"]

def fetch_buybacks():
    recs, used = [], None
    for ep in BUYBACK_ENDPOINTS:
        try:
            recs = api_get(ep, {"filter": f"operation_date:gte:{ago(180)}", "sort": "-operation_date"})
            if recs:
                used = ep; break
        except Exception:
            continue
    if used: print(f"  buybacks端点: {used}")
    rows = []
    for r in recs:
        mx = _pick(r, ["max_purchase_amt", "maximum_purchase_amt"])
        acc = _pick(r, ["total_par_amt_accepted", "par_amt_accepted", "total_accepted_amt"])
        rows.append({"op_date": r.get("operation_date"), "bucket": r.get("security_bucket") or r.get("bucket_desc"),
                     "max_bn": round(mx/1e9, 2) if mx else None,
                     "accepted_bn": round(acc/1e9, 2) if acc else None,
                     "offer_to_max": _pick(r, ["offer_to_max_ratio"])})
    if not rows and recs: _debug("buybacks", recs)
    _write("buybacks", {"sample": False, "records": rows})


def fetch_avg_rates():
    recs = api_get("/v2/accounting/od/avg_interest_rates",
                   {"filter": f"record_date:gte:{ago(430)}", "sort": "record_date"})
    s = [{"month": r["record_date"][:7], "rate": round(_pick(r, ["avg_interest_rate_amt"]), 3)}
         for r in recs if (r.get("security_desc") or "").strip() == "Total Marketable"
         and _pick(r, ["avg_interest_rate_amt"]) is not None]
    _write("avg_rates", {"sample": False, "series": s})


def fetch_interest():
    recs = api_get("/v2/accounting/od/interest_expense",
                   {"filter": f"record_date:gte:{ago(430)}", "sort": "record_date"})
    bym = {}
    for r in recs:
        v = _pick(r, ["month_expense_amt", "intr_exp_amt", "expense_amt"])
        if v is not None:
            bym[r["record_date"][:7]] = bym.get(r["record_date"][:7], 0) + v/1e9
    s = [{"month": m, "expense_bn": round(v, 1)} for m, v in sorted(bym.items())]
    if not s and recs: _debug("interest", recs)
    _write("interest", {"sample": False, "series": s})


def _mspd_cls(cls):
    c = (cls or "").lower()
    if "inflation" in c: return "TIPS"
    if "floating" in c: return "FRN"
    return {"bills": "Bills", "notes": "Notes", "bonds": "Bonds"}.get(c)

def fetch_mspd():
    recs = api_get("/v1/debt/mspd/mspd_table_1",
                   {"filter": f"record_date:gte:{ago(70)}", "sort": "-record_date"})
    latest = max((r["record_date"] for r in recs), default=None)
    mix = []
    for r in recs:
        if r["record_date"] != latest: continue
        if (r.get("security_type_desc") or "") != "Marketable": continue
        c2 = _mspd_cls(r.get("security_class_desc"))
        if c2:
            v = _pick(r, ["total_mil_amt"])
            if v is not None:
                mix.append({"type": c2, "out_bn": round(v/1e3, 0)})
    if not mix and recs: _debug("mspd", recs)
    _write("mspd_structure", {"sample": False, "as_of": latest, "mix": mix,
                              "maturity_wall": [], "wam_months": None,
                              "note": "到期墙待mspd_table_3接入"})


def fetch_supply():
    """供给结构真实序列: MSPD月度bills/marketable + SOMA bills合并 (weekly)。"""
    recs = api_get("/v1/debt/mspd/mspd_table_1",
                   {"filter": "record_date:gte:2001-01-01", "sort": "record_date"}, max_pages=30)
    bym = {}
    for r in recs:
        ty = r.get("security_type_desc") or ""
        m = r["record_date"][:7]
        v = _pick(r, ["total_mil_amt"])
        if v is None: continue
        slot = bym.setdefault(m, {})
        if ty == "Total Marketable":
            slot["mkt"] = v/1e3
        elif ty == "Marketable" and (r.get("security_class_desc") or "") == "Bills":
            slot["bills"] = v/1e3
    soma = {}
    p = OUT / "soma.json"
    if p.exists():
        soma = {r["month"]: r["soma_bills"] for r in json.loads(p.read_text(encoding="utf-8")).get("series", [])}
    s = []
    for m in sorted(bym):
        b, k = bym[m].get("bills"), bym[m].get("mkt")
        if not b or not k: continue
        s.append({"month": m, "tbills_share": round(100*b/k, 1), "bills_bn": round(b, 0),
                  "soma_bills": soma.get(m)})
    if not s and recs: _debug("supply", recs)
    else: _write("supply", {"sample": False, "series": s})



def fetch_dts_flows():
    """DTS 日度存取款, 近45天按日聚合。"""
    recs = api_get("/v1/accounting/dts/deposits_withdrawals_operating_cash",
                   {"filter": f"record_date:gte:{ago(45)}", "sort": "record_date"})
    byd = {}
    for r in recs:
        tt = (r.get("transaction_type") or "").lower()
        catg = (r.get("transaction_catg") or r.get("transaction_catg_desc") or "")
        if "Public Debt" in catg:      # 剔除国债发行/赎回现金流, 得预算性流量
            continue
        v = _pick(r, ["transaction_today_amt", "today_amt"])
        if v is None: continue
        slot = byd.setdefault(r["record_date"], {"deposits": 0.0, "withdrawals": 0.0})
        if "deposit" in tt: slot["deposits"] += v/1e3
        elif "withdraw" in tt: slot["withdrawals"] += v/1e3
    s = [{"date": d, "deposits": round(v["deposits"], 1), "withdrawals": round(v["withdrawals"], 1)}
         for d, v in sorted(byd.items())]
    if not s and recs: _debug("dts_flows", recs)
    _write("dts_flows", {"sample": False, "series": s})


def fetch_debt_limit_history():
    """限额内债务月末序列2005/6+(组件透视), 之前年度总债务近似 (weekly)。"""
    recs = api_get("/v1/accounting/dts/debt_subject_to_limit",
                   {"filter": "record_date:gte:2005-06-01", "sort": "record_date"}, max_pages=60)
    byd = {}
    for r in recs:
        v = _pick(r, ["close_today_bal"])
        if v is not None:
            byd.setdefault(r["record_date"], {})[(r.get("debt_catg") or "")] = v/1e3
    bym = {}
    NEED = ("Debt Held by the Public", "Intragovernmental Holdings", "Debt Not Subject to Limit")
    for d in sorted(byd):
        c = byd[d]
        direct = next((v for k, v in c.items()
                       if "Subject to Limit" in k and "Total" in k and "Not" not in k), None)
        if direct is not None:                     # 老格式(约2022年前)有直取合计行
            bym[d[:7]] = round(direct, 1)
        elif all(k in c for k in NEED):
            bym[d[:7]] = round(c[NEED[0]] + c[NEED[1]] - c[NEED[2]]
                               + c.get("Other Debt Subject to Limit", 0), 1)
    try:
        hist = api_get("/v2/accounting/od/debt_outstanding", {"sort": "record_date"}, max_pages=2)
        for r in hist:
            y = (r.get("record_date") or "")[:4]
            v = _pick(r, ["debt_outstanding_amt"])
            if v and "1992" < y < "2006":
                bym.setdefault(f"{y}-09", round(v/1e9, 1))
    except Exception as e:
        print(f"  年度近似段失败(不阻塞): {e}")
    s2 = [{"month": m, "actual": v} for m, v in sorted(bym.items())]
    if not s2:
        if recs: _debug("debt_limit_history", recs)
        return
    _write("debt_limit_history", {"sample": False, "series": s2})


def _validate_series(pts, lo, hi, min_len, name):
    """数据校验门: 长度/末值区间/新鲜度。不过即抛错, 由调用方保留旧数据。"""
    if len(pts) < min_len:
        raise ValueError(f"{name} 序列过短: {len(pts)}")
    last_d, last_v = pts[-1]
    if not (lo <= last_v <= hi):
        raise ValueError(f"{name} 末值越界: {last_v}")
    if last_d < (TODAY - timedelta(days=10)).isoformat():
        raise ValueError(f"{name} 数据陈旧: {last_d}")
    return pts


def _spx_yahoo():
    """主源: Yahoo chart接口, ^GSPC日线, 双域名重试。"""
    import requests
    ua = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
          "Accept": "application/json"}
    r = None
    param_sets = [{"range": "max", "interval": "1d"},
                  {"period1": "694224000", "period2": "9999999999", "interval": "1d"}]
    for params in param_sets:
        for host in ("query1", "query2"):
            try:
                r0 = requests.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/%5EGSPC",
                                  params=params, headers=ua, timeout=90)
                r0.raise_for_status()
                ts0 = (r0.json()["chart"]["result"][0]).get("timestamp") or []
                if len(ts0) > 7000:
                    r = r0
                    break
                print(f"  yahoo {host} {list(params)[0]} 返回过短({len(ts0)}), 换参数")
            except Exception as e:
                print(f"  yahoo {host} 失败: {e}")
        if r is not None:
            break
    if r is None:
        raise ValueError("yahoo双域名双参数均失败")
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    out = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        d = datetime.utcfromtimestamp(t).date().isoformat()
        if d >= "1993-01-01":
            out.append([d, round(float(c), 1)])
    return out


def _spx_stooq():
    """备源: Stooq CSV (有限流与robots限制, 仅fallback)。"""
    import requests, csv, io
    r = requests.get("https://stooq.com/q/d/l/", params={"s": "^spx", "i": "d"},
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=90)
    r.raise_for_status()
    out = []
    for row in csv.DictReader(io.StringIO(r.text)):
        d = row.get("Date")
        if d and d >= "1993-01-01" and row.get("Close"):
            out.append([d, round(float(row["Close"]), 1)])
    return out


APPROPS_BILLS = ["Defense", "Labor", "MilCon", "Agriculture", "Commerce",
                 "Energy", "Financial", "Homeland", "Interior", "Legislative",
                 "State", "Transportation"]

ANNUAL_MAP = {  # classification_desc 关键词 → 科目id (首跑校验候选)
    "individual income": "rev_ind", "social insurance": "rev_pay", "corporation income": "rev_corp",
    "customs": "rev_tariff", "social security": "out_ss", "medicare": "out_med",
    "medicaid": "out_mcd", "income security": "out_incsec",
    "national defense": "out_def", "net interest": "out_int",
}

def fetch_annual():
    """年度分科目: 历年9月MTS current_fytd=全年 (weekly/due:mts)。"""
    out = {}
    for table, mapping, rest in ((4, REV_MAP, None), (9, OUT_MAP, None)):
        recs = api_get(f"/v1/accounting/mts/mts_table_{table}",
                       {"filter": "record_date:gte:2015-08-01", "sort": "record_date"}, max_pages=25)
        for r in recs:
            d = r.get("record_date") or ""
            if d[5:7] != "09": continue
            if (r.get("data_type_cd") or "") not in ("D", "T"): continue
            cls_low = (r.get("classification_desc") or "").lower()
            cid = _cls_match(r.get("classification_desc"), mapping)
            if cid is None and rest and r.get("data_type_cd") == "D" and "total" not in cls_low:
                cid = rest
            if cid is None: continue
            cur, _py = _fytd(r)
            if cur is None: continue
            fy = int(d[:4])
            out.setdefault(cid, {})[fy] = out.setdefault(cid, {}).get(fy, 0) + cur/1e9
    if not out:
        print("  !! annual无匹配, 落debug")
        try:
            recs = api_get("/v1/accounting/mts/mts_table_4",
                           {"filter": f"record_date:gte:{ago(430)}", "sort": "-record_date"}, max_pages=1)
            _debug("annual_t4", recs)
        except Exception:
            pass
        return
    years = sorted({fy for v in out.values() for fy in v})[-10:]
    _write("annual", {"sample": False, "years": years,
                      "series": {cid: [round(v.get(fy, 0), 1) or None for fy in years]
                                 for cid, v in out.items()},
                      "ngdp": []})


def fetch_approps_status():
    """CRS拨款状态表HTML解析(防御式): 提取每法案行原始单元格,
    表结构变化时落_debug供校正 (weekly)。"""
    import requests
    from html.parser import HTMLParser

    class TP(HTMLParser):
        def __init__(self):
            super().__init__(); self.rows, self.row, self.cell, self.in_td = [], [], "", False
        def handle_starttag(self, tag, attrs):
            if tag in ("td", "th"): self.in_td, self.cell = True, ""
            if tag == "tr": self.row = []
        def handle_endtag(self, tag):
            if tag in ("td", "th"): self.in_td = False; self.row.append(self.cell.strip())
            if tag == "tr" and self.row: self.rows.append(self.row)
        def handle_data(self, d):
            if self.in_td: self.cell += d

    r = requests.get("https://crsreports.congress.gov/AppropriationsStatusTable",
                     headers={"User-Agent": "Mozilla/5.0 fiscal-monitor"}, timeout=60)
    r.raise_for_status()
    p = TP(); p.feed(r.text)
    header, out = None, []
    for row in p.rows:
        joined = " ".join(row)
        if header is None and "House" in joined and "Senate" in joined:
            header = row
            continue
        for kw in APPROPS_BILLS:
            if row and kw.lower() in row[0].lower():
                filled = [i for i, c in enumerate(row[1:], 1) if c and c not in ("--", "—")]
                refs = sorted({f"119-{t.replace('.', '').lower().replace(' ', '')[:2].replace('hr', 'hr').replace('s', 's') if False else ('hr' if 'h' in t.lower() else 's')}-{n}"
                               for t, n in re.findall(r"(H\.?\s?R\.?|S\.?)\s*(\d{3,5})", " ".join(row))})
                out.append({"bill": kw, "cells": row, "refs": refs,
                            "latest_col": header[max(filled)] if (header and filled and max(filled) < len(header)) else None,
                            "latest_val": row[max(filled)] if filled else None})
    if not out:
        (OUT / "_debug_approps_status.html").write_text(r.text[:20000], encoding="utf-8")
        print("  !! 状态表解析为空, 原文样本已落盘")
    _write("approps_status", {"sample": False, "header": header, "rows": out})


def fetch_soma():
    """NY Fed SOMA汇总: bills持仓与总量, 月末降采样 (weekly)。"""
    import requests
    r = requests.get("https://markets.newyorkfed.org/api/soma/summary.json", timeout=60)
    r.raise_for_status()
    rows = (r.json().get("soma") or {}).get("summary") or []
    bym = {}
    for x in rows:
        d = x.get("asOfDate") or ""
        bills = _pick(x, ["bills"], float)
        tot = _pick(x, ["total", "totalSoma"], float)
        if d and bills is not None:
            bym[d[:7]] = {"month": d[:7], "soma_bills": round(bills/1e9, 1),
                          "soma_total": round((tot or 0)/1e9, 1)}
    s = [bym[m] for m in sorted(bym)]
    if not s and rows: _debug("soma", rows)
    _write("soma", {"sample": False, "series": s})


def fetch_debt_long():
    """年度总债务1975+ ×NGDP (weekly)。"""
    import requests, csv, io
    recs = api_get("/v2/accounting/od/debt_outstanding", {"sort": "record_date"}, max_pages=2)
    yrs, tot = [], []
    for r in recs:
        y = int((r.get("record_date") or "0")[:4] or 0)
        v = _pick(r, ["debt_outstanding_amt"])
        if y >= 1975 and v:
            yrs.append(y); tot.append(round(v/1e9, 0))
    ngdp = {}
    try:
        r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": "GDP"}, timeout=60)
        byy = {}
        for row in csv.DictReader(io.StringIO(r.text)):
            d, v = row.get("DATE") or row.get("observation_date"), row.get("GDP")
            if d and v and v != ".":
                byy.setdefault(int(d[:4]), []).append(float(v))
        ngdp = {y: round(sum(v)/len(v), 0) for y, v in byy.items()}
    except Exception as e:
        print(f"  NGDP失败: {e}")
    _write("debt_long", {"sample": False, "years": yrs, "total": tot,
                         "ngdp": [ngdp.get(y) for y in yrs]})


def fetch_market():
    """对比指标日频: US10Y=FRED DGS10; SPX=Yahoo主源/Stooq备源。
    校验门不过则保留该序列上一版 (weekly)。"""
    import requests, csv, io
    prev = {}
    p = OUT / "market.json"
    if p.exists():
        prev = json.loads(p.read_text(encoding="utf-8"))
    # US10Y
    try:
        out10 = []
        r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                         params={"id": "DGS10"}, timeout=90)
        r.raise_for_status()
        for row in csv.DictReader(io.StringIO(r.text)):
            d, v = row.get("DATE") or row.get("observation_date"), row.get("DGS10")
            if d and d >= "1993-01-01" and v and v != ".":
                out10.append([d, float(v)])
        _validate_series(out10, 0.2, 20, 7000, "US10Y")
    except Exception as e:
        print(f"  !! US10Y失败, 保留旧序列: {e}")
        out10 = prev.get("us10y", [])
    # SPX 主备切换
    try:
        outsp = _validate_series(_spx_yahoo(), 1000, 20000, 7000, "SPX(yahoo)")
        src = "yahoo"
    except Exception as e:
        print(f"  SPX主源失败({e}), 切Stooq备源")
        try:
            outsp = _validate_series(_spx_stooq(), 1000, 20000, 7000, "SPX(stooq)")
            src = "stooq"
        except Exception as e2:
            print(f"  SPX备源亦失败({e2}), 尝试FRED近10年拼接")
            try:
                fr = []
                r2 = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                                  params={"id": "SP500"}, timeout=60)
                r2.raise_for_status()
                for row in csv.DictReader(io.StringIO(r2.text)):
                    d, v = row.get("DATE") or row.get("observation_date"), row.get("SP500")
                    if d and v and v != ".":
                        fr.append([d, round(float(v), 1)])
                if len(fr) < 2000:
                    raise ValueError(f"FRED SP500过短 {len(fr)}")
                old = [p for p in prev.get("spx", []) if p[0] < fr[0][0]]
                outsp, src = old + fr, f"fred拼接(前段={prev.get('spx_src', 'sample')})"
            except Exception as e3:
                print(f"  !! FRED亦失败, 保留旧序列: {e3}")
                outsp, src = prev.get("spx", []), prev.get("spx_src", "stale")
    # NGDP年度(财年近似=日历年名义GDP均值)
    try:
        gdp = []
        r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                         params={"id": "GDP"}, timeout=60)
        r.raise_for_status()
        byy = {}
        for row in csv.DictReader(io.StringIO(r.text)):
            d, v = row.get("DATE") or row.get("observation_date"), row.get("GDP")
            if d and v and v != ".":
                byy.setdefault(int(d[:4]), []).append(float(v))
        gdp = [{"fy": y, "ngdp": round(sum(vs)/len(vs), 0)} for y, vs in sorted(byy.items()) if y >= 2015]
        p2 = OUT / "annual.json"
        if p2.exists():
            ann = json.loads(p2.read_text(encoding="utf-8"))
            ann["ngdp"] = [next((g["ngdp"] for g in gdp if g["fy"] == fy), None) for fy in ann["years"]]
            p2.write_text(json.dumps(ann, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"  NGDP补充失败(不阻塞): {e}")
    _write("market", {"sample": False, "spx_src": src, "us10y": out10, "spx": outsp})


def fetch_auctions_history():
    """拍卖历史深回溯至账本纪元, 供事件数据库存档 (weekly)。"""
    from events import HISTORY_EPOCH
    recs = api_get("/v1/accounting/od/auctions_query",
                   {"filter": f"auction_date:gte:{HISTORY_EPOCH.isoformat()}",
                    "sort": "auction_date"}, max_pages=12)
    rows = [{"auction_date": r.get("auction_date"), "type": r.get("security_type"),
             "term": r.get("security_term"),
             "offering_bn": round(_pick(r, ["offering_amt", "total_accepted"])/1e9, 1)
                 if _pick(r, ["offering_amt", "total_accepted"]) else None,
             "high_yield": _pick(r, ["high_yield", "high_investment_rate", "high_discnt_rate"]),
             "btc": _pick(r, ["bid_to_cover_ratio"])} for r in recs]
    _write("auctions_history", {"sample": False, "records": rows})


def fetch_coupon_deep():
    """coupon尺寸2007+与52周bill利率2001+, 独立深抓不入事件库 (weekly)。"""
    TEN = {"2-Year": "2y", "3-Year": "3y", "5-Year": "5y", "7-Year": "7y",
           "10-Year": "10y", "20-Year": "20y", "30-Year": "30y"}
    sizes, b1y = {}, {}
    for ty in ("Note", "Bond"):
        recs = api_get("/v1/accounting/od/auctions_query",
                       {"filter": f"auction_date:gte:2007-01-01,security_type:eq:{ty}",
                        "sort": "auction_date"}, max_pages=15)
        for r in recs:
            m, term = (r.get("auction_date") or "")[:7], r.get("security_term") or ""
            off = _pick(r, ["offering_amt", "total_accepted"])
            base = next((k for k in TEN if term.startswith(k)), None)
            if m and base and off:
                key = TEN[base]
                sizes.setdefault(m, {})[key] = max(sizes.get(m, {}).get(key, 0), off/1e9)
    recs = api_get("/v1/accounting/od/auctions_query",
                   {"filter": "auction_date:gte:2001-01-01,security_term:eq:52-Week",
                    "sort": "auction_date"}, max_pages=4)
    for r in recs:
        m = (r.get("auction_date") or "")[:7]
        hy = _pick(r, ["high_discnt_rate", "high_investment_rate", "high_yield"])
        if m and hy is not None:
            b1y.setdefault(m, []).append(hy)
    months = sorted(sizes)
    if months:
        _write("coupon_sizes", {"sample": False, "months": months,
            "tenors": {t: [round(sizes.get(m, {}).get(t), 0) if sizes.get(m, {}).get(t) else None
                           for m in months] for t in TEN.values()}})
    if b1y:
        _write("bill1y", {"sample": False, "series": [
            {"month": m, "rate": round(sum(v)/len(v), 3)} for m, v in sorted(b1y.items())]})


# ---------------------------------------------------------------- 调度注册表
# run.py 按组取用: daily=日度源; intraday=拍卖日快线; weekly=慢频;
# due组=事件账本判定当日到期的文件类抓取
FETCHERS = {
    "daily":    [fetch_debt, fetch_debt_limit, fetch_tga, fetch_dts_flows, fetch_upcoming,
                 fetch_approps_status],
    "intraday": [fetch_auctions, fetch_upcoming, fetch_buybacks],
    "weekly":   [fetch_mspd, fetch_buybacks, fetch_auctions, fetch_auctions_history,
                 fetch_debt_limit_history, fetch_market, fetch_approps_status, fetch_annual,
                 fetch_soma, fetch_debt_long, fetch_supply, fetch_coupon_deep,
                 fetch_mts, lambda: _fetch_cat(4, "mts_receipts", REV_MAP, REV_LABEL),
                 lambda: _fetch_cat(9, "mts_outlays", OUT_MAP, OUT_LABEL), fetch_avg_rates, fetch_interest],
    "due:mts":  [fetch_mts, lambda: _fetch_cat(4, "mts_receipts", REV_MAP, REV_LABEL),
                 lambda: _fetch_cat(9, "mts_outlays", OUT_MAP, OUT_LABEL), fetch_avg_rates, fetch_interest,
                 fetch_annual],
    "due:mspd": [fetch_mspd],
    "due:tic":  [],   # 接口空置: TIC接入后挂此处
    "due:qra_est": [], "due:qra_stmt": [],   # QRA为HTML文件包, 定性通道维护
}


def run_group(names):
    """执行去重后的抓取器集合, 单项失败不阻塞。"""
    seen, failed = set(), []
    for g in names:
        for job in FETCHERS.get(g, []):
            key = getattr(job, "__name__", repr(job))
            if key in seen: continue
            seen.add(key)
            try:
                print(f"- [{g}] {key}"); job()
            except Exception as e:
                print(f"  !! {key} 失败: {e} (保留上次数据)"); failed.append(key)
    return failed


# ---------------------------------------------------------------- 示例数据

def write_sample():
    print("写入示例数据 (sample=true)")
    import random
    random.seed(11)

    def _mnum(m): y, mm = int(m[:4]), int(m[5:7]); return y*12+mm

    def _interp(knots):
        out = []
        for i in range(len(knots)-1):
            (m0, v0), (m1, v1) = knots[i], knots[i+1]
            n = _mnum(m1) - _mnum(m0)
            for k in range(n):
                t = _mnum(m0) + k
                out.append((f"{(t-1)//12:04d}-{(t-1)%12+1:02d}", v0 + (v1-v0)*k/n))
        out.append(knots[-1]); return out


    # 债务
    s, d0, n = [], date(2025, 8, 8), 52
    for i in range(n + 1):
        d = d0 + timedelta(weeks=i)
        total = 37500 + 2400*i/n + random.uniform(-25, 25)
        ig = 7350 + 150*i/n + random.uniform(-8, 8)
        s.append({"date": d.isoformat(), "total": round(total, 1),
                  "public": round(total-ig, 1), "intragov": round(ig, 1)})
    _write("debt", {"sample": True, "series": s})
    _write("debt_limit", {"sample": True, "series": [
        {"date": ago(3), "subj_limit": 39790.0}]})

    # TGA
    s, i2 = [], 0
    for i in range(150):
        d = TODAY - timedelta(days=149-i)
        if d.weekday() >= 5: continue
        i2 += 1
        drift = 300*math.exp(-((i2-14)**2)/90) - 0.9*i2*(1-i2/105) + max(0, i2-72)*4.6
        s.append({"date": d.isoformat(), "close": round(max(690+drift+random.uniform(-18, 18), 340), 1)})
    _write("tga", {"sample": True, "series": s})

    # MTS 33个月 (FY24全年, FY25全年, FY26至6月), 单位bn
    bal = {  # 月度赤字(-)/盈余(+), FY2020起8个财年
        "2019-10": -134, "2019-11": -209, "2019-12": -13, "2020-01": -33,
        "2020-02": -235, "2020-03": -119, "2020-04": -738, "2020-05": -399,
        "2020-06": -864, "2020-07": -63, "2020-08": -200, "2020-09": -125,
        "2020-10": -284, "2020-11": -145, "2020-12": -144, "2021-01": -163,
        "2021-02": -311, "2021-03": -660, "2021-04": -226, "2021-05": -132,
        "2021-06": -174, "2021-07": -302, "2021-08": -171, "2021-09": -60,
        "2021-10": -165, "2021-11": -191, "2021-12": -21, "2022-01": 119,
        "2022-02": -217, "2022-03": -193, "2022-04": 308, "2022-05": -66,
        "2022-06": -89, "2022-07": -211, "2022-08": -220, "2022-09": -430,
        "2022-10": -88, "2022-11": -249, "2022-12": -85, "2023-01": -39,
        "2023-02": -262, "2023-03": -278, "2023-04": 176, "2023-05": -240,
        "2023-06": -150, "2023-07": -221, "2023-08": -89, "2023-09": -171,
        "2023-10": -67, "2023-11": -314, "2023-12": -129, "2024-01": -22,
        "2024-02": -296, "2024-03": -236, "2024-04": 210, "2024-05": -347,
        "2024-06": -66, "2024-07": -244, "2024-08": -380, "2024-09": 64,
        "2024-10": -257, "2024-11": -367, "2024-12": -87, "2025-01": -129,
        "2025-02": -307, "2025-03": -161, "2025-04": 258, "2025-05": -316,
        "2025-06": -71, "2025-07": -235, "2025-08": -245, "2025-09": 92,
        "2025-10": -240, "2025-11": -350, "2025-12": -95, "2026-01": -60,
        "2026-02": -290, "2026-03": -200, "2026-04": 230, "2026-05": -300,
        "2026-06": -68,
    }
    s = []
    for m, b in bal.items():
        rc = {"01": 513, "02": 300, "03": 370, "04": 850, "05": 373, "06": 526,
              "07": 340, "08": 345, "09": 525, "10": 330, "11": 305, "12": 455}[m[5:]]
        rc = rc + random.uniform(-12, 12)
        s.append({"month": m, "receipts": round(rc, 1),
                  "outlays": round(rc-b, 1), "balance": b})
    _write("mts", {"sample": True, "series": s})

    _write("mts_receipts", {"sample": True, "as_of": "2026-06", "rows": [
        {"id": "rev_ind", "cat": "个人所得税", "fytd": 2400, "fytd_prior": 2280},
        {"id": "rev_pay", "cat": "Payroll(社保税)", "fytd": 1310, "fytd_prior": 1265},
        {"id": "rev_corp", "cat": "企业所得税", "fytd": 380, "fytd_prior": 355},
        {"id": "rev_tariff", "cat": "关税", "fytd": 310, "fytd_prior": 95},
        {"id": "rev_other", "cat": "其他收入", "fytd": 189, "fytd_prior": 182}]})
    _write("mts_outlays", {"sample": True, "as_of": "2026-06", "rows": [
        {"id": "out_ss", "cat": "社会保障", "fytd": 1180, "fytd_prior": 1105},
        {"id": "out_med", "cat": "Medicare", "fytd": 830, "fytd_prior": 770},
        {"id": "out_mcd", "cat": "Medicaid", "fytd": 500, "fytd_prior": 470},
        {"id": "out_incsec", "cat": "收入保障", "fytd": 520, "fytd_prior": 505},
        {"id": "out_othm", "cat": "其他强制性", "fytd": 490, "fytd_prior": 460},
        {"id": "out_def", "cat": "国防(裁量)", "fytd": 660, "fytd_prior": 630},
        {"id": "out_ndd", "cat": "非国防裁量", "fytd": 560, "fytd_prior": 540},
        {"id": "out_int", "cat": "净利息", "fytd": 720, "fytd_prior": 670}]})

    # 年度序列 FY2016-2025 (样例, 量级贴近实际)
    _write("annual", {"sample": True, "years": list(range(2016, 2026)), "series": {
        "rev_ind":   [1546,1587,1684,1718,1609,2044,2632,2176,2426,2621],
        "rev_pay":   [1115,1162,1171,1243,1310,1314,1484,1614,1709,1759],
        "rev_corp":  [300,297,205,230,212,372,425,420,530,524],
        "rev_tariff":[35,34,41,71,69,80,100,80,77,195],
        "rev_other": [272,236,229,201,221,261,255,149,176,190],
        "out_ss":    [916,939,988,1044,1096,1135,1219,1354,1463,1580],
        "out_med":   [588,591,585,644,769,689,747,839,869,930],
        "out_mcd":   [368,375,389,409,458,521,592,616,618,655],
        "out_incsec":[514,503,495,514,1052,1649,865,775,671,640],
        "out_othm":  [400,420,430,450,900,800,600,520,560,420],
        "out_def":   [585,590,623,676,714,742,751,806,874,895],
        "out_ndd":   [600,610,639,661,914,895,910,917,948,960],
        "out_int":   [240,263,325,376,345,352,475,659,882,970]},
        "ngdp": [18695,19477,20533,21381,21060,22996,25744,27360,28781,30136]})

    # DTS 日度流量 近22个交易日
    s, i2 = [], 0
    for i in range(32):
        d = TODAY - timedelta(days=31-i)
        if d.weekday() >= 5: continue
        i2 += 1
        dep = 32 + (55 if d.day in (15, 16) else 0) + random.uniform(-6, 14)
        wd = 36 + (48 if d.day in (1, 2, 3) else 0) + random.uniform(-6, 16)
        s.append({"date": d.isoformat(), "deposits": round(dep, 1), "withdrawals": round(wd, 1)})
    _write("dts_flows", {"sample": True, "series": s})

    # 拍卖
    _write("auctions", {"sample": True, "records": [
        {"auction_date": "2026-08-03", "type": "Bill", "term": "13-Week", "offering_bn": 84, "high_yield": 3.555, "btc": 2.92, "pd_pct": None, "indirect_pct": None, "tail_bp": None},
        {"auction_date": "2026-08-03", "type": "Bill", "term": "26-Week", "offering_bn": 76, "high_yield": 3.500, "btc": 3.01, "pd_pct": None, "indirect_pct": None, "tail_bp": None},
        {"auction_date": "2026-07-29", "type": "Note", "term": "7-Year", "offering_bn": 44, "high_yield": 3.952, "btc": 2.52, "pd_pct": 10.8, "indirect_pct": 71.4, "tail_bp": None},
        {"auction_date": "2026-07-29", "type": "FRN", "term": "2-Year", "offering_bn": 28, "high_yield": 0.130, "btc": 3.34, "pd_pct": None, "indirect_pct": None, "tail_bp": None},
        {"auction_date": "2026-07-28", "type": "Note", "term": "5-Year", "offering_bn": 70, "high_yield": 3.786, "btc": 2.41, "pd_pct": 14.1, "indirect_pct": 66.2, "tail_bp": None},
        {"auction_date": "2026-07-28", "type": "Note", "term": "2-Year", "offering_bn": 69, "high_yield": 3.618, "btc": 2.58, "pd_pct": 12.3, "indirect_pct": 68.9, "tail_bp": None},
        {"auction_date": "2026-07-27", "type": "Bill", "term": "4-Week", "offering_bn": 95, "high_yield": 3.545, "btc": 2.86, "pd_pct": None, "indirect_pct": None, "tail_bp": None}]})
    _write("upcoming", {"sample": True, "records": [
        {"announce": "2026-08-05", "auction_date": "2026-08-11", "issue_date": "2026-08-17", "type": "Note", "term": "3-Year", "offering_bn": None},
        {"announce": "2026-08-05", "auction_date": "2026-08-12", "issue_date": "2026-08-17", "type": "Note", "term": "10-Year", "offering_bn": None},
        {"announce": "2026-08-05", "auction_date": "2026-08-13", "issue_date": "2026-08-17", "type": "Bond", "term": "30-Year", "offering_bn": None},
        {"announce": "2026-08-06", "auction_date": "2026-08-10", "issue_date": "2026-08-13", "type": "Bill", "term": "13-Week", "offering_bn": 84},
        {"announce": "2026-08-06", "auction_date": "2026-08-10", "issue_date": "2026-08-13", "type": "Bill", "term": "26-Week", "offering_bn": 76}]})

    _write("buybacks", {"sample": True, "records": [
        {"op_date": "2026-07-29", "bucket": "TIPS 7.5Y-30Y", "max_bn": 0.5, "accepted_bn": 0.5, "offer_to_max": 2.8},
        {"op_date": "2026-07-22", "bucket": "Nominal 20Y-30Y", "max_bn": 2.0, "accepted_bn": 1.6, "offer_to_max": 1.2},
        {"op_date": "2026-07-15", "bucket": "Nominal 2Y-3Y", "max_bn": 4.0, "accepted_bn": 4.0, "offer_to_max": 2.1},
        {"op_date": "2026-07-08", "bucket": "Nominal 10Y-20Y", "max_bn": 2.0, "accepted_bn": 2.0, "offer_to_max": 3.4}]})

    # 供给结构 2000+: bills份额 + bills存量 + SOMA bills
    shr_k = [("2000-01", 23), ("2004-01", 20), ("2007-06", 21), ("2008-12", 31), ("2010-06", 23),
             ("2013-01", 17), ("2016-06", 11), ("2018-01", 13), ("2019-06", 14.5), ("2020-06", 25),
             ("2021-12", 17), ("2022-12", 15.5), ("2024-01", 21), ("2026-06", 22.3)]
    bo_k = [("2000-01", 616), ("2008-12", 1861), ("2016-06", 1650), ("2020-06", 5100),
            ("2022-12", 3900), ("2026-06", 6600)]
    sb_k = [("2000-01", 180), ("2007-06", 277), ("2009-06", 18), ("2013-01", 0), ("2019-07", 0),
            ("2020-04", 326), ("2022-06", 326), ("2023-06", 290), ("2024-06", 195),
            ("2025-09", 200), ("2026-06", 240)]
    shr, bo, sb = dict(_interp(shr_k)), dict(_interp(bo_k)), dict(_interp(sb_k))
    s = [{"month": m, "tbills_share": round(shr[m], 1), "bills_bn": round(bo[m], 0),
          "soma_bills": round(max(sb[m], 0), 0)} for m in sorted(shr) if m in bo and m in sb]
    _write("supply", {"sample": True, "series": s})

    _write("mspd_structure", {"sample": True, "as_of": "2026-06-30",
        "mix": [{"type": "Bills", "out_bn": 6600}, {"type": "Notes", "out_bn": 15200},
                {"type": "Bonds", "out_bn": 5200}, {"type": "TIPS", "out_bn": 2100},
                {"type": "FRN", "out_bn": 650}],
        "maturity_wall": [{"bucket": "<1y", "bn": 8200}, {"bucket": "1-2y", "bn": 3900},
                          {"bucket": "2-3y", "bn": 3300}, {"bucket": "3-5y", "bn": 4800},
                          {"bucket": "5-7y", "bn": 2900}, {"bucket": "7-10y", "bn": 2600},
                          {"bucket": "10y+", "bn": 4050}],
        "wam_months": 71})

    # 债限内债务历史(月度, 拐点线性插值, 达限期平台)
    knots = [("1993-01", 4150), ("1995-01", 4800), ("1997-01", 5320), ("2000-01", 5660),
             ("2001-06", 5670), ("2002-06", 6100), ("2005-06", 7830), ("2007-09", 9000),
             ("2008-11", 10600), ("2009-12", 12310), ("2011-01", 14000), ("2011-07", 14290), ("2011-09", 14790), ("2012-12", 16390),
             ("2013-05", 16700), ("2014-02", 17200), ("2015-03", 18110), ("2015-10", 18150),
             ("2016-12", 19570), ("2017-09", 20340), ("2019-02", 22020), ("2019-08", 22030),
             ("2020-06", 26480), ("2021-07", 28400), ("2021-12", 28900), ("2022-12", 31300),
             ("2023-05", 31380), ("2024-01", 34000), ("2024-12", 36100), ("2025-06", 36180),
             ("2026-07", 39790)]
    series = []
    for i in range(len(knots)-1):
        (m0, v0), (m1, v1) = knots[i], knots[i+1]
        n = _mnum(m1) - _mnum(m0)
        for k in range(n):
            t = _mnum(m0) + k
            series.append({"month": f"{(t-1)//12:04d}-{(t-1)%12+1:02d}",
                           "actual": round(v0 + (v1-v0)*k/n, 0)})
    series.append({"month": knots[-1][0], "actual": knots[-1][1]})
    _write("debt_limit_history", {"sample": True, "series": series})

    import datetime as _dt
    def _daily(knots, jitter, nd=1):
        pts, kn = [], [( _mnum(m)*30, v) for m, v in knots]
        d0 = _dt.date(1993, 1, 4)
        d = d0
        end = TODAY
        while d <= end:
            if d.weekday() < 5:
                t = (_mnum(d.strftime("%Y-%m")) * 30 + d.day)
                v = None
                for i in range(len(kn)-1):
                    if kn[i][0] <= t <= kn[i+1][0]:
                        f0 = (t - kn[i][0]) / (kn[i+1][0] - kn[i][0])
                        v = kn[i][1] + (kn[i+1][1] - kn[i][1]) * f0
                        break
                if v is None:
                    v = kn[-1][1]
                pts.append([d.isoformat(), round(v * (1 + random.uniform(-jitter, jitter)), nd)])
            d += _dt.timedelta(days=1)
        return pts
    spx_k = [("1993-01", 435), ("1997-01", 740), ("2000-08", 1500), ("2002-09", 815),
             ("2007-10", 1550), ("2009-03", 735), ("2013-01", 1480), ("2016-02", 1870),
             ("2018-09", 2900), ("2018-12", 2500), ("2020-02", 3380), ("2020-03", 2400),
             ("2021-12", 4770), ("2022-10", 3580), ("2024-12", 6040), ("2025-04", 5300),
             ("2026-07", 6850)]
    y10_k = [("1993-01", 6.6), ("1994-11", 8.0), ("1998-10", 4.5), ("2000-01", 6.7),
             ("2003-06", 3.3), ("2006-06", 5.2), ("2008-12", 2.2), ("2010-04", 4.0),
             ("2012-07", 1.5), ("2013-12", 3.0), ("2016-07", 1.4), ("2018-11", 3.2),
             ("2020-08", 0.55), ("2022-10", 4.2), ("2023-10", 4.9), ("2024-09", 3.7),
             ("2026-07", 4.25)]
    _write("market", {"sample": True,
                      "spx": _daily(spx_k, 0.012, 1),
                      "us10y": _daily(y10_k, 0.015, 2)})

    _write("approps_status", {"sample": True, "header": ["Bill", "House Sub", "House Cmte", "House Floor", "Senate Cmte", "Senate Floor", "Law"],
        "rows": [
            {"bill": "Defense", "latest_col": "House Cmte", "latest_val": "6/24/26 (35-27)", "refs": ["119-hr-9105"]},
            {"bill": "MilCon", "latest_col": "House Floor", "latest_val": "7/22/26 (219-207)"},
            {"bill": "Energy", "latest_col": "House Floor", "latest_val": "7/29/26 (214-209)"}]})

    ar_k = [("2001-01", 6.3), ("2004-01", 4.4), ("2007-06", 4.95), ("2010-01", 3.3),
            ("2013-01", 2.0), ("2016-01", 2.03), ("2019-01", 2.55), ("2021-01", 1.61),
            ("2022-06", 1.8), ("2023-06", 2.6), ("2024-06", 3.1), ("2026-07", 3.39)]
    _write("avg_rates", {"sample": True, "series": [
        {"month": m, "rate": round(v, 2)} for m, v in _interp(ar_k)]})
    b1_k = [("2001-01", 5.5), ("2003-06", 1.1), ("2006-06", 5.1), ("2008-12", 0.4),
            ("2015-01", 0.4), ("2019-01", 2.6), ("2020-06", 0.16), ("2022-12", 4.7),
            ("2023-10", 5.4), ("2024-12", 4.2), ("2026-07", 3.55)]
    _write("bill1y", {"sample": True, "series": [
        {"month": m, "rate": round(v, 2)} for m, v in _interp(b1_k)]})

    # QRA历史(每季人工录入): 私人净融资 / 期末TGA假设
    _write("qra_history", {"sample": True, "rows": [
        {"q": "2023Q4", "borrowing": 776, "tga_end": 750}, {"q": "2024Q1", "borrowing": 760, "tga_end": 750},
        {"q": "2024Q2", "borrowing": 243, "tga_end": 750}, {"q": "2024Q3", "borrowing": 740, "tga_end": 850},
        {"q": "2024Q4", "borrowing": 546, "tga_end": 700}, {"q": "2025Q1", "borrowing": 815, "tga_end": 850},
        {"q": "2025Q2", "borrowing": 514, "tga_end": 850}, {"q": "2025Q3", "borrowing": 590, "tga_end": 850},
        {"q": "2025Q4", "borrowing": 569, "tga_end": 850}, {"q": "2026Q1", "borrowing": 823, "tga_end": 900},
        {"q": "2026Q2", "borrowing": 466, "tga_end": 900}, {"q": "2026Q3", "borrowing": 671, "tga_end": 1000},
        {"q": "2026Q4", "borrowing": None, "tga_end": None, "note": "11/2 QRFE公布"}]})

    # coupon尺寸 2007+ (月度, 各期限)
    ck = {"2y": [("2007-01",18),("2009-06",44),("2011-01",35),("2015-01",26),("2019-06",40),("2021-06",60),("2023-06",42),("2024-06",69),("2026-10",69)],
          "3y": [("2007-01",12),("2009-06",40),("2011-01",32),("2015-01",24),("2019-06",38),("2021-06",58),("2023-06",40),("2024-06",58),("2026-10",58)],
          "5y": [("2007-01",13),("2009-06",42),("2011-01",35),("2015-01",35),("2019-06",41),("2021-06",62),("2023-06",43),("2024-06",70),("2026-10",70)],
          "7y": [("2009-03",22),("2010-01",29),("2015-01",29),("2019-06",32),("2021-06",62),("2023-06",35),("2024-06",44),("2026-10",44)],
          "10y": [("2007-01",8),("2009-06",21),("2011-01",24),("2015-01",21),("2019-06",24),("2021-06",41),("2023-06",35),("2024-06",42),("2026-10",42)],
          "20y": [("2020-05",20),("2021-06",27),("2022-06",16),("2024-06",16),("2026-10",16)],
          "30y": [("2007-01",5),("2009-06",13),("2011-01",16),("2015-01",13),("2019-06",16),("2021-06",27),("2023-06",21),("2024-06",25),("2026-10",25)]}
    all_m = [m for m, _ in _interp([("2007-01",0),("2026-10",0)])]
    tenors = {}
    for t, kn in ck.items():
        d = dict(_interp(kn))
        tenors[t] = [round(d[m], 0) if m in d else None for m in all_m]
    _write("coupon_sizes", {"sample": True, "months": all_m, "tenors": tenors})

    # WAM 1980+ (TBAC口径, 每QRA后校准)
    wam_k = [("1980-01",43.5),("1984-01",52),("1988-01",63),("1991-06",67),("1994-01",62),
             ("1997-01",58),("2001-01",70),("2005-06",54),("2008-12",49),("2012-01",62),
             ("2016-01",70),("2019-06",70),("2020-04",62.5),("2023-06",74),("2025-01",72),("2026-07",71)]
    _write("wam", {"sample": True, "series": [
        {"month": m, "wam": round(v, 1)} for m, v in _interp(wam_k)]})

    # 债务长史 1975+
    dl_k = [("1975-01",533),("1980-01",908),("1985-01",1823),("1990-01",3233),("1995-01",4974),
            ("2000-01",5674),("2005-01",7933),("2010-01",13562),("2015-01",18151),
            ("2020-01",23200),("2021-01",27750),("2023-01",31420),("2026-01",39400)]
    ng_k = [("1975-01",1689),("1980-01",2857),("1985-01",4339),("1990-01",5963),("1995-01",7639),
            ("2000-01",10250),("2005-01",13039),("2010-01",15049),("2015-01",18206),
            ("2020-01",21060),("2023-01",27360),("2026-01",30800)]
    dl, ng = dict(_interp(dl_k)), dict(_interp(ng_k))
    yrs = [y for y in range(1975, 2027)]
    _write("debt_long", {"sample": True, "years": yrs,
                         "total": [round(dl[f"{y}-01"], 0) for y in yrs],
                         "ngdp": [round(ng[f"{y}-01"], 0) for y in yrs]})
    _write("interest", {"sample": True, "series": [
        {"month": m2, "expense_bn": round(92+random.uniform(0, 26), 1)}
        for m2 in [f"2025-{m:02d}" for m in range(7, 13)] + [f"2026-{m:02d}" for m in range(1, 7)]]})
    print("示例完成。真实抓取: python scripts/fetch_us.py")


def main():
    if "--sample" in sys.argv:
        write_sample(); return
    run_group(["daily", "intraday", "weekly", "due:mts", "due:mspd"])  # 全量(手动兜底)


if __name__ == "__main__":
    main()
