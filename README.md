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

3. 补充：**报名截止时间未结构化收录**（赛程几乎全在通知正文或 PDF 附件里），
   网站里的"近期有通知"是用通知日期做的代理信号，不等于报名开放中。

---

## 五、脚本与更新流程

```powershell
# 依赖装在两个工作区内的目录, 与全局环境隔离
python -m pip install --target .\.tools pypdf

python scripts\crawl_xjtu_notices.py    # 抓多源通知(实践教学中心/教务处/电气学院) → notices.json
python scripts\parse_moe_catalog.py     # 教育部目录 PDF → JSON
python scripts\parse_xjtu_ab.py         # 西交 A/B 名单 PDF → JSON
python scripts\build_master_table.py    # 合并 → competitions_master.csv / .md
python scripts\build_cadence.py         # 推断年度节律 → data/seed/cadence.json
python scripts\build_site_data.py       # 打包 → site/data.js
python scripts\build_calendar.py        # 生成 → site/calendar/*.ics
node   scripts\test_site.js             # 自检(70 项)
```

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
4. 有稳定用户后，再加：报名截止时间（人工维护字段，从通知正文抽取候选）、PWA、众包纠错入口
