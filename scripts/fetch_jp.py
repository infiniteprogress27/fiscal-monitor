"""日本财政数据抓取 (data/jp)。稳定源自动; Excel/PDF源为对话锚。金额单位: ¥T(T¥)除注明外。"""
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
    urls = ["https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv",
            "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcme.csv",
            "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv",
            "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv"]
    # 累积档: 历史文件若不可得, 当月文件逐日并入
    p_arch = OUT / "jgb_yields.json"
    if p_arch.exists():
        arch = json.loads(p_arch.read_text(encoding="utf-8"))
        if not arch.get("sample"):
            for i, d in enumerate(arch.get("dates", [])):
                byd_prev = {k: arch["series"][k][i] for k in arch["series"] if arch["series"][k][i] is not None}
                if byd_prev: globals().setdefault("_ARCH", {})[d] = byd_prev
    TEN = {"1年": "1y", "2年": "2y", "5年": "5y", "10年": "10y", "20年": "20y", "30年": "30y", "40年": "40y"}
    byd = dict(globals().get("_ARCH", {}))
    got = 0
    diag = []
    for u in urls:
        try:
            r = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=90)
            diag.append(f"URL {u.rsplit('/',1)[-1]} status={r.status_code} bytes={len(r.content)} ctype={r.headers.get('content-type')}")
            if r.status_code != 200: continue
            text = r.content.decode("shift_jis", "ignore")
            rows = list(csv.reader(io.StringIO(text)))
            diag.append("首5行: " + " || ".join(",".join(x)[:120] for x in rows[:5]))
            diag.append("末2行: " + " || ".join(",".join(x)[:120] for x in rows[-2:]))
            hdr_i = next((i for i, row in enumerate(rows) if any(("10年" in c) or (c.strip().upper() == "10Y") for c in row)), None)
            if hdr_i is None: continue
            hdr = [c.strip() for c in rows[hdr_i]]
            idx = {TEN[h]: i for i, h in enumerate(hdr) if h in TEN}
            if not idx:   # 英文表头
                EN = {"1Y": "1y", "2Y": "2y", "5Y": "5y", "10Y": "10y", "20Y": "20y", "30Y": "30y", "40Y": "40y"}
                idx = {EN[h.upper()]: i for i, h in enumerate(hdr) if h.upper() in EN}
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
    (OUT / "_debug_jgb.txt").write_text(f"parsed={len(byd)} got={got}\n" + "\n".join(diag), encoding="utf-8")
    if got == 0:
        print("  !! JGB利率零命中, 保留上一版"); return
    if len(byd) < 500:
        print(f"  JGB利率累积档 {len(byd)}日 (历史文件未得, 逐日增长)")
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
        out["ngdp"] = {str(y): round(sum(v)/len(v)/1000, 1) for y, v in byy.items()}   # →¥T
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


# ---------------------------------------------------------------- 尽力自动三项 (2026-11 接入)
UA = {"User-Agent": "fiscal-monitor (+https://github.com/infiniteprogress27/fiscal-monitor)"}
MOF = "https://www.mof.go.jp"


def _debug(name, obj):
    (OUT / f"_debug_{name}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def _flat(html):
    """HTML→单行纯文本: 去标签/空白, 全角数字→半角, ▲→负号。"""
    import re, html as H
    t = re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", "", html, flags=re.S)
    t = H.unescape(re.sub(r"<[^>]+>", "", t))
    t = t.translate(str.maketrans("０１２３４５６７８９．，", "0123456789.,"))
    return re.sub(r"[\s　|]+", "", t).replace("▲", "-")


def _oku(s):
    """'1兆5,126億円' → 15126 (億円)。"""
    import re
    m = re.search(r"(?:(\d+)兆)?([\d,]+)億円", s or "")
    return (int(m.group(1) or 0)*10000 + int(m.group(2).replace(",", ""))) if m else None


def _jp_tenor(name):
    """招标对象名 → 期限标签; 国库短期证券(T-bill)不收。"""
    import re
    n = name.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if "国庫短期証券" in n: return None
    if "流動性供給" in n:
        m = re.search(r"(\d+)年超(\d+)年", n)
        return f"流动性供给{m.group(1)}-{m.group(2)}年" if m else "流动性供给"
    m = re.search(r"(\d+)年", n)
    if not m: return None
    if "物価連動" in n: return f"{m.group(1)}年物价联动"
    if "クライメート" in n: return f"{m.group(1)}年GX"
    if "利付国債" in n: return f"{m.group(1)}年"
    return None


def _auction_result(txt):
    """逐场结果页纯文本 → btc/tail_bp/size_t。字段校准(2026-11, resul20261110/20261022):
    利付债: 6.价格竞争 应募额/募入决定额/(募入最高利回り)/(募入平均利回り); 7.第Ⅰ非价格 募入决定额。
    流动性供给: 应募额/募入决定额/募入最大利回格差/募入平均利回格差(▲=负, 也有+号)。
    40年(利回り竞争)与GX(单一价格)无平均利回り, 尾差留空。
    倍数=应募额/价格竞争募入决定额; 尾差=(最高-平均)利回り×100bp; 规模=价格竞争+第Ⅰ非价格(不含第Ⅱ)。"""
    import re
    out = {}
    i_nc = txt.find("第Ⅰ非価格", max(txt.find("応募額"), 0))   # 导语句也含"第Ⅰ非価格", 从应募额之后找
    comp_part = txt[:i_nc] if i_nc > 0 else txt
    bid = _oku(comp_part[comp_part.find("応募額"):][:40]) if "応募額" in comp_part else None
    j = comp_part.find("募入決定額")
    alloc = _oku(comp_part[j:j+40]) if j >= 0 else None
    nc1 = None
    if i_nc > 0:
        k = txt.find("募入決定額", i_nc)
        nc1 = _oku(txt[k:k+40]) if k >= 0 else None
    if bid and alloc:
        out["btc"] = round(bid/alloc, 2)
        out["size_t"] = round((alloc + (nc1 or 0))/10000, 2)
    hi = re.search(r"募入最高利回り）?（?([+-]?[\d.]+)％", txt) or re.search(r"募入最大利回格差（?([+-]?[\d.]+)％", txt)
    av = re.search(r"募入平均利回り）?（?([+-]?[\d.]+)％", txt) or re.search(r"募入平均利回格差（?([+-]?[\d.]+)％", txt)
    if hi and av:
        out["tail_bp"] = round((float(hi.group(1)) - float(av.group(1)))*100, 1)
        if "利回格差" not in txt: out["yield"] = float(av.group(1))
    return out


def fetch_auctions_jp():
    """財務省 入札カレンダー(YYMM.htm) → 利付债/物价联动/GX/流动性供给 逐场; 已过场次抓结果页, 未来场次抓发行预定额。
    累积档: 已有真实记录按(date,tenor)保留, 只补抓缺结果的场次。"""
    import requests, re
    p = OUT / "auctions_jp.json"
    old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    keep = {(r["date"], r["tenor"]): r for r in (old.get("records", []) if not old.get("sample") else [])}
    months = []
    for k in (-2, -1, 0, 1):
        y, m = divmod(TODAY.year*12 + TODAY.month - 1 + k, 12)
        months.append((y, m + 1))
    rows, diag, skipped = [], [], []
    for y, m in months:
        u = f"{MOF}/jgbs/auction/calendar/{y % 100:02d}{m:02d}.htm"
        try:
            r = requests.get(u, headers=UA, timeout=60)
            diag.append(f"{u.rsplit('/', 1)[-1]} status={r.status_code} bytes={len(r.content)}")
            if r.status_code != 200: continue
            html = r.content.decode("utf-8", "ignore")
        except Exception as e:
            diag.append(f"{u} 失败 {e}"); continue
        # 只取第一张表((1)国债入札), 买入消却/借入金表不收
        t0 = html.find("<table"); t1 = html.find("</table>", t0)
        for tr in re.findall(r"<tr.*?</tr>", html[t0:t1], flags=re.S):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S)
            if len(cells) < 3: continue
            dm = re.search(r"(\d+)月(\d+)日", _flat(cells[0]))
            if not dm: continue
            name = _flat(cells[1]); tenor = _jp_tenor(name)
            if not tenor:
                if "国庫短期証券" not in name: skipped.append(name)
                continue
            d = date(y, int(dm.group(1)), int(dm.group(2))).isoformat()
            res = re.search(r"/jgbs/auction/calendar/nyusatsu/resul\d{8}\.htm", tr)
            yot = re.search(r"/jgbs/auction/calendar/yotei/auct\d{8}[a-z]?\.htm", tr)
            rows.append({"date": d, "tenor": tenor, "name": name,
                         "res": MOF + res.group(0) if res else None, "yot": MOF + yot.group(0) if yot else None})
    if not rows:
        _debug("auctions_jp", {"diag": diag, "skipped": skipped[:40]})
        print("  !! JP招标日历零命中, 保留上一版"); return
    recs, fails = dict(keep), []
    for row in rows:
        key = (row["date"], row["tenor"])
        cur = recs.get(key, {"date": row["date"], "tenor": row["tenor"], "size_t": None, "btc": None, "tail_bp": None})
        if cur.get("btc") is not None:
            continue
        try:
            if row["res"] and row["date"] <= TODAY.isoformat():
                txt = _flat(requests.get(row["res"], headers=UA, timeout=60).content.decode("utf-8", "ignore"))
                got = _auction_result(txt)
                if got.get("btc") is None: fails.append({"url": row["res"], "text": txt[txt.find("記"):][:600]})
                cur.update(got)
            elif row["yot"] and cur.get("size_t") is None:
                txt = _flat(requests.get(row["yot"], headers=UA, timeout=60).content.decode("utf-8", "ignore"))
                m = re.search(r"発行予定額[^億兆]{0,20}?((?:\d+兆)?[\d,]+億円)", txt)   # 面包屑也含"発行予定額"
                v = _oku(m.group(1)) if m else None
                if v: cur["size_t"] = round(v/10000, 2)
            time.sleep(0.5)
        except Exception as e:
            fails.append({"url": row["res"] or row["yot"], "err": str(e)})
        recs[key] = cur
    _debug("auctions_jp", {"diag": diag, "calendar_rows": len(rows), "skipped": skipped[:40], "fails": fails[:20]})
    out = sorted(recs.values(), key=lambda r: (r["date"], r["tenor"]))
    lo = (TODAY - timedelta(days=730)).isoformat()
    out = [r for r in out if r["date"] >= lo]
    n_res = sum(1 for r in out if r.get("btc") is not None)
    if n_res == 0:
        print("  !! JP招标结果零解析, 保留上一版 (见_debug_auctions_jp)"); return
    _write("auctions_jp", {"sample": False, "records": out,
        "note": "财务省入札カレンダー+逐场结果页(利付债/物价联动/GX/流动性供给, 不含国库短期证券); 倍数=应募额/价格竞争募入决定额; "
                "尾差=(募入最高-平均)利回り bp, 流动性供给为利回格差之差; 规模=价格竞争+第Ⅰ非价格(¥T)"})
    print(f"  JP招标 {len(out)}场 (结果{n_res} · 解析失败{len(fails)})")


TAX_IDX = f"{MOF}/tax_policy/reference/taxes_and_stamp_revenues/data.htm"


def _tax_sheet(content, fname):
    """収入額調 单月文件 → (fy, month_label, rows{税目: (预算, 累计, 前年度决算)})。
    字段校准(2026-11): 表头第0行标题'令和N年度 [M年]K月末'; 一般会计分计/所得税計/法人税/消費税行;
    列2=预算额(补正后), 列4=累计(出纳整理月为决算额概数), 列6=前年度决算额(仅常规月, 出纳整理月列6为上年同月)。单位百万円。
    文件名: YYYYMMs=新年度4/5月, 无s的YYYY04/05=上年度出纳整理期; 2023-03前为.xlsx; 标题数字可能全角。"""
    import re
    if fname.endswith(".xlsx"):
        import openpyxl, io
        ws = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True).worksheets[0]
        grid = [[("" if c is None else c) for c in row] for row in ws.iter_rows(values_only=True)]
    else:
        import xlrd
        sh = xlrd.open_workbook(file_contents=content).sheet_by_index(0)
        grid = [sh.row_values(r) for r in range(sh.nrows)]
    title = "".join(str(c) for row in grid[:2] for c in row)
    t = re.search(r"令和\s*(\d+)\s*年度.*?(\d+)\s*月末", title)
    if not t: return None
    fy = 2018 + int(t.group(1)); mon = int(t.group(2))
    settle = (mon in (4, 5)) and fy < int(fname[:4])          # 出纳整理期(上年度4/5月)
    hdr = "".join(str(c) for row in grid[3:8] for c in row)
    rows = {}
    for row in grid:
        a, b = str(row[0]).strip(), str(row[1]).strip() if len(row) > 1 else ""
        key = {"一般会計分計": "total", "法人税": "corp", "消費税": "vat"}.get(a.replace(" ", "")) or ("income" if b == "計" else None)
        if not key or key in rows: continue
        def num(i):
            try: return float(row[i])
            except (ValueError, TypeError, IndexError): return None
        if mon == 4 and not settle:   # 新年度4月文件少一组累计列: 列3=4月分即累计(常为负, 退税), 无前年度决算列
            rows[key] = (num(2), num(3), None)
        else:
            rows[key] = (num(2), num(4), None if settle else num(6))
    if "total" not in rows: return None
    return {"fy": fy, "month": mon, "settle": settle, "revised": "補正" in hdr, "rows": rows}


def fetch_tax_jp():
    """財務省 租税及び印紙収入、収入額調(月度Excel, 2023-02起) → 各财年累计路径+最新税种进度。"""
    import requests, re
    r = requests.get(TAX_IDX, headers=UA, timeout=60)
    if r.status_code != 200:
        _debug("tax_jp", {"index_status": r.status_code}); print(f"  !! 税收目录 {r.status_code}, 保留上一版"); return
    files = sorted(set(re.findall(r'href="\./(\d{6}s?\.xlsx?)"', r.content.decode("utf-8", "ignore"))))
    parsed, bad = [], []
    for f in files:
        try:
            c = requests.get(TAX_IDX.rsplit("/", 1)[0] + "/" + f, headers=UA, timeout=60)
            s = _tax_sheet(c.content, f) if c.status_code == 200 else None
            (parsed.append(s) if s else bad.append({"file": f, "status": c.status_code}))
        except Exception as e:
            bad.append({"file": f, "err": str(e)})
        time.sleep(0.3)
    _debug("tax_jp", {"files": len(files), "parsed": len(parsed), "bad": bad[:20]})
    if not parsed:
        print("  !! 税收Excel零解析, 保留上一版"); return
    order = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
    paths, settle = {}, {}
    for s in parsed:
        tot = s["rows"]["total"][1]
        if tot is None: continue
        if s["settle"]:
            if s["month"] == 5: settle[s["fy"]] = round(tot/1e6, 1)
            continue
        paths.setdefault(s["fy"], {})[order.index(s["month"])] = round(tot/1e6, 1)
    cur = max(paths)
    fys = sorted(fy for fy, p in paths.items() if fy == cur or len(p) >= 10)[-4:]   # 4月新年度多为"－", 不以4月判全
    latest = max((s for s in parsed if s["fy"] == cur and not s["settle"]), key=lambda s: order.index(s["month"]))
    bud = latest["rows"]["total"][0]
    series = {}
    for fy in fys:
        p = paths[fy]; n = max(p) + 1
        lab = f"FY{fy}(实绩)" if fy == cur else f"FY{fy}(决算{settle[fy]:.1f})" if fy in settle else f"FY{fy}"
        if fy == cur:
            series[f"FY{fy}({'补正后' if latest['revised'] else '当初'}预算)"] = [round(bud/1e6, 1)]*12
        series[lab] = [p.get(i) for i in range(n)]
    # 实绩线放最后(视图以'实绩'加粗, '当初'虚线)
    series = dict(sorted(series.items(), key=lambda kv: ("实绩" in kv[0], "预算" in kv[0], kv[0])))
    R = latest["rows"]
    def trio(k):
        v = R.get(k, (None, None, None)); return v
    oth = tuple((R["total"][i] - sum((R.get(k, (0, 0, 0))[i] or 0) for k in ("income", "corp", "vat"))) if R["total"][i] is not None else None
                for i in range(3))
    by = []
    for nm, v in (("所得税", trio("income")), ("法人税", trio("corp")), ("消费税", trio("vat")), ("其他", oth), ("合计", R["total"])):
        b, c, pr = v
        by.append((nm, round(b/1e6, 2) if b else None, round(pr/1e6, 2) if pr else None, round(c/1e6, 2) if c is not None else None))
    mlab = f"{latest['month']}月末"
    _write("tax_progress", {"sample": False, "months": ["4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月", "1月", "2月", "3月"],
        "fys": series, "by_tax": by, "fy": cur, "cum_label": mlab, "settle": {str(k): v for k, v in settle.items()},
        "as_of": f"FY{cur} {mlab}实绩",
        "note": f"财务省収入額調(一般会计分, ¥T); 曲线为4月起各月末累计, 止于3月末——4/5月出纳整理期另计入当年度决算, 故3月末低于决算约两成; "
                f"预算线={'补正后' if latest['revised'] else '当初'}预算额"})
    print(f"  JP税收 {len(parsed)}文件 · FY{cur} {mlab} ¥{R['total'][1]/1e6:.1f}T")


FOF_API = "https://www.stat-search.boj.or.jp/api/v1/getDataCode"
# 资金循环 国債・財投債(A311)+国庫短期証券(A310), 资产侧存量(億円)。部门码: 110中央银行 120存款取扱机构 130保险·年金基金
# 424公的年金(社会保障基金内, 与130不重叠) 500海外 700合计; 家庭·其他=合计-前五。
FOF_SECTORS = [("日本银行", "110"), ("银行等", "120"), ("保险·年金", "130"), ("海外", "500"), ("公的年金", "424")]


def fetch_holders_jp():
    """日银 时系列统计检索站 API (db=FF, JSON) → 国债+国库短期证券持有者份额, 2012Q1+。"""
    import requests
    codes = [f"FOF_FFAS{s}A{i}" for _, s in FOF_SECTORS + [("合计", "700")] for i in ("311", "310")]
    r = requests.get(FOF_API, params={"format": "json", "lang": "jp", "db": "FF", "startDate": "201201", "code": ",".join(codes)},
                     headers=UA, timeout=90)
    try: js = r.json()
    except ValueError: js = {}
    res = {x["SERIES_CODE"]: dict(zip(x["VALUES"]["SURVEY_DATES"], x["VALUES"]["VALUES"])) for x in js.get("RESULTSET", []) if x.get("VALUES")}
    if len(res) < len(codes):
        _debug("holders_jp", {"status": r.status_code, "msg": js.get("MESSAGE"), "got": sorted(res), "want": codes, "head": r.text[:800]})
        print(f"  !! 资金循环API缺序列({len(res)}/{len(codes)}), 保留上一版"); return
    def amt(sec, q):
        a, b = res[f"FOF_FFAS{sec}A311"].get(q), res[f"FOF_FFAS{sec}A310"].get(q)
        return None if a is None or b is None else a + b
    qs = sorted(q for q in res["FOF_FFAS700A311"] if amt("700", q))
    shares = {k: [] for k, _ in FOF_SECTORS}; shares["家庭·其他"] = []; tot = []
    for q in qs:
        T = amt("700", q); acc = 0
        for k, s in FOF_SECTORS:
            v = amt(s, q); shares[k].append(round(100*v/T, 1) if v is not None else None); acc += v or 0
        shares["家庭·其他"].append(round(100*(T-acc)/T, 1)); tot.append(round(T/10000, 1))
    upd = max(x.get("LAST_UPDATE", 0) for x in js["RESULTSET"])
    _write("holders_jp", {"sample": False, "quarters": [f"{str(q)[:4]}Q{int(str(q)[4:])}" for q in qs], "shares": shares, "total_t": tot,
        "as_of": f"{str(qs[-1])[:4]}Q{int(str(qs[-1])[4:])} · 日银更新{upd}",
        "note": "资金循环统计(日银, 季度存量): 国债·财投债+国库短期证券合计, 资产侧持有者份额%; 银行等=存款取扱机构(含邮储), 公的年金=社会保障基金内公的年金, 家庭·其他=合计减前五"})
    print(f"  JP持有者 {len(qs)}季 · 最新{qs[-1]} 日银{shares['日本银行'][-1]}%")



def ensure_seeds_jp():
    """锚文件缺失自动播种(不覆盖)。"""
    missing = [n for n in SEEDS if not (OUT / f"{n}.json").exists()]
    for n in missing:
        SEEDS[n](); print(f"  播种: {n}")


# ---------------------------------------------------------------- 锚/样例生成器
def seed_budget():
    _write("budget_jp", {"sample": True, "fy": 2026, "as_of": "2025-12-26政府案 · 2026-04-07成立",
        "total": 122.3, "revenue": [
            ("税收(租税及印花收入)", 83.7), ("所得税", 25.3), ("法人税", 20.7), ("消费税", 26.7), ("其他税", 11.0),
            ("其他收入", 9.0), ("公债金(新规国债)", 29.6), ("建设国债", 6.7), ("特例国债", 22.9)],
        "outlay": [("一般歳出(政策支出)", 70.2), ("社会保障", 39.1), ("防卫", 9.0), ("公共事业", 6.1),
                   ("文教科技", 6.0), ("其他政策支出", 10.0), ("国债费", 31.3), ("债务偿还费", 18.2),
                   ("利息支付等", 13.1), ("地方交付税等", 20.9)],
        "pb_initial": 0.2, "note": "当初预算口径一般会计基本财政收支28年来首次转正(+¥0.2T); 预算假定利率2.6%"})


def seed_supplementary():
    _write("supplementary", {"sample": True, "rows": [
        {"fy": 2019, "amount": 4.5, "count": 1}, {"fy": 2020, "amount": 73.0, "count": 3},
        {"fy": 2021, "amount": 36.0, "count": 1}, {"fy": 2022, "amount": 31.6, "count": 2},
        {"fy": 2023, "amount": 13.2, "count": 1}, {"fy": 2024, "amount": 13.9, "count": 1},
        {"fy": 2025, "amount": 18.3, "count": 1}, {"fy": 2026, "amount": 3.1, "count": 1, "note": "第1号6/5成立(中东应对); 脱补充依赖方针下秋季第2号待观察"}],
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
                            "note": "普通国债残高(年度末, ¥T) 与 名目GDP; 2026为年度末见込"})


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
        "note": "利息支付等(一般会计国债费, ¥T)/存量加权利率%/预算假定利率%/平均剩余期限(年)"})


def seed_boj_plan():
    _write("boj_plan", {"sample": True, "as_of": "2025-06-17决定; 2026-06中期评估(维持, 待核)",
        "path": [("2024Q3", 5.7), ("2024Q4", 5.3), ("2025Q1", 4.9), ("2025Q2", 4.5), ("2025Q3", 4.1), ("2025Q4", 3.7),
                 ("2026Q1", 3.3), ("2026Q2", 2.9), ("2026Q3", 2.7), ("2026Q4", 2.5), ("2027Q1", 2.1)],
        "note": "月度长期国债购入预定额(¥T): 2026Q1前每季减¥0.4T, 2026Q2起每季减¥0.2T, 2027Q1约¥2T; 持有份额约48%→减持中"})


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




def seed_yields():
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


def seed_macro():
    _write("macro_jp", {"sample": True, "ngdp": {str(y): v for y, v in zip(range(2015, 2027), [540, 545, 553, 556, 558, 539, 553, 562, 597, 610, 628, 640])},
                        "debt_gdp": {str(y): v for y, v in zip(range(2015, 2027), [228, 232, 231, 232, 236, 258, 253, 248, 240, 237, 234, 232])},
                        "pb_gdp": {str(y): v for y, v in zip(range(2015, 2027), [-3.6, -3.4, -2.8, -2.2, -2.9, -8.6, -5.6, -3.6, -2.1, -1.5, -0.9, -0.5])}})

SEEDS = {"budget_jp": seed_budget, "supplementary": seed_supplementary, "mlt_projection": seed_mlt,
         "issuance_plan": seed_issuance_plan, "tenor_history": seed_tenor_history, "tax_progress": seed_tax,
         "treasury_flows": seed_flows, "local_jp": seed_local_jp, "debt_long_jp": seed_debt_long,
         "holders_jp": seed_holders_jp, "interest_jp": seed_interest_jp, "boj_plan": seed_boj_plan,
         "auctions_jp": seed_auctions_jp, "jgb_yields": seed_yields, "macro_jp": seed_macro}


def write_sample():
    for n, fn in SEEDS.items(): fn()
    print("日本示例完成")


GROUPS = {"daily": [ensure_seeds_jp, fetch_jgb_yields, fetch_auctions_jp],
          "weekly": [ensure_seeds_jp, fetch_jgb_yields, fetch_macro_jp, fetch_auctions_jp, fetch_tax_jp, fetch_holders_jp],
          "intraday": [ensure_seeds_jp]}


def run_group(mode):
    for fn in GROUPS.get(mode, []):
        print(f"- [jp:{mode}] {fn.__name__}")
        try: fn()
        except Exception as e: print(f"  !! {fn.__name__} 失败: {e} (保留上次数据)")


if __name__ == "__main__":
    if "--sample" in sys.argv: write_sample()
    else: run_group(sys.argv[1] if len(sys.argv) > 1 else "daily")
