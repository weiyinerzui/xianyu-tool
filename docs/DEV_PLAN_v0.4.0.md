# 闲鱼店铺运营工具 · 开发计划（v0.4.0）

> 基线：`xianyu-ops` v0.3.0（branch `ops-v2`）
> 日期：2026-10-05
> 方法：先实测基线能力，再按「实测证据」而非「代码看起来如何」排期

---

## 0. 一句话结论

**工具的「分析大脑」已经很完整，「眼睛」（数据采集）是坏的。**

8 大模块 / 30 个 API / 84 个测试全绿 / 前端构建通过 —— 但选品、竞品、看板三个模块全部依赖采集数据，而**采集链路在当前环境下 100% 拿不到数据**。所以 P0 不是加功能，是修眼睛。

---

## 1. 基线实测结果（真实输出，非推断）

### 1.1 健康的部分 ✅

| 模块 | 实测方式 | 结果 |
|------|---------|------|
| 测试套件 | `pytest -q` | **84 passed** |
| 前端构建 | `vite build` | ✅ built in 9.42s（3895 modules） |
| API 完整性 | OpenAPI 导出 | 30 个端点全部注册 |
| 违禁词检测 | 真实违规文案 POST | ✅ 命中 7 处，`risk_level: danger`，含位置/替换建议/分类 |
| 标题优化 | 真实标题 POST | ✅ 86 分，指出缺失段位并给出补全建议 |
| 曝光诊断 | 构造异常商品 POST | ✅ 命中全部 10 类归因，每类带概率+证据+修复动作 |

违禁词库实测覆盖 **192 词 + 2 正则**，7 大类（绝对化/外部联系方式/品牌侵权/医疗夸大/敏感/虚假数据/虚拟商品）。

### 1.2 坏掉的部分 ❌（核心发现）

实测 `POST /api/v1/crawl/search` → `{"source": "none", "total": 0}`，耗时 1.5 秒即失败。

逐层排查结果：

| 层级 | 状态 | 实测证据 |
|------|------|---------|
| L1 httpx 直连 | ❌ | `RGV587_ERROR::SM::哎哟喂,被挤爆啦` — IP 段风控 |
| L2 Playwright headless | ❌ | 页面返回「**非法访问** / 请使用正常浏览器访问闲鱼」，0 张商品卡片 |
| L2 Playwright **headed + xvfb** | ⚠️ 部分 | ✅ **反爬拦截被绕过**，搜索页正常渲染；但 mtop 搜索 API 仍返回 `RGV587` |
| 数据库 | ❌ 空 | `products` 表 0 行、`crawl_tasks` 表 0 行 |

**关键洞察**：反爬拦截分两层，必须都突破才能取到数据——
1. **浏览器指纹层**：`headless=True` 必被识别。改 `headless=False` + `xvfb-run` 后**成功绕过**（已实测验证）。
2. **业务风控层**：mtop 搜索接口需要**登录态 cookie**，未登录一律 `RGV587`。

现有代码**两处都没做对**：`playwright_crawler.py:118` 硬编码 `headless=True`；cookie 仅用于 httpx 签名（`httpx_crawler.py:120`），**从未注入 Playwright 浏览器上下文**（`playwright_crawler.py:122`）。

---

## 2. 结构性问题（不改会持续产生"假数据"）

这些不是 bug，是设计缺口，会让工具**看似在工作、实则不可信**：

### S1 🔴 55% 评分权重永久空转

`config.py:25-29` 定义 5 维权重，但其中 2 维在生产环境**恒为 0**：

```
weight_want_velocity    0.35  →  scheduler.py:94 硬编码 previous_want=None, hours=0 → 恒 0.0
weight_engagement_rate  0.20  →  base.py 从不解析 view_count → 恒 0 分（分母为 0）
```

实测确认（真实参数喂入）：
```
{'hot_score': 20.35, 'want_velocity': 0.0, 'engagement_rate': 0.0, ...}
结构性空转权重: 55%   有效权重仅 45%
```

**后果**：`hot_score` 被硬性压到 45 分上限，而看板、选品排序、选品榜单**全部按 hot_score 排序** —— 等于用一把折了 55% 的尺子量商品。

### S2 🔴 实时采集不写分数

`routes.py:139` 的 `/crawl/search` **完全没调用** `calculate_hot_score`（实测 grep 命中 0 次）。只有 scheduler 路径算分，但 scheduler 的分数又受 S1 影响。

### S3 🟡 没有时序快照表

`app/models/` 只有 `product.py` + `crawl_task.py`，无历史表。
「想要数增速」本质是**时间序列指标**，没有快照表就无法计算 —— 这正是 S1 的根因。

### S4 🟡 翻页配置形同虚设

`config.py:18` 定义 `crawler_search_max_pages: 3`，但**全代码库零引用**（实测 grep 仅在定义处出现）。爬虫永远只抓第 1 页 30 条 → 样本量不足，选品结论不可靠。

### S5 🟡 采集无代理轮换

风控是 IP 级硬事实。`ai-goofish-monitor` 已有代理池设计，本项目无。

---

## 3. 开发计划

### P0 — 修复数据采集链路（最高优先级，一切分析功能的前提）

> **目标：让选品/看板/竞品三个模块从"空转"变为"有数据"。**
> 这一步不做，后面全是无米之炊。

| # | 任务 | 交付物 | 验收标准 |
|---|------|--------|---------|
| P0-1 | **浏览器反指纹**：L2 改 `headless=False`，配置项化（`crawler_headless: bool = False`），Linux 无显示器时自动走 xvfb；补 stealth 参数（UA/时区/语言/webdriver 抹除）+ 持久化 user profile | `playwright_crawler.py` 改造 + `config.py` 新配置 | 实测搜索页返回真实商品卡片，**不再是「非法访问」**；已验证 headed+xvfb 可绕过 |
| P0-2 | **Cookie 注入浏览器**：把 `session_manager` 的登录态注入 `browser.new_context(storage_state=...)`，让 L2 复用登录 cookie | L2 与 L1 共用登录态 | 携带用户 cookie 时 mtop 搜索接口**不再返回 RGV587**，能取到真实商品 |
| P0-3 | **登录态引导**：新增「扫码登录」流程（Playwright 打开 goofish 登录页 → 用户扫码 → 自动落盘 cookie），前置到采集之前 | 新增 `POST /api/v1/session/qr-login` + 前端扫码页 | 用户一次扫码，后续采集全部免登录 |
| P0-4 | **修复 item 解析**：dump 真实 mtop 响应结构 → 校准 `parse_search_api_json`；确认 `cards.data` vs `cardList` 层级；补 `view_count` | `base.py` 解析器 + 解析单测 | 用真实响应样本解析出 ≥1 条含标题/价格/想要数的商品；`view_count` 不再恒 0 |
| P0-5 | **代理轮换**：支持代理列表，命中风控自动切下一个 IP | `proxy_pool.py` + `crawler_service` 集成 | 连续 10 次采集不因单 IP 被封而中断 |

### P1 — 恢复评分可信度（承接 P0）

| # | 任务 | 验收标准 |
|---|------|---------|
| P1-1 | **新增快照表** `product_snapshots`（xianyu_id, want_count, view_count, price, captured_at），每次采集写入一条 | 同一商品连续采集 2 次后，`want_velocity` **不再为 0**（实测 > 0） |
| P1-2 | **真实计算增速**：读上一条快照计算 Δwant / Δhours，替换 `scheduler.py:94` 的硬编码 `None` | `scheduler.py` 不再出现 `previous_want=None` |
| P1-3 | **`/crawl/search` 实时算分**，让手动采集也能立刻出分数/排行 | 手动采集后 `products/search` 返回的 `hot_score > 0` |
| P1-4 | **修复 view_count**：若闲鱼搜索接口不返回浏览量，则**从评分体系中移除 engagement_rate 并重新分配权重**（不可用指标不应占 20% 权重） | 权重和 = 1.0，且每维都有真实数据支撑 |
| P1-5 | **启用翻页**：让 `crawler_search_max_pages` 真正生效 | 采集单关键词可获 ≥60 条（3 页），去重后入库 |

### P2 — 补齐"曝光提升技巧"知识层（你的第 3 项需求）

现有 `diagnosis_rules.yaml` 有 10 类归因，但**偏"诊断"、轻"主动优化"**。建议补充：

| # | 任务 | 验收标准 |
|---|------|---------|
| P2-1 | **曝光提升技巧库**：把 `goofish-cli/skills/goofish-publish-item` 的发布技巧结构化入库 → 新增「上架前检查清单」 | 新增 `publish_checklist` 规则文件 + 端点；输入商品草稿返回 N 项待优化 |
| P2-2 | **一键体检**：串起违禁词检测 + 标题优化 + 诊断引擎 → 单次请求输出上架前完整体检报告 | 新增 `POST /api/v1/preflight/check`；实测虚拟商品文案输出违禁词+标题+描述三类问题 |
| P2-3 | **商品利润/定价助手**（贴合你的虚拟商品场景）：结合市场均价分布 + 成本，给出定价区间与"低价冲量 vs 高毛利"策略 | 新增 `POST /api/v1/pricing/suggest` |

### P3 — 体验与稳定性

| # | 任务 |
|---|------|
| P3-1 | 采集失败原因在**前端显式展示**（当前 `source: "none"` 对用户等于静默失败） |
| P3-2 | `scheduler.py` 的 `datetime.utcnow()` 全量替换为 timezone-aware（消除 25 处 DeprecationWarning） |
| P3-3 | 前端补 3 个页面：扫码登录、采集任务历史、上架前体检 |
| P3-4 | README 增补：Linux 无显示器环境的 xvfb 启动方式（本次踩坑点） |

---

## 4. 排期建议

| 阶段 | 内容 | 依赖 |
|------|------|------|
| 第一周 | P0-1、P0-2、P0-4（让采集真正出数据） | 无 |
| 第二周 | P0-3 扫码登录 + P0-5 代理池（稳定性） | P0-1/2 |
| 第三周 | P1-1 ~ P1-5（评分可信度） | P0 |
| 第四周 | P2 知识层 + P3 体验 | P1 |

**关键路径**：P0-2（cookie 注入）→ P0-4（解析校准）→ P1（评分）。P0-3 扫码登录可与 P1 并行。

---

## 5. 优先级排序的判断依据

我把「修复采集」排在「加新功能」之前，理由是实测结果：

- 现有 8 大模块**代码完整度很高**（诊断引擎 410 行、违禁词 351 行、192 词库、前端 8 页面），**继续加模块的边际收益低**
- 但这些模块**共享同一个数据入口**。入口不通，8 个模块同时失效
- 实测 `products` 表 **0 行** —— 选品中心、看板 6 个维度、竞品监控当前都拿不到数据

换句话说：**现在最该做的不是"再加一个功能"，而是"把已有的 8 个功能喂上数据"。**

---

## 6. 风险与合规提示

⚠️ **技术风险**：闲鱼反爬策略会持续演进。P0-1 的绕过手段（headed 模式）不是永久方案，需预留指纹对抗升级空间。P0-5 代理池是长期必需，不是可选项。

⚠️ **合规风险**：本工具涉及平台数据采集，务必遵守闲鱼平台规则与相关法律法规；建议仅用于个人店铺运营分析，控制频率、避免商业化转售采集数据。README 中已有免责声明，建议在 UI 中同样提示。

⚠️ **账号风险**：真实登录 cookie 意味着账号存在被风控可能。建议使用**专门的运营小号**，避免主账号登录采集环境。

---

## 附：本次实测命令清单（可复现）

```bash
# 测试
cd backend && python -m pytest -q                    # 84 passed
# 前端
cd frontend && npx vite build                        # built in 9.42s
# 违禁词
curl -X POST .../banned/check -d '{"text":"专业破解版 Office 2024 永久激活 加微信"}'
# 采集（失败复现）
curl -X POST .../crawl/search -d '{"keyword":"考研数学资料"}'   # source: none
# 反爬验证（关键）
xvfb-run -a python diag_stealth.py                  # headed 通过，headless 被拦
```
