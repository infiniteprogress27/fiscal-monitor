# Fiscal Monitor — US

对象制财政追踪看板。五层(规则与立法/预算/收支/发行/债务管理) × 约18个财政对象,
每对象三档: 状态行 / 工作视图 / 档案。框架法档案并入L1并与对象互链。

## 事件数据库 (data/us/events.jsonl)
永久数据库, 只增不删: scheduled → occurred(自动回填结果) / revised(改期留痕) / cancelled。
规则事件从 HISTORY_EPOCH (events.py, 默认2025-07) 全量展开历史; 拍卖历史由
fetch_auctions_history 深回溯至纪元(weekly)。改纪元日期即可加深数据库。
来源: 管线自动(拍卖/回购+结果回填) / 节奏规则(MTS/MBR/MSPD/TIC/QRA/PB/MSR/税期) /
立法与人工(events_seed.yaml, 估计值带标记与修正历史)。

## 日历更新规则 (账本各类事件的维护节奏)
| 类别 | 前瞻来源 | 更新节奏 | 结果回填 |
|---|---|---|---|
| 发行 | 暂定=规则推算(Treasury节奏模式, dtype估); 公告=upcoming_auctions | 暂定日滚+公告daily拉取, 公告落地自动作废±3天内同term暂定 | intraday拍卖日 |
| 回购 | config/buyback_schedule.yaml (QRA随发的schedule表) | 每季Refunding Statement后录入一次(对话/手动) | intraday |
| 文件 | scripts/events.py RULES (MTS/MBR/MSPD/TIC/QRA/PB/MSR/税期) | daily滚动120天, weekly从纪元全量 | daily(MTS/MBR挂赤字) |
| 立法/到期日 | config/events_seed.yaml | 每周核对更新(对话/手动), 估计值改期自动留痕 | — |
页面日历底栏显示账本最近维护时间与本表摘要。

## 财政日历 (页面组件)
月历网格视图: 四类分组过滤(发行回购/重要文件/立法时间/重要到期日, chips开关),
月份双向翻页回溯历史, 点击日期出明细面板(状态/结果/核对清单/改期记录/归属对象)。
已发生事件灰显并带结果, 今日高亮。时钟条保留为日扫入口。

## 三层调度 (.github/workflows/update.yml, 单workflow多cron路由)
| 模式 | 时点(UTC) | 动作 |
|---|---|---|
| daily | 22:30 周二至六 | 日度源(DTS/TGA/债务/债限/日历) + 账本到期检查→按需拉月度文件(MTS日自动带出MTS/分科目/利率/利息) |
| intraday | 17:45 & 21:00 工作日 | 仅拍卖/回购日生效: 拉结果+回填; 无市场事件秒退、零commit |
| weekly | 周一 12:00 | MSPD/慢频 + 账本窗口前滚120天 |
无变化不产生commit; concurrency防重叠。

## 更新总纲 (顶层要求, 适用L1-L5全部内容)
1. **定量**: 全自动 (三层cron + 事件账本到期检查)
2. **定性**: 触发自动化 — 内容由人写, 但"该更新了"由机器发现:
   - 立法监听: 对象挂bills锚(119-hr-7567格式), daily拉Congress.gov latestAction,
     变化→入账本+变化流水+对象"有未消化更新"标记
   - 页面监听: 对象挂watch_pages(302(b)/Apportionment库), weekly哈希比对,
     变化或不可达均为信号
3. **鲜度自监督**: 对象带verified日期, 超45天状态行自动亮"内容N天未核";
   监听命中晚于verified则亮"有未消化更新", 更新yaml并推进verified即消化
监听需CONGRESS_API_KEY: 仓库Settings→Secrets→Actions新建, key不入库不入代码。

## 部署
1. 新建public仓库, push本目录全部内容
2. Settings → Secrets and variables → Actions → New repository secret: `CONGRESS_API_KEY`
3. Settings → Pages → Source: Deploy from a branch → main, /docs
4. Actions → update-dashboard → Run workflow, 先 mode=daily 跑一次, 再 mode=weekly 跑一次
5. 首跑校验: 页面上仍挂SAMPLE或空白的模块 + data/us/_debug_*.json(会随commit出现在仓库里),
   把debug文件内容发回对话, 一次性校正字段映射后重跑即常态化

## 维护通道
- 定量: 全自动
- 定性: config/objects_us.yaml (对象状态/base case/机制/人工锚)
- 事件: config/events_seed.yaml (立法/人工节点) — 其余自动
- 空置接口: tail(BBG) / TIC与Fed数据(due:tic槽位已留) / MSPD品种结构(首跑校验) / QRA文件包(定性通道)
