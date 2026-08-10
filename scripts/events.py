#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
events.py — 事件账本 (data/us/events.jsonl)
一行一事件: {id, date, cat, owner, label, dtype, status, checklist, result, revisions}
  cat:    发行 | 回购 | 文件 | 立法 | 税期 | 政治 | 人工
  dtype:  法定 | 惯例 | 估计 | 自动
  status: scheduled | occurred | revised | cancelled
生命周期: 规则展开/管线同步 → scheduled → 过期回填 occurred(+result) → 永久存档。
"""
import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "data" / "us" / "events.jsonl"
TODAY = date.today()

# 账本为永久数据库: 只增不删。HISTORY_EPOCH为规则事件的历史起点,
# weekly/sample模式从纪元全量展开, daily只滚动近端窗口。
HISTORY_EPOCH = date(2025, 7, 1)

# 展示分组 (日历四色): cat→group默认映射, 种子事件可显式覆盖 group 字段
GROUP_BY_CAT = {"发行": "发行回购", "回购": "发行回购", "文件": "重要文件",
                "立法": "立法时间", "政治": "立法时间",
                "税期": "重要到期日", "人工": "重要到期日"}


# ---------------------------------------------------------------- 日期工具

def nth_business_day(y, m, n):
    d, cnt = date(y, m, 1), 0
    while True:
        if d.weekday() < 5:
            cnt += 1
            if cnt == n:
                return d
        d += timedelta(days=1)


def first_weekday(y, m, wd):
    d = date(y, m, 1)
    return d + timedelta(days=(wd - d.weekday()) % 7)


def next_business_day(d):
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def month_iter(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


# ---------------------------------------------------------------- 节奏规则

@dataclass
class Rule:
    rid: str
    owner: str
    cat: str
    label: str          # {ym}/{m} 可用
    dtype: str
    gen: object         # (y, m) -> date | None
    checklist: list = field(default_factory=list)


RULES = [
    Rule("mbr", "mts_progress", "文件", "CBO MBR ({pm}月号)", "惯例",
         lambda y, m: nth_business_day(y, m, 5),
         ["当月赤字估计入锚", "归因文字段", "有无领先基线修正的表述"]),
    Rule("mts", "mts_progress", "文件", "MTS {pm}月号", "惯例",
         lambda y, m: nth_business_day(y, m, 8),
         ["赤字vs MBR偏差", "累计vs可比带位置", "利息支出科目", "关税科目"]),
    Rule("mspd", "structure_maturity", "文件", "MSPD {pm}月号", "惯例",
         lambda y, m: nth_business_day(y, m, 4),
         ["品种结构变化", "债限对账", "WAM"]),
    Rule("tic", "holders", "文件", "TIC 月度 (滞后6周)", "惯例",
         lambda y, m: next_business_day(date(y, m, 17)),
         ["海外官方/私人分解", "主要国别增减"]),
    Rule("tax", "mts_progress", "税期", "预缴税日", "法定",
         lambda y, m: next_business_day(date(y, m, 15)) if m in (1, 4, 6, 9, 12) else None,
         ["DTS税收存款强度", "对当月收支的影响"]),
    Rule("qra_est", "qra_cycle", "文件", "QRA 融资估计 (QRFE) 15:00 ET", "惯例",
         lambda y, m: first_weekday(y, m, 2) - timedelta(days=2) if m in (2, 5, 8, 11) else None,
         ["三指标vs卖方锚", "TGA目标", "SOMA假设"]),
    Rule("qra_stmt", "qra_cycle", "文件", "QRA Refunding Statement 8:30 ET", "惯例",
         lambda y, m: first_weekday(y, m, 2) if m in (2, 5, 8, 11) else None,
         ["coupon表vs上季", "前瞻指引措辞diff", "buyback envelope", "TBAC专题"]),
    Rule("pb", "budget_cycle", "文件", "总统预算 提交DDL", "法定",
         lambda y, m: first_weekday(y, m, 0) if m == 2 else None,
         ["topline与政策优先级", "Historical Tables更新"]),
    Rule("msr", "budget_cycle", "文件", "Mid-Session Review DDL", "法定",
         lambda y, m: date(y, 7, 15) if m == 7 else None,
         ["赤字重估的立法/经济分解"]),
]


# ---------------------------------------------------------------- 账本IO

def load():
    if not LEDGER.exists():
        return []
    return [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]


def save(evs):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    evs = sorted(evs, key=lambda e: (e["date"], e["cat"], e["id"]))
    LEDGER.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in evs) + "\n",
                      encoding="utf-8")


def upsert(evs, ev):
    """按id合并: 已有事件保留status/result/revisions; 日期变动记入revisions。"""
    by_id = {e["id"]: e for e in evs}
    old = by_id.get(ev["id"])
    if old is None:
        ev.setdefault("status", "scheduled")
        ev.setdefault("result", {})
        ev.setdefault("revisions", [])
        ev.setdefault("group", GROUP_BY_CAT.get(ev["cat"], "重要文件"))
        ev.setdefault("created_at", TODAY.isoformat())
        evs.append(ev)
        return
    if old["status"] == "scheduled" and old["date"] != ev["date"]:
        old["revisions"].append({"from": old["date"], "to": ev["date"],
                                 "at": TODAY.isoformat()})
        old["date"] = ev["date"]
        old["status"] = "revised"
    # label/checklist跟随最新规则, 其余字段不动
    old["label"], old["checklist"] = ev["label"], ev.get("checklist", old.get("checklist", []))


def _slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "-", str(s)).strip("-").lower()[:40]


# ---------------------------------------------------------------- 生成与同步

def rollforward(evs, back=45, ahead=120, start=None):
    """按节奏规则展开。daily: 近端窗口滚动; weekly/sample: start=HISTORY_EPOCH全量补历史。
    upsert幂等, 已有事件的状态与结果不受重复展开影响。"""
    lo = start or (TODAY - timedelta(days=back))
    hi = TODAY + timedelta(days=ahead)
    for rule in RULES:
        for y, m in month_iter(lo, hi):
            d = rule.gen(y, m)
            if d is None or not (lo <= d <= hi):
                continue
            pm = m - 1 or 12
            upsert(evs, {"id": f"{rule.rid}-{y}{m:02d}", "date": d.isoformat(),
                         "cat": rule.cat, "owner": rule.owner, "dtype": rule.dtype,
                         "label": rule.label.format(pm=pm, m=m),
                         "checklist": rule.checklist})


def merge_seed(evs, seed_events):
    """人工/立法事件 (config/events_seed.yaml), 幂等合并。"""
    for ev in seed_events or []:
        upsert(evs, {**ev, "checklist": ev.get("checklist", [])})


def sync_auctions(evs, upcoming, auctions, history=None):
    """history: auctions_history.json (深回溯), 与近端auctions同构。"""
    if history:
        auctions = {"records": (history.get("records") or []) + (auctions.get("records") or [])}
    for r in upcoming.get("records", []):
        if not r.get("auction_date"):
            continue
        upsert(evs, {"id": f"auc-{r['auction_date']}-{_slug(r.get('term'))}",
                     "date": r["auction_date"], "cat": "发行", "owner": "qra_cycle",
                     "dtype": "自动", "term": r.get("term"),
                     "label": f"拍卖 {r.get('term') or ''} {r.get('type') or ''}".strip(),
                     "checklist": ["B/C vs 近5次", "HY vs WI(tail·BBG)", "PD被动接量"]})
    for r in auctions.get("records", []):
        if not r.get("auction_date"):
            continue
        eid = f"auc-{r['auction_date']}-{_slug(r.get('term'))}"
        upsert(evs, {"id": eid, "date": r["auction_date"], "cat": "发行",
                     "owner": "qra_cycle", "dtype": "自动", "term": r.get("term"),
                     "label": f"拍卖 {r.get('term') or ''} {r.get('type') or ''}".strip(),
                     "checklist": []})
        ev = next(e for e in evs if e["id"] == eid)
        ev["status"] = "occurred"
        ev["result"] = {"summary": " · ".join(x for x in [
            f"{r['offering_bn']:.0f}B" if r.get("offering_bn") else None,
            f"HY {r['high_yield']:.3f}" if r.get("high_yield") is not None else None,
            f"B/C {r['btc']:.2f}" if r.get("btc") is not None else None] if x)}


def sync_buybacks(evs, buybacks):
    for r in buybacks.get("records", []):
        if not r.get("op_date"):
            continue
        eid = f"bb-{r['op_date']}-{_slug(r.get('bucket'))}"
        upsert(evs, {"id": eid, "date": r["op_date"], "cat": "回购", "owner": "buyback",
                     "dtype": "自动", "label": f"回购 {r.get('bucket') or ''}", "checklist": []})
        ev = next(e for e in evs if e["id"] == eid)
        if r["op_date"] <= TODAY.isoformat():
            ev["status"] = "occurred"
            ev["result"] = {"summary": " · ".join(x for x in [
                f"接纳 {r['accepted_bn']:.1f}/{r['max_bn']:.1f}B" if r.get("accepted_bn") is not None and r.get("max_bn") else None,
                f"offer/max {r['offer_to_max']:.1f}" if r.get("offer_to_max") is not None else None] if x)}


def backfill(evs, mts):
    """过期scheduled→occurred; MTS/MBR事件回填当月赤字。"""
    bal = {r["month"]: r["balance"] for r in mts.get("series", [])}
    for e in evs:
        if e["date"] >= TODAY.isoformat() or e["status"] in ("occurred", "cancelled"):
            continue
        e["status"] = "occurred"
        if e["id"].split("-")[0] in ("mts", "mbr"):
            y, m = int(e["date"][:4]), int(e["date"][5:7])
            pm = f"{y if m > 1 else y-1}-{(m-1 or 12):02d}"
            if pm in bal:
                e["result"] = {"summary": f"{pm} 月度{'盈余' if bal[pm] > 0 else '赤字'} {abs(bal[pm]):.0f}B"}


def due_groups(evs, lookback=2):
    """近lookback天内到期的文件类事件 → 需按需抓取的组。"""
    lo = (TODAY - timedelta(days=lookback)).isoformat()
    hits = {e["id"].split("-")[0] for e in evs
            if e["cat"] == "文件" and lo <= e["date"] <= TODAY.isoformat()}
    return hits & {"mts", "mspd", "tic", "qra_est", "qra_stmt"}


# ---------------------------------------------------------------- 暂定发行日历
# Treasury发行节奏高度规律(tentative schedule无API), 按规则推算未来窗口, dtype=估计。
# upcoming_auctions公告落地后, 同term±3天内的暂定事件自动作废(cancelled), 实现"公告覆盖暂定"。

def _week_anchor(y, m, contains_day, weekday):
    """包含contains_day的那一周里的指定weekday。"""
    base = date(y, m, contains_day)
    return base + timedelta(days=weekday - base.weekday())


def gen_tentative_auctions(evs, ahead=100):
    lo, hi = TODAY + timedelta(days=1), TODAY + timedelta(days=ahead)
    anchor52 = date(2026, 7, 28)          # 52wk每4周周二, 锚点已知拍卖日
    plans = []                             # (date, term, type)
    d = lo
    while d <= hi:
        wd = d.weekday()
        if wd == 0: plans += [(d, "13-Week", "Bill"), (d, "26-Week", "Bill")]
        if wd == 2: plans += [(d, "17-Week", "Bill")]
        if wd == 3: plans += [(d, "4-Week", "Bill"), (d, "8-Week", "Bill")]
        if wd == 1 and (d - anchor52).days % 28 == 0: plans += [(d, "52-Week", "Bill")]
        d += timedelta(days=1)
    for y, m in month_iter(lo, hi):
        month_plan = [
            (_week_anchor(y, m, 11, 1), "3-Year", "Note"),
            (_week_anchor(y, m, 11, 2), "10-Year", "Note"),
            (_week_anchor(y, m, 11, 3), "30-Year", "Bond"),
            (_week_anchor(y, m, 18, 2), "20-Year", "Bond"),
            (_week_anchor(y, m, 18, 3), "TIPS", "TIPS"),
            (_week_anchor(y, m, 25, 0), "2-Year", "Note"),
            (_week_anchor(y, m, 25, 1), "5-Year", "Note"),
            (_week_anchor(y, m, 25, 2), "7-Year", "Note"),
            (_week_anchor(y, m, 25, 2), "2-Year FRN", "FRN"),
        ]
        plans += [(d, t, ty) for d, t, ty in month_plan if lo <= d <= hi]
    for d, term, ty in plans:
        upsert(evs, {"id": f"tauc-{d.isoformat()}-{_slug(term)}", "date": d.isoformat(),
                     "cat": "发行", "owner": "qra_cycle", "dtype": "估计",
                     "label": f"拍卖(暂定) {term} {ty}", "term": term, "checklist": []})


def supersede_tentative(evs):
    """公告(auc-)覆盖同term±3天内的暂定(tauc-)。"""
    real = [(date.fromisoformat(e["date"]), e["id"].split("-", 2)[-1] if False else e["id"])
            for e in evs if e["id"].startswith("auc-")]
    real_keys = [(date.fromisoformat(e["date"]), _slug(e.get("term") or e["label"]))
                 for e in evs if e["id"].startswith("auc-")]
    for e in evs:
        if not e["id"].startswith("tauc-") or e["status"] == "cancelled":
            continue
        td, tslug = date.fromisoformat(e["date"]), _slug(e.get("term") or "")
        if any(abs((td - rd).days) <= 3 and tslug and tslug in rk
               for rd, rk in real_keys):
            e["status"] = "cancelled"
            e["result"] = {"summary": "已被官方公告覆盖"}


def sync_buyback_schedule(evs, schedule):
    """config/buyback_schedule.yaml → 未来回购事件 (每QRA周三后更新一次)。"""
    for op in (schedule or {}).get("ops", []):
        upsert(evs, {"id": f"bb-{op['date']}-{_slug(op['bucket'])}", "date": str(op["date"]),
                     "cat": "回购", "owner": "buyback", "dtype": op.get("dtype", "惯例"),
                     "label": f"回购 {op['bucket']}" + (f" (上限{op['max_bn']}B)" if op.get("max_bn") else ""),
                     "checklist": ["接纳/上限", "offer-to-max", "所购CUSIP分布"]})


def market_events_today(evs):
    t = TODAY.isoformat()
    return [e for e in evs if e["date"] == t and e["cat"] in ("发行", "回购")
            and e["status"] != "cancelled"]
