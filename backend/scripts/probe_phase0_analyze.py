"""S0.1b 零成本分析：读取 Phase 0 已落盘产物，判定宽层想要数来源。

用法（backend 目录，无任何网络请求）：
    python -m scripts.probe_phase0_analyze

回答三个问题（全部只读 scripts/probe_out/ 已有文件）：
1. SEARCH_RESPONSE_LATER_CALL 的"后一次调用"到底是哪一次？
   想要数以什么形式存在（wantNum 非零 / "N人想要"显示串 / 纯单位字段误报）？
   首次调用与后续调用的 clickParam.args 差异是什么（翻页？参数变化？）
2. 详情 API browseCnt / collectCnt 的完整 JSON 路径
   （report.md 只打印了 want 系字段，没打印 browse/collect 的路径）
3. S0.3 发现信号汇总（联想词 / 详情页 / 店铺货架）——已在 capture manifest 里

背景（Phase 0 探针用户机实测 verdict）：
  WANT_SOURCE = NOT_FOUND / capture: SEARCH_RESPONSE_LATER_CALL
  DETAIL_API  = OK_FIELDS（wantCnt/browseCnt/collectCnt，211ms，无浏览器）
  CCATID      = GRANULAR（5 词 5 个互异众数）

later-call 的两种可能，结论截然不同：
  (a) 翻页/二次调用带回真实想要数 → 宽层免详情调用（最优结局）
  (b) 纯单位字段（如 wantCntUnit="人想要"）造成的误报（无数值）→ 宽层想要数仍需详情 API
"""

from __future__ import annotations

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

from scripts.probe_phase0 import _walk  # 复用同包探针的递归扫描

OUT = Path(__file__).resolve().parent / "probe_out"
SEARCH_API_NAME = "mtop.taobao.idlemtopsearch.pc.search"
# 每请求天然不同的键，args diff 时跳过（不代表行为差异）
PER_REQUEST_KEYS = {"search_id", "rn", "superlink_g_source_rn", "log_id"}
# 超长/无信息 args，打印样本时排除
_NOISE_ARGS = {"idle_mount_tai_task_abs", "unShowLabelParams"}


def _load_json(p: Path) -> Any:
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return None


def _args_of(item: dict) -> dict:
    return (
        ((((item.get("data") or {}).get("item") or {}).get("main") or {}).get("clickParam") or {}).get("args")
        or {}
    )


def _summarize_search_body(raw: str) -> dict:
    """从搜索响应体提取判定信息（JSON 解析失败时退回正则，适配 BODY_CAP 截断）。"""
    rec: dict[str, Any] = {}
    data = None
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        rec["parse"] = "TRUNCATED_OR_INVALID_JSON"
        rec["wantNum_regex"] = Counter(re.findall(r'"wantNum":"(\d+)"', raw)).most_common(6)
        rec["page_regex"] = Counter(re.findall(r'"page":"(\d+)"', raw)).most_common(4)
        rec["display_regex"] = re.findall(r"(\d+)\s*人想要", raw)[:10]
        return rec
    items = (data.get("data") or {}).get("resultList") or []
    rec["items"] = len(items)
    pages: Counter = Counter()
    wants: Counter = Counter()
    args0: dict = {}
    for i, it in enumerate(items):
        a = _args_of(it)
        if i == 0:
            args0 = a
        pages[str(a.get("page", "?"))] += 1
        wants[str(a.get("wantNum", "<none>"))] += 1
    rec["pages"] = dict(pages)
    rec["wantNum_dist"] = dict(wants.most_common(8))
    rec["args0"] = {k: str(v)[:50] for k, v in args0.items() if k not in _NOISE_ARGS}
    # 显示字符串载体分类：带数字 = 真数据；纯"人想要" = 单位字段（误报）
    bearers = _walk(data, lambda k, v: isinstance(v, str) and "人想要" in v) if data else []
    real = [(p, v) for p, _k, v in bearers if re.search(r"\d", v)]
    unit = [(p, v) for p, _k, v in bearers if not re.search(r"\d", v)]
    if real:
        rec["display_real"] = [(p, v[:40]) for p, v in real[:6]]
    if unit:
        rec["display_unit_only"] = [(p, v[:20]) for p, v in unit[:4]]
    return rec


def _args_diff(a: dict, b: dict, cap: int = 15) -> list:
    out: list[str] = []
    for k in sorted(set(a) | set(b)):
        if k in PER_REQUEST_KEYS:
            continue
        va, vb = str(a.get(k, ""))[:40], str(b.get(k, ""))[:40]
        if va != vb:
            out.append(f"{k}: {va!r} -> {vb!r}")
        if len(out) >= cap:
            break
    return out


def analyze_capture() -> dict:
    print("\n" + "=" * 60)
    print("[S0.1b-a] capture manifest analysis (zero network requests)")
    cap = _load_json(OUT / "stage2_capture.json") or {}
    result: dict[str, Any] = {"stage": "analyze_capture"}
    if not cap:
        print("  stage2_capture.json MISSING -> 先跑 python -m scripts.probe_phase0 capture")
        result["verdict"] = "NO_FILE"
        return result
    # S0.3 发现信号（已在 manifest 里，直接打印）
    for k in (
        "suggest_apis",
        "detail_new_apis",
        "detail_dom_has_display",
        "shelf_cards",
        "shelf_new_apis",
        "ssr_html",
        "dom_html",
    ):
        if k in cap:
            print(f"  {k}: {cap[k]}")
            result[k] = cap[k]
    entries = cap.get("entries") or []
    n_search = sum(1 for e in entries if SEARCH_API_NAME in e.get("api", ""))
    n_bearer = sum(1 for e in entries if e.get("has_display"))
    print(f"  entries: {len(entries)} (search API: {n_search}, display-bearers: {n_bearer})")

    calls: list[dict] = []
    for e in entries:
        if SEARCH_API_NAME not in e.get("api", ""):
            continue
        p = OUT / e["file"]
        raw = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        s = _summarize_search_body(raw)
        s["idx"] = e["idx"]
        s["has_display"] = bool(e.get("has_display"))
        calls.append(s)
        wn = s.get("wantNum_dist") or s.get("wantNum_regex") or "-"
        print(
            f"  -- call #{e['idx']} display={s['has_display']}: "
            f"items={s.get('items', '-')} pages={s.get('pages', s.get('page_regex', '-'))} wantNum={wn}"
        )
        if s.get("display_real"):
            print(f"     REAL display: {s['display_real'][:3]}")
        if s.get("display_unit_only"):
            print(f"     unit-only (false positive): {s['display_unit_only'][:2]}")
    result["search_calls"] = calls

    # args diff：首次调用 vs 后续调用（定位触发条件：翻页？参数？）
    if len(calls) >= 2:
        base = calls[0].get("args0") or {}
        for c in calls[1:]:
            d = _args_diff(base, c.get("args0") or {})
            c["args_diff_vs_first"] = d
            if d:
                print(f"  args diff call#0 -> call#{c['idx']}:")
                for line in d:
                    print(f"     {line}")

    # 判定宽层想要数来源
    real_src = None
    for c in calls:
        wn_raw = c.get("wantNum_dist") or c.get("wantNum_regex") or {}
        wn = dict(wn_raw) if isinstance(wn_raw, list) else wn_raw
        non_zero = sum(n for v, n in wn.items() if v not in ("0", "<none>", "None", ""))
        if non_zero:
            real_src = f"call#{c['idx']} wantNum non-zero x{non_zero} (pages={c.get('pages')})"
            break
        if c.get("display_real") or c.get("display_regex"):
            first = (c.get("display_real") or [["?"]])[0]
            real_src = f"call#{c['idx']} display string {first}"
            break
    if real_src:
        result["verdict"] = "L1_SEARCH_DIRECT"
        result["real_source"] = real_src
        print(f"  VERDICT: WIDE_WANT=L1_SEARCH_DIRECT ({real_src})")
        print("     -> 宽层翻页/二次调用即可拿到想要数，无需对每条调详情 API")
    elif any(c.get("display_unit_only") for c in calls):
        result["verdict"] = "FALSE_POSITIVE_UNIT_FIELD"
        print("  VERDICT: FALSE_POSITIVE — '人想要'只是单位字段（如 wantCntUnit），无数值")
        print("     -> 宽层想要数仍需详情 API（top-K enrich）或 L2-DOM 兜底")
    else:
        result["verdict"] = "INCONCLUSIVE"
        print("  VERDICT: INCONCLUSIVE — 需要 S0.1c 微探针（捕获请求参数的完整 diff）")
    return result


def analyze_detail() -> dict:
    print("\n" + "=" * 60)
    print("[S0.1b-b] detail API field paths (report.md 只打印了 want 系字段)")
    d = _load_json(OUT / "stage3_detail_summary.json") or {}
    result: dict[str, Any] = {"stage": "analyze_detail", "verdict": d.get("verdict", "NO_FILE")}
    if not d:
        print("  stage3_detail_summary.json MISSING")
        return result
    print(f"  verdict={d.get('verdict')} avg_latency={d.get('avg_latency_ms')}ms risk_after={d.get('risk_after_calls')}")
    paths: dict[str, tuple] = {}
    for r in d.get("items") or []:
        for f in r.get("fields") or []:
            key = f["path"].split(".")[-1]
            paths.setdefault(key, (f["path"], f["value"], r.get("item_id")))
    for key in sorted(paths):
        p, v, iid = paths[key]
        print(f"  {key:22s} {p} = {v!r}  (item {iid})")
    result["field_paths"] = {k: paths[k][0] for k in paths}
    result["itemDO_confirmed"] = any(".itemDO." in p for p in result["field_paths"].values())
    print(f"  itemDO structure confirmed: {result['itemDO_confirmed']}")
    return result


def main() -> None:
    cap = analyze_capture()
    det = analyze_detail()
    combined = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "capture": {k: v for k, v in cap.items() if k != "search_calls"},
        "detail": det,
    }
    print("\n" + "=" * 60)
    print("==== S0.1b ANALYZE VERDICT ====")
    print(f"WIDE_WANT_SOURCE : {cap.get('verdict', '?')}" + (f" — {cap.get('real_source')}" if cap.get("real_source") else ""))
    print(f"DETAIL_ITEMDO     : {det.get('itemDO_confirmed')} ({det.get('verdict')})")
    print("NEXT: 把以上输出贴回给维护者（零请求分析，可反复跑）")
    OUT.mkdir(exist_ok=True)
    (OUT / "analyze_s01b.json").write_text(json.dumps(combined, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved: {OUT / 'analyze_s01b.json'}")


if __name__ == "__main__":
    main()
