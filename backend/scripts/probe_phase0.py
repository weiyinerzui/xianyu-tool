"""Phase 0 数据探针（v0.5.0 类型化选品方案，见 docs/DEV_PLAN_v0.5.0-类型化选品.md）。

用法（backend 目录，Windows PowerShell）：
    python -m scripts.probe_phase0 all      # 推荐：按成本升序跑全部，自动门控
    python -m scripts.probe_phase0 grep     # 仅 Stage 1：离线 grep 已有样本（零风险，秒级）
    python -m scripts.probe_phase0 capture  # 仅 Stage 2：浏览器全量抓包（会弹窗口）
    python -m scripts.probe_phase0 detail   # 仅 Stage 3：详情 API httpx 实测（≤5 次，间隔 4s）
    python -m scripts.probe_phase0 catid    # 仅 Stage 4：5 个差异词 cCatId 分布（L1 httpx）
    python -m scripts.probe_phase0 report   # 仅 Stage 5：小样本类型报告

设计原则（Phase 0 评审结论）：
- 探针按成本升序执行；Stage 1（grep 已有样本文件）零风险且其结果可能直接改写架构
  —— 若想要数以显示字符串（"514人想要"）藏在搜索响应的非 want 命名字段里，
  早期诊断（只收纯数字值 + 字段名含 want）会漏掉它。
- Stage 2 仅在 Stage 1 无果时执行（`all` 自动门控）。
- Stage 3 详情 API 走 httpx 签名路径（复用 L1 机制），先于浏览器验证——
  关键问题是"无浏览器能否拿到"。
- 任何阶段失败不阻断其他阶段；产物全部落盘 scripts/probe_out/。
- 控制台输出尽量 ASCII 安全；中文乱码不影响结果，以 probe_out/ 文件为准。
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:  # Windows 控制台中文安全
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

OUT = Path(__file__).resolve().parent / "probe_out"
SAMPLES = {
    "l1": Path(__file__).resolve().parent / "_sample_response.json",  # inspect_want_num 产物
    "l2": Path(__file__).resolve().parent / "_l2_sample_response.json",  # inspect_want_l2 产物
}
SEARCH_API_NAME = "mtop.taobao.idlemtopsearch.pc.search"
DETAIL_API_NAME = "mtop.taobao.idle.pc.detail"
DETAIL_URL = "https://h5api.m.goofish.com/h5/mtop.taobao.idle.pc.detail/1.0/"
# 已知商品 ID（用户端历次实测输出中出现过的真实 ID）
KNOWN_ITEM_IDS = [
    "1071372202842", "1073794772566", "729250874602", "1079625092040",
    "1048204884222", "1088553828602", "1001243689293", "956287387316",
]
# 已知 DOM 想要数（用户端最终验证时实测：用于详情 API 交叉校验）
KNOWN_DOM_WANTS = {"1073794772566": 303, "1079625092040": 90}
# Stage 4 差异词：教程 / 软件 / 卡券 / 学习资料 / 服务
CATID_KEYWORDS = ["python教程", "ps安装包", "视频会员", "考研资料", "代做"]
BODY_CAP = 200_000  # 抓包单响应体保存上限


# ---------- 通用工具 ----------

def _save(name: str, content: str) -> Path:
    OUT.mkdir(exist_ok=True)
    p = OUT / name
    p.write_text(content, encoding="utf-8")
    return p


def _load_json(p: Path) -> Any:
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return None


def _walk(obj: Any, pred: Any, path: str = "$", out: list | None = None, depth: int = 0) -> list:
    """递归收集满足 pred(key, value) 的 (path, key, value)。列表最多深入 30 个元素。"""
    if out is None:
        out = []
    if depth > 12:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}"
            try:
                if pred(k, v):
                    out.append((p, k, v))
            except Exception:  # noqa: BLE001
                pass
            if isinstance(v, (dict, list)):
                _walk(v, pred, p, out, depth + 1)
    elif isinstance(obj, list):
        for idx, v in enumerate(obj[:30]):
            _walk(v, pred, f"{path}[{idx}]", out, depth + 1)
    return out


def _ret_str(data: dict) -> str:
    try:
        return json.dumps(data.get("ret", []), ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return ""


def _pick_item_ids(n: int = 5) -> list[str]:
    """优先从已有样本取前 N 个 item_id，兜底用已知 ID 列表。"""
    for tag in ("l2", "l1"):
        p = SAMPLES[tag]
        if not p.exists():
            continue
        data = _load_json(p)
        if not data:
            continue
        items = (data.get("data", {}) or {}).get("resultList", []) or []
        ids: list[str] = []
        for it in items:
            args = (((it.get("data", {}) or {}).get("item", {}) or {}).get("main", {}) or {}).get("clickParam", {}) or {}
            args = args.get("args", {}) or {}
            iid = str(args.get("item_id") or args.get("id") or "")
            if iid:
                ids.append(iid)
        if ids:
            return ids[:n]
    return KNOWN_ITEM_IDS[:n]


# ---------- Stage 1：离线 grep（零风险） ----------

def stage_grep() -> dict:
    print("\n" + "=" * 60)
    print("[Stage 1] offline grep of existing samples (zero risk)")
    result: dict[str, Any] = {"stage": "grep", "files": {}, "hits": [], "verdict": "NOT_FOUND"}
    display_pat = "人想要"
    for tag, p in SAMPLES.items():
        info: dict[str, Any] = {"path": str(p), "exists": p.exists()}
        if not p.exists():
            print(f"  {tag}: MISSING ({p.name})")
            result["files"][tag] = info
            continue
        raw = p.read_text(encoding="utf-8", errors="replace")
        info["size"] = len(raw)
        info["known_ids_present"] = [i for i in KNOWN_ITEM_IDS if i in raw]
        if display_pat in raw:
            info["has_display_string"] = True
            data = _load_json(p)
            if data:
                for path, key, val in _walk(data, lambda k, v: isinstance(v, str) and display_pat in v):
                    hit = {"file": tag, "path": path, "value": val}
                    result["hits"].append(hit)
                    print(f"  HIT {tag} {path} = {val!r}")
        result["files"][tag] = info
        print(
            f"  {tag}: size={info['size']} display_string={info.get('has_display_string', False)} "
            f"known_ids={len(info['known_ids_present'])}/{len(KNOWN_ITEM_IDS)}"
        )
    if result["hits"]:
        result["verdict"] = "SEARCH_RESPONSE_DISPLAY_STRING"
        print(f"  VERDICT: WANT_SOURCE=SEARCH_RESPONSE_DISPLAY_STRING ({len(result['hits'])} hits)")
        print("  -> L1 可直接从搜索响应提取想要数，无需浏览器/详情 API（吞吐问题就此解除）")
    else:
        print("  VERDICT: NOT_FOUND in saved samples -> Stage 2 full capture needed")
    _save("stage1_grep.json", json.dumps(result, ensure_ascii=False, indent=1))
    return result


# ---------- Stage 2：浏览器全量抓包（仅 Stage 1 无果时） ----------

async def stage_capture() -> dict:
    print("\n" + "=" * 60)
    print("[Stage 2] full browser capture (ALL mtop/h5api, no URL filter)")
    print("  >> 将弹出浏览器窗口 1-2 分钟，请勿操作它 <<")
    result: dict[str, Any] = {"stage": "capture", "entries": [], "ssr_html": False, "dom_html": False, "verdict": "NOT_FOUND"}
    try:
        from urllib.parse import quote, urljoin

        from playwright.async_api import async_playwright  # pyright: ignore[reportMissingImports]

        from app.services.playwright_runtime import browser_launch_kwargs, context_kwargs
        from app.services.session_manager import get_session
    except Exception as e:  # noqa: BLE001
        print(f"  SKIP: import/launch deps unavailable: {e}")
        result["verdict"] = "SKIP_DEPS"
        _save("stage2_capture.json", json.dumps(result, ensure_ascii=False, indent=1))
        return result

    cookies: dict[str, str] = {}
    try:
        sess = get_session()
        if sess.path.exists():
            cookies = sess.get_cookies() or {}
    except Exception:  # noqa: BLE001
        pass
    print(f"  cookies: {len(cookies)}")

    entries: list[dict] = []

    async def on_response(resp: Any) -> None:
        url = resp.url or ""
        if "mtop" not in url and "h5api" not in url:
            return
        try:
            body = await resp.text()
        except Exception:  # noqa: BLE001
            return
        m = re.search(r"/h5/(mtop\.[a-z0-9.]+)/", url)
        api = m.group(1) if m else (url.split("?")[0][-60:])
        entries.append(
            {
                "api": api,
                "url": url[:200],
                "size": len(body),
                "has_display": "人想要" in body,
                "body": body[:BODY_CAP],
            }
        )

    keyword = "python教程"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(**browser_launch_kwargs(p.chromium))
            ctx = await browser.new_context(**context_kwargs(cookies))
            page = await ctx.new_page()
            page.on("response", on_response)

            # --- 2a. 搜索页 ---
            url = f"https://www.goofish.com/search?q={quote(keyword)}"
            print(f"  open search page: q={keyword}")
            nav = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(6000)
            try:  # 触发懒加载
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2500)
            except Exception:  # noqa: BLE001
                pass
            ssr_html = ""
            if nav is not None:
                try:
                    ssr_html = await nav.text()
                except Exception:  # noqa: BLE001
                    ssr_html = ""
            result["ssr_html"] = "人想要" in ssr_html
            dom_html = await page.content()
            result["dom_html"] = "人想要" in dom_html
            _save("stage2_ssr_html.txt", ssr_html[:BODY_CAP])
            _save("stage2_dom_html.txt", dom_html[:BODY_CAP])
            print(f"  search page: SSR_html_has_display={result['ssr_html']} DOM_html_has_display={result['dom_html']}")

            # --- 2b. 搜索联想词（S0.3 信号①） ---
            n_before = len(entries)
            try:
                loc = None
                for sel in ('input[placeholder*="搜索"]', 'input[placeholder*="宝贝"]', 'input[type="text"]'):
                    cand = page.locator(sel).first
                    if await cand.count():
                        loc = cand
                        break
                if loc is None:
                    print("  suggest: no input found -> SKIP")
                else:
                    await loc.fill("")
                    try:
                        await loc.press_sequentially("py", delay=180)
                    except AttributeError:
                        await loc.type("py", delay=180)  # type: ignore[attr-defined]
                    await page.wait_for_timeout(2500)
                    new_apis = sorted({e["api"] for e in entries[n_before:]})
                    print(f"  suggest: new apis after typing: {new_apis or '(none captured)'}")
                    result["suggest_apis"] = new_apis
            except Exception as e:  # noqa: BLE001
                print(f"  suggest: SKIP ({type(e).__name__}: {e})")

            # --- 2c. 详情页（相似宝贝信号 + 详情页 DOM） ---
            n_before = len(entries)
            try:
                cards = page.locator('a[href*="/item?id="]')
                if await cards.count():
                    href = await cards.first.get_attribute("href")
                    if href:
                        durl = urljoin(page.url, href)
                        print(f"  open detail page: {durl[:80]}")
                        nav2 = await page.goto(durl, wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(8000)
                        detail_html = await page.content()
                        detail_has = "人想要" in detail_html
                        _save("stage2_detail_html.txt", detail_html[:BODY_CAP])
                        new_apis = sorted({e["api"] for e in entries[n_before:]})
                        print(f"  detail page: DOM_has_display={detail_has} new apis: {new_apis or '(none)'}")
                        result["detail_dom_has_display"] = detail_has
                        result["detail_new_apis"] = new_apis
                    else:
                        print("  detail page: first card has no href -> SKIP")
                else:
                    print("  detail page: no cards rendered (login wall?) -> SKIP")
            except Exception as e:  # noqa: BLE001
                print(f"  detail page: SKIP ({type(e).__name__}: {e})")

            # --- 2d. 他人店铺货架（S0.3 信号③：personal 页是否公开在售列表） ---
            n_before = len(entries)
            try:
                seller_links = page.locator('a[href*="personal"]')
                if await seller_links.count():
                    href = await seller_links.first.get_attribute("href")
                    if href:
                        surl = urljoin(page.url, href)
                        print(f"  open shop shelf: {surl[:80]}")
                        await page.goto(surl, wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(6000)
                        shelf_html = await page.content()
                        shelf_cards = await page.locator('a[href*="/item?id="]').count()
                        _save("stage2_shelf_html.txt", shelf_html[:BODY_CAP])
                        new_apis = sorted({e["api"] for e in entries[n_before:]})
                        print(f"  shop shelf: cards={shelf_cards} new apis: {new_apis or '(none)'}")
                        result["shelf_cards"] = shelf_cards
                        result["shelf_new_apis"] = new_apis
                    else:
                        print("  shop shelf: personal link has no href -> SKIP")
                else:
                    print("  shop shelf: no personal link on detail page -> SKIP")
            except Exception as e:  # noqa: BLE001
                print(f"  shop shelf: SKIP ({type(e).__name__}: {e})")

            await browser.close()
    except Exception as e:  # noqa: BLE001
        print(f"  SKIP: browser launch/nav failed: {type(e).__name__}: {e}")
        result["verdict"] = "SKIP_LAUNCH"

    # --- 2d. 落盘 + 判定 ---
    manifest = []
    for idx, e in enumerate(entries):
        fname = f"stage2_capture_{idx:02d}_{re.sub(r'[^a-z0-9.]', '_', e['api'])}.txt"
        _save(fname, e["body"])
        manifest.append({"idx": idx, "api": e["api"], "size": e["size"], "has_display": e["has_display"], "file": fname})
    result["entries"] = manifest
    want_bearers = [e for e in entries if e["has_display"]]
    if want_bearers:
        apis = sorted({e["api"] for e in want_bearers})
        if SEARCH_API_NAME in apis:
            result["verdict"] = "SEARCH_RESPONSE_LATER_CALL"
        else:
            result["verdict"] = f"SEPARATE_API:{'|'.join(apis)}"
    elif result.get("ssr_html"):
        result["verdict"] = "SSR_EMBEDDED"
    elif result.get("dom_html"):
        result["verdict"] = "DOM_ONLY_CAPTURE_GAP"
    print(f"  captured {len(entries)} mtop/h5api responses; want_bearers={len(want_bearers)}")
    print(f"  VERDICT: WANT_SOURCE={result['verdict']}")
    _save("stage2_capture.json", json.dumps(result, ensure_ascii=False, indent=1))
    return result


# ---------- Stage 3：详情 API httpx 实测（≤5 次，间隔 4s，遇风控即停） ----------

async def stage_detail() -> dict:
    print("\n" + "=" * 60)
    print("[Stage 3] detail API via httpx signing path (no browser)")
    print("  cap: 5 items, 4s apart, STOP at first risk error (this is also S0.4 baseline)")
    result: dict[str, Any] = {"stage": "detail", "items": [], "verdict": "NO_DATA"}
    try:
        import httpx

        from app.crawlers.httpx_crawler import (
            APP_KEY,
            RISK_KEYWORDS,
            TOKEN_FAIL_KEYWORDS,
            HttpxCrawler,
            generate_sign,
            get_h5_token,
            set_h5_token,
        )
    except Exception as e:  # noqa: BLE001
        print(f"  SKIP: import failed: {e}")
        _save("stage3_detail_summary.json", json.dumps(result, ensure_ascii=False, indent=1))
        return result

    ids = _pick_item_ids(5)
    print(f"  items: {ids}")
    crawler = HttpxCrawler()
    headers = crawler._headers()
    cookies = crawler._user_cookies()
    if cookies:
        set_h5_token(cookies.get("_m_h5_tk", ""))

    import hashlib

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, trust_env=False) as client:
        if not get_h5_token():
            try:
                await crawler._bootstrap_token(client, headers)
            except Exception as e:  # noqa: BLE001
                print(f"  token bootstrap failed: {e}")
        for i, iid in enumerate(ids):
            if i:
                await asyncio.sleep(4)
            t0 = time.time()
            t = str(int(time.time() * 1000))
            data_val = json.dumps({"itemId": iid}, separators=(",", ":"))
            log_id = hashlib.md5(f"{iid}{t}".encode()).hexdigest()[:16]
            params = {
                "jsv": "2.7.2",
                "appKey": APP_KEY,
                "t": t,
                "sign": generate_sign(t, get_h5_token(), data_val),
                "v": "1.0",
                "type": "originaljson",
                "accountSite": "xianyu",
                "dataType": "json",
                "timeout": "20000",
                "api": DETAIL_API_NAME,
                "sessionOption": "AutoLoginOnly",
                "spm_cnt": "a21ybx.item.want.0.0",
                "spm_pre": f"a21ybx.item.want.1.{log_id}",
                "log_id": log_id,
            }
            try:
                resp = await client.post(
                    DETAIL_URL, params=params, headers=headers, cookies=cookies or None, data={"data": data_val}
                )
            except Exception as e:  # noqa: BLE001
                print(f"  {iid}: request error {type(e).__name__}: {e}")
                break
            try:
                crawler._absorb_token(resp)
            except Exception:  # noqa: BLE001
                pass
            latency = int((time.time() - t0) * 1000)
            try:
                data = resp.json()
            except Exception:  # noqa: BLE001
                print(f"  {iid}: HTTP {resp.status_code} non-JSON")
                continue
            ret = _ret_str(data)
            rec: dict[str, Any] = {"item_id": iid, "latency_ms": latency, "ret": ret[:150]}
            _save(f"stage3_detail_{iid}.json", json.dumps(data, ensure_ascii=False, indent=1))
            if any(k in ret for k in RISK_KEYWORDS):
                rec["risk"] = True
                result["items"].append(rec)
                print(f"  {iid}: RISK [{ret[:100]}] -> STOP whole stage")
                print(f"  S0.4 baseline: risk appeared after {i + 1} calls")
                result["verdict"] = "RISK_BLOCKED"
                result["risk_after_calls"] = i + 1
                break
            if "SUCCESS" not in ret:
                if any(k in ret for k in TOKEN_FAIL_KEYWORDS):
                    print(f"  {iid}: token fail [{ret[:80]}] -> re-bootstrap, skip this item")
                    try:
                        await crawler._bootstrap_token(client, headers, force=True)
                    except Exception:  # noqa: BLE001
                        pass
                    rec["token_fail"] = True
                    result["items"].append(rec)
                    continue
                print(f"  {iid}: ret not SUCCESS: {ret[:100]}")
                result["items"].append(rec)
                continue
            # SUCCESS：全量字段扫描（不预设 itemDO 路径——wantNum 教训）
            fields = [
                {"path": p, "value": v if not isinstance(v, (dict, list)) else str(v)[:80]}
                for p, k, v in _walk(data, lambda k, v: re.search(r"(?i)want|collect|browse", str(k)) and not isinstance(v, (dict, list)))
            ]
            raw = json.dumps(data, ensure_ascii=False)
            rec["fields"] = fields
            rec["has_display_string"] = "人想要" in raw
            if iid in KNOWN_DOM_WANTS:
                rec["dom_want_crosscheck"] = KNOWN_DOM_WANTS[iid]
            result["items"].append(rec)
            keys = sorted({f["path"].split(".")[-1] for f in fields})
            extra = f" dom_want={rec['dom_want_crosscheck']}" if "dom_want_crosscheck" in rec else ""
            print(f"  {iid}: SUCCESS {latency}ms field_keys={keys}{extra}")

    # 汇总
    ok_items = [r for r in result["items"] if r.get("fields")]
    if ok_items:
        all_keys = sorted({f["path"].split(".")[-1] for r in ok_items for f in r["fields"]})
        result["verdict"] = "OK_FIELDS"
        result["field_keys"] = all_keys
        result["avg_latency_ms"] = int(sum(r["latency_ms"] for r in ok_items) / len(ok_items))
        print(f"  VERDICT: DETAIL_API=OK_FIELDS keys={all_keys} avg_latency={result['avg_latency_ms']}ms")
    elif result["verdict"] != "RISK_BLOCKED":
        print("  VERDICT: DETAIL_API=NO_DATA (no successful call)")
    _save("stage3_detail_summary.json", json.dumps(result, ensure_ascii=False, indent=1))
    return result


# ---------- Stage 4：cCatId 分布（5 差异词，L1 httpx） ----------

async def stage_catid() -> dict:
    print("\n" + "=" * 60)
    print("[Stage 4] cCatId distribution across 5 diverse keywords (L1 httpx)")
    result: dict[str, Any] = {"stage": "catid", "keywords": {}, "verdict": "NO_DATA"}
    try:
        import app.crawlers.httpx_crawler as hc
    except Exception as e:  # noqa: BLE001
        print(f"  SKIP: import failed: {e}")
        _save("stage4_catid_summary.json", json.dumps(result, ensure_ascii=False, indent=1))
        return result

    captured: dict[str, Any] = {}
    orig = hc.parse_search_api_json

    def spy(json_data: dict, category: str = "") -> list:
        captured["raw"] = json_data
        return orig(json_data, category)

    hc.parse_search_api_json = spy
    try:
        crawler = hc.HttpxCrawler()
        for kw in CATID_KEYWORDS:
            captured.pop("raw", None)
            rec: dict[str, Any] = {}
            try:
                products = await crawler.search(kw)
            except Exception as e:  # noqa: BLE001
                rec["error"] = f"{type(e).__name__}: {e}"[:120]
                result["keywords"][kw] = rec
                print(f"  {kw}: ERROR {rec['error']}")
                continue
            rec["products"] = len(products or [])
            raw = captured.get("raw")
            if raw:
                items = (raw.get("data", {}) or {}).get("resultList", []) or []
                rec["items"] = len(items)
                cc: Counter = Counter()
                tc: Counter = Counter()
                for it in items:
                    args = (((it.get("data", {}) or {}).get("item", {}) or {}).get("main", {}) or {}).get("clickParam", {}) or {}
                    args = args.get("args", {}) or {}
                    cc[str(args.get("cCatId", "?"))] += 1
                    tc[str(args.get("tbCatId", "?"))] += 1
                rec["cCatId"] = dict(cc.most_common())
                rec["tbCatId"] = dict(tc.most_common(8))
                names = [
                    {"path": p, "value": str(v)[:60]}
                    for p, k, v in _walk(raw, lambda k, v: re.search(r"(?i)catname|categoryname|cat_name|category_name|breadcrumb|channelname", str(k)))
                ]
                rec["name_fields"] = names[:5]
                if products:
                    ps = sorted(float(p.price) for p in products if p.price)
                    if ps:
                        rec["price"] = {"p25": ps[len(ps) // 4], "p50": ps[len(ps) // 2], "p75": ps[3 * len(ps) // 4]}
            result["keywords"][kw] = rec
            print(f"  {kw}: products={rec.get('products', 0)} cCatId={rec.get('cCatId', {})}")
    finally:
        hc.parse_search_api_json = orig

    # 粒度判定：各词的 cCatId 众数是否互相区分
    modals: dict[str, str] = {}
    for kw, rec in result["keywords"].items():
        dist = rec.get("cCatId") or {}
        if dist:
            modals[kw] = max(dist.items(), key=lambda kv: kv[1] or 0)[0]
    if modals:
        modal_ids = list(modals.values())
        unique_modals = len(set(modal_ids))
        result["modals"] = modals
        result["unique_modal_count"] = unique_modals
        any_names = any(rec.get("name_fields") for rec in result["keywords"].values())
        result["has_name_fields"] = any_names
        if unique_modals >= len(modals) - 1:
            result["verdict"] = "GRANULAR"
        elif unique_modals >= 2:
            result["verdict"] = "PARTIAL"
        else:
            result["verdict"] = "COARSE"
        print(f"  modals={modals} unique={unique_modals}/{len(modals)} name_fields={any_names}")
        print(f"  VERDICT: CCATID={result['verdict']}")
    _save("stage4_catid_summary.json", json.dumps(result, ensure_ascii=False, indent=1))
    return result


# ---------- Stage 5：小样本类型报告（预期对齐用） ----------

def stage_report() -> dict:
    print("\n" + "=" * 60)
    print("[Stage 5] small-sample type report (format demo for expectation alignment)")
    s1 = _load_json(OUT / "stage1_grep.json") or {}
    s2 = _load_json(OUT / "stage2_capture.json") or {}
    s3 = _load_json(OUT / "stage3_detail_summary.json") or {}
    s4 = _load_json(OUT / "stage4_catid_summary.json") or {}
    lines: list[str] = [
        "# Phase 0 小样本类型报告（格式演示）",
        "",
        f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "> **代理指标声明**：想要数 ≠ 销量；浏览数 ≠ 曝光。所有数值仅代表搜索可见性（基于搜索结果页样本）。",
        "> 本报告用真实但量小的数据演示最终格式；Phase 1+ 会扩大采样并加入跨词覆盖度/类型动能。",
        "",
        "## 数据源判定",
        "",
        f"- WANT_SOURCE（想要数来源）：{s1.get('verdict', '?')}"
        + (f" / capture: {s2.get('verdict', '?')}" if s2 else ""),
        f"- DETAIL_API（详情 API）：{s3.get('verdict', '?')}"
        + (f"（字段 {s3.get('field_keys')}，均延迟 {s3.get('avg_latency_ms')}ms）" if s3.get("field_keys") else ""),
        f"- CCATID（类目粒度）：{s4.get('verdict', '?')}"
        + (f"（众数映射 {s4.get('modals')}）" if s4.get("modals") else ""),
        "",
        "## 类型代理词卡片（每词 ≈ 一个类型的代理样本）",
        "",
    ]
    for kw, rec in (s4.get("keywords") or {}).items():
        lines.append(f"### {kw}")
        if rec.get("error"):
            lines.append(f"- 采集失败：{rec['error']}")
            lines.append("")
            continue
        lines.append(f"- 样本量：{rec.get('items', 0)} 条（<30 时正式版会标「数据不足」）")
        if rec.get("cCatId"):
            lines.append(f"- cCatId 分布：{rec['cCatId']}")
        if rec.get("tbCatId"):
            lines.append(f"- tbCatId 分布：{rec['tbCatId']}")
        if rec.get("price"):
            pr = rec["price"]
            lines.append(f"- 价格带：p25={pr['p25']} / p50={pr['p50']} / p75={pr['p75']}")
        if rec.get("name_fields"):
            lines.append(f"- 类目名字段：{rec['name_fields']}")
        lines.append("")
    detail_items = [r for r in (s3.get("items") or []) if r.get("fields")]
    if detail_items:
        lines.append("## 详情 API 交叉验证（前 5 项）")
        lines.append("")
        for r in detail_items:
            want_fields = [f for f in r["fields"] if re.search(r"(?i)want", f["path"])]
            cross = f"（DOM 实测想要数={r['dom_want_crosscheck']}）" if "dom_want_crosscheck" in r else ""
            lines.append(f"- {r['item_id']}：{want_fields or '无 want 字段'} {cross}")
        lines.append("")
    lines.append("## 结论与下一步")
    lines.append("")
    lines.append(f"- 想要数通路：{s1.get('verdict', '?')}")
    lines.append(f"- 详情 API：{s3.get('verdict', '?')}")
    lines.append(f"- 类目粒度：{s4.get('verdict', '?')} → 聚合层采用 {'cCatId' if s4.get('verdict') == 'GRANULAR' else '用户桶（标题规则）为主，cCatId 辅助'}")
    lines.append("")
    p = _save("report.md", "\n".join(lines))
    print(f"  saved: {p}")
    print("  NOTE: 格式演示（真实小样本）。确认此格式即对齐 Phase 1+ 的最终报告形态。")
    return {"stage": "report", "path": str(p)}


# ---------- 调度 ----------

async def _all() -> None:
    print("Phase 0 probe: running ALL stages in cost-ascending order with gating")
    print(f"artifacts dir: {OUT}")
    g: dict = {}
    c: dict = {}
    d: dict = {}
    k: dict = {}
    r: dict = {}
    try:
        g = stage_grep()
    except Exception as e:  # noqa: BLE001
        print(f"  Stage 1 CRASHED: {e}")
    if g.get("verdict") == "SEARCH_RESPONSE_DISPLAY_STRING":
        print("\n[gating] Stage 1 found the source -> SKIP Stage 2 (browser) entirely")
    else:
        try:
            c = await stage_capture()
        except Exception as e:  # noqa: BLE001
            print(f"  Stage 2 CRASHED: {e}")
    try:
        d = await stage_detail()
    except Exception as e:  # noqa: BLE001
        print(f"  Stage 3 CRASHED: {e}")
    if d.get("verdict") == "RISK_BLOCKED":
        print("\n[gating] Stage 3 hit RISK control -> SKIP Stage 4 (protect the account, no more requests)")
        print("         Stage 4 can be re-run later: python -m scripts.probe_phase0 catid")
    else:
        try:
            k = await stage_catid()
        except Exception as e:  # noqa: BLE001
            print(f"  Stage 4 CRASHED: {e}")
    try:
        r = stage_report()
    except Exception as e:  # noqa: BLE001
        print(f"  Stage 5 CRASHED: {e}")
    print("\n" + "=" * 60)
    print("==== PHASE 0 PROBE VERDICT ====")
    print(f"WANT_SOURCE : {g.get('verdict', '?')}" + (f" / capture: {c.get('verdict', '-')}" if c else " (capture skipped)"))
    print(f"DETAIL_API  : {d.get('verdict', '?')}" + (f" keys={d.get('field_keys')}" if d.get("field_keys") else ""))
    print(f"CCATID      : {k.get('verdict', '?')}" + (f" modals={k.get('modals')}" if k.get("modals") else ""))
    print(f"REPORT      : {r.get('path', '-')}")
    print("NEXT: 把以上输出 + probe_out/report.md 内容贴回给维护者")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "grep":
        stage_grep()
    elif cmd == "capture":
        asyncio.run(stage_capture())
    elif cmd == "detail":
        asyncio.run(stage_detail())
    elif cmd == "catid":
        asyncio.run(stage_catid())
    elif cmd == "report":
        stage_report()
    elif cmd == "all":
        asyncio.run(_all())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
