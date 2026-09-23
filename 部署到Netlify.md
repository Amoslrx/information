# 部署到 Netlify

站点是**纯静态**的：`site/data.js` 和 `site/calendar/*.ics` 都已经由脚本生成好并提交进仓库，
所以**不需要构建步骤**，Netlify 直接把 `site/` 当发布目录即可。

发布总体积约 **250 KB**，Netlify 免费额度（100 GB 流量/月）完全够用。

---

## ⚠️ 先看这一条：拖哪个文件夹

| | |
|---|---|
| ✅ **要拖的是 `site/` 文件夹** | 它里面的东西会成为网站的根目录 |
| ❌ **千万不要拖 `F:\竞赛信息`（仓库根目录）** | 会把 `data/raw/` 的 PDF、`scripts/` 源码、调研文档、`.tools/`（3.6 MB Python 包）全部公开出去 |

拖拽部署时 `netlify.toml` 不会被读取（它需要构建过程），但 **`site/_headers` 会生效**
—— 关键的 MIME 配置我特意放在 `site/` 里，就是为了两种部署方式都管用。

---

## 方式一：拖拽部署（3 分钟，适合先看效果）

1. 打开 <https://app.netlify.com/drop>
2. 把 `F:\竞赛信息\site` **这个文件夹**拖进页面
3. 等几秒，Netlify 给一个 `https://随机名.netlify.app` 的网址
4. 想改名字：Site configuration → Change site name

**特点**：最快，但**每次更新数据都要重新拖一遍**。适合先验证效果。

---

## 方式二：Git 部署（推荐，能自动更新）

推到 GitHub，让 Netlify 连仓库 —— 之后每周的自动更新会直接触发重新发布，你什么都不用做。

### 1. 本地仓库已经准备好了

`git init` + `git add` + 首次提交**已经做完**（53 个文件，约 2.4 MB，提交号 `624e75b`）。
`.gitignore`、`.gitattributes` 都已配好，审计确认没有混入 `.tools/`、`node_modules` 等。

**只需先修一下提交身份**——当前 git 的 `user.email` 是占位的 `你的邮箱`，
这样推到 GitHub 后提交不会算在你账号名下：

```powershell
cd F:\竞赛信息
git config user.name  "你的名字"
git config user.email "你的GitHub邮箱"
git commit --amend --reset-author --no-edit
```

### 2. 在 GitHub 建仓库并推送

在 <https://github.com/new> 建一个**空仓库**（不要勾选 README / .gitignore / License，
否则会和非空推送冲突），然后：

```powershell
cd F:\竞赛信息
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

如果开了两步验证，push 时密码要填 **Personal Access Token**（不是账号密码）：
GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens，
权限给 `Contents: Read and write`。或者用 `gh auth login`。

### 3. 开启 Action 的写权限

仓库 **Settings → Actions → General → Workflow permissions → 选 `Read and write permissions`**。

不做这步，每周自动更新最后一步 `git push` 会失败。

### 4. 在 Netlify 连仓库

1. <https://app.netlify.com> → **Add new site** → **Import an existing project**
2. 选 **GitHub** → 授权 → 选中你的仓库
3. 构建设置（Netlify 会自己读 `netlify.toml`，确认一下即可）：

   | 字段 | 值 |
   |---|---|
   | Base directory | 留空 |
   | Build command | **留空** |
   | Publish directory | `site` |

4. 点 **Deploy**

### 4. 之后的自动化闭环

```
GitHub Action（每周一 02:00）
   → 抓新通知、重建数据、自检
   → 提交并 push
      → Netlify 检测到 push
         → 自动重新发布
```

**一次配好，之后不用管。**

---

## 部署后必须验证的 3 件事

这几条是静态站部署最容易出错、而且**本地测不出来**的地方。

### 1. `.ics` 的 MIME 类型（最关键）

日历订阅能不能用，全看这一条。浏览器里打开：

```
https://你的域名.netlify.app/calendar/all.ics
```

- ✅ **对**：显示为纯文本（`BEGIN:VCALENDAR...`），或直接触发「订阅日历」
- ❌ **错**：被当成文件下载、或乱码 → 说明 `Content-Type` 不对

用命令行确认更准：

```powershell
curl.exe -sI https://你的域名.netlify.app/calendar/all.ics | Select-String -Pattern "content-type"
# 期望: content-type: text/calendar; charset=utf-8
```

如果不对，检查 `site/_headers` 是否被部署上去了（见下一条）。

### 2. `_headers` 文件是否生效

```
https://你的域名.netlify.app/_headers
```

Netlify 会**处理并隐藏**这个文件 —— 如果它返回 404，说明文件没部署上去；
如果返回文件内容，说明没被当作配置处理。两种都不对，需要重新部署。

### 3. 订阅网址是否变成绝对地址

打开网站的「年度节律」标签页，看「日历订阅」面板里输入框的内容：

- ✅ 应该是 `https://你的域名.netlify.app/calendar/all.ics`
- ❌ 如果显示 `file:///...`，说明你是本地打开的，不是线上页面

这个网址是 JS 用 `location` 动态算的（没写死域名），所以换域名、换子路径都会自动正确。

---

## 顺手做的几件事

### 自定义域名

Netlify → Domain management → Add a domain。
用自己的域名（约 ¥30/年）看着更可信，也方便印在群里发。

免费的子域名 `xxx.netlify.app` 也完全够用。

### 确认 404 页面

随便访问一个不存在的路径，比如 `https://你的域名.netlify.app/xyz`，
应该看到「这个页面不存在」的自定义页面，而不是 Netlify 默认页。

### 关掉不必要的东西

这是个公开的信息站，**没有表单、没有用户输入、没有后端**，
所以不用配 Netlify Forms / Identity / Functions。保持简单。

---

## 关于「上传资料」

如果你说的「资料」是指**竞赛相关的文件**（历年题目、备赛笔记、经验帖、培训讲义），
而不是网站本身的文件，那么：

**放在 `site/` 目录下的一个子文件夹里**，例如：

```
site/
  materials/
    电赛备赛笔记.pdf
    数模历年题目.zip
```

这样它会随站点一起发布，网址就是 `https://你的域名.netlify.app/materials/xxx.pdf`。
然后我可以给网站加一个「资料」标签页来索引它们。

### ⚠️ 两点提醒

1. **版权**：历年真题、官方培训材料很多是有版权的，**不要直接公开传播**。
   自己整理的笔记、经验总结、公开的官方通知没有这个问题。
2. **体积**：Netlify 免费额度是 **100 GB 流量/月**，单文件建议不超过 25 MB。
   如果是几百 MB 的题目压缩包，放网盘更合适，网站上只放链接。

告诉我你手上的资料是什么类型、大概多少，我来给你定放法和页面结构。

---

## 常见坑速查

| 现象 | 原因 | 处理 |
|---|---|---|
| 页面能开但样式全丢 | 拖的是仓库根目录，`index.html` 不在根 | 改拖 `site/` |
| 日历订阅失败 / `.ics` 被下载 | `Content-Type` 不是 `text/calendar` | 确认 `site/_headers` 已部署 |
| 日历能订阅但事件不显示 | `.ics` 换行被 git 转成了 LF | `.gitattributes` 里 `*.ics -text` 必须**在 `* text=auto` 之后** |
| 订阅网址显示 `file://` | 本地打开页面，Netlify 地址无效 | 用线上网址打开再看 |
| Action 跑成功但 Netlify 没更新 | Netlify 没连仓库，或不在 production 分支 | 检查 Netlify 的 Deploy 设置 |
| Action 最后一步 push 失败 | 没开 Workflow 写权限 | Settings → Actions → General |
| 本地好好的线上却 404 | Windows 不区分大小写，Linux 区分 | 检查文件名大小写（自检里有这条断言） |
| 中文文件名打不开 | URL 里的中文没编码 | 尽量用英文文件名 |

---

## 为什么需要 `.gitattributes`

这台机器的 git 配置是 `core.autocrlf=true`，默认会把文件里的 CRLF 归一化成 LF 再存进仓库。
对代码没问题，但**对 `.ics` 是致命的**：RFC 5545 规定 iCalendar 内容行以 CRLF 分隔，
存成 LF 后 Netlify 的 Linux 检出拿到的就是 LF 版本，严格的日历客户端会解析失败。

`.gitattributes` 里的关键两行：

```
* text=auto          # 通配规则必须在最前面
*.ics -text diff     # -text = 不做任何换行转换, 原样保留 CRLF
```

> ⚠️ **顺序不能反**。gitattributes 是**后面的规则覆盖前面的**——
> 如果把 `* text=auto` 写在 `*.ics -text` 后面，通配规则会把 `.ics` 的规则盖掉，
> 文件仍会被转成 LF。这个坑我实际踩过一次，靠 `git ls-files --eol` 才发现。

验证方法：

```powershell
git ls-files --eol site/calendar/
# 期望看到: i/crlf  w/crlf  attr/-text
# 如果显示 i/lf 或 attr/text=auto, 说明规则没生效
```
