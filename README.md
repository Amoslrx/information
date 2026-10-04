# 竞赛信息汇总 — 网站与数据

面向西安交通大学电气工程及其自动化专业的学科竞赛信息站。
当前阶段：**静态网站 MVP 已跑通**（官方数据源 → 结构化 → 静态站，全链路脚本可重跑）。

> 调研结论、方案取舍、法务红线见 [`调研结论与方案.md`](调研结论与方案.md)。

---

## 一、网站

纯静态、零依赖、无构建步骤。手机优先。

| 文件 | 作用 |
|---|---|
| `site/index.html` | 页面骨架 |
| `site/style.css` | 样式 |
| `site/app.js` | 逻辑（筛选 / 搜索 / 排序 / 详情抽屉 / 节律图） |
| `site/data.js` | **数据层，由脚本生成，勿手工编辑** |
| `site/calendar/all.ics` | 日历订阅：全部可推断节律的竞赛 |
| `site/calendar/ee-core.ics` | 日历订阅：仅电气相关度 ≥4 的核心竞赛 |

### 三种打开方式

```powershell
# 1) 直接双击（数据已内联进 data.js，file:// 下可用，无需服务器）
start site\index.html

# 2) 本地预览服务（已启动在 http://127.0.0.1:8099）
python -m http.server 8099 --directory site

# 3) 部署（见下方"部署"）
```

### 功能

**竞赛目录**（91 条）
- 搜索：名称 / 西交名单用名 / 主办单位 / 说明
- 筛选：电气相关度（5 / ≥4 / ≥3）、西交认定（A 类 / B 类 / 未认定）、是否在教育部目录、只看近期有通知
- 排序：相关度优先 / 近期有通知优先 / 通知数优先 / 教育部序号 / 名称
- 点卡片打开详情抽屉：完整字段 + 该竞赛相关的全部校内通知 + 官网直达

**年度节律**（37 个竞赛，用 306 条历史通知推断）
- 全校通知的月度柱状图 + 自动生成的高峰月洞察（**3–4 月是双高峰**）
- 每个竞赛 12 个月份格，深色为稳定出现月份，描边为当前月份
- **日历订阅**：`calendar/ee-core.ics` / `calendar/all.ics`，年度重复 + 提前 7 天提醒
- 按月份筛选、搜索、排序

**校内通知**（451 条，多源聚合，2003-12-22 ~ 2026-09-23）
- **三个来源**：实践教学中心(306) · 教务处(45) · 电气学院(100)
- **默认只显示竞赛相关**（按标题关键词打标，滤掉转专业/选课/停水这类行政通知）
- 可按来源筛选、搜索、按范围（已关联/未关联）与时间（近 90 天/半年/一年）筛选
- 按年月分组，90 天内的标 `NEW`
- 每条显示来源徽章 + 自动关联到的竞赛，点一下跳到该竞赛详情

> **多源抓取策略**：只爬每个源的前 N 页，再与历史按 URL 合并。
> 每周跑一次很便宜，而历史会逐周累积，不会因为只爬前几页而丢数据。
>
> **实测过的其他源**（原因记录在 `crawl_xjtu_notices.py` 的 `SKIPPED` 里）：
> 电气学院"团学工作"栏目是党团活动；交大新闻网是图文新闻且列表无日期；
> 研究生院以招生培养为主；校团委是 Nuxt.js 单页应用需额外解析。
> **电气学院官网没有竞赛通知栏目**——学院主要通过公众号发布（见下方"公众号"一节）。

**说明与来源** — 数据缺陷、字段口径、更新命令

### 年度节律是怎么来的

`scripts/build_cadence.py` 只用已有的 `notices.json`，不新增抓取：

1. 把通知按「关联竞赛 + 发布月份」归集；
2. 对每个竞赛，在环形月份上找出能覆盖 **≥60% 历史通知的最短连续窗口**（最宽 6 个月）；
3. 同时统计「稳定月份」（在 ≥2 个不同年份都出现过的月份）；
4. 观测年数 <2 的不输出节律（样本不足，宁缺勿错）；
5. 置信度按观测年数分级：≥4 年 high，≥3 年 medium，2 年 low。

得出的窗口例如：电子设计竞赛 `3–5 月`（覆盖 60%）、智能汽车竞赛 `3–4 月`（71%）、
互联网+ `4–6 月`（72%）、蓝桥杯 `10 月`（80%）、美赛 `12–1 月`（71%）。

> ⚠️ 这是**统计推断，不是官方赛程**，只表示往年在这些月份发过通知。

### 日历订阅怎么用

部署到公网后（见下方「部署」），把 `calendar/all.ics` 的完整网址填进日历：

- **iOS**：设置 → 日历 → 账户 → 添加账户 → 其他 → 添加已订阅的日历
- **Android / Google 日历**：其他日历 → 通过网址订阅
- **Outlook / Apple 日历（电脑）**：添加日历 → 从网络订阅

也可以直接点链接下载 `.ics` 双击导入（但不会自动更新）。

> **UID 稳定性**：日历事件标识由教育部目录序号或竞赛名的 md5 生成，是确定性的。
> 如果每次生成都换 UID，日历客户端会把事件当成新的，逐年堆积重复项——
> 所以**不能用 `hash()`**（每个进程随机化）。`test_site.js` 有断言守着这一点。

### 自检

```powershell
node scripts\test_site.js     # 89 项断言
```

覆盖：HTML/JS 元素 id 一致性、CSS class 覆盖、app.js 在 DOM 桩中无异常初始化、
渲染出的卡片/通知/节律卡片数量、月份格数量、核心赛事是否在列、筛选与关联的数据口径、
URL 与日期格式、竞赛名唯一性、通知关联孤儿、节律窗口合法性与覆盖率、
跨年窗口（如 12–1 月）判定、ICS 的 CRLF/折行 75 字节/VEVENT 配对/UID 确定性/年度重复，
以及**部署相关**：订阅网址在各种部署环境（Netlify 根域 / GitHub Pages 子路径 / 本地）
下是否推导正确、`_headers` 是否覆盖 `/calendar/*.ics`、发布目录有无多余文件、
HTML 资源路径大小写是否安全（线上 Linux 区分大小写，本地 Windows 测不出来）。

> **注意**：本机沙箱禁止 Chrome/Edge 启动（多进程 IPC 需要命名管道），
> 因此**真实浏览器渲染未经自动化验证**。自检是用最小 DOM 桩在 Node 里跑 `app.js`
> 并断言其写出的 HTML。视觉与布局请你实际打开确认。

---

## 二、部署

> **完整步骤、验证清单和常见坑见 [`部署到Netlify.md`](部署到Netlify.md)。**
>
> ⚠️ **拖拽部署时要拖 `site/` 文件夹，不要拖仓库根目录** ——
> 否则会把 `data/raw/` 的 PDF、`scripts/` 源码、调研文档和 `.tools/`（3.6 MB Python 包）全部公开出去。

### Netlify（推荐）

**拖拽**：把 `site/` 拖到 <https://app.netlify.com/drop>，几秒出网址。

**Git 部署**（能配合 Action 自动更新，推荐）：

1. 推到 GitHub（**要包含 `data/raw/` 里的 PDF**，CI 要用）
2. 仓库 Settings → Actions → General → Workflow permissions → **Read and write permissions**
3. Netlify → Add new site → Import an existing project → 选仓库
4. 构建设置：Base directory 留空、**Build command 留空**、Publish directory = `site`

之后形成闭环：Action 每周更新数据并 push → Netlify 自动重新发布。

### GitHub Pages

```powershell
cd site && git init && git add . && git commit -m "竞赛信息站"
git branch -M main
git remote add origin https://github.com/<用户名>/<仓库名>.git
git push -u origin main
```
仓库 Settings → Pages → Source 设为 `main` 根目录。

> GitHub Pages **不能**设置自定义响应头，所以 `.ics` 的 `Content-Type` 可能不对，
> 日历订阅在 Pages 上不保证可用。**要用日历订阅就部署到 Netlify**（用 `site/_headers` 控制 MIME）。

### 部署后必须验证

1. `https://<域名>/calendar/all.ics` → `Content-Type` 应为 `text/calendar; charset=utf-8`
2. `https://<域名>/_headers` → 应被 Netlify 处理并隐藏（404 或返回内容都不对）
3. 打开「年度节律」页，订阅输入框里应是**绝对网址**（不是 `file://`）

---

## 二·五、自动更新（GitHub Actions）

`.github/workflows/update.yml` 已配好：**每周一 02:00（北京时间）**自动重跑整条数据管道，
有变化就自动提交。这是对抗「信息聚合站经典死因：没人维护 → 数据过期 → 更没人看」的办法。

只重抓**会变的部分**（校内通知）；教育部目录和西交 A/B 名单的 PDF 保留在仓库里重新解析
——它们一年才变一次，没必要每次下载（何况西交附件需要 `Referer` 头）。

**启用步骤（一次性）**：

1. 把这整个目录推到一个 GitHub 仓库（**包含 `data/raw/` 里的 PDF**，CI 要用）
2. 仓库 Settings → Actions → General → Workflow permissions
   → 选 **Read and write permissions** ← 不设这个，最后一步 `git push` 会失败
3. 到 Actions 标签页，点 **每周更新竞赛数据** → **Run workflow** 手动跑一次验证

之后每周自动跑。自检失败时**不会提交**，保留上一版可用数据 —— 站点不会因为一次抓取抖动而变坏。

本地想手动跑同一套流程：

```powershell
python scripts\crawl_xjtu_notices.py
python scripts\parse_moe_catalog.py
python scripts\parse_xjtu_ab.py
python scripts\build_master_table.py
python scripts\build_cadence.py
python scripts\build_site_data.py
python scripts\build_calendar.py
node   scripts\test_site.js
```


---

## 三、数据与产出

| 文件 | 说明 |
|---|---|
| `data/seed/competitions_master.csv` | 91 条竞赛总表（UTF-8 BOM，可直接导入飞书 / Notion / Excel） |
| `data/seed/competitions_master.md` | 同一份数据的 Markdown 版 |
| `data/seed/moj_2025_catalog.json` | 教育部 2025 认可竞赛目录 84 项（83 项含官网） |
| `data/seed/xjtu_ab_list.json` | 西交 A/B 类名单 19 项（**旧版，不完整**） |
| `data/seed/notices.json` | 校内通知 451 条（**多源聚合**，含自动关联到的竞赛与竞赛相关性标记） |
| `data/seed/cadence.json` | 年度节律推断结果 37 个竞赛 + 全校月份分布 |
| `data/curated/ee_relevance.json` | **电气相关度人工研判 —— 唯一应该手工编辑的数据文件** |

### 字段

```
竞赛名称 | 电气相关度 | 西交类别 | 西交名单用名 | 级别 | 归口部门
教育部目录 | 教育部目录序号 | 主办单位 | 官网 | 相关理由 | 数据来源 | 最后核对
```

### 电气相关度分布

| 分值 | 含义 | 条数 |
|---|---|---|
| 5 | 电气/自动化核心赛事 | 10 |
| 4 | 高度相关 | 10 |
| 3 | 有一定交叉 | 15 |
| 2 | 弱相关 | 19 |
| 1 | 基本无关 | 37 |

**5 分的 10 项**：中国国际大学生创新大赛、挑战杯课外学术科技作品竞赛、全国大学生数学建模竞赛、
全国大学生电子设计竞赛、全国大学生智能汽车竞赛、中国大学生工程实践与创新能力大赛、
"西门子杯"中国智能制造挑战赛、全国大学生嵌入式芯片与系统设计竞赛、
全国大学生节能减排社会实践与科技竞赛、美国大学生数学建模竞赛。

---

## 四、⚠️ 两个必须知道的数据缺陷

1. **西交 A/B 名单是旧版且不完整**（仅 2 页 / 19 项，科技竞赛编号从 7 跳到 9，
   且缺"西门子杯"、嵌入式芯片设计竞赛、智能机器人创意大赛等电气核心赛事）。
   **总表与网站里标 `未认定(待核)` 的 72 条，不代表学校未认定，只代表这份旧名单里没有。**
   → 上线前必须向实践教学中心 / 教务处核对现行完整版。

2. **电气相关度是 AI 初判**，用于排序和初筛，需逐条复核。
   只改 `data/curated/ee_relevance.json` 再重跑脚本，不要手工改 CSV 或 `data.js`。

3. 正文和附件中的报名安排已按证据提取，但尚未读取或有歧义的信息仍标为待核实。
   "近期有通知"不等于报名开放；报名状态仅取本届明确的时间节点。

---

## 五、脚本与更新流程

```powershell
# 依赖装在两个工作区内的目录, 与全局环境隔离
python -m pip install --target .\.tools pypdf

python scripts\crawl_xjtu_notices.py    # 抓多源通知(实践教学中心/教务处/电气学院) → notices.json
python scripts\crawl_notice_bodies.py   # 普通正文 / 团委文章 API → notice_bodies.json
python scripts\crawl_notice_resources.py # 附件、OCR 与二维码 → notice_resources.json
python scripts\extract_notice_fields.py # 字段、联系人、赛道、时间节点及原文证据 → notice_fields.json
python scripts\extract_deadlines.py     # 使用统一正文缓存提取报名截止时间
python scripts\parse_moe_catalog.py     # 教育部目录 PDF → JSON
python scripts\parse_xjtu_ab.py         # 西交 A/B 名单 PDF → JSON
python scripts\build_master_table.py    # 合并 → competitions_master.csv / .md
python scripts\build_cadence.py         # 推断年度节律 → data/seed/cadence.json
python scripts\build_site_data.py       # 打包 → site/data.js
python scripts\build_calendar.py        # 生成 → site/calendar/*.ics
python -m unittest discover -s scripts -p "test_notice*.py"
node   scripts\test_site.js             # 站点与交互自检
```

正文数据使用 `schema_version: 2`，每条保存 `url`、`title`、`date`（发布日期）、
`source`、`site`、`fetchedAt`（含时区的 UTC 时间）、`status`、`error`、`contentHash`（SHA-256）。
`status` 为 `success`、`empty` 或 `failed`；正文定位失败属于 `failed`，匹配到正文容器但无文字、图片或附件属于 `empty`。
短通知和纯图片／附件通知也可以成功，不再按正文长度拒绝。

完整内容保存在 `body`、`bodyHtml`、`paragraphs`、`tables`、`images`、`attachments` 和 `links`；
`blocks` 按原文顺序引用段落和表格，表格保留单元格及合并信息，HTML 保留图片位置。
正文及链接不截断，相对资源链接转换为完整地址。页面打包摘要、结构化字段及证据和最多四个优先报名／附件链接。
抓取失败保留错误和 `lastSuccess`（如果存在），不会把旧正文冒充本次成功。

默认增量抓取竞赛通知和最近 540 天的其他通知；`--limit 24` 控制本轮数量，
`--force` 重抓，`--url "通知地址"` 指定抽样地址（可重复）。
普通站点的正文选择器在 `scripts/notice_content.py` 中配置；团委通过独立的 `fetch_tuanwei` 适配器读取公开文章接口。

### 结构化字段与证据

格式定义见 [`data/schemas/notice_fields.schema.json`](data/schemas/notice_fields.schema.json)，
提取规则见 [`scripts/notice_fields.py`](scripts/notice_fields.py)。
每条通知包含竞赛名称 `competitionNames`、届次 `editions`、对象 `audiences`、赛道 `tracks`、
报名方式 `registrationMethods`、入口 `registrationLinks`、材料 `requiredMaterials`、
时间节点 `timeline`、联系人 `contacts` 和交流群 `groups`，均为数组；缺失项为空数组，缺失标量为 `null`。

每个字段包含 `value`、`raw`（原文）、`sourceUrl`、`location`（正文／标题的 Unicode 字符起止位置，
或资源引用）、`method`、`verification`、`flags` 和 `trackId`。
`source_matched` 表示提取结果与原文及规则对应，不代表人工核实；`needs_review` 表示有歧义或模型候选待核实。
`trackId: null` 表示未明确赛道归属，不会自动分配给其他赛道。
页面提供逐字段的原文证据，待核实字段只显示状态和原文，不把候选值当作确定值。

`contacts` 按人保存 `name`、`phones`、`emails` 和个人 `qq`；QQ群号码单独存于 `groups.number`。
共同联系人未明确号码归属时，号码保存在未指定姓名的记录中并标为待核实。
群图片保留资源地址和附近原文；OCR 与二维码解码的候选保留原图、识别来源及待核实状态。

`timeline.kind` 区分 `registration_start`、`campus_deadline`、`official_deadline`、
`registration_deadline`（未明确校内／官方）、`submission`、`competition` 和 `other`。
保留 `time`（含有效的 `24:00`）、`timezone`、`dateRaw` 和 `endDate`。
校验真实日历日期；缺少年份、可能跨年、跨年范围、月份精度、延期、冲突和近似日期显式保留在 `flags` 中。
年月范围不会被补成具体日期，缺少年份的候选值也不会自动成为报名截止。
只有无歧义且有证据的报名截止进入 `deadlines.json` 和页面报名状态；作品或材料提交及比赛日期不参与该判断。
多个赛道或不同截止值不压缩为一个日期，旧版评分日期保留为 `legacyCandidate`，不进入页面。
`extract_deadlines.py` 默认离线；可用 `--fetch-missing` 显式补抓正文。

### 可选模型层

默认仅运行规则，不需要模型服务或密钥。配置模型时，使用 JSON stdin/stdout 的进程适配器：

```powershell
python scripts\extract_notice_fields.py --model-command '["python","my_model_adapter.py"]'
```

适配器从 stdin 读取 `instructions`、`article`、`schema`、`format`、`ruleResult`，向 stdout
写出符合 schema 的完整字段对象。标准错误可用于服务端诊断。文章作为不可信数据传递。
[`scripts/model_http_adapter.py`](scripts/model_http_adapter.py) 提供可选 HTTP 网关适配器：设置
`NOTICE_MODEL_URL`（HTTPS 或本地网关地址），可选 `NOTICE_MODEL_TOKEN`，并将其作为 `--model-command` 的脚本参数。
网关需接受上述请求格式并直接返回字段对象；不同供应商的调用逻辑放在网关或自定义适配器中。

输出会校验字段形状、未知字段、引用地址、原文字符位置、日期类型和联系人／赛道对应关系。
模型不能自行宣称已核实；只有规则也能确认的结果才成为 `source_matched`，其余有证据候选保持待核实。
无证据、格式错误、超时或进程失败会完整保留规则结果并记录错误。
缓存位于 `.cache/notice-model/`（不入库），键含正文内容哈希、标题、发布日期、来源、schema 版本、提示及适配器参数；
缓存命中后仍重新校验证据。默认自动更新流程不开启模型。

### 按届次关联通知与报名详情

`scripts/notice_editions.py` 在站点构建时按竞赛、明确的年份及届次建立独立分组。
发布日期不会被当作赛事年份；年份和届次都未明确的通知按原网址单独保留。
只有同一赛道中同时写明年份和届次的通知，才可为仅写其中一项的通知提供唯一关联依据；
关系有歧义时不合并。中文和数字届次统一比较，原文及锚点证据保留。
同年不同届次并列展示；跨年赛季仅在标题明确给出年份范围时作为跨年组。

报名、补充、延期、结果公示分别标注；赛道、校赛／省赛／国赛及第一／第二阶段独立保存。
时间节点按类型、赛道、阶段及轮次汇总。明确的“延期至／调整为”等新时间，只有能唯一对应已有节点、
旧值一致且发布日期先后明确时才替换；同日无法判断先后、缺少年份、范围不明和 OCR／模型候选保持待核实。
保留每次变更的旧值、新值、来源链接及原始表述；没有变更依据的不同日期显示信息冲突。
公示只影响对应赛道和阶段，不关闭其他赛道或国赛的报名。

本届卡片展示报名状态、具体截止时刻、参赛对象及已核实的报名入口。
详情按“参赛对象 → 报名方式 → 入口 → 材料”组织步骤，再展示时间线、延期记录、联系人、交流群和通知依据。
往届与届次待核实信息可展开独立查看，不填入本届卡片。
“未提及”指已读取的通知没有该项；正文未读取完整或候选有歧义时为“待核实”；相互矛盾的安排为“信息冲突”。
报名开始时间未到时显示尚未开始，截止时刻按北京时间比较，`24:00` 按次日零点处理。
重建及回归检查：

```powershell
python scripts\extract_notice_fields.py
python scripts\build_site_data.py
python -m unittest discover -s scripts -p "test_notice*.py"
node scripts\test_site.js
```

### 通知附件、海报与二维码

在正文抓取后、字段提取前运行：

```powershell
python scripts\crawl_notice_resources.py
python scripts\extract_notice_fields.py
python scripts\extract_deadlines.py
python scripts\build_site_data.py
```

资源清单写入 `data/seed/notice_resources.json`，原文件和解析缓存位于 `.cache/notice-resources/`，
页面预览位于 `site/media/`。下载携带通知 Referer，默认单文件 20 MiB、连接读取超时 20 秒、
下载总时限 45 秒、解析子进程时限 120 秒、PDF 最多 30 页；均有命令行参数可调。
缓存按文件 SHA-256 校验，解析配置改变会重新解析；附件内容变化会使字段及模型缓存失效。
失败、正文为空、部分解析、成功和不支持的格式分别记录，不用失败结果冒充正文。

PDF 使用文字层并保留真实页码；扫描页和图片执行 OCR，页面尝试二维码解码。
DOCX 提取正文、表格文字及内嵌图片，不虚构分页；旧 `.doc` 需要 `antiword` 或环境变量
`NOTICE_ANTIWORD` 指定转换器。安装 Python 依赖 `pypdfium2 Pillow zxing-cpp`；Windows 可用系统 OCR，
Linux 需安装 `tesseract-ocr` 与 `tesseract-ocr-chi-sim`。自动更新工作流已包含依赖。

附件文本按同一字段规则提取，每条证据记录附件 URL、文本片段与可用页码。
OCR 和二维码结果始终待核实，不直接变成报名截止；识别失败保留原始资源和图片预览，
不补全模糊数字，不把任意二维码网址认定为报名入口。

教务处部分下载链接返回验证码页面，记录 `captcha_required`。手动下载原附件后可导入并继续同一流程：

```powershell
python scripts\crawl_notice_resources.py --notice-url "通知原网址" --asset-url "通知中的附件网址" --import-file "本地原附件.docx"
```

导入必须对应已抓取通知中的资源 URL，仍执行大小限制、格式检测和解析校验。
可用 `--notice-url`、`--limit` 抽样，`--force` 重新下载，`--ocr-backend` 指定 OCR 引擎。

### PDF 下载（重跑前置）

```powershell
# 西交 A/B 名单 —— 关键: 必须带 Referer, 否则只返回附件页 HTML
Invoke-WebRequest -Uri 'http://pec.xjtu.edu.cn/system/_content/download.jsp?urltype=news.DownloadAttachUrl&owner=1723267192&wbfileid=5156266' `
  -Headers @{'User-Agent'='Mozilla/5.0'; 'Referer'='http://pec.xjtu.edu.cn/'} `
  -OutFile 'data\raw\xjtu_ab_competitions.pdf'

# 教育部 2025 目录(中山大学站点副本)
# https://ifcen.sysu.edu.cn/sites/default/files/2026-01/2025年教育部认可的全国大学生学科竞赛目录清单.pdf
```

> **注意**：Windows 沙箱下 PowerShell 的 TLS 不可用（schannel `SEC_E_NO_CREDENTIALS`），
> 但 **Python 自带的 OpenSSL 可以正常访问 HTTPS**。所以脚本统一用 Python 发请求。

---

## 六、目录结构

```
site/          网站(发布目录)
  index.html / style.css / app.js / data.js
  404.html     自定义 404
  _headers     Netlify 响应头(含 .ics 的 MIME) —— 拖拽部署也生效
  calendar/    ICS 日历订阅文件
netlify.toml   Netlify 构建配置(Git 部署用)
.github/       GitHub Actions 定时更新
data/
  raw/         原始下载件与探测结果(可重建, 但 CI 需要其中的 PDF)
  seed/        结构化数据(脚本产出)
  curated/     人工研判数据(唯一应手工编辑处)
scripts/       抓取、解析、构建、自检脚本
部署到Netlify.md  部署步骤与验证清单
.tools/        Python 本地依赖(不入库)
.tools_js/     Node 本地依赖(不入库)
```

---

## 七、已验证可行 / 不可行（实测结论）

| 数据源 | 结论 |
|---|---|
| `pec.xjtu.edu.cn/cxcy/js.htm` | ✅ 可爬，**17 页 / 306 条**，robots.txt 404 未禁止 |
| 西交 A/B 名单附件 | ✅ 可下载（**须带 Referer**） |
| 83 个竞赛官网 | ✅ 76 个可达、6 个失败；30 个首页含日期模式；约 7% 需人工兜底 |
| 教育部目录 | ⚠️ 中国高等教育学会官网无结构化名单/API，**需人工年更** |
| 报名截止时间 | ⚠️ 几乎全在正文或 PDF 附件里，**只能半自动** |
| 赛氪 saikr.com | 🚫 robots 有 `Disallow: /*?*`，**不要爬** |
| 挑战杯 tiaozhanbei.net | 🚫 robots 点名封禁 GPTBot / ClaudeBot 等，**不要爬** |

---

## 八、下一步

1. **向实践教学中心 / 教务处核对现行完整 A/B 目录**（最大阻塞项）
2. 复核 `data/curated/ee_relevance.json` 里的电气相关度
3. 推到 GitHub 并开 Action，然后把网站丢进班级群
4. 有稳定用户后，再加：PWA、众包纠错入口及待核实信息的人工复核流程
