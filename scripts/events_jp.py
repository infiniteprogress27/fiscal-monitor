"""日本事件账本: 种子 + 招标日程规则(月度典型日, 估) + 到期推定。"""
import json, sys
from pathlib import Path
from datetime import date, timedelta
import yaml
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "jp"; DATA.mkdir(parents=True, exist_ok=True)
TODAY = date.today()
LEDGER = DATA / "events.jsonl"

def load():
    if not LEDGER.exists(): return []
    return [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]

def upsert(evs, e):
    for i, x in enumerate(evs):
        if x["id"] == e["id"]:
            for k, v in e.items():
                if k not in ("status", "result"): x[k] = v
            return
    e.setdefault("status", "scheduled"); e.setdefault("created_at", TODAY.isoformat()); evs.append(e)

# 典型月度招标节奏(估): 财务省每月末公布次月日程, 公告后覆盖
RULE = [(1, "10年", 2.6), (3, "30年", 0.7), (8, "5年", 2.4), (11, "20年", 0.9), (17, "2年", 2.6), (22, "40年", 0.5), (25, "流动性供给", 0.6)]

def refresh():
    evs = load()
    seed = yaml.safe_load((ROOT / "config/events_seed_jp.yaml").read_text(encoding="utf-8")) or {}
    for e in seed.get("events", []):
        upsert(evs, dict(e))
    d0 = TODAY - timedelta(days=45)
    for k in range(0, 135):
        d = d0 + timedelta(days=k)
        for dom, tenor, size in RULE:
            if d.day == dom and d.weekday() < 5:
                upsert(evs, {"id": f"jpauc-{d.isoformat()}-{tenor}", "date": d.isoformat(), "cat": "发行",
                             "owner": "auctions_jp", "dtype": "估", "label": f"招标 {tenor} {size}兆円", "checklist": []})
    # 招标结果回填
    p = DATA / "auctions_jp.json"
    if p.exists():
        for r in json.loads(p.read_text(encoding="utf-8")).get("records", []):
            if r.get("btc") is not None:
                eid = f"jpauc-{r['date']}-{r['tenor']}"
                upsert(evs, {"id": eid, "date": r["date"], "cat": "发行", "owner": "auctions_jp", "dtype": "自动",
                             "label": f"招标 {r['tenor']} {r['size_t']}兆円", "checklist": []})
                ev = next(x for x in evs if x["id"] == eid)
                ev["status"] = "occurred"; ev["result"] = {"summary": f"倍数 {r['btc']:.2f} · 尾差 {r.get('tail_bp', 0):.1f}bp"}
    for e in evs:
        if e["date"] < TODAY.isoformat() and e["status"] == "scheduled":
            e["status"] = "occurred"
    evs.sort(key=lambda e: e["date"])
    LEDGER.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in evs) + "\n", encoding="utf-8")
    print(f"  jp events: {len(evs)}")

if __name__ == "__main__":
    refresh()
