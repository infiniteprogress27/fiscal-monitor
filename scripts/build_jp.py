"""日本站构建: 复用美国站引擎(图表/表格/卡片/模板/日历JS), 换数据目录·注册表·视图 → docs/jp/index.html"""
import json, sys
from pathlib import Path
from datetime import datetime, timedelta
import yaml
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_site as bs

ROOT = bs.ROOT
bs.DATA = ROOT / "data" / "jp"
esc, fmt, table, chart, qual_card = bs.esc, bs.fmt, bs.table, bs.chart, bs.qual_card
TODAY = bs.TODAY


def J(name):
    p = bs.DATA / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _note(t): return f'<div class="anchor-note">{t}</div>'


# ------------------------------------------------------------------ L1
def v_deficit_authority(obj, ctx):
    ip = ctx.get("issuance_plan") or {}
    b = ctx.get("budget_jp") or {}
    rows = [(k, fmt(v, 1)) for k, v in b.get("revenue", []) if "国债" in k]
    h = "<h4>发行合法性依据 · 按法律依据分类(FY2026当初, ¥T)</h4>"
    h += table(["依据", "#金额"], [("建设国债(财政法第4条)", fmt(6.7, 1)), ("特例国债(特例国债法授权)", fmt(22.9, 1)),
                                  ("再融资国债(国债整理基金特别会计法)", fmt(130.0, 1)), ("财投债(财政融资资金法)", fmt(13.0, 1)),
                                  ("GX经济转型债 / 儿童特例债 / 复兴债", "1.8 / 0.3 / 0.1")])
    h += table(["约束", "现行状态", "下一节点"], [
        ("特例国债法(赤字国债授权)", "5年延长案(FY2026-2030)2026年3月国会审议 · 成立待核", "FY2030到期 → 2031年3月前需再立法"),
        ("60年偿还规则", "维持; 2025年起债务偿还费与规则脱钩之议题被政治化", "预算编成期(12月)"),
        ("提前发行债限额", "FY2026 ¥50T", "每年度发行计划"),
    ])
    return h + _note("日本无法定债务上限; 功能对应物是'发行必须有法律依据'——特例国债法的授权期限是最接近美国债限的硬节点") + qual_card(obj["qual"])


def v_spending_rules(obj, ctx):
    ml = ctx.get("mlt_projection") or {}
    mac = ctx.get("macro_jp") or {}
    h = table(["规则", "内容", "性质"], [
        ("基本财政收支目标", "中央+地方PB黑字化: 2025-26年度目标 → 经济财政新生计划(2025-2030)期内稳定实现", "软目标(骨太方针)"),
        ("债务/GDP", "公债等残高/GDP安定地下降", "软目标"),
        ("社会保障自然增目安", "高龄化相当增(约+0.4-¥0.5T/年)以内", "预算编成目安"),
        ("非社保支出目安", "+¥0.33T/年 → 2025骨太起弹性化", "预算编成目安"),
        ("概算请求基准", "8月末各省概算请求上限; 要望枠¥4T", "行政规则"),
        ("防卫", "5年¥43T(FY2023-27), GDP2%达成FY2027", "计划约束"),
    ])
    pb = mac.get("pb_gdp") or {}
    if pb:
        ys = sorted(pb)[-15:]
        h += chart("ch_pb_jp", "line", ys, [{"label": "一般政府基本财政收支/GDP %", "data": [pb[y] for y in ys], "color": "red", "w": 2}], "%",
                   opts={"h": 260})
    return h + _note("美国的支出约束是硬上限(caps/PAYGO/ICA), 日本是'目安'——如实标注软硬之别, 达成度按年度追踪") + qual_card(obj["qual"])


def v_tax_legislation_jp(obj, ctx):
    return table(["议题", "状态", "赤字影响", "节点"], [
        ("消费税(食品零税率/减税之议)", "在野党主张; 高市政权未纳入FY2026", "食品零税率约-¥5T/年", "2026秋临时国会 / 年末税制改正"),
        ("所得税'壁'(基础控除等提高至160万円)", "FY2025税改成法, FY2026全年生效", "约-¥1.2T/年", "已生效"),
        ("防卫财源(防卫特别法人税·所得税附加·烟税)", "防卫特别法人税FY2026起(法人税额4%); 所得税附加时点待定", "+¥1T级/年", "年末税制改正"),
        ("儿童·育儿支援金", "FY2026起征收(医保附加), FY2028满额¥1T", "+0.6→¥1.0T", "已生效"),
        ("给付附带税额抵免", "国民民主/立宪主张, 政府检讨", "待定", "2026年末税改"),
        ("汽油税暂定税率废止", "2025年末决定废止", "-¥1.5T/年(国+地方)", "已生效"),
    ]) + qual_card(obj["qual"])


# ------------------------------------------------------------------ L2
def v_mlt_matrix(obj, ctx):
    ml = ctx.get("mlt_projection") or {}
    yrs = [str(y) for y in ml.get("years", [])]
    if not yrs: return _note("中长期测算待录入") + qual_card(obj["qual"])
    D = ml["data"]; vs = ml["versions"]
    cur = vs[-1]["id"]; prev = vs[0]["id"] if len(vs) > 1 else None
    h = chart("ch_mlt_pb", "line", yrs,
              [{"label": f"PB/GDP 成长实现({vs[-1]['name']})", "data": D[cur]["pb_growth"], "color": "green", "w": 2},
               {"label": f"PB/GDP 基线({vs[-1]['name']})", "data": D[cur]["pb_base"], "color": "red", "w": 2},
               {"label": f"成长实现({vs[0]['name']})", "data": D[prev]["pb_growth"] if prev else [], "color": "green", "alpha": "66", "dash": [5, 4], "w": 1.2},
               {"label": f"基线({vs[0]['name']})", "data": D[prev]["pb_base"] if prev else [], "color": "red", "alpha": "66", "dash": [5, 4], "w": 1.2}],
              "%", opts={"h": 300})
    rows = []
    for k, lab in (("pb_growth", "PB/GDP 成长实现"), ("pb_base", "PB/GDP 基线"), ("debt_growth", "债务/GDP 成长实现"), ("debt_base", "债务/GDP 基线")):
        rows.append((lab,) + tuple(f"{D[cur][k][i]:.1f}" for i in range(len(yrs))))
    h += table(["测算(现行版)"] + [f"#{y}" for y in yrs], rows)
    return h + _note(ml.get("note", "")) + qual_card(obj["qual"])


def v_budget_cycle_jp(obj, ctx):
    b = ctx.get("budget_jp") or {}
    h = table(["阶段", "时点", "FY2027周期状态"], [
        ("概算请求", "8月末", "已提出(8/31) · 总额待核"), ("财务省审查", "9-12月", "进行中"),
        ("政府预算案阁议决定", "12月下旬", "待"), ("通常国会召集·众院审议", "1月下旬-3月初", "待"),
        ("参院审议·成立", "3月末", "待(逾期则暂定预算)"), ("补充预算(秋)", "10-12月", "FY2026补充: 待观察"),
    ])
    if b:
        h += f"<h4>FY{b.get('fy')} 当初预算构成 (¥T) · {esc(b.get('as_of', ''))}</h4>"
        h += table(["岁入", "#¥T", "岁出", "#¥T"],
                   [(r[0], fmt(r[1], 1), o[0], fmt(o[1], 1)) for r, o in zip(b.get("revenue", []) + [("", None)]*2, b.get("outlay", []))])
        h += _note(b.get("note", ""))
    return h + qual_card(obj["qual"])


def v_supplementary(obj, ctx):
    s = ctx.get("supplementary") or {}
    rows = s.get("rows", [])
    h = chart("ch_supp", "pnbar", [f"FY{r['fy']}" for r in rows],
              [{"label": "补充预算规模(¥T)", "data": [r.get("amount") for r in rows], "color": "red"}], "", opts={"h": 240})
    h += table(["财年", "#补充预算(¥T)", "#次数", "#预备费(¥T)"],
               [(f"FY{r['fy']}", fmt(r.get("amount"), 1), r.get("count", ""),
                 fmt(next((x["t"] for x in s.get("reserve", []) if x["fy"] == r["fy"]), None), 1)) for r in rows])
    return h + _note("补充预算+预备费是日本财政扩张的主通道: 当初预算守PB形式, 补充预算承载经济对策; 税收超收→决算剩余金是其常规财源") + qual_card(obj["qual"])


# ------------------------------------------------------------------ L3
def v_tax_progress(obj, ctx):
    t = ctx.get("tax_progress") or {}
    ms = t.get("months", []); fys = t.get("fys", {})
    cols = ["muted", "blue", "green", "ink", "red"]
    ds = []
    for i, (k, v) in enumerate(fys.items()):
        ds.append({"label": k, "data": v + [None]*(len(ms)-len(v)), "color": cols[i % len(cols)],
                   "w": 2.4 if "实绩" in k else 1.4, "dash": [5, 4] if "当初" in k else None})
    h = chart("ch_tax_jp", "line", ms, ds, "", opts={"h": 320})
    h += f"<h4>税种进度 · {esc(t.get('as_of', ''))}</h4>"
    h += table(["税种", "#FY2026当初", "#FY2025决算见込", "#当初/决算"],
               [(r[0], fmt(r[1], 1), fmt(r[2], 1), f"{r[1]/r[2]*100:.0f}%" if r[2] else "—") for r in t.get("by_tax", [])])
    return h + _note(t.get("note", "")) + qual_card(obj["qual"])


def v_treasury_flows(obj, ctx):
    s = (ctx.get("treasury_flows") or {}).get("series") or []
    s = s[-36:]
    h = chart("ch_tf_jp", "line", [r["month"][2:] for r in s],
              [{"label": "受入(收)", "data": [r["receipts"] for r in s], "color": "green", "w": 1.6},
               {"label": "支付(支)", "data": [r["payments"] for r in s], "color": "red", "w": 1.6}], "", opts={"h": 260})
    return h + _note((ctx.get("treasury_flows") or {}).get("note", "")) + qual_card(obj["qual"])


def v_local_jp(obj, ctx):
    l = ctx.get("local_jp") or {}
    yrs = [str(y) for y in l.get("years", [])]; S = l.get("series", {})
    h = chart("ch_local_jp", "line", yrs,
              [{"label": "地方财政计划规模", "data": S.get("plan_total"), "color": "ink", "w": 2},
               {"label": "地方税", "data": S.get("local_tax"), "color": "green", "w": 1.6},
               {"label": "地方交付税(央→地)", "data": S.get("lat"), "color": "blue", "w": 1.6},
               {"label": "国库支出金(央→地)", "data": S.get("grants"), "color": "blue", "alpha": "77", "dash": [5, 4], "w": 1.4},
               {"label": "地方债", "data": S.get("local_bond"), "color": "red", "w": 1.2}], "", opts={"h": 320})
    dep = [round(100*(a+b)/c, 1) for a, b, c in zip(S.get("lat", []), S.get("grants", []), S.get("plan_total", []))]
    h += table(["年度"] + [f"#{y}" for y in yrs], [("央地转移占计划规模 %",) + tuple(f"{v:.1f}" for v in dep)])
    return h + _note(l.get("note", "")) + qual_card(obj["qual"])


# ------------------------------------------------------------------ L4
def v_issuance_plan(obj, ctx):
    ip = ctx.get("issuance_plan") or {}
    h = f"<h4>FY{ip.get('fy')} 国债发行计划 (¥T) · {esc(ip.get('as_of', ''))}</h4>"
    h += table(["项目", "#FY2026当初", "#FY2025当初", "#增减"],
               [(r[0], fmt(r[1], 1), fmt(r[2], 1), f"{r[1]-r[2]:+.1f}") for r in ip.get("table", [])])
    h += "<h4>日历基准市中发行额 · 单次规模 × 年度场次</h4>"
    h += table(["期限", "#单次(¥T)", "#场次/年", "#年度合计"],
               [(r[0], fmt(r[1], 2), r[2], fmt(r[1]*r[2], 1)) for r in ip.get("calendar", [])])
    th = ctx.get("tenor_history") or {}
    ms = th.get("months", []); T = th.get("tenors", {})
    if ms:
        cols = ["ink", "blue", "green", "amber", "red", "#6B4E8C"]
        h += chart("ch_tenor_jp", "line", [m[2:] for m in ms],
                   [{"label": t, "data": T[t], "color": cols[i], "w": 1.5} for i, t in enumerate(["2y", "5y", "10y", "20y", "30y", "40y"]) if t in T],
                   "", opts={"tall": True, "zoom": True})
    return h + _note(ip.get("note", "") + " · 再融资国债占发行总额约3/4: 净供给=新规财源债, 总供给看日历基准") + qual_card(obj["qual"])


def v_boj_view(obj, ctx):
    bp = ctx.get("boj_plan") or {}
    p = bp.get("path", [])
    h = chart("ch_boj_jp", "line", [x[0] for x in p],
              [{"label": "月度长期国债购入预定额(¥T)", "data": [x[1] for x in p], "color": "blue", "w": 2.2}], "", opts={"h": 240})
    mac = ctx.get("macro_jp") or {}
    ba = (mac.get("boj_assets") or [])[-120:]
    if ba:
        h += "<h4>日银总资产 (¥T, 月度)</h4>"
        h += chart("ch_bojassets", "line", [x["month"][2:] for x in ba],
                   [{"label": "BOJ总资产", "data": [x["t_yen"] for x in ba], "color": "ink", "w": 1.6}], "", opts={"h": 240, "zoom": True})
    return h + _note(bp.get("note", "")) + qual_card(obj["qual"])


def v_auctions_jp(obj, ctx):
    a = ctx.get("auctions_jp") or {}
    recs = a.get("records", [])
    past = [r for r in recs if r["date"] <= TODAY.isoformat()][-12:]
    nxt = [r for r in recs if r["date"] > TODAY.isoformat()][:8]
    h = "<h4>近期招标结果</h4>"
    h += table(["日期", "期限", "#规模(¥T)", "#倍数", "#尾差bp"],
               [(r["date"][5:], r["tenor"], fmt(r["size_t"], 2), fmt(r.get("btc"), 2), fmt(r.get("tail_bp"), 1)) for r in reversed(past)])
    h += "<h4>未来招标日程</h4>"
    h += table(["日期", "期限", "#规模(¥T)"], [(r["date"][5:], r["tenor"], fmt(r["size_t"], 2)) for r in nxt])
    return h + _note(a.get("note", "")) + qual_card(obj["qual"])


# ------------------------------------------------------------------ L5
def v_debt_long_jp(obj, ctx):
    d = ctx.get("debt_long_jp") or {}
    yrs = [str(y) for y in d.get("years", [])]
    ratio = [round(100*a/b, 0) if (a and b) else None for a, b in zip(d.get("jgb", []), d.get("ngdp", []))]
    h = chart("ch_debt_jp", "line", yrs,
              [{"label": "普通国债残高(¥T)", "data": d.get("jgb"), "color": "ink", "w": 2},
               {"label": "残高/名目GDP % (右轴)", "data": ratio, "color": "red", "dash": [5, 4], "w": 1.6, "axis": "y2"}],
              "", opts={"tall": True, "zoom": True, "axes": {"y2": {"unit": "%"}}})
    mac = ctx.get("macro_jp") or {}
    dg = mac.get("debt_gdp") or {}
    if dg:
        ys = sorted(dg)[-20:]
        h += "<h4>一般政府总债务/GDP (IMF口径, %)</h4>"
        h += chart("ch_ggdebt_jp", "line", ys, [{"label": "一般政府债务/GDP", "data": [dg[y] for y in ys], "color": "amber", "w": 2}], "%", opts={"h": 220})
    return h + _note(d.get("note", "") + " · 普通国债口径(财务省)与一般政府口径(IMF/SNA)并列, 不跨口径相减") + qual_card(obj["qual"])


def v_holders_jp(obj, ctx):
    hd = ctx.get("holders_jp") or {}
    qs = hd.get("quarters", []); S = hd.get("shares", {})
    cols = ["ink", "blue", "green", "red", "amber", "muted"]
    h = chart("ch_holders_jp", "line", qs,
              [{"label": k, "data": v, "color": cols[i % 6], "w": 2 if k == "日本银行" else 1.4} for i, (k, v) in enumerate(S.items())],
              "%", opts={"tall": True, "zoom": True})
    return h + _note(hd.get("note", "") + " · 日银份额从2013年11%升至2024年53%后进入减持段——供给侧对手方消失是日本国债市场结构变化的主线") + qual_card(obj["qual"])


def v_interest_jp(obj, ctx):
    it = ctx.get("interest_jp") or {}
    yrs = [f"FY{y}" for y in it.get("years", [])]
    h = chart("ch_int_rate_jp", "line", yrs,
              [{"label": "存量加权利率 %", "data": it.get("avg_rate"), "color": "amber", "w": 2},
               {"label": "预算假定利率 %", "data": it.get("assumed_rate"), "color": "blue", "dash": [5, 4], "w": 1.6}], "%", opts={"h": 280})
    h += "<h4>利息支付等 (一般会计国债费内, ¥T)</h4>"
    h += chart("ch_int_jp", "pnbar", yrs, [{"label": "利息支付等", "data": it.get("interest_t"), "color": "red"}], "", opts={"h": 240})
    h += "<h4>平均剩余期限 (年)</h4>"
    h += chart("ch_wam_jp", "line", yrs, [{"label": "普通国债平均剩余期限", "data": it.get("wam_yr"), "color": "ink", "w": 2}], "", opts={"h": 220})
    return h + _note(it.get("note", "") + " · 预算假定利率是日本特有的预算变量: 其与实际10年利率的裂口决定国债费的下年调整方向") + qual_card(obj["qual"])


def v_yields_jp(obj, ctx):
    y = ctx.get("jgb_yields") or {}
    ds = y.get("dates", []); S = y.get("series", {})
    if not ds: return _note("利率数据待首跑") + qual_card(obj["qual"])
    step = max(1, len(ds)//2600)
    idx = list(range(0, len(ds), step))
    lab = [ds[i][2:7] for i in idx]
    cols = {"2y": "green", "5y": "blue", "10y": "ink", "20y": "amber", "30y": "red", "40y": "#6B4E8C"}
    h = chart("ch_jgb", "line", lab,
              [{"label": f"JGB {k}", "data": [S[k][i] for i in idx], "color": c, "w": 2 if k == "10y" else 1.2}
               for k, c in cols.items() if k in S], "%", opts={"tall": True, "zoom": True})
    last = {k: S[k][-1] for k in S if S[k] and S[k][-1] is not None}
    h += table(["期限"] + [f"#{k}" for k in last], [("最新 %",) + tuple(f"{v:.3f}" for v in last.values())])
    return h + _note(f"财务省国债金利情报日频 · 最新 {ds[-1]} · {'示例' if y.get('sample') else '真实'} · 滚轮缩放双击复位") + qual_card(obj["qual"])


VIEWS_JP = {"deficit_authority": v_deficit_authority, "spending_rules": v_spending_rules,
            "tax_legislation_jp": v_tax_legislation_jp, "mlt_matrix": v_mlt_matrix,
            "budget_cycle_jp": v_budget_cycle_jp, "supplementary": v_supplementary,
            "tax_progress": v_tax_progress, "treasury_flows": v_treasury_flows, "local_jp": v_local_jp,
            "issuance_plan": v_issuance_plan, "boj_view": v_boj_view, "auctions_jp": v_auctions_jp,
            "debt_long_jp": v_debt_long_jp, "holders_jp": v_holders_jp, "interest_jp": v_interest_jp,
            "yields_jp": v_yields_jp}


def main():
    bs.VIEWS.update(VIEWS_JP)
    bs.CHARTS.clear()
    cfg = yaml.safe_load((ROOT / "config/objects_jp.yaml").read_text(encoding="utf-8"))
    ctx = {"anchors": cfg.get("anchors", {})}
    for p in sorted(bs.DATA.glob("*.json")):
        if not p.name.startswith("_"): ctx[p.stem] = J(p.stem)
    bs.EVENTS = bs.load_events()
    bs.OBJ_NAMES = {o["id"]: o["name"] for l in cfg["layers"] for o in l["objects"]}
    bs.LAWS = cfg.get("framework_laws", [])
    bs.WATCH = {}
    laws_rows = [(esc(l["name"]), l["note"], l["status"], l.get("last_change", "—")) for l in bs.LAWS]
    ctx["laws_html"] = f'<details class="dossier" open><summary>框架法档案</summary>{table(["法律", "要点", "现行状态", "最近变化"], laws_rows)}</details>'
    layers_html = ""
    for layer in cfg["layers"]:
        objs = "".join(bs.render_object(o, ctx) for o in layer["objects"])
        layers_html += f'''
<div class="layer" id="{layer['id']}">
  <div class="lhead"><h2>{layer['id']} · {esc(layer['name'])}</h2>
  <button class="ltoggle" data-layer="{layer['id']}">收起工作视图</button></div>
  {objs}
</div>'''
    lo7 = (TODAY - timedelta(days=7)).isoformat()
    feed = [e for e in bs.EVENTS if lo7 <= e["date"] <= TODAY.isoformat() and e["status"] == "occurred"]
    feed = sorted(feed, key=lambda e: e["date"], reverse=True)[:18]
    flux = "".join(f'<div class="fx"><span class="fxd">{e["date"][5:]}</span><span class="fxc c-{e["cat"]}">{e["cat"]}</span>'
                   f'<span>{esc(e["label"])}</span><span class="fxr">{esc((e.get("result") or {}).get("summary", ""))}</span></div>'
                   for e in feed) or '<span class="hint">近7日无入账变化</span>'
    nav = "".join(f'<a href="#{l["id"]}">{l["id"]} {esc(l["name"])}</a>' for l in cfg["layers"])
    page = bs.TEMPLATE
    page = page.replace('<span>/ US 美国</span>', '<span>/ JP 日本</span> <a href="../" style="font-size:12px;margin-left:12px">→ US</a>')
    rep = {"__NAV__": nav, "__FLUX__": flux,
           "__CALRULES__": f"事件账本 · 招标日程为财务省月度计划(估标待公告覆盖) · 生成 {TODAY.isoformat()}",
           "__ANNUAL__": json.dumps({"years": [], "series": {}, "ngdp": [], "fytd": {}}),
           "__LOCAL__": "{}", "__TICS__": "{}", "__FNXDEF__": '{"baseline":[0,0,0]}', "__CBOMATRIX__": "null",
           "__EVENTS__": json.dumps(bs.EVENTS, ensure_ascii=False),
           "__OBJNAMES__": json.dumps(bs.OBJ_NAMES, ensure_ascii=False),
           "__LAYERS__": layers_html,
           "__NOTES__": "".join(f"<li>{esc(n)}</li>" for n in cfg.get("reference", {}).get("pipeline_notes", [])),
           "__META__": f"生成 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} · 对象注册表 {cfg.get('updated')}",
           "__SAMPLE__": "", "__CHARTS__": json.dumps(bs.CHARTS, ensure_ascii=False)}
    for k, v in rep.items(): page = page.replace(k, v)
    (ROOT / "docs/jp").mkdir(parents=True, exist_ok=True)
    (ROOT / "docs/jp/index.html").write_text(page, encoding="utf-8")
    print(f"docs/jp/index.html ({len(page)//1024} KB, {len(bs.CHARTS)} charts)")


if __name__ == "__main__":
    main()
