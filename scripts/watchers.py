#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
watchers.py — 触发自动化层
原则: 定性内容由人写, 但"该更新了"由机器发现。
  watch_legislation — Congress.gov API逐案监听latestAction, 变化→事件账本+对象陈旧标记
  watch_pages       — 关键页面哈希监听(302(b)/Apportionment库等), 变化或不可达→同上
状态: data/us/watch_state.json
  {"bills": {ref: {date, text}}, "pages": {id: {hash, ok}},
   "obj_last_change": {object_id: iso_date}}
API key: 环境变量 CONGRESS_API_KEY (GitHub Secrets, 不入库)。
"""
import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "us" / "watch_state.json"
TODAY = date.today()


def _load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"bills": {}, "pages": {}, "obj_last_change": {}}


def _save_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def _collect(cfg, key):
    out = []
    for layer in cfg["layers"]:
        for obj in layer["objects"]:
            for item in obj.get(key, []) or []:
                out.append((obj["id"], item))
    return out


def watch_legislation(cfg):
    """返回变化列表: [{owner, date, label, summary, ref}]。
    监听锚 = yaml显式bills ∪ 状态表解析出的拨款法案号(自动发现)。"""
    key = os.environ.get("CONGRESS_API_KEY")
    bills = _collect(cfg, "bills")
    ap = ROOT / "data" / "us" / "approps_status.json"
    if ap.exists():
        seen = {b["ref"] for _, b in bills}
        for row in json.loads(ap.read_text(encoding="utf-8")).get("rows", []):
            for ref in row.get("refs", []):
                if ref not in seen:
                    bills.append(("appropriations",
                                  {"ref": ref, "name": f"{row['bill']}拨款案({ref})"}))
                    seen.add(ref)
    if not bills:
        return []
    if not key:
        print("watch_legislation: 无CONGRESS_API_KEY, 跳过 (Secrets中配置后自动启用)")
        return []
    import requests
    st, changes = _load_state(), []
    for owner, b in bills:
        try:
            c, t, n = b["ref"].split("-")
            r = requests.get(f"https://api.congress.gov/v3/bill/{c}/{t}/{n}",
                             params={"api_key": key, "format": "json"}, timeout=30)
            r.raise_for_status()
            bill = r.json().get("bill") or {}
            la = bill.get("latestAction") or {}
            cbos = bill.get("cboCostEstimates") or []
            cbo_latest = max(cbos, key=lambda x: x.get("pubDate", "")) if cbos else None
            cur = {"date": la.get("actionDate"), "text": la.get("text"),
                   "cbo": (cbo_latest or {}).get("pubDate")}
            if not cur["date"]:
                continue
            old = st["bills"].get(b["ref"]) or {}
            if (old.get("date"), old.get("text")) != (cur["date"], cur["text"]):
                st["obj_last_change"][owner] = max(st["obj_last_change"].get(owner, ""), cur["date"])
                changes.append({"owner": owner, "date": cur["date"], "ref": b["ref"],
                                "label": f"{b['name']} 有新动作",
                                "summary": (cur["text"] or "")[:180]})
                print(f"  立法更新: {b['name']} @{cur['date']}")
            if cur["cbo"] and old.get("cbo") != cur["cbo"]:
                changes.append({"owner": "cbo_baseline", "date": cur["cbo"][:10], "ref": b["ref"] + "-cbo",
                                "label": f"{b['name']} 新CBO评分发布",
                                "summary": (cbo_latest or {}).get("title", "")[:140] + " · 数字待录入评分表"})
                print(f"  新评分: {b['name']} @{cur['cbo'][:10]}")
            st["bills"][b["ref"]] = cur
        except Exception as e:
            print(f"  !! {b['ref']} 监听失败: {e}")
    _save_state(st)
    return changes


def watch_pages(cfg):
    """页面哈希监听; 不可达本身作为信号(Apportionment库场景)。"""
    pages = _collect(cfg, "watch_pages")
    if not pages:
        return []
    import requests
    st, changes = _load_state(), []
    for owner, p in pages:
        rec, ok, digest = st["pages"].get(p["id"], {}), True, None
        try:
            r = requests.get(p["url"], timeout=45,
                             headers={"User-Agent": "fiscal-monitor/1.0"})
            r.raise_for_status()
            text = re.sub(r"\s+", " ", re.sub(r"<script.*?</script>", "", r.text, flags=re.S))
            digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        except Exception as e:
            ok = False
            print(f"  !! {p['id']} 不可达: {e}")
        if rec.get("ok", True) and not ok:
            changes.append({"owner": owner, "date": TODAY.isoformat(), "ref": p["id"],
                            "label": f"{p['name']} 不可达", "summary": "页面无法访问, 可用性本身是信号"})
        elif ok and not rec.get("ok", True):
            changes.append({"owner": owner, "date": TODAY.isoformat(), "ref": p["id"],
                            "label": f"{p['name']} 恢复可达", "summary": ""})
        elif ok and rec.get("hash") and rec["hash"] != digest:
            changes.append({"owner": owner, "date": TODAY.isoformat(), "ref": p["id"],
                            "label": f"{p['name']} 内容变化", "summary": "哈希变更, 待人工核对"})
        if changes and changes[-1].get("ref") == p["id"]:
            st["obj_last_change"][owner] = TODAY.isoformat()
        st["pages"][p["id"]] = {"hash": digest or rec.get("hash"), "ok": ok}
    _save_state(st)
    return changes


def changes_to_events(changes, cat_map=None):
    """变化列表→账本事件dict。"""
    evs = []
    for ch in changes:
        evs.append({"id": f"watch-{ch['ref']}-{ch['date']}", "date": ch["date"],
                    "cat": "立法" if "-hr-" in ch["ref"] or "-s-" in ch["ref"]
                           or "hconres" in ch["ref"] else "人工",
                    "owner": ch["owner"], "dtype": "自动", "status": "occurred",
                    "label": ch["label"], "checklist": [],
                    "result": {"summary": ch["summary"]}})
    return evs


def sample_demo():
    """示例: 伪造一条监听命中, 演示变化流水与未消化标记。"""
    st = _load_state()
    st["bills"]["119-hr-8870"] = {"date": "2026-08-04", "text":
        "Placed on the Union Calendar. (sample)"}
    st["obj_last_change"]["mandatory_legislation"] = "2026-08-06"
    _save_state(st)
    return [{"owner": "mandatory_legislation", "date": "2026-08-06", "ref": "119-hr-8870",
             "label": "BUILD America 250(H.R.8870) 有新动作",
             "summary": "Placed on the Union Calendar. (sample演示条目)"}]
