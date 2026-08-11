#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_site.py — 对象驱动渲染
输入: config/objects_us.yaml + data/us/*.json
输出: docs/index.html (单页, 数据内嵌)
结构: 时钟条 → 变化流水(占位) → 五层×对象卡(状态行/工作视图/档案) → 参考层
"""
import html as htmlmod
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "us"
TODAY = date.today()

CHARTS = []  # 收集图表spec, 前端通用初始化


def esc(s):
    return htmlmod.escape(str(s)) if s is not None else ""


def J(name):
    p = DATA / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def fmt(v, d=0):
    if v is None: return "—"
    return f"{v:,.{d}f}"


def bn(v):
    if v is None: return "—"
    return f"{v/1000:,.2f}T" if abs(v) >= 1000 else f"{v:,.0f}B"


def chart(cid, kind, labels, datasets, y_unit="", opts=None):
    CHARTS.append({"id": cid, "kind": kind, "labels": labels,
                   "datasets": datasets, "y_unit": y_unit, "opts": opts or {}})
    o = opts or {}
    if o.get("h"):
        return (f'<div class="chart" style="height:{o["h"]}px;max-height:{o["h"]}px">'
                f'<canvas id="{cid}" style="max-height:{o["h"]-10}px"></canvas></div>')
    cls = "chart tall" if o.get("tall") else "chart"
    return f'<div class="{cls}"><canvas id="{cid}"></canvas></div>' 


def table(headers, rows, cls=""):
    th = "".join(f"<th{' class=\"num\"' if h.startswith('#') else ''}>{esc(h.lstrip('#'))}</th>" for h in headers)
    trs = []
    for row in rows:
        tds = []
        for h, c in zip(headers, row):
            numcls = ' class="num"' if h.startswith("#") else ' class="t"'
            tds.append(f"<td{numcls}>{c if isinstance(c, str) and c.startswith('<') else esc(c)}</td>")
        trs.append("<tr>" + "".join(tds) + "</tr>")
    return f'<table class="{cls}"><tr>{th}</tr>{"".join(trs)}</table>'


# ---------------------------------------------------------------- FY工具

def dts_nowcast(mts_series, dts_series):
    """DTS→下月MTS赤字预测: 月内现金赤字(剔债务流) + 近3年同月MTS均值×未过日比例。"""
    if not mts_series or not dts_series:
        return None
    last_m = mts_series[-1]["month"]
    y, m = int(last_m[:4]), int(last_m[5:7])
    ty, tm = (y + 1, 1) if m == 12 else (y, m + 1)
    target = f"{ty:04d}-{tm:02d}"
    days = [r for r in dts_series if r["date"].startswith(target)]
    if not days:
        return None
    mtd = sum(r["deposits"] - r["withdrawals"] for r in days)
    hist = [r["balance"] for r in mts_series if r["month"][5:7] == f"{tm:02d}"][-3:]
    avg = sum(hist) / len(hist) if hist else 0.0
    frac = min(len(days) / 21.0, 1.0)
    return {"month": target, "value": round(mtd + avg * (1 - frac), 0),
            "mtd": round(mtd, 0), "frac": round(frac, 2), "hist_avg": round(avg, 0)}


def fy_paths(mts_series):
    """按财年分组累计赤字: {fy: [cum1..cum12]}"""
    fys = {}
    for r in mts_series:
        y, m = int(r["month"][:4]), int(r["month"][5:7])
        fy = y + 1 if m >= 10 else y
        idx = m - 9 if m >= 10 else m + 3  # 10月=1 ... 9月=12
        fys.setdefault(fy, {})[idx] = r["balance"]
    out = {}
    for fy, months in fys.items():
        cum, arr = 0.0, []
        for i in range(1, 13):
            if i not in months:
                break
            cum += months[i]; arr.append(round(cum, 1))
        out[fy] = arr
    return out


# ---------------------------------------------------------------- 状态行

def status_metric(obj, ctx):
    try:
        return _status_metric(obj, ctx)
    except Exception:
        return '<span class="stub">数据待校准</span>'


def _status_metric(obj, ctx):
    t = obj.get("status_line", "stage")
    a = ctx["anchors"]
    if t == "headroom":
        dsl = (ctx["debt_limit"].get("series") or [{}])[-1]
        hr = a["debt_limit_bn"] - dsl.get("subj_limit", 0) if dsl.get("subj_limit") else None
        return f"headroom <b>{bn(hr)}</b> · 限额内 {bn(dsl.get('subj_limit'))}"
    if t == "text":
        return esc(obj.get("text_status", ""))
    if t == "fytd":
        paths = ctx["fy_paths"]; fy = max(paths)
        cur = paths[fy][-1] if paths[fy] else None
        return f"FY{fy} 累计 <b>{bn(abs(cur)) if cur is not None else '—'}</b> 赤字 (第{len(paths[fy])}个月)"

    if t == "tga":
        last = (ctx["tga"].get("series") or [{}])[-1]
        dev = last.get("close", 0) - a["tga_target_bn"] if last.get("close") else None
        sign = "+" if dev and dev > 0 else ""
        return f"<b>{bn(last.get('close'))}</b> · vs目标 {sign}{fmt(dev)}B"
    if t == "tbills_share":
        s = (ctx["supply"].get("series") or [{}])[-1]
        return f"Tbills份额 <b>{fmt(s.get('tbills_share'), 1)}%</b> · 区间15-20%上方"
    if t == "expansion":
        inst = next((i for i in obj.get("instances", []) if i.get("active")), {})
        prop = sum(r.get("proposed_bn") or 0 for r in inst.get("rows", []))
        enac = sum(r.get("enacted_bn") or 0 for r in inst.get("rows", []))
        return f"FY{inst.get('fy', '—')} 基线外已提出 <b>{bn(prop)}</b> · 已成法 {bn(enac)}"
    if t == "debt_tiers":
        d = (ctx["debt"].get("series") or [{}])[-1]
        return f"总 <b>{bn(d.get('total'))}</b> · 公众 {bn(d.get('public'))} · 政府间 {bn(d.get('intragov'))}"
    if t == "debt_total":
        d = (ctx["debt"].get("series") or [{}])[-1]
        return f"总债务 <b>{bn(d.get('total'))}</b>"
    if t == "avg_rate":
        r = (ctx["avg_rates"].get("series") or [{}])[-1]
        return f"加权利率 <b>{fmt(r.get('rate'), 2)}%</b> · {esc(r.get('month', ''))}"
    st = (obj.get("qual") or {}).get("state", "")
    return esc(st)


EVENTS = []      # main()载入账本
OBJ_NAMES = {}   # oid -> 名称
LAWS = []        # 框架法档案
WATCH = {}       # watch_state: obj_last_change等

STALE_DAYS = 45

def freshness_marks(obj):
    marks = []
    v = obj.get("verified")
    lc = (WATCH.get("obj_last_change") or {}).get(obj.get("part_ids", [obj["id"]])[0] if obj.get("part_ids") else obj["id"])
    if lc and (not v or v < lc):
        marks.append('<span class="mk hot">有未消化更新</span>')
    if v:
        age = (TODAY - date.fromisoformat(v)).days
        if age > STALE_DAYS:
            marks.append(f'<span class="mk old">内容{age}天未核</span>')
    return "".join(marks)

def next_node(obj):
    ids = set(obj.get("part_ids") or []) | {obj["id"]}
    fut = sorted([e for e in EVENTS if e.get("owner") in ids
                  and e["date"] >= TODAY.isoformat() and e["status"] != "cancelled"],
                 key=lambda e: e["date"])
    if not fut: return "—"
    e = fut[0]
    dd = (date.fromisoformat(e["date"]) - TODAY).days
    tag = "今日" if dd == 0 else f"D-{dd}"
    est = ' <span class="stub">估</span>' if e.get("dtype") == "估计" else ""
    return f'<span class="nn">{tag}</span> {esc(e["label"])}{est}'


# ---------------------------------------------------------------- 视图

def qual_card(q):
    if not q: return ""
    parts = []
    for k, lab in [("state", "状态"), ("base_case", "Base case"), ("watch", "观察")]:
        if q.get(k):
            parts.append(f'<div class="qrow"><span class="qk">{lab}</span><span>{esc(q[k])}</span></div>')
    return f'<div class="qcard">{"".join(parts)}</div>'


def _limit_steps(obj, months):
    """限额历史(法定台阶)对齐到月度标签; 暂停期=null(空档)。"""
    hist = sorted(obj.get("limit_history", []), key=lambda x: x["from"])
    out = []
    for m in months:
        val = None
        for ev in hist:
            if ev["from"] <= m:
                val = ev["limit"]
        out.append(val)
    return out


def v_debt_limit(obj, ctx):
    hist = ctx["debt_limit_history"].get("series") or []
    months = [r["month"] for r in hist]
    mk = ctx.get("market") or {}
    smp = " (示例)" if mk.get("sample") else ""
    limits = _limit_steps(obj, months)
    h = chart("ch_dl_hist", "line", [],
              [{"label": "法定限额(空档=暂停期)", "color": "red", "w": 1.6, "step": True,
                "xy": [[m + "-01", v] for m, v in zip(months, limits)]},
               {"label": "限额内债务(实际)", "color": "muted", "w": 1.4,
                "xy": [[r["month"] + "-01", r["actual"]] for r in hist]},
               {"label": "SPX (右轴1, 对数)" + smp, "color": "blue", "alpha": "4D", "w": 1.1,
                "axis": "y1", "xy": mk.get("spx", [])},
               {"label": "US10Y (右轴2)" + smp, "color": "amber", "alpha": "55", "w": 1.1,
                "axis": "y2", "xy": mk.get("us10y", [])}],
              "bn", opts={"tall": True, "zoom": True, "time": True,
                          "axes": {"y1": {"log": True}, "y2": {"unit": "%"}}})
    note = ('<div class="anchor-note">1993年至今 · 限额台阶为法定事件(config维护), 实际线2022/10起为DTS精确值、2005-2022为月末总债务近似(差<0.5%)、'
            '之前为年度总债务近似 · 空档=暂停期 · 滚轮/拖拽双轴缩放, 双击复位</div>')
    return h + note + links_chips(obj) + qual_card(obj["qual"])


def v_qual_only(obj, ctx):
    return links_chips(obj) + qual_card(obj["qual"])


def v_baseline_center(obj, ctx):
    h = """
<div class="blx">
  <div class="chart tall" style="height:340px;max-height:340px"><canvas id="ch_bl_matrix"></canvas></div>
  <div class="blx-bar">
    <span class="chips" id="blxViews"></span>
    <span class="blx-hint">点击行切换上图分项 · Δ行可编辑(存本机) </span>
    <button class="cbtn" id="blxReset">清除调整</button>
  </div>
  <div class="blx-tbl" id="blxTable"></div>
</div>"""
    dec_rows = []
    for v in obj.get("baseline_changes", []):
        tot = sum(x for x in [v.get("legislative"), v.get("economic"), v.get("technical")] if x is not None)
        dec_rows.append((v["version"], fmt(v.get("legislative")), fmt(v.get("economic")),
                         fmt(v.get("technical")), fmt(tot), v.get("note", "")))
    h += "<h4>版本间变化 · 三因素分解 (FY2026赤字, bn, 负=增赤)</h4>"
    h += table(["版本", "#立法", "#经济", "#技术", "#合计", "说明"], dec_rows)
    sc_rows = [(r["bill"], r["name"], r["score"], r["status"], r["note"]) for r in obj.get("scores", [])]
    h += "<h4>活跃法案评分 (监听器自动捕获新评分)</h4>"
    h += table(["法案", "名称", "#10年评分", "状态", "备注"], sc_rows)
    return h + links_chips(obj) + qual_card(obj["qual"])


import flow_svg


def v_cycle_instances(obj, ctx):
    h = ""
    for inst in obj.get("instances", []):
        tag = " · 活跃" if inst.get("active") else " · 归档"
        h += f'<h4>FY{inst["fy"]}{tag}</h4>'
        h += f'<div class="anchor-note">{esc(inst.get("threea", ""))}</div>'
        if inst.get("flow_states"):
            h += flow_svg.render(inst["flow_states"])
            if inst.get("flow_note"):
                h += f'<div class="anchor-note">{esc(inst["flow_note"])}</div>' 
        h += table(["泳道", "当前stage", "下一节点"],
                   [(l["lane"], l["stage"], l["next"]) for l in inst.get("swimlanes", [])])
    return h + qual_card(obj["qual"])


def v_approps_v2(obj, ctx):
    auto = {r["bill"]: r for r in (ctx.get("approps_status") or {}).get("rows", [])}
    h = ""
    for inst in obj.get("instances", []):
        h += f'<h4>FY{inst["fy"]} 12法案矩阵 · 302(b)数额与状态</h4>'
        tl = inst.get("toplines", {})
        h += (f'<div class="anchor-note">topline: 众院 ${fmt(tl.get("house_total"))}B · '
              f'参院 {fmt(tl.get("senate_total")) + "B" if tl.get("senate_total") else "未定"} · '
              f'FY26 enacted ${fmt(tl.get("fy26_enacted"))}B · 分表数额待录入(302(b)链接直达)</div>')
        rows = []
        for m in inst.get("matrix", []):
            a = auto.get(m["bill"].split("-")[0], {})
            auto_txt = f'{a.get("latest_col")}: {a.get("latest_val")}' if a.get("latest_val") else "—"
            rows.append((m["bill"], fmt(m.get("h302b")), fmt(m.get("s302b")),
                         f'<span class="stg s{STAGES.index(m["house"]) if m["house"] in STAGES else 0}">{esc(m["house"])}</span>',
                         f'<span class="stg s{STAGES.index(m["senate"]) if m["senate"] in STAGES else 0}">{esc(m["senate"])}</span>',
                         f'<span class="auto">{esc(auto_txt)}</span>', m.get("note", "")))
        h += table(["法案", "#302(b)众", "#302(b)参", "众院", "参院", "状态表自动检测", "备注"], rows)
        if inst.get("supplementals"):
            h += "<h4>补充拨款轨道 (紧急指定, 302(b)外)</h4>"
            h += table(["名称", "#请求(bn)", "递交", "阶段", "指定", "备注"],
                       [(sp["name"], fmt(sp["requested_bn"], 1), sp["date"], sp["stage"],
                         sp["designation"], sp.get("note", "")) for sp in inst["supplementals"]])
        for c in inst.get("cr_chain", []):
            h += f'<div class="crlink">CR链条: <b>{esc(c["name"])}</b> {esc(c["covers"])} · {esc(c["status"])}</div>'
    return h + links_chips(obj) + qual_card(obj["qual"])


def v_expansion_view(obj, ctx):
    h = ""
    for inst in obj.get("instances", []):
        tag = " · 活跃" if inst.get("active") else " · 归档"
        h += f'<h4>FY{inst["fy"]}{tag} · 扩张项清单</h4>'
        h += table(["扩张项", "规模", "载体", "阶段", "基线内外", "赤字影响"],
                   [(r["item"], r["scale"], r["vehicle"], r["stage"], r["baseline"], r["impact"])
                    for r in inst.get("rows", [])])
        if inst.get("directives"):
            h += "<h4>和解指令表 (载体机制之一)</h4>"
            h += table(["受指令委员会", "指令", "产出法案", "Byrd审查"],
                       [(d["committee"], d["instruction"], d["product"], d["byrd"])
                        for d in inst["directives"]])
    return h + links_chips(obj) + qual_card(obj["qual"])


STAGES = ["未动", "小组", "全委", "floor", "对院", "enacted"]

def v_fytd_progress(obj, ctx):
    paths = ctx["fy_paths"]
    fys = sorted(paths)
    cur = fys[-1]; priors = [f for f in fys[:-1] if len(paths[f]) == 12][-6:]
    labels = ["10", "11", "12", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
    ds = []
    for i, fy in enumerate(priors):   # 越近越深
        shade = ["#D3D9D5", "#C4CCC7", "#B2BCB6", "#9FABA4", "#8A97A1", "#6E7C86"][i % 6]
        ds.append({"label": f"FY{fy}", "data": paths[fy], "color": shade, "w": 1.1})
    anchor = -ctx["anchors"]["cbo_fy2026_deficit_bn"]
    shapes = [[c/paths[fy][-1] for c in paths[fy]] for fy in priors[-2:]]
    if shapes:
        avg = [sum(s[i] for s in shapes)/len(shapes) for i in range(12)]
        ds.append({"label": f"CBO基线路径(FY{cur})", "data": [round(anchor*x, 0) for x in avg],
                   "color": "blue", "dash": [6, 4], "w": 1.5})
    ds.append({"label": f"FY{cur}", "data": paths[cur], "color": "red", "w": 2.6})
    # DTS预测点: 空心菱形+虚线延伸
    nc = dts_nowcast(ctx["mts"].get("series") or [], ctx["dts_flows"].get("series") or [])
    nc_note = ""
    if nc and len(paths[cur]) < 12:
        idx = len(paths[cur])
        proj = round(paths[cur][-1] + nc["value"], 0)
        data = [None]*(idx-1) + [paths[cur][-1], proj] + [None]*(12-idx-1)
        ds.append({"label": "DTS预测(下月)", "data": data, "color": "red",
                   "dash": [3, 4], "w": 1.6, "pstyle": "circle", "pr": 5.5})
        nc_note = (f'<div class="anchor-note">DTS预测 {nc["month"]}: 月度赤字≈{fmt(abs(nc["value"]))}B '
                   f'(月内现金已实现 {fmt(abs(nc["mtd"]))}B · 经过{nc["frac"]:.0%} · 近3年同月MTS均值 {fmt(abs(nc["hist_avg"]))}B补余) '
                   f'· 现金/权责楔子未校正, 精度弱于MBR</div>')
    h = chart("ch_fytd", "line", labels, ds, "bn", opts={"h": 400})
    h += nc_note
    mts = ctx["mts"].get("series") or []
    tail = mts[-13:]
    h += chart("ch_mbal", "pnbar", [r["month"][2:] for r in tail],
               [{"label": "月度赤字", "data": [r["balance"] for r in tail], "color": "auto"}], "bn")
    mbr = f'<div class="anchor-note">MBR锚: {esc(ctx["anchors"]["mbr_latest"])}</div>'
    return h + mbr + qual_card(obj["qual"])


def v_local_widget(obj, ctx):
    h = """
<div class="blx">
  <div class="chart tall" style="height:320px;max-height:320px"><canvas id="ch_local"></canvas></div>
  <div class="blx-bar"><span class="blx-hint">默认: 联邦/州地方收支四线+转移支付 · 点击行切换该序列(绝对额+/NGDP双轴)</span></div>
  <div class="blx-tbl" id="lxTable"></div>
</div>"""
    return h + qual_card(obj["qual"])


def v_holders_v2(obj, ctx):
    tic = ctx.get("tic_holders") or {}
    soma = (ctx.get("soma") or {}).get("series") or []
    sup = (ctx["supply"].get("series") or [{}])[-1]
    mkt = sup.get("bills_bn", 0) / (sup.get("tbills_share", 1) or 1) * 100 if sup.get("bills_bn") else None
    soma_tot = soma[-1].get("soma_total") if soma else None
    ft = tic.get("foreign_total")
    pct = lambda v: f"{100*v/mkt:.1f}%" if (v and mkt) else "—"
    rows = [("海外合计 (TIC)", fmt(ft), pct(ft), "自动·月度(滞后6周)"),
            ("美联储SOMA", fmt(soma_tot), pct(soma_tot), "自动·周度")]
    for r in (obj.get("anchors_z1") or {}).get("rows", []):
        rows.append((r["holder"] + " (Z.1)", fmt(r["bn"]), pct(r["bn"]),
                     f"人工锚·{(obj.get('anchors_z1') or {}).get('as_of', '')}"))
    h = "<h4>持有人总览 · 占marketable比</h4>"
    h += table(["持有人", "#$bn", "#占比", "更新方式"], rows)
    top = tic.get("top") or []
    if top:
        h += "<h4>海外持有前列国别/地区 (TIC MFH)</h4>"
        h += table(["国别/地区", "#$bn"], [(t["name"], fmt(t["bn"])) for t in top])
    return h + qual_card(obj["qual"])


def v_annual_widget(obj, ctx):
    h = """
<div class="blx">
  <div class="chart tall" style="height:330px;max-height:330px"><canvas id="ch_annual"></canvas></div>
  <div class="blx-bar"><span class="blx-hint">默认六线: 收/支/赤绝对额+各自/NGDP · 点击行切换该科目(绝对额左轴+%NGDP右轴)</span></div>
  <div class="blx-tbl" id="anxTable"></div>
</div>"""
    return h + qual_card(obj["qual"])


def v_dts_flows(obj, ctx):
    s = ctx["dts_flows"].get("series") or []
    h = chart("ch_dts", "pnbar", [r["date"][5:] for r in s],
              [{"label": "存入", "data": [r["deposits"] for r in s], "color": "green"},
               {"label": "支取", "data": [-r["withdrawals"] for r in s], "color": "red"}], "bn")
    return h + qual_card(obj["qual"])








def v_supply_share(obj, ctx):
    s = ctx["supply"].get("series") or []
    soma_share = [round(100*r["soma_bills"]/r["bills_bn"], 1)
                  if (r.get("bills_bn") and r.get("soma_bills") is not None) else None for r in s]
    h = chart("ch_share", "line", [r["month"][2:] for r in s],
              [{"label": "Tbills份额 %marketable", "data": [r["tbills_share"] for r in s], "color": "ink", "w": 2},
               {"label": "SOMA bills/bills存量 %", "data": soma_share, "color": "green", "w": 1.5, "dash": [5, 3]},
               {"label": "SOMA bills $bn (右轴)", "data": [r.get("soma_bills") for r in s],
                "color": "blue", "alpha": "77", "w": 1.3, "axis": "y1"}], "%",
              opts={"tall": True, "zoom": True})
    note = '<div class="anchor-note">2000年至今月度 · SOMA bills为Fed持仓(周度源, 月末采样) · 私人吸收压力=份额上行且SOMA不增持的组合</div>'
    return h + note + qual_card(obj["qual"])


def v_structure_view(obj, ctx):
    d = ctx["mspd_structure"]
    mix = d.get("mix") or []
    h = ""
    if mix:
        h += chart("ch_mix", "hbar", [m["type"] for m in mix],
                   [{"label": "存量", "data": [m["out_bn"] for m in mix], "color": "blue"}], "bn")
    mw = d.get("maturity_wall") or []
    if mw:
        h += chart("ch_mw", "hbar", [m["bucket"] for m in mw],
                   [{"label": "到期量", "data": [m["bn"] for m in mw], "color": "amber"}], "bn")
    w = (ctx.get("wam") or {}).get("series") or []
    if w:
        vals = [x["wam"] for x in w]
        mean = sum(vals)/len(vals)
        std = (sum((v-mean)**2 for v in vals)/len(vals)) ** 0.5
        n = len(w)
        h += "<h4>加权平均久期 WAM (月)</h4>"
        h += chart("ch_wam", "line", [x["month"][2:] for x in w],
                   [{"label": "WAM实际", "data": vals, "color": "ink", "w": 2},
                    {"label": f"全史均值 {mean:.1f}", "data": [round(mean, 1)]*n, "color": "amber", "w": 1.2},
                    {"label": "+1σ", "data": [round(mean+std, 1)]*n, "color": "green", "dash": [4, 4], "w": 1},
                    {"label": "-1σ", "data": [round(mean-std, 1)]*n, "color": "green", "dash": [4, 4], "w": 1}],
                   "", opts={"h": 320, "zoom": True})
    if not mix:
        h += f'<div class="anchor-note">{esc(d.get("note", "待首跑字段校验"))}</div>'
    return h + qual_card(obj["qual"])


def v_holders_table(obj, ctx):
    rows = [("TIC (海外国别)", "月, 滞后6周", "机读", "待接入"),
            ("SOMA (CUSIP级)", "周四", "Fed接口", "待接入"),
            ("Z.1 L.210 (全景)", "季", "Fed接口", "待接入"),
            ("PD持仓", "周", "Fed接口", "待接入")]
    return table(["来源", "频率", "类型", "状态"], rows) + qual_card(obj["qual"])



def links_chips(obj):
    ls = obj.get("links") or []
    if not ls: return ""
    return '<div class="lchips">' + "".join(
        f'<a class="lchip" href="{esc(l["url"])}" target="_blank">{esc(l["name"])} ↗</a>' for l in ls) + "</div>"


def v_expiry_table(obj, ctx):
    rows = [(p["item"], p["vehicle"], p["expiry"], p["plan"],
             f'<span class="imp">{esc(p["impact"])}</span>' if p.get("impact") else "")
            for p in obj.get("provisions", [])]
    note = ('<div class="anchor-note">口径: 到期后年均赤字变化 = 官方评分÷窗口年数(简单平均), 来源见括号; '
            '负=到期使赤字收窄。无到期影响留空。</div>')
    return table(["条款/授权", "载体", "到期/节点", "后续计划", "到期后每年赤字变化"], rows) + note + links_chips(obj) + qual_card(obj["qual"])


def v_debt_tiers(obj, ctx):
    a = ctx["anchors"]
    d = (ctx["debt"].get("series") or [{}])[-1]
    dsl = (ctx["debt_limit"].get("series") or [{}])[-1]
    tga = (ctx["tga"].get("series") or [{}])[-1]
    net = (d.get("public") or 0) - (tga.get("close") or 0) - a.get("loans_fin_assets_bn", 0) if d.get("public") else None
    def ind(txt, lv):
        return f'<span style="padding-left:{lv*18}px;display:inline-block">{txt}</span>'
    rows = [
        ("总债务 Total Federal Debt", "公众持有 + 政府间", bn(d.get("total")), "Debt to the Penny(日)"),
        (ind("公众持有 Held by Public", 1), "总债务 - 政府间", bn(d.get("public")), "Debt to the Penny(日)"),
        (ind("其中: 净金融资产口径", 2), "公众持有 - TGA - 贷款类金融资产", bn(net), "CBO口径(贷款资产为人工锚)"),
        (ind("政府间 Intragov", 1), "GAS(90%+) + FFB + 少量marketable", bn(d.get("intragov")), "Debt to the Penny(日)"),
        ("限额内债务 Subject to Limit", "总债务 - FFB等 ± 未摊销项", bn(dsl.get("subj_limit")), "DTS(日) / MSPD对账(月)"),
    ]
    return table(["口径", "构成", "#当前量级", "权威源"], rows) + qual_card(obj["qual"])


def v_caps_view(obj, ctx):
    rows = [(c["fy"], c["defense"], c["nondefense"], c["note"]) for c in obj.get("caps_table", [])]
    return table(["财年", "国防cap", "非国防cap", "备注"], rows) + links_chips(obj) + qual_card(obj["qual"])


def v_paygo_view(obj, ctx):
    rows = [(r["item"], r["value"], r["note"]) for r in obj.get("scorecard", [])]
    return table(["记分卡项", "#状态/数额", "备注"], rows) + links_chips(obj) + qual_card(obj["qual"])


def v_qra_view(obj, ctx):
    qh = (ctx.get("qra_history") or {}).get("rows") or []
    h = "<h4>QRFE 融资估计历史 (每季录入)</h4>"
    h += table(["季度", "#私人净融资 (bn)", "#期末TGA假设", "备注"],
               [(r["q"], fmt(r.get("borrowing")), fmt(r.get("tga_end")), r.get("note", "")) for r in qh])
    cs = ctx.get("coupon_sizes") or {}
    months, tenors = cs.get("months") or [], cs.get("tenors") or {}
    order = ["2y", "3y", "5y", "7y", "10y", "20y", "30y"]
    if months:
        h += "<h4>Coupon发行结构 · 近6个月 (bn)</h4>"
        rows = []
        for i in range(max(0, len(months)-6), len(months)):
            rows.append((months[i],) + tuple(fmt(tenors.get(t, [None]*len(months))[i]) for t in order))
        h += table(["月份"] + [f"#{t}" for t in order], rows)
        cols = ["ink", "blue", "green", "amber", "red", "#6B4E8C", "muted"]
        newt = cs.get("tenors_new") or {}
        def _ffill(arr):
            out, last = [], None
            for v in arr:
                if v is not None: last = v
                out.append(last)
            return out
        h += chart("ch_coupon", "line", [m[2:] for m in months],
                   [{"label": t, "data": _ffill(newt.get(t) or tenors.get(t, [])), "color": cols[i], "w": 1.5}
                    for i, t in enumerate(order)], "bn",
                   opts={"tall": True, "zoom": True})
        h += '<div class="anchor-note">图为新发场次规模(阶梯态, 前向填充); 表为月度实况(新发与续发并存, 42/39交替为发行节奏本身)</div>' 
    return h + links_chips(obj) + qual_card(obj["qual"])


def v_funding_widget(obj, ctx):
    return """
<div class="blx">
  <div class="blx-bar"><span class="blx-hint">Exhibit式三年联动: 编辑任意假设单元格全表重算 · 存本机</span>
  <button class="cbtn" id="fnxReset">恢复默认</button></div>
  <div class="blx-tbl" id="fnxTable"></div>
</div>""" + qual_card(obj["qual"])


def v_cash_buyback(obj, ctx):
    s = ctx["tga"].get("series") or []
    t = ctx["anchors"]["tga_target_bn"]
    h = "<h4>TGA现金水位</h4>"
    h += chart("ch_tga", "line", [r["date"][5:] for r in s],
               [{"label": "TGA", "data": [r["close"] for r in s], "color": "blue", "w": 2, "fill": True},
                {"label": "QRA目标", "data": [t]*len(s), "color": "muted", "dash": [5, 4], "w": 1}], "bn")
    bs = yaml.safe_load((ROOT / "config/buyback_schedule.yaml").read_text(encoding="utf-8"))         if (ROOT / "config/buyback_schedule.yaml").exists() else {}
    recs = (ctx["buybacks"].get("records") or [])
    typed = {str(o["date"]): o.get("type", "流动性支持") for o in bs.get("ops", [])}
    ex_liq = sum(r.get("accepted_bn") or 0 for r in recs if typed.get(r.get("op_date"), "流动性支持") == "流动性支持")
    ex_cm = sum(r.get("accepted_bn") or 0 for r in recs if typed.get(r.get("op_date")) == "现金管理")
    env = bs.get("envelopes") or {}
    cum = (bs.get("cum_since_2024_bn") or 0) + ex_liq + ex_cm
    sup = (ctx["supply"].get("series") or [{}])[-1]
    mkt = sup.get("bills_bn", 0) / (sup.get("tbills_share", 1) or 1) * 100 if sup.get("bills_bn") else None
    pct = f"{cum/mkt*100:.2f}%" if mkt else "—"
    h += f"<h4>回购二分结构 · {esc(bs.get('quarter', ''))}</h4>"
    h += table(["类型", "目的", "#当季envelope", "#本季已执行", "#2024以来累计", "占marketable比"],
               [("流动性支持", "周度买入off-the-run, 缓解做市商资产负债表", fmt(env.get("liquidity_bn"), 1),
                 fmt(ex_liq, 1), "", ""),
                ("现金管理", "缴税季现金高峰赎回短端, 削融资波动", fmt(env.get("cashmgmt_bn"), 1),
                 fmt(ex_cm, 1), "", ""),
                ("合计", "", "", fmt(ex_liq+ex_cm, 1), fmt(cum, 0), pct)])
    h += "<h4>近期操作</h4>"
    h += table(["日期", "类型", "bucket", "#上限", "#接纳", "#offer/max"],
               [((r.get("op_date") or "")[5:], typed.get(r.get("op_date"), "流动性支持"),
                 esc(r.get("bucket")), fmt(r.get("max_bn"), 1), fmt(r.get("accepted_bn"), 1),
                 fmt(r.get("offer_to_max"), 1)) for r in recs[:10]])
    return h + qual_card(obj["qual"])


def v_debt_long(obj, ctx):
    d = ctx.get("debt_long") or {}
    yrs, tot, ng = d.get("years") or [], d.get("total") or [], d.get("ngdp") or []
    ratio = [round(100*t/g, 1) if (t and g) else None for t, g in zip(tot, ng)]
    h = chart("ch_debt_long", "line", [str(y) for y in yrs],
              [{"label": "总债务", "data": tot, "color": "ink", "w": 2},
               {"label": "总债务/NGDP (右轴)", "data": ratio, "color": "red", "w": 1.6,
                "dash": [5, 4], "axis": "y2"}], "bn",
              opts={"tall": True, "zoom": True, "axes": {"y2": {"unit": "%"}}})
    note = '<div class="anchor-note">1975年至今年度 · 左轴绝对额, 右轴/NGDP · 滚轮缩放双击复位</div>'
    return h + note + qual_card(obj["qual"])


def v_interest_view(obj, ctx):
    r = ctx["avg_rates"].get("series") or []
    b1 = (ctx.get("bill1y") or {}).get("series") or []
    b1m = {x["month"]: x["rate"] for x in b1}
    h = chart("ch_rate", "line", [x["month"][2:] for x in r],
              [{"label": "存量加权利率", "data": [x["rate"] for x in r], "color": "amber", "w": 2},
               {"label": "1Y bill发行利率(边际)", "data": [b1m.get(x["month"]) for x in r],
                "color": "blue", "w": 1.3, "alpha": "AA"}], "%",
              opts={"h": 340, "zoom": True})
    ie = ctx["interest"].get("series") or []
    h += "<h4>月度利息支出</h4>"
    h += chart("ch_ie", "pnbar", [x["month"][2:] for x in ie],
               [{"label": "月度利息支出", "data": [x["expense_bn"] for x in ie], "color": "red"}], "bn")
    return h + qual_card(obj["qual"])


def v_combo(obj, ctx):
    h = ""
    for p in obj.get("parts", []):
        h += f'<div class="ptitle">{esc(p["name"])}</div>'
        try:
            h += VIEWS[p["view"]](p, ctx)
        except Exception as e:
            h += f'<div class="anchor-note">子模块降级 ({type(e).__name__})</div>'
    if obj.get("include_laws"):
        h += '<div class="ptitle">框架法档案</div>' + ctx.get("laws_html", "")
    return h


VIEWS = {"combo": v_combo, 
    "debt_limit": v_debt_limit, "qual_only": v_qual_only,
    "expiry_table": v_expiry_table, "debt_tiers": v_debt_tiers,
    "caps_view": v_caps_view, "paygo_view": v_paygo_view,
    "baseline_center": v_baseline_center, "cycle_instances": v_cycle_instances,
    "approps_v2": v_approps_v2, "expansion_view": v_expansion_view, "fytd_progress": v_fytd_progress,
    "annual_widget": v_annual_widget, "local_widget": v_local_widget, "holders_v2": v_holders_v2, "dts_flows": v_dts_flows,
    "qra_view": v_qra_view, "funding_widget": v_funding_widget,
    "cash_buyback": v_cash_buyback, "debt_long": v_debt_long,
    "supply_share": v_supply_share,
    "structure_view": v_structure_view, "holders_table": v_holders_table,
    "interest_view": v_interest_view,
}


# ---------------------------------------------------------------- 组装

def sources_table(obj):
    rows = []
    for s in obj.get("sources", []):
        nm = f'<a href="{esc(s["link"])}" target="_blank">{esc(s["name"])}</a>' if s.get("link") else esc(s["name"])
        rows.append((nm, s.get("freq", ""), s.get("kind", "")))
    return table(["来源", "频率", "接入"], rows, "src") if rows else ""


def render_object(obj, ctx):
    q = obj.get("qual") or {}
    dossier = ""
    if q.get("mechanism"):
        dossier += f'<div class="mech"><b>机制</b><br>{esc(q["mechanism"])}</div>'
    if q.get("background"):
        dossier += f'<div class="mech"><b>背景</b><br>{esc(q["background"])}</div>'
    if obj.get("laws"):
        links = " ".join(f'<a href="#law-{lid}">{esc(next((l["name"] for l in LAWS if l["id"] == lid), lid))}</a>'
                         for lid in obj["laws"])
        dossier += f'<div class="mech"><b>相关框架法</b><br>{links}</div>'
    dossier += sources_table(obj)
    try:
        view_html = VIEWS[obj["view"]](obj, ctx)
    except Exception as e:
        view_html = (f'<div class="anchor-note">模块渲染降级: 数据待首跑校准 '
                     f'({type(e).__name__}) · 校正字段映射后自动恢复</div>')
    return f"""
<section class="obj" id="obj-{obj['id']}">
  <div class="srow">
    <span class="oname">{esc(obj['name'])}</span>
    <span class="osum">{status_metric(obj, ctx)}</span>
    <span class="ostat">{freshness_marks(obj)}{next_node(obj)}</span>
  </div>
  <div style="display:none">
  </div>
  <div class="work">{view_html}</div>
  <details class="dossier"><summary>档案 · 机制与来源</summary>{dossier}</details>
</section>"""


def load_events():
    p = DATA / "events.jsonl"
    if not p.exists(): return []
    return sorted((json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()),
                  key=lambda e: e["date"])


def ev_meta(e):
    marks = []
    if e.get("dtype") == "估计": marks.append("估")
    if e.get("revisions"): marks.append(f"改期×{len(e['revisions'])}")
    return " · ".join(marks)


def render_strip(evs):
    horizon = (TODAY + timedelta(days=90)).isoformat()
    strip = ""
    for e in evs:
        if not (TODAY.isoformat() <= e["date"] <= horizon) or e["status"] == "cancelled":
            continue
        dd = (date.fromisoformat(e["date"]) - TODAY).days
        strip += f"""<div class="ev cat-{e['cat']}{' today' if dd <= 0 else ''}">
<div class="d">{'今日' if dd <= 0 else f'D-{dd}'}<small> {e['cat']}</small></div>
<div class="lbl">{esc(e['label'])}</div>
<div class="own">{esc(OBJ_NAMES.get(e.get('owner'), e.get('owner', '')))} · {e['date']}{(' · ' + ev_meta(e)) if ev_meta(e) else ''}</div></div>"""
    return strip


def main():
    cfg = yaml.safe_load((ROOT / "config/objects_us.yaml").read_text(encoding="utf-8"))
    ctx = {"anchors": cfg["anchors"]}
    for name in ["debt", "debt_limit", "debt_limit_history", "market", "tga", "mts", "mts_receipts", "mts_outlays",
                 "dts_flows", "auctions", "upcoming", "buybacks", "supply", "approps_status",
                 "qra_history", "coupon_sizes", "wam", "debt_long", "bill1y", "local_fiscal", "tic_holders", "soma",
                 "mspd_structure", "avg_rates", "interest"]:
        ctx[name] = J(name)
    ctx["fy_paths"] = fy_paths(ctx["mts"].get("series") or [])
    global EVENTS, OBJ_NAMES, LAWS
    EVENTS = load_events()
    OBJ_NAMES = {o["id"]: o["name"] for l in cfg["layers"] for o in l["objects"]}
    OBJ_NAMES.update({"tax_legislation": "立法", "mandatory_legislation": "立法",
                      "debt_structure": "债务限制", "debt_limit": "债务限制",
                      "caps_sequestration": "支出限制", "paygo": "支出限制",
                      "impoundment": "支出限制"})
    LAWS = cfg.get("framework_laws", [])
    global WATCH
    wp = DATA / "watch_state.json"
    WATCH = json.loads(wp.read_text(encoding="utf-8")) if wp.exists() else {}
    any_sample = any(ctx[n].get("sample") for n in
                     ["debt", "tga", "mts", "auctions", "supply"] if ctx.get(n))

    # 层与对象
    laws_rows = [(f'<span id="law-{l["id"]}">{esc(l["name"])}</span>', l["note"], l["status"], l.get("last_change", "—"))
                 for l in LAWS]
    laws_card = f"""
<section class="obj"><div class="srow"><span class="oname">框架法档案</span>
<span class="ometric">规则的法律底座 · 本身会到期与修订</span></div>
<details class="dossier" open><summary>展开档案</summary>
{table(["框架法", "要点", "现行状态", "最近变化"], laws_rows)}
</details></section>"""
    ctx["laws_html"] = laws_card
    L1G = [("legislation", "立法", ["tax_legislation", "mandatory_legislation"], True,
            "到期结点×赤字影响一表尽览; 官方评分口径见表注"),
           ("debt_limits", "债务限制", ["debt_structure", "debt_limit"], False,
            "口径瀑布(总→公众→限额内) + 1993年至今债限双曲线"),
           ("spending_limits", "支出限制", ["caps_sequestration", "paygo", "impoundment"], False,
            "法定caps · PAYGO记分卡 · 行政扣款三道闸")]
    for layer in cfg["layers"]:
        if layer["id"] == "L1":
            by_id = {o["id"]: o for o in layer["objects"]}
            merged = []
            for gid, gname, pids, laws, summ in L1G:
                parts = [by_id[p] for p in pids if p in by_id]
                m0 = {"id": gid, "name": gname, "view": "combo", "parts": parts,
                      "part_ids": pids, "include_laws": laws,
                      "status_line": "text", "text_status": summ,
                      "verified": min(p.get("verified", "") for p in parts)}
                merged.append(m0)
            layer["objects"] = merged
    layers_html = ""
    for layer in cfg["layers"]:
        objs = ""
        for o in layer["objects"]:
            objs += render_object(o, ctx)
        layers_html += f"""
<div class="layer" id="{layer['id']}">
  <div class="lhead">
    <h2>{layer['id']} · {esc(layer['name'])}</h2>
    <button class="ltoggle" data-layer="{layer['id']}">收起工作视图</button>
  </div>
  {objs}
</div>"""

    # 日历 (账本视图聚合)

    # 近7日变化流水: 新入账(created_at)与新发生(date)取并集
    lo7 = (TODAY - timedelta(days=7)).isoformat()
    feed = [e for e in EVENTS if (e.get("created_at", "") >= lo7 and e["id"].startswith("watch-"))
            or (lo7 <= e["date"] <= TODAY.isoformat() and e["status"] == "occurred"
                and (e.get("result") or {}).get("summary"))]
    feed = sorted(feed, key=lambda e: e["date"], reverse=True)[:18]
    flux = "".join(
        f'<div class="fx"><span class="fxd">{e["date"][5:]}</span>'
        f'<span class="fxc c-{e["cat"]}">{e["cat"]}</span>'
        f'<span>{esc(e["label"])}</span>'
        f'<span class="fxr">{esc((e.get("result") or {}).get("summary", ""))}</span></div>'
        for e in feed) or '<span class="hint">近7日无入账变化</span>' 

    # 参考层
    notes = "".join(f"<li>{esc(n)}</li>" for n in cfg.get("reference", {}).get("pipeline_notes", []))

    nav = "".join(f'<a href="#{l["id"]}">{l["id"]} {esc(l["name"])}</a>' for l in cfg["layers"])

    page = TEMPLATE
    page = page.replace("__NAV__", nav)
    page = page.replace("__FLUX__", flux)
    lm = J("../us/ledger_meta") if False else (json.loads((DATA / "ledger_meta.json").read_text(encoding="utf-8"))
          if (DATA / "ledger_meta.json").exists() else {})
    rules_line = " · ".join(f"{k}: {v}" for k, v in (lm.get("rules") or {}).items())
    page = page.replace("__CALRULES__",
        f"账本维护 {lm.get('maintained_at', '—')} · 暂定事件带估标, 公告后自动作废覆盖<br>更新规则 — {rules_line}")
    # 融资预测默认值(基线赤字联动CBO矩阵现行版)
    fnx_def = {"baseline": [1925, 2075, 2250]}
    try:
        mxd = json.loads((DATA / "cbo_matrix.json").read_text(encoding="utf-8"))
        vc = mxd["versions"][-1]["id"]; yrs_m = mxd["years"]
        D = mxd["data"][vc]
        revk = [k for k in D if k.startswith("rev_")]; outk = [k for k in D if k.startswith("out_")]
        defs = []
        for fy in (2026, 2027, 2028):
            i = yrs_m.index(fy)
            defs.append(round(sum(D[k][i] for k in outk) - sum(D[k][i] for k in revk), 0))
        fnx_def["baseline"] = defs
    except Exception:
        pass
    page_fnx = json.dumps(fnx_def, ensure_ascii=False)
    ann = J("annual")
    anx = {"years": ann.get("years", []), "series": ann.get("series", {}), "ngdp": ann.get("ngdp", []),
           "fytd": {r["id"]: r for r in (ctx["mts_receipts"].get("rows") or []) + (ctx["mts_outlays"].get("rows") or []) if r.get("id")},
           "as_of": ctx["mts_receipts"].get("as_of")}
    page_anx = json.dumps(anx, ensure_ascii=False)
    lx_payload = dict(ctx.get("local_fiscal") or {})
    for l_ in cfg["layers"]:
        for o_ in l_["objects"]:
            parts_ = o_.get("parts") or [o_]
            for p_ in parts_:
                if p_.get("id") == "local_fiscal":
                    lx_payload["census"] = p_.get("anchors_census") or {}
    page_lx = json.dumps(lx_payload, ensure_ascii=False)
    mx = DATA / "cbo_matrix.json"
    page = page.replace("__ANNUAL__", page_anx)
    page = page.replace("__LOCAL__", page_lx)
    page = page.replace("__FNXDEF__", page_fnx)
    page = page.replace("__CBOMATRIX__", mx.read_text(encoding="utf-8") if mx.exists() else "null")
    page = page.replace("__EVENTS__", json.dumps(EVENTS, ensure_ascii=False))
    page = page.replace("__OBJNAMES__", json.dumps(OBJ_NAMES, ensure_ascii=False))
    page = page.replace("__LAYERS__", layers_html)
    page = page.replace("__NOTES__", notes)
    page = page.replace("__META__", f"生成 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} · 对象注册表 {cfg['updated']}")
    page = page.replace("__SAMPLE__", '<span class="badge">SAMPLE DATA · 首跑后替换</span>' if any_sample else "")
    page = page.replace("__CHARTS__", json.dumps(CHARTS, ensure_ascii=False))
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs/index.html").write_text(page, encoding="utf-8")
    print(f"docs/index.html ({len(page)//1024} KB, {len(CHARTS)} charts)")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fiscal Monitor · US</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&family=Noto+Sans+SC:wght@400;500;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1"></script>
<script src="https://cdn.jsdelivr.net/npm/hammerjs@2.0.8"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.2.0"></script>
<style>
:root{--paper:#F4F6F3;--card:#FFF;--ink:#16222C;--muted:#5D6B76;--line:#E2E6E2;
--green:#0E5A45;--red:#B03A2E;--blue:#2B5B8A;--amber:#8A6410;--amber-bg:#FBF3DC;
--mono:'IBM Plex Mono',monospace;--sans:'IBM Plex Sans','Noto Sans SC',system-ui,sans-serif}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:13.5px;line-height:1.5}
.wrap{max-width:1560px;margin:0 auto;padding:18px 28px 60px}
a{color:var(--blue)}
header{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px;
border-bottom:2px solid var(--ink);padding-bottom:10px}
header h1{font-size:18px;font-weight:600}
header h1 span{color:var(--blue)}
.meta{font-family:var(--mono);font-size:11.5px;color:var(--muted)}
.badge{background:var(--amber-bg);color:var(--amber);border:1px solid var(--amber);
border-radius:3px;padding:1px 8px;font-size:11px;font-family:var(--mono);margin-left:8px}
nav.top{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;padding:8px 0;border-bottom:1px solid var(--line);margin-bottom:12px}
nav.top a{text-decoration:none;color:var(--muted);font-weight:500}
nav.top a:hover{color:var(--ink)}

.sec{font-size:11.5px;letter-spacing:1.5px;color:var(--muted);margin:14px 0 8px;font-weight:600}
.clock{display:flex;gap:10px;overflow-x:auto;padding-bottom:8px}
.ev{flex:0 0 auto;background:var(--card);border:1px solid var(--line);border-left:3px solid var(--blue);
border-radius:5px;padding:7px 12px;min-width:150px}
.ev .d{font-family:var(--mono);font-size:18px;font-weight:600}
.ev .lbl{font-size:12px;margin-top:2px}
.ev .own{font-family:var(--mono);font-size:10.5px;color:var(--muted);margin-top:2px}
.ev.today{background:var(--ink);color:#fff}
.ev .d small{font-size:10px;font-weight:400;color:var(--muted)}
.ev.cat-发行{border-left-color:var(--green)}.ev.cat-回购{border-left-color:var(--amber)}
.ev.cat-文件{border-left-color:var(--blue)}.ev.cat-立法{border-left-color:var(--red)}
.ev.cat-税期{border-left-color:var(--amber)}.ev.cat-政治{border-left-color:#6B4E8C}
.ev.cat-人工{border-left-color:var(--muted)}
.ev.today .own{color:#B9C2C9}
.calbox{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:12px 14px}
.calbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px}
#calTitle{font-family:var(--mono);font-weight:600;font-size:14px;min-width:96px;text-align:center}
.cbtn{background:none;border:1px solid var(--line);border-radius:4px;padding:2px 10px;
cursor:pointer;font-size:13px;color:var(--ink);font-family:var(--sans)}
.cbtn:hover{border-color:var(--muted)}
.chips{display:flex;gap:6px;margin-left:auto;flex-wrap:wrap}
.chip{border:1px solid var(--line);border-radius:12px;padding:1px 10px;font-size:11.5px;
cursor:pointer;user-select:none;color:var(--muted)}
.chip.on{color:#fff}
.chip.on[data-g="发行回购"]{background:var(--green);border-color:var(--green)}
.chip.on[data-g="重要文件"]{background:var(--blue);border-color:var(--blue)}
.chip.on[data-g="立法时间"]{background:var(--red);border-color:var(--red)}
.chip.on[data-g="重要到期日"]{background:var(--amber);border-color:var(--amber)}
.calhead{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-bottom:4px}
.calhead div{font-family:var(--mono);font-size:10.5px;color:var(--muted);text-align:center}
.calgrid{display:grid;grid-template-columns:repeat(7,1fr);gap:4px}
.day{border:1px solid #EEF0EC;border-radius:4px;min-height:84px;padding:3px 4px;
cursor:pointer;background:var(--card);overflow:hidden}
.day:hover{border-color:var(--muted)}
.day.dim{background:#F8F9F7;color:#B9C2C9}
.day.wknd{background:#F8F9F7}
.day.today{outline:2px solid var(--ink);outline-offset:-2px}
.day .dn{font-family:var(--mono);font-size:11px;color:var(--muted)}
.day.today .dn{color:var(--ink);font-weight:600}
.pill{font-size:10.5px;border-radius:3px;padding:0 4px;margin-top:2px;white-space:nowrap;
overflow:hidden;text-overflow:ellipsis;border-left:3px solid transparent;background:transparent}
.pill{color:var(--ink)}
.pill.g-发行回购{border-left-color:var(--green);background:#E7F0EA}
.pill.g-重要文件{border-left-color:var(--blue);background:#E4ECF4}
.pill.g-立法时间{border-left-color:var(--red);background:#F5E6E4}
.pill.g-重要到期日{border-left-color:var(--amber);background:#F6EEDC}
.pill.done{opacity:.55}
.pill.more{color:var(--blue);border-left-color:transparent;opacity:1}
.caldetail{border-top:1px solid var(--line);margin-top:10px;padding-top:8px;font-size:12.5px}
.caldetail .hint{color:var(--muted);font-size:12px}
.calrules{border-top:1px dashed var(--line);margin-top:10px;padding-top:6px;
font-family:var(--mono);font-size:10.5px;color:var(--muted);line-height:1.7}
.dev{padding:6px 8px;border-left:3px solid var(--line);margin:6px 0;background:#FBFCFA;border-radius:0 4px 4px 0}
.dev.g-发行回购{border-left-color:var(--green)}
.dev.g-重要文件{border-left-color:var(--blue)}
.dev.g-立法时间{border-left-color:var(--red)}
.dev.g-重要到期日{border-left-color:var(--amber)}
.dev .l1{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.dev .st{font-family:var(--mono);font-size:10.5px;border-radius:3px;padding:0 5px}
.dev .st.occurred{background:#E3ECE2;color:var(--green)}
.dev .st.scheduled{background:#E8EDF3;color:var(--blue)}
.dev .st.revised{background:var(--amber-bg);color:var(--amber)}
.dev .res{font-family:var(--mono);font-size:11.5px;color:var(--ink);margin-top:2px}
.dev .chk{color:var(--muted);font-size:11.5px;margin-top:2px}


.layer{margin-top:22px}
.lhead{display:flex;align-items:baseline;gap:12px;border-bottom:1.5px solid var(--ink);padding-bottom:6px;margin-bottom:10px}
.lhead h2{font-size:15px;font-weight:600}
.ltime{font-size:11.5px;color:var(--muted)}
.ltoggle{margin-left:auto;background:none;border:1px solid var(--line);border-radius:4px;
padding:2px 10px;font-size:11.5px;color:var(--muted);cursor:pointer;font-family:var(--sans)}

.obj{background:var(--card);border:1px solid var(--line);border-radius:6px;margin-bottom:12px;overflow:hidden}
.srow{display:flex;align-items:baseline;gap:14px;padding:9px 16px;border-bottom:1px solid var(--line);
background:#FBFCFA;flex-wrap:wrap}
.oname{font-weight:600;font-size:13.5px;min-width:120px}
.ometric{font-family:var(--mono);font-size:12.5px;color:var(--muted)}
.ometric b{color:var(--ink);font-size:14px}
.ostat{flex:0 0 auto;margin-left:auto;font-family:var(--mono);font-size:11.5px;color:var(--muted);text-align:right;white-space:nowrap;padding-left:16px}
.osum{flex:1 1 auto;min-width:0;font-size:12px;color:var(--muted);line-height:1.5;text-align:left}
.osum b{color:var(--muted);font-weight:600;font-size:12px}
.srow .oname{flex:0 0 168px}
.ptitle{font-size:13.5px;font-weight:600;margin:16px 0 6px;padding-left:8px;border-left:3px solid var(--ink)}
.onode{margin-left:auto;font-size:12px;color:var(--muted)}
.nn{font-family:var(--mono);font-weight:600;color:var(--red)}
.work{padding:12px 16px}
.work h4{font-size:11.5px;color:var(--muted);letter-spacing:.5px;margin:8px 0 6px}
.chart{max-height:230px;margin:4px 0 10px}
.chart.tall{height:470px;max-height:470px;width:100%}
.chart.tall canvas{max-height:460px;width:100%!important}
canvas{max-height:220px}
.imp{font-family:var(--mono);font-size:11px;display:block;max-width:190px;
white-space:normal;line-height:1.4;color:var(--ink)}
.qcard{background:#F6F8F5;border-radius:5px;padding:9px 12px;margin-top:8px}
.qrow{display:flex;gap:10px;font-size:12.5px;margin:3px 0}
.qk{flex:0 0 68px;color:var(--blue);font-weight:500}
.anchor-note{font-family:var(--mono);font-size:11.5px;color:var(--amber);margin:4px 0}
details.dossier{border-top:1px solid var(--line)}
details.dossier summary{cursor:pointer;padding:7px 16px;font-size:12px;color:var(--muted)}
details.dossier > div, details.dossier > table{margin:4px 16px 12px}
.mech{font-size:12.5px;color:var(--ink);background:#FBFCFA;border-left:3px solid var(--line);
padding:8px 12px;margin-bottom:8px;white-space:pre-line}

table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;color:var(--muted);font-weight:500;padding:4px 8px;border-bottom:1.5px solid var(--line);
font-size:11px;letter-spacing:.4px;white-space:nowrap}
td{padding:4px 8px;border-bottom:1px solid #F0F2EF}
td.t{font-family:var(--sans)}
td.num,th.num{text-align:right;font-family:var(--mono);white-space:nowrap}
tr:last-child td{border-bottom:none}
.pos{color:var(--green)}.neg{color:var(--red)}
.auto{font-family:var(--mono);font-size:11px;color:var(--blue)}
.flow{margin:10px 0}
.ftrack{display:flex;align-items:center;gap:12px;margin:7px 0;flex-wrap:wrap}
.ftname{flex:0 0 88px;font-size:11.5px;color:var(--muted);font-weight:600;text-align:right}
.fnodes{display:flex;align-items:center;flex-wrap:wrap;row-gap:6px}
.fnode{font-size:11.5px;border:1.5px solid var(--line);border-radius:14px;padding:2px 11px;
white-space:nowrap;color:var(--muted);background:var(--card)}
.fnode b{font-weight:600;margin-right:2px}
.fnote{font-size:10px;margin-left:5px;opacity:.85}
.f-done{border-color:var(--green);color:var(--green);background:#EFF5F0}
.f-active{border-color:var(--red);color:var(--red);font-weight:600;box-shadow:0 0 0 3px #B03A2E1F}
.f-blocked{border-color:var(--amber);color:#7A5A0E;background:var(--amber-bg)}
.f-late{border-color:var(--amber);color:var(--amber)}
.f-risk{border-color:var(--red);color:var(--red);border-style:dashed}
.f-branch{border-color:var(--blue);color:var(--blue)}
.fcon{width:22px;height:1.5px;background:var(--line);margin:0 2px;flex:0 0 auto}
.flegend{margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;opacity:.8}
.blx-bar{display:flex;align-items:center;gap:10px;margin:6px 0;flex-wrap:wrap}
.blx-hint{font-size:11.5px;color:var(--muted);margin-left:auto}
.blx-tbl{overflow-x:auto}
.blx-tbl table td{font-family:var(--mono);font-size:11.5px;text-align:right;white-space:nowrap}
table.anx{table-layout:fixed;width:100%}
table.anx .c-lbl{width:220px;text-align:left}
table.anx .c-spk{width:84px;text-align:center}
table.anx th.num,table.anx td.num{text-align:right}
.blx-tbl table td.lbl{font-family:var(--sans);text-align:left}
.blx-tbl tr.sel td{background:#EEF3F7}
.blx-tbl tr.clickable{cursor:pointer}
.blx-tbl tr.l0 td.lbl{font-weight:600}
.blx-tbl input{width:56px;font-family:var(--mono);font-size:11px;border:1px solid var(--line);
border-radius:3px;padding:1px 3px;text-align:right;background:#FFFDF5}
.chip.on[data-g^="v"]{background:var(--ink);border-color:var(--ink)}
.stub{color:var(--amber);font-family:var(--mono);font-size:11px;border:1px dashed var(--amber);
border-radius:3px;padding:0 4px}
.stg{font-family:var(--mono);font-size:11px;border-radius:3px;padding:1px 7px;white-space:nowrap}
.s0{background:#F1F2F0;color:var(--muted)}.s1{background:#EDF1EA;color:var(--muted)}
.s2{background:#E3ECE2;color:var(--green)}.s3{background:#D2E3D4;color:var(--green)}
.s4{background:#C4DBF0;color:var(--blue)}.s5{background:var(--green);color:#fff}
.crlink{font-size:12.5px;margin-top:8px}
.mk{font-family:var(--mono);font-size:10.5px;border-radius:3px;padding:0 6px;margin-right:8px}
.mk.hot{background:#F6E3DF;color:var(--red)}
.mk.old{background:var(--amber-bg);color:var(--amber)}
.flux{background:var(--card);border:1px solid var(--line);border-radius:5px;padding:8px 14px}
.fx{display:flex;gap:10px;align-items:baseline;font-size:12.5px;padding:3px 0;
border-bottom:1px solid #F0F2EF;flex-wrap:wrap}
.fx:last-child{border-bottom:none}
.fxd{font-family:var(--mono);color:var(--muted);flex:0 0 44px}
.fxc{font-family:var(--mono);font-size:10.5px;border-radius:3px;padding:0 5px;background:#F1F2F0;color:var(--muted)}
.fxc.c-立法{color:var(--red)}.fxc.c-发行{color:var(--green)}.fxc.c-文件{color:var(--blue)}
.fxr{font-family:var(--mono);font-size:11.5px;color:var(--muted);margin-left:auto}
.grp{font-size:12px;font-weight:600;letter-spacing:.8px;color:var(--ink);
margin:14px 0 8px;border-left:3px solid var(--ink);padding-left:8px}
.lchips{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.lchip{font-size:11.5px;border:1px solid var(--line);border-radius:12px;padding:2px 10px;
text-decoration:none;color:var(--blue)}
.lchip:hover{border-color:var(--blue)}
.src td{font-size:12px}
footer{margin-top:26px;border-top:1px solid var(--line);padding-top:10px;
font-family:var(--mono);font-size:11px;color:var(--muted);display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px}
@media (max-width:720px){.onode{margin-left:0;width:100%}}
</style></head>
<body><div class="wrap">
<header><h1>FISCAL MONITOR <span>/ US 美国</span>__SAMPLE__</h1><div class="meta">__META__</div></header>
<nav class="top"><a href="#L0">L0 Timeline</a>__NAV__<a href="#ref">参考层</a></nav>

<div class="layer" id="L0">
<div class="lhead"><h2>L0 · Timeline</h2>
<button class="ltoggle" data-layer="L0">收起工作视图</button></div>
<section class="obj"><div class="srow"><span class="oname">财政日历</span>
<span class="ostat">事件数据库 · 历史可回溯</span></div>
<div class="work">
<div class="calbox">
  <div class="calbar">
    <button class="cbtn" id="calPrev">‹</button>
    <span id="calTitle"></span>
    <button class="cbtn" id="calNext">›</button>
    <button class="cbtn" id="calHome">今天</button>
    <span class="chips" id="calChips"></span>
  </div>
  <div class="calhead" id="calHead"></div>
  <div class="calgrid" id="calGrid"></div>
  <div class="caldetail" id="calDetail"><span class="hint">点击日期查看事件明细、核对清单与结果</span></div>
  <div class="calrules">__CALRULES__</div>
</div>
</div></section>
<section class="obj"><div class="srow"><span class="oname">近7日变化流水</span>
<span class="ostat">数据落地与监听命中</span></div>
<div class="work"><div class="flux">__FLUX__</div></div></section>
</div>

__LAYERS__

<div class="layer" id="ref">
<div class="lhead"><h2>R · 参考层</h2></div>
<section class="obj"><div class="srow"><span class="oname">管线注记</span></div>
<div class="work"><ul style="padding-left:18px;font-size:12.5px">__NOTES__</ul>
<div class="qcard" style="margin-top:10px">完整数据源清单与勾稽关系另见 us_fiscal_data_sources.md (仓库内)。</div></div></section>
</div>

<footer><span>数据: FiscalData / QRA文件包 / congress.gov / OMB / CBO · 定性: objects_us.yaml + events_seed.yaml · 账本: events.jsonl</span>
<span>对象制 · 单页 · 层内折叠</span></footer>
</div>
<script>
const CHARTS = __CHARTS__;
const PAL = {ink:'#16222C',muted:'#8A97A1',gray:'#5D6B76',green:'#0E5A45',red:'#B03A2E',blue:'#2B5B8A',amber:'#B07C10'};
Chart.defaults.font.family="'IBM Plex Mono',monospace";
Chart.defaults.font.size=10.5; Chart.defaults.color='#5D6B76';
Chart.defaults.plugins.legend.labels.boxWidth=9;
CHARTS.forEach(c=>{
  const el=document.getElementById(c.id); if(!el) return;
  if(c.kind==='line'){
    const fmtT=v=>Math.abs(v)>=1000?Math.round(v/1000)+'T':Math.round(v).toLocaleString();
    const scales={y:{grid:{color:'#EDEFEA'},
      ticks:c.y_unit==='bn'?{callback:fmtT}:(c.y_unit==='%'?{callback:v=>(Math.round(v*100)/100)+'%'}:{})},
      x:(c.opts&&c.opts.time)
        ?{type:'time',grid:{display:false},ticks:{maxTicksLimit:12}}
        :{grid:{display:false},ticks:{maxTicksLimit:c.opts&&c.opts.zoom?14:10}}};
    const ax=(c.opts&&c.opts.axes)||{};
    c.datasets.forEach(d=>{
      if(d.axis==='y1') scales.y1={position:'right',type:(ax.y1&&ax.y1.log)?'logarithmic':'linear',
        grid:{display:false},ticks:{color:PAL.blue+'99',
        callback:v=>{const s=[100,200,500,1000,2000,5000,10000];return (ax.y1&&ax.y1.log)?(s.includes(v)?v.toLocaleString():null):v.toLocaleString();}}};
      if(d.axis==='y2') scales.y2={position:'right',grid:{display:false},
        ticks:{color:PAL.amber+'BB',callback:v=>v.toFixed(2)+((ax.y2&&ax.y2.unit)||'')}};
    });
    if(c.opts&&(c.opts.zoom||c.opts.tall)){
      scales.y.afterFit=a=>{a.width=64};
      if(scales.y1) scales.y1.afterFit=a=>{a.width=58};
      if(scales.y2) scales.y2.afterFit=a=>{a.width=56};
    }
    const opts={scales,interaction:{mode:'index',intersect:false}};
    if(c.opts&&(c.opts.tall||c.opts.h)) opts.maintainAspectRatio=false;
    if(c.opts&&c.opts.zoom){
      opts.plugins={zoom:{zoom:{wheel:{enabled:true},pinch:{enabled:true},mode:'xy'},
                          pan:{enabled:true,mode:'xy',modifierKey:null}}};
    }
    const ch=new Chart(el,{type:'line',data:{labels:c.labels,datasets:c.datasets.map(d=>({
      label:d.label,data:d.xy?d.xy.map(p=>({x:p[0],y:p[1]})):d.data,
      borderColor:(PAL[d.color]||d.color)+(d.alpha||''),borderWidth:d.w||1.5,
      borderDash:d.dash||[],pointRadius:0,tension:d.step?0:.15,stepped:!!d.step,spanGaps:false,
      yAxisID:d.axis||'y',pointStyle:d.pstyle||'circle',
      pointRadius:d.pr!=null?d.data.map((v,i)=>(v!=null&&(i+1>=d.data.length||d.data[i+1]==null))?d.pr:0):0,
      pointBackgroundColor:'#fff',pointBorderColor:PAL[d.color]||d.color,pointBorderWidth:2,
      fill:!!d.fill,backgroundColor:(PAL[d.color]||d.color)+'14'}))},
      options:opts});
    if(c.opts&&c.opts.zoom) el.ondblclick=()=>ch.resetZoom();
  } else if(c.kind==='pnbar'){
    new Chart(el,{type:'bar',data:{labels:c.labels,datasets:c.datasets.map(d=>({
      label:d.label,data:d.data,
      backgroundColor:d.color==='auto'?d.data.map(v=>v>=0?PAL.green+'B3':PAL.red+'B3'):(PAL[d.color]||d.color)+'B3'}))},
      options:{scales:{y:{grid:{color:'#EDEFEA'}},x:{grid:{display:false},ticks:{maxTicksLimit:12}}}}});
  } else if(c.kind==='hbar'){
    new Chart(el,{type:'bar',data:{labels:c.labels,datasets:c.datasets.map(d=>({
      label:d.label,data:d.data,backgroundColor:(PAL[d.color]||d.color)+'B3'}))},
      options:{indexAxis:'y',plugins:{legend:{display:false}},
      scales:{x:{grid:{color:'#EDEFEA'}},y:{grid:{display:false}}}}});
  }
});
// ---- 地方收支 (央地对照, 图表联动)
const LX = __LOCAL__;
if(document.getElementById('lxTable') && !(LX && LX.years && LX.years.length)){
  document.getElementById('lxTable').innerHTML =
    '<div class="anchor-note">数据文件待weekly首跑生成(NIPA/QTAX), 生成后自动填充</div>';
}
if(LX && LX.years && LX.years.length && document.getElementById('lxTable')){
(function(){
  const Y = LX.years, N = Y.length, S = LX.series, G = LX.ngdp || [];
  const ROWS = [
    {id:'sl_rev',l:'州地方总收入',lv:0},
    {id:'grants',l:'其中: 联邦转移(Grants)',lv:1},
    {id:'sl_own',l:'其中: 自有收入',lv:1},
    {id:'t_prop',l:'财产税 (QTAX·滞后一季)',lv:2},
    {id:'t_sales',l:'一般销售税',lv:2},
    {id:'t_ind',l:'州个人所得税',lv:2},
    {id:'t_corp',l:'州企业所得税',lv:2},
    {id:'sl_exp',l:'州地方总支出',lv:0},
    ...(((LX.census||{}).spending)||[]).map((r,i)=>({id:'cx'+i,l:'支出·'+r.item+' (Census '+((LX.census||{}).as_of||'')+'锚)',lv:1,fixed:r.bn})),
    {id:'fed_rev',l:'联邦总收入 (NIPA口径)',lv:0},
    {id:'fed_exp',l:'联邦总支出 (NIPA口径)',lv:0},
    {id:'dep',l:'联邦转移/州地方收入 %',lv:0,pct:true},
  ];
  const ser = id => {
    if(id.startsWith('cx')) return Y.map(()=>null);
    if(id==='sl_own') return Y.map((_,t)=>(S.sl_rev&&S.grants&&S.sl_rev[t]!=null&&S.grants[t]!=null)?S.sl_rev[t]-S.grants[t]:null);
    if(id==='dep') return Y.map((_,t)=>(S.grants&&S.sl_rev&&S.grants[t]&&S.sl_rev[t])?100*S.grants[t]/S.sl_rev[t]:null);
    return (S[id]||Y.map(()=>null));
  };
  const fmtc=v=>v==null?'—':Math.round(v).toLocaleString();
  function spark(id){
    const s=ser(id), yy=[];
    for(let t=N-5;t<N;t++){ if(s[t]!=null&&s[t-1]) yy.push({fy:Y[t],v:100*(s[t]/s[t-1]-1)}); }
    if(yy.length<2) return '';
    const vs=yy.map(p=>p.v), mn=Math.min(...vs,0), mx=Math.max(...vs,0), rg=(mx-mn)||1;
    const XY=yy.map((p,i)=>[6+i*(56/(yy.length-1)), 18-3-(p.v-mn)/rg*12]);
    const zy=18-3-(0-mn)/rg*12, col=vs[vs.length-1]>=0?'#0E5A45':'#B03A2E';
    let g=`<svg width="70" height="20" style="display:block;margin:0 auto"><line x1="6" y1="${zy}" x2="62" y2="${zy}" stroke="#E2E6E2"/><polyline points="${XY.map(p=>p.join(',')).join(' ')}" fill="none" stroke="${col}" stroke-width="1.4"/>`;
    XY.forEach((p,i)=>{g+=`<circle cx="${p[0]}" cy="${p[1]}" r="2" fill="${col}"><title>${yy[i].fy}: ${yy[i].v>=0?'+':''}${yy[i].v.toFixed(1)}%</title></circle>`;});
    return g+'</svg>';
  }
  let SEL=null, CH=null;
  function drawT(){
    let h=`<table class="anx"><tr><th class="c-lbl">科目 (bn · CY${Y[N-1]})</th><th class="c-spk">5年yoy走势</th><th class="num">最新</th><th class="num">上年</th><th class="num">yoy</th></tr>`;
    ROWS.forEach(r=>{
      if(r.fixed!=null){
        h+=`<tr class="l${r.lv}"><td class="lbl c-lbl" style="padding-left:${8+r.lv*16}px">${r.l}</td>`
          +`<td class="c-spk"></td><td class="num">${Math.round(r.fixed).toLocaleString()}</td>`
          +`<td class="num">—</td><td class="num">—</td></tr>`;
        return;
      }
      const s=ser(r.id), a=s[N-1], b0=s[N-2];
      const yoy=(a!=null&&b0)?100*(a/b0-1):null;
      const val = r.pct? (a==null?'—':a.toFixed(1)+'%') : fmtc(a);
      const pv = r.pct? (b0==null?'—':b0.toFixed(1)+'%') : fmtc(b0);
      h+=`<tr class="clickable l${r.lv}${SEL===r.id?' sel':''}" data-id="${r.id}">`
        +`<td class="lbl c-lbl" style="padding-left:${8+r.lv*16}px">${r.l}</td><td class="c-spk">${spark(r.id)}</td>`
        +`<td class="num">${val}</td><td class="num">${pv}</td>`
        +`<td class="num ${yoy>=0?'pos':'neg'}">${yoy==null?'—':yoy.toFixed(1)+'%'}</td></tr>`;
    });
    document.getElementById('lxTable').innerHTML=h+'</table>';
    document.querySelectorAll('#lxTable tr.clickable').forEach(tr=>tr.onclick=()=>{
      SEL=(SEL===tr.dataset.id)?null:tr.dataset.id; drawT(); drawC();
    });
  }
  function drawC(){
    const lbls=Y.map(String);
    let ds,title;
    if(!SEL){
      title='联邦 vs 州地方 · 收支与转移 (bn)';
      ds=[
        {label:'联邦收入',data:ser('fed_rev'),borderColor:PAL.green,borderWidth:2},
        {label:'联邦支出',data:ser('fed_exp'),borderColor:PAL.red,borderWidth:2},
        {label:'州地方收入',data:ser('sl_rev'),borderColor:PAL.green+'88',borderDash:[6,4],borderWidth:1.6},
        {label:'州地方支出',data:ser('sl_exp'),borderColor:PAL.red+'88',borderDash:[6,4],borderWidth:1.6},
        {label:'联邦转移(勾稽线)',data:ser('grants'),borderColor:PAL.blue,borderWidth:1.6}];
      ds.forEach(d=>{d.yAxisID='y';});
    } else {
      const r=ROWS.find(x=>x.id===SEL); title=r.l;
      if(r.pct){
        ds=[{label:r.l,data:ser(SEL),borderColor:PAL.blue,borderWidth:2,yAxisID:'y2'}];
      } else {
        ds=[{label:r.l,data:ser(SEL),borderColor:PAL.red,borderWidth:2.2,yAxisID:'y'},
            {label:'/NGDP %',data:ser(SEL).map((v,t)=>v!=null&&G[t]?100*v/G[t]:null),
             borderColor:PAL.blue,borderDash:[5,4],borderWidth:1.6,yAxisID:'y2'}];
      }
    }
    ds.forEach(d=>{d.pointRadius=0;d.tension=.15;});
    const pctOnly = !!(SEL && (ROWS.find(x=>x.id===SEL)||{}).pct);
    if(CH) CH.destroy();
    CH=new Chart(document.getElementById('ch_local'),{type:'line',
      data:{labels:lbls,datasets:ds},
      options:{maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
        plugins:{title:{display:true,text:title,font:{size:12}}},
        scales:{y:{display:!pctOnly,grid:{color:'#EDEFEA'},ticks:{callback:v=>Math.abs(v)>=1000?Math.round(v/1000)+'T':v},afterFit:a=>{a.width=60}},
                y2:{position:'right',grid:{display:false},ticks:{callback:v=>(Math.round(v*100)/100)+'%'},afterFit:a=>{a.width=52}},
                x:{grid:{display:false}}}}});
  }
  drawT(); drawC();
})();
}

// ---- 财年融资预测 (Exhibit式三年联动)
const FNXD = __FNXDEF__;
if(document.getElementById('fnxTable')){
(function(){
  const FYS=[2026,2027,2028], LS='fm_fnx_v1';
  const DEF={baseline:FNXD.baseline||[1925,2075,2250], other:[-67,0,0],
    tga_end:[950,1001,1031], tga_start0:890, gross:[4395,4432,5414],
    maturing:[3325,3615,3915], rollover:[483,460,418], buyback:[265,302,302],
    start_c0:23318, start_b0:6397, soma_bills:[200,220,240], soma_total:[4200,4150,4100]};
  let E; try{E=JSON.parse(localStorage.getItem(LS))||{};}catch(e){E={};}
  const g=(k,i)=> (E[k]&&E[k][i]!=null&&E[k][i]!=='')?parseFloat(E[k][i]):(Array.isArray(DEF[k])?DEF[k][i]:DEF[k]);
  function compute(){
    const R={}; ['fin_need','dcash','need','pub_mat','net_c','net_b','end_c','end_b','pct','ppct','tga_start','start_c','start_b'].forEach(k=>R[k]=[]);
    for(let i=0;i<3;i++){
      const bl=g('baseline',i), ot=g('other',i);
      R.fin_need[i]=bl+ot;
      R.tga_start[i]= i===0? g('tga_start0',0): g('tga_end',i-1);
      R.dcash[i]=g('tga_end',i)-R.tga_start[i];
      R.need[i]=R.fin_need[i]+R.dcash[i];
      R.pub_mat[i]=g('maturing',i)-g('rollover',i);
      R.net_c[i]=g('gross',i)-R.pub_mat[i]-g('buyback',i);
      R.net_b[i]=R.need[i]-R.net_c[i];
      R.start_c[i]= i===0? g('start_c0',0): R.end_c[i-1];
      R.start_b[i]= i===0? g('start_b0',0): R.end_b[i-1];
      R.end_c[i]=R.start_c[i]+R.net_c[i];
      R.end_b[i]=R.start_b[i]+R.net_b[i];
      const mkt=R.end_c[i]+R.end_b[i];
      R.pct[i]=100*R.end_b[i]/mkt;
      R.ppct[i]=100*(R.end_b[i]-g('soma_bills',i))/(mkt-g('soma_total',i));
    }
    return R;
  }
  const ROWS=[
    ['baseline','1 基线赤字 (CBO现行版默认)','edit'],
    ['other','2 其他调整','edit'],
    ['fin_need','3 融资需求 (1+2)','calc'],
    ['tga_end','4 期末TGA假设','edit'],
    ['dcash','5 现金变动 ΔTGA','calc'],
    ['need','6 Marketable borrowing need (3+5)','bold'],
    ['gross','7 总coupon拍卖','edit'],
    ['maturing','8 coupon总到期','edit'],
    ['rollover','9 Fed rollover','edit'],
    ['pub_mat','10 公众持有到期 (8-9)','calc'],
    ['buyback','11 预期回购','edit'],
    ['net_c','12 净coupon供给 (7-10-11)','bold'],
    ['net_b','15 净bills供给 (6-12, 残差)','bold'],
    ['start_c','20 期初coupons存量','chain0'],
    ['start_b','21 期初bills存量','chain0'],
    ['end_c','22 期末coupons (12+20)','calc'],
    ['end_b','23 期末bills (15+21)','calc'],
    ['pct','24 Bills %marketable','pct'],
    ['soma_bills','· SOMA bills持仓假设','edit'],
    ['soma_total','· SOMA总持仓假设','edit'],
    ['ppct','25 私人持有bills %','pct'],
  ];
  const F=v=>v==null?'—':Math.round(v).toLocaleString();
  function draw(){
    const R=compute();
    let h='<table class="anx"><tr><th class="c-lbl" style="width:280px">项目 (bn)</th>'+FYS.map(y=>`<th class="num">FY${y}</th>`).join('')+'</tr>';
    ROWS.forEach(([k,l,kind])=>{
      const b=kind==='bold'?' style="font-weight:600"':'';
      h+=`<tr${b}><td class="lbl c-lbl">${l}</td>`;
      for(let i=0;i<3;i++){
        if(kind==='edit'||(kind==='chain0'&&i===0)){
          const key=kind==='chain0'?(k==='start_c'?'start_c0':'start_b0'):k;
          const idx=kind==='chain0'?0:i;
          h+=`<td class="num"><input data-k="${key}" data-i="${idx}" value="${g(key,idx)}"></td>`;
        } else if(kind==='pct') h+=`<td class="num">${R[k][i].toFixed(1)}%</td>`;
        else h+=`<td class="num">${F(R[k]?R[k][i]:null)}</td>`;
      }
      h+='</tr>';
    });
    document.getElementById('fnxTable').innerHTML=h+'</table>';
    document.querySelectorAll('#fnxTable input').forEach(inp=>inp.onchange=()=>{
      const k=inp.dataset.k, i=+inp.dataset.i;
      E[k]=E[k]||[]; E[k][i]=inp.value;
      localStorage.setItem(LS, JSON.stringify(E)); draw();
    });
  }
  document.getElementById('fnxReset').onclick=()=>{E={};localStorage.removeItem(LS);draw();};
  draw();
})();
}

// ---- 年度收支进度 (图+表联动, sparkline)
const ANX = __ANNUAL__;
if(ANX && ANX.years.length && document.getElementById('anxTable')){
(function(){
  const Y = ANX.years, N = Y.length, S = ANX.series, G = ANX.ngdp;
  const sum = ids => Y.map((_,t)=> ids.reduce((a,k)=> a+((S[k]||[])[t]||0), 0));
  const REV = Object.keys(S).filter(k=>k.startsWith('rev')), OUT = Object.keys(S).filter(k=>k.startsWith('out'));
  const MAND = ['out_ss','out_med','out_mcd','out_incsec','out_othm'].filter(k=>S[k]);
  const DISC = ['out_def','out_ndd'].filter(k=>S[k]);
  function ser(id){
    if(id==='rev') return sum(REV);
    if(id==='out') return sum(OUT);
    if(id==='mand') return sum(MAND);
    if(id==='disc') return sum(DISC);
    if(id==='deficit'){const r=sum(REV),o=sum(OUT);return Y.map((_,t)=>r[t]-o[t]);}
    if(id==='primary'){const d=ser('deficit');return Y.map((_,t)=>d[t]+(S['out_int']||[])[t]);}
    return S[id]||Y.map(()=>null);
  }
  const ROWS = [
    {id:'rev',l:'收入 Revenues',lv:0,par:null},
    {id:'rev_ind',l:'个人所得税',lv:1,par:'rev'},{id:'rev_pay',l:'Payroll税',lv:1,par:'rev'},
    {id:'rev_corp',l:'企业所得税',lv:1,par:'rev'},{id:'rev_tariff',l:'关税',lv:1,par:'rev'},
    {id:'rev_other',l:'其他收入',lv:1,par:'rev'},
    {id:'out',l:'支出 Outlays',lv:0,par:null},
    {id:'mand',l:'强制性 Mandatory',lv:1,par:'out'},
    {id:'out_ss',l:'社会保障',lv:2,par:'out'},{id:'out_med',l:'Medicare',lv:2,par:'out'},
    {id:'out_mcd',l:'Medicaid',lv:2,par:'out'},{id:'out_incsec',l:'收入保障',lv:2,par:'out'},
    {id:'out_othm',l:'其他强制性',lv:2,par:'out'},
    {id:'disc',l:'自由裁量 Discretionary',lv:1,par:'out'},
    {id:'out_def',l:'国防',lv:2,par:'out'},{id:'out_ndd',l:'非国防',lv:2,par:'out'},
    {id:'out_int',l:'净利息',lv:1,par:'out'},
    {id:'deficit',l:'赤字 Deficit',lv:0,par:null},{id:'primary',l:'初级赤字 Primary',lv:1,par:null},
  ];
  const FY = ANX.fytd, fmtc=v=>v==null?'—':Math.round(v).toLocaleString();
  function fytdOf(id){
    if(FY[id]) return [FY[id].fytd, FY[id].fytd_prior];
    const kids = {rev:REV,out:OUT,mand:MAND,disc:DISC}[id];
    if(kids){let a=0,b=0,ok=false;kids.forEach(k=>{if(FY[k]){a+=FY[k].fytd;b+=FY[k].fytd_prior;ok=true;}});return ok?[a,b]:[null,null];}
    if(id==='deficit'){const[r,rp]=fytdOf('rev'),[o,op]=fytdOf('out');return [r-o,rp-op];}
    if(id==='primary'){const[d,dp]=fytdOf('deficit');return FY['out_int']?[d+FY['out_int'].fytd,dp+FY['out_int'].fytd_prior]:[null,null];}
    return [null,null];
  }
  function spark(id){
    const s=ser(id), yy=[];
    for(let t=N-5;t<N;t++){ if(s[t]!=null&&s[t-1]) yy.push({fy:Y[t],v:100*(s[t]/s[t-1]-1)}); }
    if(yy.length<2) return '';
    const vs=yy.map(p=>p.v), mn=Math.min(...vs,0), mx=Math.max(...vs,0), rg=(mx-mn)||1;
    const XY=yy.map((p,i)=>[6+i*(56/(yy.length-1)), 18-3-(p.v-mn)/rg*12]);
    const zy=18-3-(0-mn)/rg*12;
    const col=vs[vs.length-1]>=0?'#0E5A45':'#B03A2E';
    let g=`<svg width="70" height="20" style="vertical-align:middle;display:block;margin:0 auto">`
      +`<line x1="6" y1="${zy}" x2="62" y2="${zy}" stroke="#E2E6E2"/>`
      +`<polyline points="${XY.map(p=>p.join(',')).join(' ')}" fill="none" stroke="${col}" stroke-width="1.4"/>`;
    XY.forEach((p,i)=>{ g+=`<circle cx="${p[0]}" cy="${p[1]}" r="2" fill="${col}"><title>FY${String(yy[i].fy).slice(2)}: ${yy[i].v>=0?'+':''}${yy[i].v.toFixed(1)}%</title></circle>`; });
    return g+'</svg>';
  }
  let SEL=null;
  function drawT(){
    const [revT]=fytdOf('rev'),[outT]=fytdOf('out');
    let h=`<table class="anx"><tr><th class="c-lbl">科目 (bn · FYTD至${ANX.as_of||'—'})</th><th class="c-spk">5年yoy走势</th><th class="num">FYTD</th><th class="num">去年同期</th><th class="num">yoy</th><th class="num">占比</th></tr>`;
    ROWS.forEach(r=>{
      const [a,b]=fytdOf(r.id);
      const yoy=(a!=null&&b)?100*(a/b-1):null;
      const base=r.id.startsWith('rev')&&r.lv>0?revT:(r.par==='out'?outT:null);
      const share=(a!=null&&base)?(100*a/base).toFixed(0)+'%':'—';
      h+=`<tr class="clickable l${r.lv}${SEL===r.id?' sel':''}" data-id="${r.id}">`
        +`<td class="lbl c-lbl" style="padding-left:${8+r.lv*16}px">${r.l}</td><td class="c-spk">${spark(r.id)}</td>`
        +`<td class="num">${fmtc(a)}</td><td class="num">${fmtc(b)}</td>`
        +`<td class="num ${yoy>=0?'pos':'neg'}">${yoy==null?'—':yoy.toFixed(1)+'%'}</td><td class="num">${share}</td></tr>`;
    });
    document.getElementById('anxTable').innerHTML=h+'</table>';
    document.querySelectorAll('#anxTable tr.clickable').forEach(tr=>tr.onclick=()=>{
      SEL=(SEL===tr.dataset.id)?null:tr.dataset.id; drawT(); drawC();
    });
  }
  let CH2=null;
  const pct=id=>ser(id).map((v,t)=>v!=null&&G[t]?100*v/G[t]:null);
  function drawC(){
    let ds,title;
    const lbls=Y.map(y=>'FY'+String(y).slice(2));
    if(!SEL){
      title='收/支/赤 绝对额(左) 与 /NGDP(右)';
      ds=[
        {label:'收入',data:ser('rev'),borderColor:PAL.green,borderWidth:2,yAxisID:'y'},
        {label:'支出',data:ser('out'),borderColor:PAL.red,borderWidth:2,yAxisID:'y'},
        {label:'赤字',data:ser('deficit'),borderColor:PAL.ink,borderWidth:2,yAxisID:'y'},
        {label:'收入/NGDP',data:pct('rev'),borderColor:PAL.green+'66',borderDash:[5,4],borderWidth:1.3,yAxisID:'y2'},
        {label:'支出/NGDP',data:pct('out'),borderColor:PAL.red+'66',borderDash:[5,4],borderWidth:1.3,yAxisID:'y2'},
        {label:'赤字/NGDP',data:pct('deficit'),borderColor:PAL.ink+'66',borderDash:[5,4],borderWidth:1.3,yAxisID:'y2'}];
    } else {
      const r=ROWS.find(x=>x.id===SEL); title=r.l+' · 绝对额(左)与/NGDP(右)';
      ds=[{label:r.l,data:ser(SEL),borderColor:PAL.red,borderWidth:2.2,yAxisID:'y'},
          {label:'/NGDP %',data:pct(SEL),borderColor:PAL.blue,borderDash:[5,4],borderWidth:1.6,yAxisID:'y2'}];
    }
    ds.forEach(d=>{d.pointRadius=0;d.tension=.15;});
    if(CH2) CH2.destroy();
    CH2=new Chart(document.getElementById('ch_annual'),{type:'line',
      data:{labels:lbls,datasets:ds},
      options:{maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
        plugins:{title:{display:true,text:title,font:{size:12}}},
        scales:{y:{grid:{color:'#EDEFEA'},ticks:{callback:v=>Math.abs(v)>=1000?Math.round(v/1000)+'T':v},afterFit:a=>{a.width=60}},
                y2:{position:'right',grid:{display:false},ticks:{callback:v=>v.toFixed(1)+'%'},afterFit:a=>{a.width=52}},
                x:{grid:{display:false}}}}});
  }
  drawT(); drawC();
})();
}

// ---- CBO基线矩阵 (图+表联动, Δ可编辑)
const MX = __CBOMATRIX__;
if(MX && document.getElementById('blxTable')){
(function(){
  const YRS = MX.years, N = YRS.length;
  const VCUR = MX.versions[MX.versions.length-1].id, VPRV = MX.versions[0].id;
  const LS = 'fm_blx_adj_v1';
  let adj; try{ adj = JSON.parse(localStorage.getItem(LS)) || {}; }catch(e){ adj = {}; }
  adj.rev = adj.rev || Array(N).fill(0); adj.out = adj.out || Array(N).fill(0);
  const st = {view:'cur', sel:'deficit'};
  const D = MX.data;
  const leaf = (v,id)=> D[v][id] || Array(N).fill(null);
  function series(v, id, withAdj){
    const revIds = MX.items.filter(i=>i.id.startsWith('rev_')).map(i=>i.id);
    const outIds = MX.items.filter(i=>i.id.startsWith('out_')).map(i=>i.id);
    const rev = YRS.map((_,t)=> revIds.reduce((a,k)=>a+leaf(v,k)[t],0) + (withAdj?adj.rev[t]:0));
    const out = YRS.map((_,t)=> outIds.reduce((a,k)=>a+leaf(v,k)[t],0) + (withAdj?adj.out[t]:0));
    const def = YRS.map((_,t)=> rev[t]-out[t]);
    if(id==='rev') return rev;
    if(id==='out') return out;
    if(id==='deficit') return def;
    if(id==='primary') return YRS.map((_,t)=> def[t]+leaf(v,'out_int')[t]);
    if(id==='debt_public'){
      if(!withAdj) return leaf(v,'debt_public');
      const base = leaf(v,'debt_public');
      const def0 = series(v,'deficit',false);
      let cum=0; return YRS.map((_,t)=>{cum+=def0[t]-def[t]; return base[t]+cum;});
    }
    if(id==='adj_rev') return adj.rev.slice();
    if(id==='adj_out') return adj.out.slice();
    return leaf(v,id);
  }
  const fmtc = v=> v==null?'':Math.round(v).toLocaleString();
  function cellVal(item, t){
    const id=item.id;
    if(st.view==='cur')  return fmtc(series(VCUR,id,true)[t]);
    if(st.view==='prev') return fmtc(series(VPRV,id,false)[t]);
    if(st.view==='diff') return fmtc(series(VCUR,id,false)[t]-series(VPRV,id,false)[t]);
    if(st.view==='pct'){ const g=leaf(VCUR,'ngdp')[t];
      const x=series(VCUR,id,true)[t]; return id==='ngdp'?fmtc(x):(100*x/g).toFixed(1)+'%';}
  }
  const VIEWS_BLX = [['cur','现行基线(含Δ)'],['prev','上一版'],['diff','差异'],['pct','%GDP']];
  function drawBar(){
    document.getElementById('blxViews').innerHTML = VIEWS_BLX.map(([k,l])=>
      `<span class="chip${st.view===k?' on':''}" data-g="v${k}" data-v="${k}">${l}</span>`).join('');
    document.querySelectorAll('#blxViews .chip').forEach(c=>c.onclick=()=>{st.view=c.dataset.v; drawBar(); drawTbl();});
  }
  function drawTbl(){
    let h='<table><tr><th style="text-align:left">科目 (USD bn)</th>'+YRS.map(y=>`<th class="num">FY${String(y).slice(2)}</th>`).join('')+'</tr>';
    MX.items.forEach(it=>{
      const editable = it.id.startsWith('adj_');
      const cls = `l${it.lv}${it.memo?'':' clickable'}${st.sel===it.id?' sel':''}`;
      h += `<tr class="${cls}" data-id="${it.id}"><td class="lbl" style="padding-left:${8+it.lv*16}px">${it.label}</td>`;
      for(let t=0;t<N;t++){
        if(editable){
          const arr = it.id==='adj_rev'?adj.rev:adj.out;
          h += `<td><input data-k="${it.id}" data-t="${t}" value="${arr[t]||0}"></td>`;
        } else h += `<td>${cellVal(it,t)}</td>`;
      }
      h += '</tr>';
    });
    h+='</table>';
    document.getElementById('blxTable').innerHTML=h;
    document.querySelectorAll('#blxTable tr.clickable').forEach(tr=>tr.onclick=e=>{
      if(e.target.tagName==='INPUT') return;
      st.sel=tr.dataset.id; drawTbl(); drawChart();
    });
    document.querySelectorAll('#blxTable input').forEach(inp=>inp.onchange=()=>{
      const arr = inp.dataset.k==='adj_rev'?adj.rev:adj.out;
      arr[+inp.dataset.t] = parseFloat(inp.value)||0;
      localStorage.setItem(LS, JSON.stringify(adj));
      drawTbl(); drawChart();
    });
  }
  let CH=null;
  function drawChart(){
    const item = MX.items.find(i=>i.id===st.sel) || MX.items[0];
    const mk = (v,withAdj)=> series(v,item.id,withAdj);
    const hasAdj = adj.rev.some(x=>x)||adj.out.some(x=>x);
    const ds=[
      {label:MX.versions[0].label,data:mk(VPRV,false),borderColor:PAL.muted,borderDash:[4,3],borderWidth:1.3,pointRadius:0},
      {label:MX.versions[MX.versions.length-1].label+(hasAdj?' (含Δ)':''),data:mk(VCUR,true),borderColor:PAL.red,borderWidth:2.2,pointRadius:2},
    ];
    if(hasAdj)
      ds.push({label:'现行·官方原值',data:mk(VCUR,false),borderColor:PAL.red+'55',borderDash:[6,4],borderWidth:1.2,pointRadius:0});
    if(CH) CH.destroy();
    CH = new Chart(document.getElementById('ch_bl_matrix'),{type:'line',
      data:{labels:YRS.map(y=>'FY'+String(y).slice(2)),datasets:ds},
      options:{maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
        plugins:{title:{display:true,text:item.label+' · 10年路径 (USD bn)',font:{size:12}}},
        scales:{y:{grid:{color:'#EDEFEA'}},x:{grid:{display:false}}}}});
  }
  document.getElementById('blxReset').onclick=()=>{
    adj={rev:Array(N).fill(0),out:Array(N).fill(0)};
    localStorage.setItem(LS, JSON.stringify(adj)); drawTbl(); drawChart();
  };
  drawBar(); drawTbl(); drawChart();
})();
}

// ---- 财政日历 (事件数据库视图)
const EVDB = __EVENTS__, ONAMES = __OBJNAMES__;
const GROUPS = ["发行回购","重要文件","立法时间","重要到期日"];
const byDate = {};
EVDB.forEach(e=>{ if(e.status!=='cancelled') (byDate[e.date]=byDate[e.date]||[]).push(e); });
const calState = {ym: new Date(), on: new Set(GROUPS)};
const $ = id=>document.getElementById(id);
const ymTitle = d=>`${d.getFullYear()}.${String(d.getMonth()+1).padStart(2,'0')}`;
const dstr = d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
function drawChips(){
  $('calChips').innerHTML = GROUPS.map(g=>
    `<span class="chip${calState.on.has(g)?' on':''}" data-g="${g}">${g}</span>`).join('');
  $('calChips').querySelectorAll('.chip').forEach(c=>c.onclick=()=>{
    const g=c.dataset.g;
    calState.on.has(g)?calState.on.delete(g):calState.on.add(g);
    drawChips(); drawCal();
  });
}
function drawCal(){
  const y=calState.ym.getFullYear(), m=calState.ym.getMonth();
  $('calTitle').textContent = ymTitle(calState.ym);
  $('calHead').innerHTML = ['一','二','三','四','五','六','日'].map(w=>`<div>${w}</div>`).join('');
  const first=new Date(y,m,1), start=new Date(first);
  start.setDate(1-((first.getDay()+6)%7));
  const todayS=dstr(new Date());
  let html='';
  for(let i=0;i<42;i++){
    const d=new Date(start); d.setDate(start.getDate()+i);
    const ds=dstr(d), dim=d.getMonth()!==m, wknd=d.getDay()===0||d.getDay()===6;
    const evs=(byDate[ds]||[]).filter(e=>calState.on.has(e.group||'重要文件'));
    let pills=evs.slice(0,3).map(e=>
      `<div class="pill g-${e.group}${e.status==='occurred'?' done':''}" title="${e.label}">${e.label}</div>`).join('');
    if(evs.length>3) pills+=`<div class="pill more">+${evs.length-3}</div>`;
    html+=`<div class="day${dim?' dim':''}${wknd?' wknd':''}${ds===todayS?' today':''}" data-d="${ds}">
<div class="dn">${d.getDate()}</div>${pills}</div>`;
    if(i===41 && d.getMonth()===m) {} 
  }
  $('calGrid').innerHTML=html;
  $('calGrid').querySelectorAll('.day').forEach(el=>el.onclick=()=>drawDetail(el.dataset.d));
}
function drawDetail(ds){
  const evs=(byDate[ds]||[]).filter(e=>calState.on.has(e.group||'重要文件'));
  if(!evs.length){ $('calDetail').innerHTML=`<span class="hint">${ds} 无事件</span>`; return; }
  $('calDetail').innerHTML = `<b style="font-family:var(--mono)">${ds}</b>` + evs.map(e=>{
    const rev=(e.revisions||[]).length?` · 改期×${e.revisions.length}`:'';
    const est=e.dtype==='估计'?' · 估计值':'';
    return `<div class="dev g-${e.group}">
<div class="l1"><span class="st ${e.status}">${e.status}</span><b>${e.label}</b>
<span style="color:var(--muted);font-size:11.5px">${ONAMES[e.owner]||e.owner||''} · ${e.cat}${est}${rev}</span></div>
${e.result&&e.result.summary?`<div class="res">结果: ${e.result.summary}</div>`:''}
${(e.checklist||[]).length?`<div class="chk">核对: ${e.checklist.join(' / ')}</div>`:''}</div>`;
  }).join('');
}
$('calPrev').onclick=()=>{calState.ym.setMonth(calState.ym.getMonth()-1); drawCal();};
$('calNext').onclick=()=>{calState.ym.setMonth(calState.ym.getMonth()+1); drawCal();};
$('calHome').onclick=()=>{calState.ym=new Date(); drawCal(); drawDetail(dstr(new Date()));};
drawChips(); drawCal(); drawDetail(dstr(new Date()));

document.querySelectorAll('.ltoggle').forEach(btn=>{
  btn.addEventListener('click',()=>{
    const layer=document.getElementById(btn.dataset.layer);
    const hidden=layer.classList.toggle('collapsed');
    layer.querySelectorAll('.work, details.dossier').forEach(el=>{el.style.display=hidden?'none':'';});
    btn.textContent=hidden?'展开工作视图':'收起工作视图';
  });
});
</script></body></html>"""

if __name__ == "__main__":
    main()
