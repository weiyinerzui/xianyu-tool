# 无显示器（Linux 服务器 / Docker / WSL）部署说明

采集功能依赖真实浏览器，而闲鱼会**识别 headless 浏览器**。本文件说明如何正确部署。

## 为什么不能直接用 headless

实测（2026-10）闲鱼有两层拦截：

| 层级 | 表现 | 解决办法 |
|------|------|---------|
| 浏览器指纹层 | 页面返回「非法访问 / 请使用正常浏览器访问闲鱼」 | `headless=False` + xvfb 虚拟显示器 |
| 业务风控层 | mtop 接口返回 `RGV587_ERROR`，搜索结果**根本不渲染**（页面停在「加载中」） | 导入登录 cookie 或扫码登录 |

只解决第一层还不够 —— **未登录时搜索页永远不渲染商品**。
工具会明确报错提示你登录，而不是静默返回 0 条。

## 方案 A：xvfb-run（推荐）

```bash
apt install xvfb                 # 一次性安装
cd backend
source .venv/bin/activate
xvfb-run -a uvicorn app.main:app --port 8000
```

## 方案 B：Docker 里配虚拟显示器

```dockerfile
RUN apt-get update && apt-get install -y xvfb
CMD ["xvfb-run", "-a", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## 方案 C：配好真实显示器 / VNC

有桌面环境时直接 `uvicorn app.main:app` 即可，扫码登录也更方便（能看到二维码窗口）。

## 扫码登录（数据采集的前置条件）

登录态是采集数据的**必要条件**，有两种方式：

### 方式 1：扫码登录（推荐）

```bash
curl "http://127.0.0.1:8000/api/v1/session/qr-login?timeout=180"
```

会用浏览器打开闲鱼登录页 → 用闲鱼 App 扫码 → 登录成功后 cookie 自动落盘
（`~/.xianyu-ops/cookies.json`，权限 0600），后续采集免登录。

### 方式 2：手动导入 cookie

从浏览器 DevTools → Network → 任意 goofish 请求 → 复制 Cookie 请求头，粘贴进来：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/session/import \
  -H 'Content-Type: application/json' \
  -d '{"raw":"cookie2=xxx; unb=xxx; cna=xxx; _m_h5_tk=xxx"}'
```

支持 dict / 数组 / `{cookies:[...]}` 包装对象 / Cookie 头字符串四种格式。

## 环境变量

| 变量 | 说明 | 默认 |
|------|------|------|
| `XIANYU_OPS_CRAWLER_HEADLESS` | 是否无头模式。**闲鱼会识别 headless，建议保持 false** | `false` |
| `XIANYU_OPS_CRAWLER_AUTO_XVFB` | 无 DISPLAY 时提示使用 xvfb | `true` |
| `XIANYU_OPS_CRAWLER_USER_DATA_DIR` | 持久化浏览器 profile 目录（复用登录态与设备指纹） | 空 |
| `XIANYU_OPS_CRAWLER_PROXIES` | 代理池，逗号分隔。命中风控时轮换 | 空 |
| `XIANYU_OPS_CRAWLER_SEARCH_MAX_PAGES` | 单关键词采集页数（每页 30 条） | `3` |

## 降低风控命中率

1. **用运营小号登录**，不要用主账号（真实登录 cookie 有账号风控风险）
2. 配置代理池：风控是 IP 级行为，单 IP 连续请求必然被拦
3. 降低采集频率：`crawler_request_delay_min/max` 控制请求间隔（默认 3~8 秒）

## 常见报错对照

| 报错 | 原因 | 处理 |
|------|------|------|
| `Missing X server or $DISPLAY` | 无显示器且未用 xvfb | 用 `xvfb-run -a` 启动 |
| `搜索结果未渲染：闲鱼要求登录后才返回数据` | 缺登录态 | 扫码登录或导入 cookie |
| `被闲鱼反爬拦截（非法访问页）` | 指纹被识别 | 确认 headless=false；配代理 |
| `RGV587_ERROR` | IP 级风控 | 配置代理池；降低频率 |