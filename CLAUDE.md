# fiscal-monitor · 交接说明 (给Claude Code)

> 美国与日本财政追踪看板。GitHub Pages: `/fiscal-monitor/`(US) 与 `/fiscal-monitor/jp/`(JP)。
> 2026-08启动, 2026-11-01交接。本文件是全部工作的权威摘要, 改动架构时同步更新本文件。

## 1. 定位与现状

对象制财政看板: 每个财政对象(债务上限、拨款、QRA、持有人结构…)有 状态行 / 工作视图 / 档案 三档。
五层结构 L1规则与立法 → L2预算 → L3收支 → L4发行 → L5债务管理, 加 L0 Timeline(财政日历+近7日变化流水) 与 R参考层。
US站约24个对象、13张图, 28/34数据集真实自动更新。JP站16个对象、15张图, 2/15真实(利率全史、宏观六序列), 其余为核实过的人工锚。
用户sc: 宏观交易员, 要求中文简洁书面语、专业图表、先讨论结构再动手、改视觉必先说明差异。

## 2. 仓库结构

| 路径 | 作用 |
|---|---|
| `scripts/fetch_us.py` | US抓取器全集 + `write_sample()` + `ensure_seeds()`锚播种 (1593行) |
| `scripts/build_site.py` | US渲染引擎: 图表/表格/卡片/模板/日历JS/四个联动组件(blx基线矩阵, anx年度收支, fnx融资预测, lx地方收支, hx国别持有) |
| `scripts/events.py` | US事件账本: 规则事件(MTS/MBR/MSPD/TIC/QRA/税期)+拍卖回购同步+到期推定 |
| `scripts/watchers.py` | 监听器: congress.gov法案latestAction(需CONGRESS_API_KEY)+页面哈希(CRS/CBO被机房封锁→QUIET_BLOCK静默) |
| `scripts/flow_svg.py` | 预算周期通关图固定模板(25节点6泳道), 每财年只给flow_states |
| `scripts/fetch_jp.py` `build_jp.py` `events_jp.py` | JP站: build_jp以模块方式导入build_site复用引擎, 只换数据目录/注册表/视图 |
| `scripts/run.py` | 入口: `--mode daily/intraday/weekly/sample`, 先US后JP, 任一国失败不阻塞另一国 |
| `config/objects_us.yaml` `objects_jp.yaml` | 对象注册表: 层/对象/qual(state·base_case·watch·mechanism)/sources/人工锚/框架法档案 |
| `config/events_seed*.yaml` | 立法与人工事件种子(按id upsert, 状态不被种子覆盖) |
| `config/buyback_schedule.yaml` | 回购计划结构(两计划×期限篮×每场上限×场次), 每QRA后更新 |
| `data/us/` `data/jp/` | 数据集json + `events.jsonl`(只增不删) + `watch_state.json` + `_debug_*`(零命中样本) |
| `docs/index.html` `docs/jp/index.html` | 构建产物, Pages从`/docs`发布, 需`docs/.nojekyll` |

## 3. 运行

| 模式 | cron(UTC) | 内容 |
|---|---|---|
| daily | 22:30 周二至六 | DTS/TGA/债务/债限/拍卖日历/监听器/账本; JP: 利率 |
| intraday | 17:45与21:00 工作日 | 仅拍卖/回购日生效, 结果回填 |
| weekly | 12:00 周一 | 慢频全量: MSPD/供给/coupon深抓/TIC/SOMA/债务长史/市场日频/MTS套件bootstrap/annual/地方/总发行/SIFMA尝试/JP宏观+TIC历史 |
| sample | 手动 | 全样例数据, 本地开发用 |

本地: 需Python 3.12+(build_site用了3.12的f-string写法)。`python scripts/run.py --mode sample` 自动复制到`.sample/`(不进git)里跑, 页面在`.sample/docs/`, 仓库data/docs不受影响。
构建会在任一模式执行, 改视图后跑daily即可看到页面变化(不需要weekly)。

分工: 本地=开发与预览, Actions=唯一数据生产者。
1. 本地只提交代码/配置/人工锚; data/与docs/只由fiscal-bot写入。守门hook `scripts/hooks/pre-commit`(新克隆需 `git config core.hooksPath scripts/hooks`), 人工锚白名单写在hook里。
2. 流程: 改 → sample预览 → `git pull --rebase` → push → `gh workflow run update-dashboard -f mode=daily` → `gh run watch` 看真实数据结果。
3. bot每天往main提交, push前必须先rebase。
Actions日志的下载重定向到对象存储域名, 容器内不可读, 用`data/*/_debug_*`文件取证。

## 4. 数据流与机制

1. fetch → `data/<country>/<name>.json`(每文件带`sample`与`fetched_at`) → build读全部json进ctx → 视图渲染 → 页面。
2. 事件账本: scheduled→occurred(到期推定/结果回填)/revised/cancelled, 永久库。规则事件从HISTORY_EPOCH(2025-07)展开。
3. 监听器: 法案动作变化入流水并给对象挂"有未消化更新"徽章(监听命中晚于对象verified日期)。
4. 定性层(qual文字)只靠对话消化更新, 这是设计使然。审计固定三段: 管线鲜度 → 逐对象事实核查(含预算周期节点状态) → 全量verified日期推到当天。
5. L1三对象(立法/债务限制/支出限制)在构建期由原七对象合并(build_site main里的L1G), yaml保持原对象, 旧owner有别名映射。

## 5. 数据集成色

US真实自动(31): MTS表1(96月)与分科目(表4收入/表9支出)、年度分科目(FY2025赤字=官方-1775B)、DTS/TGA/债限(组件透视)/债限史(DTS精确+DTP近似)、债务长史+NGDP、MSPD结构(含表3到期墙)、WAM(2001+由MSPD表3逐券计算, 之前为TBAC节点插值)、供给结构2001+、coupon尺寸2007+(新发/续发分列)、52周bill利率、拍卖与历史、buybacks(`/v1/accounting/od/buybacks_operations`)、SOMA(NY Fed)、TIC国别2000+(mfhhis回填+mfh逐月累积)、利率与利息10年、地方收支五序列(FRED: FGRECPT/FGEXPND/W077RC1Q027SBEA/W079RCQ027SBEA/FGSL)、总发行(全口径+coupon口径)、市场日频(SPX=FRED拼接, 10Y=FRED)、拨款12法案进度(congress.gov API, 2026-11起替代被封的CRS表)、投资者类别配售(财政部IC-Coupons.xls, 2009-10+)。
US锚/样例(3): qra_history, cbo_matrix(2月版, CBO封机房), corp_issuance(SIFMA xls需填表无法自动; 统计页YTD差分自2026-10起逐月累积真实值, 2025-09~2026-09已由固收汇总xls回填; 更早月份仍是旧锚(年度合计与SIFMA偏差-24%~+79%), 待公司债专表xls经apply_corp_xlsx回填)。
JP真实(2): jgb_yields(财务省CSV 1974+, 英文站历史文件+当月文件累积), macro_jp(FRED JPNNGDP/JPNASSETS/IRLTLT01JPM156N + IMF WEO债务/收支/PB)。
JP锚(13): 预算构成、补充预算史、中长期测算、发行计划、期限史、税收进度、国库收支、地方、债务长史、持有者、利息、日银减购、招标。

## 6. 工程纪律 (每条都是踩坑后立的规矩)

1. 零命中保旧: 抓取解析为空时不写文件, 落`_debug_<name>.json`(前20-40条原始记录), 下轮据样本校正字段。
2. 视图级降级: `render_object`包住视图调用, 单视图异常只出降级卡片, 不阻塞整页。`status_metric`同样包住。
3. 补丁必断言: 对源码做字符串替换必须`assert old in src`, 多处改动最后一次性写入(原子)。没有断言的"patched"是假阳性, 已多次翻车。
4. 新数据集必播种: 新增数据集若无真实抓取路径, 必须进`ensure_seeds`/`SEEDS`, 否则生产端文件不存在、模块空白。
5. 首跑校验循环: 远程字段只能猜 → 部署 → 读debug → 修 → 重跑。字段校准结论写进代码注释, 勿再猜。
6. 限流: FiscalData无key限流, api_get三次退避重试, weekly轻请求前置、annual(25页×2表)殿后; 月度分科目由annual一次拉取顺手产出, 不单独调用。
7. 图表要求: tall+滚轮缩放双击复位, 轴宽固定(y64/右58), 单位精确, 对数/双轴/长尺度, %轴两位小数。改动会改变已有图表视觉的, 先说明差异再动手。
8. 数据口径注: 不跨源相减(NIPA/QTAX/Census三口径, 财务省普通国债vs IMF一般政府)。
9. 日本术语: 标准中文优先(补充预算/特例国债/再融资国债/基本财政收支/预算假定利率/平均剩余期限/税收超收/决算剩余金/预备费/地方交付税), 无对应概念才留日文(骨太方针)。货币一律`¥…T`, 不用兆円。
10. 文件替换纪律(网页上传时代遗留): 隐藏目录会被网页拖拽丢掉, 文件名前易混入全角冒号(U+FF1A); 现在改走API/git, 但验收仍以仓库实况为准。

## 7. 已校准的字段结论 (勿再猜)

- MTS表1: `classification_desc`=月份名, `record_type_cd=MTH`, `data_type_cd=D`; 字段`current_month_gross_rcpt_amt/gross_outly_amt/dfct_sur_amt`(赤字为正取负)。
- MTS表4/9: FYTD字段带`current_`前缀(`current_fytd_net_rcpt_amt`, 表9为`current_fytd_rcpt_outly_amt`), 个税在`Total -- Individual Income Taxes`合计行(T), 表9收支同表不可用兜底桶, 支出走14职能白名单。
- DTS债限表IIIC无合计行: 限额内=公众+政府间−不计入+其他计入; 数据集仅2022-10起, 之前用Debt to the Penny月末总债务近似。
- MSPD表1: `Total Marketable`在`security_type_desc`层, 品种在`security_class_desc`。
- auctions_query: TIPS的`security_type`也是Note/Bond, 旗标列`inflation_index_security`=Yes; 10/20/30年名义新发仅在2/5/8/11月, 图用新发前向填充+异类场次护栏(低于近3次中位数60%剔除)。
- buybacks端点 `/v1/accounting/od/buybacks_operations`。
- congress.gov委员会法案列表(hsap00/ssap00): 条目字段名不稳, 以url解析congress/type/number; 拨款阶段正则APPROPS_STAGES为首跑候选。
- 投资者类别: 页面href无引号, 表头第4行, 列序见ALLOT_COLS注释; .xls需xlrd。
- SIFMA统计页正文: "YTD <年> statistics include: Issuance (through <月>) $X billion"。
- MSPD表3 `/v1/debt/mspd/mspd_table_3_market`: 每CUSIP多行, outstanding_amt仅首行(续发行为null), 剔除Total Marketable与FFB行; 逐券合计+FFB=Total Marketable。
- Census QTAX: 需`CENSUS_API_KEY`, 字段名大写, 必带`for=us:*`。
- TIC: mfh.txt白名单国别×13月矩阵; 历史文件`mfhhis01-05.txt`通用解析器。
- 财务省利率CSV: `jgbcm.csv`当月(和历R8.9.1, Shift-JIS), 历史全量在英文站`english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv`。
- FRED S&L: 总收入`W077RC1Q027SBEA`, 总支出`W079RCQ027SBEA`, 转移支付`FGSL`(B087RC1Q027SBEA是别的序列)。
- SPX: Yahoo在机房返回过短, Stooq空, 用FRED SP500近十年拼接旧序列。

## 8. 内容更新通道(人工锚与节奏)

| 锚 | 文件 | 节奏 | 触发 |
|---|---|---|---|
| QRFE历史/回购结构 | data/us/qra_history.json, config/buyback_schedule.yaml | 每季QRA(11/2·11/4最近) | 对话转换 |
| CBO基线矩阵 | data/us/cbo_matrix.json | CBO每版(夏季更新截至10月未见) | xlsx对话转换 |
| 拨款状态/302(b)/CR链/预算周期节点 | objects_us.yaml appropriations·budget_cycle实例 | 每周核 | 对话 |
| 事件种子 | config/events_seed*.yaml | 每周 | 对话 |
| 企业债SIFMA历史 | data/us/corp_issuance.json | 一次性 | 用户网页填表下载xls → apply_corp_xlsx(path) |
| JP全部锚 | data/jp/*.json(由fetch_jp.py SEEDS生成, 改数字改代码) | 发行计划12月+改定, 补充预算, 中长期测算1/7月, 骨太6月 | 对话 |

## 9. 凭据与权限

- Secrets: `CONGRESS_API_KEY`(已配, 建议旋转), `CENSUS_API_KEY`(未配→QTAX四税种为"—")。
- Pages: Deploy from branch main `/docs`。workflow需`permissions: contents: write`, 提交范围`git add data/us data/jp docs`。
- 之前通过细粒度PAT走GitHub API推文件和触发workflow(Contents/Actions/Workflows三权限); Claude Code用git即可, 该PAT应撤销。

## 10. 待办

US
1. 11/2 QRFE录qra_history一行, 11/4 Statement后校回购结构(长端加码是否常态化)。WAM已自动。
2. CBO夏季/秋季基线出来转cbo_matrix。
3. 11/3中期选举后: 预算周期FY2027节点、拨款12/11节点、补充拨款$87.6B、农业法案(9/30已过期)、NDAA全部重核。
4. Z.1 2026Q2/Q3持有者锚(货基/银行/家庭/养老)录入。
5. 拨款首跑校准: MilCon-VA/Leg Branch/SFOPS与参院侧未识别, 看日志扫描条数与_debug_approps_actions。
6. ~~CENSUS_API_KEY~~(2026-11-01已配, QTAX已通); SIFMA: 固收汇总xls已回填13个月, 2025-08及以前待公司债专表xls(US Corporate Bonds Statistics)。
7. 债务限制卡头恢复实时headroom读数(合并时丢失)。
8. 变化提醒规则细化。(mspd_table_3到期墙已接入)

JP
1. 尽力自动三项首跑校验: 招标结果HTML, 税收月度Excel(収入額調), 资金循环CSV。
2. 特例国债法5年延长成立确认; 骨太2026 PB表述; 中长期测算7月版录入; FY2026秋季补充预算与发行计划改定; FY2027政府案(12月下旬)。
3. 是否复刻US的拍卖需求结构(日本无投资者类别统计)与总发行对照(社债用日本证券业协会统计做锚), 待用户定。
4. 招标日程规则改为财务省月度日历真实日期。

技术债
1. build_site.py单文件1400+行, 视图/引擎/JS混在一起, 宜拆模块(engine/views_us/views_jp/js)。
2. 模板占位符`__X__`硬替换, JP站必须把所有占位符替换为合法空JSON否则JS崩。
3. `_debug_*`文件随commit进仓库, 可设清理策略。
4. 账本owner别名映射散落在build_site main, 宜迁进yaml。
5. 大改之前先在sample模式跑全链路并对页面做结构断言(已有的检查脚本模式), 再部署。

## 11. 用户风格要求

中文简洁书面语, 短句, 少用连接词, 标点极简(少引号少分号), 表格优先, 表格单元格用编号短点, 先给高层结论再给细节。
每轮改动必须一次性验证完整并明确告知需要跑哪个模式, 能自动的绝不让用户手动。用户对"没完没了"的手动循环与未经说明的视觉改动极度反感。
