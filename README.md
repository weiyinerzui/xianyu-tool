# 闲鱼店铺运营工具 (Xianyu Ops)

一站式闲鱼（Goofish）店铺运营工具，覆盖**选品、违禁词检测、曝光诊断、标题优化、数据看板、竞品监控、AI 智能助手**全链路。帮助虚拟商品卖家解决曝光不稳定、销量波动、违禁词误触等核心痛点。

## ✨ 核心功能

| 模块 | 说明 |
|------|------|
| **选品中心** | httpx + Playwright 双层爬虫采集闲鱼搜索结果，5 维热度评分（销量/价格竞争力/新鲜度/关键词命中/图片质量），筛选高需求商品 |
| **违禁词检测** | AC 自动机多模式匹配 + 正则兜底，200+ 违禁词库（7 大类），分级（高/中/低危）+ 替换建议，支持批量检测 |
| **曝光诊断** | 规则引擎诊断 10 类流量下跌原因 + 排名因子分析，给出可执行修复建议 |
| **标题优化** | 五段式公式（品牌+核心词+属性+场景+长尾）评分 + 候选标题生成 |
| **数据看板** | 总览统计 / 价格分布 / 热门商品排行 / 关键词排行 / 类目分布 / 发布时间趋势（6 维度） |
| **竞品监控** | 头部卖家排行 / 卖家商品列表 / 最近新品 / 价格变动检测（4 维度） |
| **AI 智能助手** | LLM 驱动的标题优化与商品描述生成，无 LLM 时自动回退规则引擎 |
| **定时采集** | APScheduler 定时关键词采集，令牌桶限速 + 熔断器风控 |

## 🏗️ 技术栈

- **后端**：Python 3.13 + FastAPI + SQLAlchemy (async) + SQLite + APScheduler
- **前端**：React 18 + TypeScript + Ant Design 5 + Recharts + Vite 5
- **爬虫**：httpx (L1) → Playwright (L2) 自动降级
- **知识库**：YAML 规则文件（违禁词 / 诊断规则 / 标题公式），源自 goofish-cli Claude Skills

## 📁 目录结构

```
xianyu-ops/
├── backend/
│   ├── app/
│   │   ├── api/routes.py          # 27 个 API 端点
│   │   ├── config.py              # pydantic-settings 配置
│   │   ├── database.py            # async SQLAlchemy
│   │   ├── models/                # Product, CrawlTask
│   │   ├── crawlers/              # base, httpx_crawler, playwright_crawler
│   │   ├── services/              # banned_checker, diagnosis_engine, title_advisor,
│   │   │                          # scorer, guard, session_manager, scheduler,
│   │   │                          # dashboard, competitor_monitor, llm_advisor
│   │   ├── data/                  # banned_words.yaml, diagnosis_rules.yaml, title_rules.yaml
│   │   └── main.py                # FastAPI 入口
│   └── tests/                     # 70 个 pytest 测试
├── frontend/
│   ├── src/
│   │   ├── api.ts                 # axios 封装（27 端点）
│   │   ├── App.tsx                # 8 菜单布局
│   │   └── pages/                 # 8 个页面组件
│   └── vite.config.ts             # 代理 /api → 127.0.0.1:8000
└── README.md
```

## 🚀 快速开始

### 后端

**Linux / macOS:**

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Windows (PowerShell):**

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium          # 首次需安装浏览器二进制（L2 爬虫用）
uvicorn app.main:app --reload --port 8000
```

> 如果 PowerShell 提示无法执行脚本，先运行一次：
> `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

### 前端

```bash
cd frontend
npm install
npx vite          # 开发模式 http://localhost:5173
npx vite build    # 生产构建 → dist/
```

> ⚠️ 如果 `npm install` 只装了 135 个包（缺 vite），说明 `NODE_ENV=production` 导致跳过了 devDependencies。修复：
> - **Linux/macOS:** `NODE_ENV=development npm install`
> - **Windows PowerShell:** `$env:NODE_ENV="development"; npm install`

### 环境变量（可选）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `XIANYU_OPS_LLM_API_KEY` | LLM API Key（启用 AI 助手） | 空（回退规则引擎） |
| `XIANYU_OPS_LLM_BASE_URL` | LLM 服务地址 | OpenAI 兼容 |
| `XIANYU_OPS_LLM_MODEL` | 模型名 | gpt-4o-mini |
| `XIANYU_OPS_DB_URL` | 数据库连接 | sqlite+aiosqlite:///./xianyu_ops.db |

## 📡 API 端点（27 个）

### 违禁词
- `POST /api/v1/banned/check` — 单条检测
- `POST /api/v1/banned/check-batch` — 批量检测

### 曝光诊断
- `POST /api/v1/diagnosis/diagnose` — 曝光诊断

### 标题优化
- `POST /api/v1/title/score` — 标题评分
- `POST /api/v1/title/generate` — 候选标题生成

### 采集与选品
- `POST /api/v1/crawl/search` — 触发爬取
- `GET /api/v1/products/search` — 库内商品查询
- `GET /api/v1/products/stats` — 价格带 + 竞争度统计

### 风控与会话
- `GET /api/v1/guard/status` · `POST /api/v1/guard/reset`
- `GET /api/v1/session/status` · `POST /api/v1/session/import`

### 调度器
- `GET /api/v1/scheduler/status` · `POST /api/v1/scheduler/run` · `POST /api/v1/scheduler/keywords`

### 数据看板
- `GET /api/v1/dashboard/{overview,price-distribution,top-products,keyword-ranking,category-distribution,publish-trend}`

### 竞品监控
- `GET /api/v1/competitors/{top-sellers,seller/{name},new-listings,price-changes}`

### AI 助手
- `POST /api/v1/llm/optimize-title` · `POST /api/v1/llm/generate-description` · `GET /api/v1/llm/status`

## 🧪 测试

```bash
cd backend
pytest -q    # 70 passed
```

## 📝 致谢

本项目复用了以下开源项目的知识与代码：
- [xianyu-tool](https://github.com/weiyinerzui/xianyu-tool) — 项目基础结构
- [ai-goofish-monitor](https://github.com/weiyinerzui/ai-goofish-monitor) — 搜索结果解析器
- [goofish-cli](https://github.com/weiyinerzui/goofish-cli) — Claude Skills 知识库 + 基础设施模块
- [XianYuApis](https://github.com/weiyinerzui/XianYuApis) · [goofish_api](https://github.com/weiyinerzui/goofish_api) · [xianyu_spider](https://github.com/weiyinerzui/xianyu_spider) — API 参考

## ⚠️ 免责声明

本工具仅供学习研究使用。使用时请遵守闲鱼/Goofish 平台规则与相关法律法规，因使用本工具产生的一切后果由使用者自行承担。
