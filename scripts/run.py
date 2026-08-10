#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run.py — 单一入口调度器
  --mode sample    示例数据 + 账本初始化 + 构建 (离线开发)
  --mode daily     日度源 + 账本到期检查按需抓取 + 滚动展开 + 回填 + 构建
  --mode intraday  拍卖/回购日快线: 无市场事件则秒退不提交
  --mode weekly    慢频源 + 账本窗口前滚 + 构建
效率约定: 每次跑只碰该碰的端点; 无变化则workflow不产生commit。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import events as EV
import fetch_us as F
import watchers as W

ROOT = Path(__file__).resolve().parent.parent


def _j(name):
    p = ROOT / "data" / "us" / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def refresh_ledger(rollforward=True, full_history=False, watch_changes=None):
    """账本维护: 规则展开 + 种子合并 + 管线同步 + 监听命中 + 过期回填。幂等, 只增不删。"""
    evs = EV.load()
    for wev in W.changes_to_events(watch_changes or []):
        EV.upsert(evs, wev)
        nev = next(e for e in evs if e["id"] == wev["id"])
        nev["status"], nev["result"] = "occurred", wev["result"]
    if rollforward:
        EV.rollforward(evs, start=EV.HISTORY_EPOCH if full_history else None)
    seed = yaml.safe_load((ROOT / "config/events_seed.yaml").read_text(encoding="utf-8"))
    EV.merge_seed(evs, seed.get("events"))
    EV.gen_tentative_auctions(evs)
    EV.sync_auctions(evs, _j("upcoming"), _j("auctions"), history=_j("auctions_history"))
    EV.supersede_tentative(evs)
    bbs_p = ROOT / "config/buyback_schedule.yaml"
    if bbs_p.exists():
        EV.sync_buyback_schedule(evs, yaml.safe_load(bbs_p.read_text(encoding="utf-8")))
    EV.sync_buybacks(evs, _j("buybacks"))
    EV.backfill(evs, _j("mts"))
    EV.save(evs)
    meta = {"maintained_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
            "counts": {}, "rules": {
                "发行": "暂定=规则推算(日滚), 公告覆盖(daily), 结果回填(intraday)",
                "回购": "计划表=每QRA后更新(buyback_schedule.yaml), 结果回填(intraday)",
                "文件": "节奏规则自动展开(daily滚动/weekly全量)",
                "立法/到期日": "events_seed.yaml, 每周核对(weekly提醒)"}}
    from collections import Counter
    meta["counts"] = dict(Counter(e["cat"] for e in evs))
    (ROOT / "data/us/ledger_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return evs


def build():
    subprocess.run([sys.executable, str(ROOT / "scripts/build_site.py")], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="daily",
                    choices=["sample", "daily", "intraday", "weekly"])
    mode = ap.parse_args().mode

    cfg = yaml.safe_load((ROOT / "config/objects_us.yaml").read_text(encoding="utf-8"))

    if mode == "sample":
        F.write_sample()
        refresh_ledger(full_history=True, watch_changes=W.sample_demo())
        build()
        return

    if mode == "intraday":
        todays = EV.market_events_today(EV.load())
        if not todays:
            print("intraday: 今日无发行/回购事件, 跳过")
            return
        print(f"intraday: 今日{len(todays)}个市场事件, 拉取结果")
        F.run_group(["intraday"])
        refresh_ledger(rollforward=False)
        build()
        return

    if mode == "daily":
        due = EV.due_groups(EV.load())
        groups = ["daily"] + [f"due:{g}" for g in sorted(due)]
        if due:
            print(f"daily: 到期文件组 {sorted(due)}")
        F.run_group(groups)
        refresh_ledger(watch_changes=W.watch_legislation(cfg))
        build()
        return

    if mode == "weekly":
        F.run_group(["weekly"])
        refresh_ledger(full_history=True,
                       watch_changes=W.watch_legislation(cfg) + W.watch_pages(cfg))
        build()


if __name__ == "__main__":
    main()
