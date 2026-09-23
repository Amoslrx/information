# 赛历 · 大学生竞赛信息平台

极简复古杂志风格的大学生竞赛信息聚合平台。汇集各类大学生学科竞赛信息，帮助学生及时了解和参与适合自己的竞赛。

## ✨ 功能特性

- 📋 **竞赛浏览** - 按分类、级别、状态筛选竞赛
- 🔍 **搜索功能** - 关键词搜索竞赛信息
- 📅 **时间线展示** - 清晰展示竞赛重要时间节点
- 📊 **数据统计** - 竞赛数量、分类分布等统计信息
- 📱 **响应式设计** - 适配桌面和移动设备
- 🎨 **复古杂志风格** - 独特的视觉设计

## 🏆 涵盖竞赛分类

- **计算机设计类** - ACM、蓝桥杯、计算机设计大赛等
- **数据与AI类** - 大数据挑战赛、KDD Cup、GAIIc等
- **创新创业类** - 互联网+、挑战杯、三创赛等
- **数学建模类** - 数模国赛、美赛、统计建模大赛等

## 📁 项目结构

```
competitions-platform/
├── frontend/              # React 前端应用
│   ├── src/
│   │   ├── components/    # UI 组件
│   │   ├── data/          # 静态竞赛数据
│   │   ├── types/         # TypeScript 类型定义
│   │   ├── hooks/         # 自定义 Hooks
│   │   └── utils/         # 工具函数
│   ├── public/            # 静态资源
│   └── package.json
├── backend/               # Express 后端 API
│   ├── models/            # Mongoose 数据模型
│   ├── routes/            # API 路由
│   ├── data/              # 种子数据
│   ├── server.js          # 服务入口
│   └── seed.js            # 数据导入脚本
├── crawler/               # Python 爬虫服务
│   ├── parsers/           # 页面解析器
│   ├── crawler.py         # 爬虫主程序
│   ├── scheduler.py       # 定时任务
│   └── database.py        # 数据库操作
├── .gitignore
└── README.md
```

## 🚀 快速开始

### 前置条件

- Node.js >= 18
- MongoDB（后端使用）
- Python >= 3.8（爬虫使用）

### 1. 前端开发

```bash
cd frontend
npm install
npm run dev
# 访问 http://localhost:5173
```

构建生产版本：

```bash
npm run build
npm run preview
```

### 2. 后端服务

```bash
cd backend
npm install
cp .env.example .env
# 编辑 .env 配置 MongoDB 连接

npm run seed   # 导入种子数据（12个竞赛）
npm run dev    # 启动开发服务器
# API 运行在 http://localhost:3001
```

### 3. 爬虫服务

```bash
cd crawler
pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# 编辑 .env 配置数据库连接

python crawler.py      # 单次爬取
python scheduler.py    # 定时爬取（每6小时）
```

## 🔌 API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/competitions` | 获取竞赛列表 |
| GET | `/api/competitions/:id` | 获取竞赛详情 |
| GET | `/api/competitions/stats` | 获取统计数据 |
| POST | `/api/competitions` | 创建竞赛 |
| PUT | `/api/competitions/:id` | 更新竞赛 |
| DELETE | `/api/competitions/:id` | 删除竞赛 |

### 查询参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `category` | string | 分类筛选：computer-design / data-ai / innovation / math-modeling |
| `status` | string | 状态筛选：upcoming / open / closed |
| `search` | string | 关键词搜索（名称、描述、标签） |
| `sort` | string | 排序方式，默认 deadline |
| `page` | number | 页码 |
| `limit` | number | 每页数量 |

## 🛠 技术栈

### 前端
- **框架**: React 19 + TypeScript
- **样式**: Tailwind CSS
- **动画**: Framer Motion
- **路由**: React Router
- **图标**: Lucide React
- **构建工具**: Vite

### 后端
- **框架**: Node.js + Express
- **数据库**: MongoDB + Mongoose
- **开发工具**: Nodemon
- **环境变量**: dotenv

### 爬虫
- **语言**: Python
- **浏览器自动化**: Playwright
- **定时任务**: APScheduler
- **HTML解析**: BeautifulSoup

## 📊 竞赛数据

项目内置 **12个** 精选大学生竞赛数据，包括：

| 竞赛名称 | 级别 | 分类 | 状态 |
|---------|------|------|------|
| 中国大学生计算机设计大赛 | 国家级 | 计算机设计 | 报名中 |
| 全国大学生数学建模竞赛 | 国家级 | 数学建模 | 即将开始 |
| 大数据挑战赛 | 国家级 | 数据与AI | 报名中 |
| 互联网+大学生创新创业大赛 | 国际级 | 创新创业 | 报名中 |
| 挑战杯课外学术科技作品竞赛 | 国家级 | 创新创业 | 报名中 |
| ACM-ICPC 国际大学生程序设计竞赛 | 国际级 | 计算机设计 | 即将开始 |
| 蓝桥杯全国软件和信息技术大赛 | 国家级 | 计算机设计 | 即将开始 |
| KDD Cup 国际知识发现和数据挖掘竞赛 | 国际级 | 数据与AI | 即将开始 |
| 美国大学生数学建模竞赛（MCM/ICM） | 国际级 | 数学建模 | 即将开始 |
| 全国大学生统计建模大赛 | 国家级 | 数学建模 | 报名中 |
| 全国大学生电子商务三创赛 | 国家级 | 创新创业 | 即将开始 |
| 全球人工智能技术创新大赛（GAIIc） | 国家级 | 数据与AI | 即将开始 |

## 📝 开发说明

### 数据同步

前端静态数据位于 `frontend/src/data/competitions.ts`
后端种子数据位于 `backend/data/seedData.js`

两处数据保持一致，新增竞赛时请同步更新。

### 类型定义

共享类型定义在 `frontend/src/types/index.ts` 中维护。

## 📄 License

MIT
