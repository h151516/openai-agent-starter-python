"""
本地无模型演示规划器（只给 local_dev.py 用，不参与线上部署）
==================================================

为什么需要它
------------
课程里两个 Key 通常拿不到先后顺序：高德 Key 要实名，Makers 的模型 Key 要开
通项目。在两者都空的时候，前端能打开、能发消息，但一问就回 401，看不出
这个 Agent 到底做了什么 —— 演示、截图、验收都会卡住。

本文件是一条**只在本机生效**的降级路径：没有模型可用时，用一个规则式规划器
按同样的顺序调用真实的四个工具，再把结果拼成固定的回答，并通过**完全相同
的 SSE 协议**推给前端。因此：

  - 前端一行不改，工具灯牌照样依次点亮，逐字输出照样有；
  - 调用的还是 agents/_tools.py 里的四个工具，业务逻辑是真的；
  - 只有"把结果组织成自然语言"这一步从模型换成了模板，所以每条回答开头
    都会明确标注「本地演示模式 · 无模型」。

不启用的条件：
  - .env 里有真实的 AI_GATEWAY_API_KEY（那就走真正的 Agent）；
  - 或显式设置 LOCAL_DEMO=0。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import AsyncGenerator

# 逐字输出节奏（秒/块）。为了让"流式"看得见，但整体不要拖太久。
STREAM_DELAY = 0.02
CHUNK = 3

BANNER = "> ⚙️ **本地演示模式**：未配置模型 Key，这条回答由内置规则生成；地图数据来源见每张表下方标注。\n\n"

# 可识别的品牌（和 _fixtures.py 对齐，另外给几个常见写法兜底）
KNOWN_BRANDS = ["倍轻松", "西厅村屋", "Nike", "耐克", "苹果", "Apple", "华为", "小米", "优衣库", "海底捞"]

# 可识别的位置关键词（命中即认为用户报了位置）
KNOWN_PLACES = ["红莲南路", "深圳大学", "西单", "广安门", "宣武门", "深圳北站"]

# "只要求一个品牌 / 不要求都有"这类改口
ANY_MODE_HINTS = ["不要求", "不用都", "只要一个", "任意一个", "有一个就行", "一个就行", "不必同时"]

# 距离偏好
NEAR_HINTS = ["更近", "最近的", "近一点", "离我近"]

PLACE_PATTERNS = [
    re.compile(r"(?:我在|我在位于|我在)?([\u4e00-\u9fa5A-Za-z0-9]{2,15}?)(?:附近|周边|旁边|这边|那儿|那里)"),
    re.compile(r"我在([\u4e00-\u9fa5A-Za-z0-9]{2,15}?)[，,。\s]"),
]

BOTH_PATTERN = re.compile(r"既有(.{1,10}?)又有(.{1,10}?)(?:的|，|,|。|\s|$)")


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ============================================================
# 一、意图解析
# ============================================================
def _find_brands(text: str) -> list[str]:
    """按出现顺序去重取品牌名（长名优先，避免「苹果」截断「苹果园」之类）。"""
    hits: list[tuple[int, str]] = []
    for brand in sorted(KNOWN_BRANDS, key=len, reverse=True):
        for m in re.finditer(re.escape(brand), text):
            hits.append((m.start(), brand))
    hits.sort()
    out: list[str] = []
    for _, b in hits:
        if b not in out:
            out.append(b)
    # 去重同义词
    if "耐克" in out and "Nike" in out:
        out.remove("耐克")
    return out


def _find_place(text: str) -> str:
    for place in KNOWN_PLACES:
        if place in text:
            return place
    for pattern in PLACE_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1)
    return ""


def _history_text(history: list[dict]) -> str:
    """把历史里的用户发言拼成一串，用来在多轮里找回位置/品牌。"""
    return "\n".join(m.get("content", "") for m in history if m.get("role") == "user")


# ============================================================
# 二、工具调用（复用 agents/_tools.py）
# ============================================================
async def _invoke(tool, args: dict) -> dict:
    """走 @function_tool 包装后的正式入口，和线上跑的是同一段代码。"""
    from agents import RunConfig
    from agents.tool_context import ToolContext

    payload = json.dumps(args, ensure_ascii=False)
    ctx = ToolContext(
        None,
        tool_name=tool.name,
        tool_call_id="local-demo",
        tool_arguments=payload,
        run_config=RunConfig(),
    )
    raw = await tool.on_invoke_tool(ctx, payload)
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {"error": raw}


def _fmt_m(distance_m: int) -> str:
    return f"{distance_m} 米" if distance_m < 1000 else f"{distance_m / 1000:.1f} 公里"


# ============================================================
# 三、主流程
# ============================================================
async def stream(
    tools: dict,
    message: str,
    history: list[dict],
) -> AsyncGenerator[str, None]:
    """按「定位 → 找商场 → 核品牌 → 量距离」的顺序跑一遍，并逐字吐出结论。"""

    prev = _history_text(history)
    both_text = f"{prev}\n{message}"

    brands = _find_brands(message) or _find_brands(prev)
    place = _find_place(message) or _find_place(prev)
    any_mode = any(h in message for h in ANY_MODE_HINTS)

    # 品牌不在已知词表里（比如「星巴克」「无印良品」）时，用「既有A又有B」句式兜底抽取
    if not brands:
        m = BOTH_PATTERN.search(message) or BOTH_PATTERN.search(prev)
        if m:
            brands = [g.strip() for g in m.groups() if g.strip()]

    # ---- 缺位置：先追问，不要瞎猜 ----
    if not place:
        text = BANNER + "请先告诉我你在哪儿 —— 比如「我在红莲南路地铁站附近」，我才能查周边商场。"
        async for frame in _speak(text):
            yield frame
        return

    # ---- 1. 定位 ----
    yield sse("tool_called", {"tool": "resolve_location"})
    geo = await _invoke(tools["resolve_location"], {"address": place})
    if geo.get("error"):
        async for frame in _speak(BANNER + f"定位「{place}」失败了：{geo['error']}。换个更精确的说法（加城市名或地标）再试。"):
            yield frame
        return
    origin = geo["location"]

    # ---- 2. 找商场 ----
    yield sse("tool_called", {"tool": "search_nearby_malls"})
    near = await _invoke(tools["search_nearby_malls"], {"location": origin, "radius": 3000})
    malls = near.get("malls") or []
    if not malls:
        city = (geo.get("city") or "").strip()
        mock_on = (os.getenv("AMAP_MOCK") or "").strip().lower() in ("1", "true", "yes", "on")
        if mock_on and city and "北京" not in city:
            # 演示样例只铺了北京西城一个片区，别的城市必然查空，得说清楚原因
            text = (
                BANNER
                + f"已定位到「{geo.get('formatted_address') or place}」，"
                f"但**内置演示数据只覆盖北京西城区红莲南路一带**，{city}这边没有样例商场。\n\n"
                "两条路：\n"
                "1. 换成「我在红莲南路地铁站附近，想找既有倍轻松又有西厅村屋的商场」——能复现完整链路；\n"
                "2. 在 `.env` 填上 `AMAP_API_KEY`、把 `AMAP_MOCK` 改成 `0`，就能查真实周边。"
            )
        else:
            text = BANNER + f"「{place}」周边 3 公里没查到商场，可以让我放大到 5 公里再试。"
        async for frame in _speak(text):
            yield frame
        return

    # ---- 3. 核品牌（逐个商场 × 逐个品牌） ----
    matrix: list[dict] = []
    for mall in malls:
        hits: dict[str, bool] = {}
        stores: dict[str, str] = {}
        for brand in brands:
            yield sse("tool_called", {"tool": "search_brand_in_mall"})
            r = await _invoke(
                tools["search_brand_in_mall"],
                {"brand": brand, "mall_location": mall["location"]},
            )
            hits[brand] = bool(r.get("matched"))
            if r.get("stores"):
                stores[brand] = r["stores"][0]["name"]
        matrix.append({"mall": mall, "hits": hits, "stores": stores})

    # ---- 4. 排序与筛选 ----
    if brands:
        key = all if not any_mode else any
        picked = [row for row in matrix if key(row["hits"].values())]
        mode_note = "至少命中一个品牌" if any_mode else "要求的品牌全部命中"
    else:
        picked = matrix
        mode_note = "用户没指定品牌，按距离排序"

    picked.sort(key=lambda row: row["mall"]["distance_m"])
    if not picked:
        names = "、".join(brands) or "该品牌"
        async for frame in _speak(
            BANNER + f"{place} 周边 3 公里的商场里，没有同时包含「{names}」的。"
            "可以把范围放大到 5 公里，或告诉我只要求其中一个品牌。"
        ):
            yield frame
        return

    best = picked[0]

    # ---- 5. 量距离（给最优候选算驾车） ----
    yield sse("tool_called", {"tool": "measure_distance"})
    dist = await _invoke(
        tools["measure_distance"],
        {"origin": origin, "destination": best["mall"]["location"]},
    )

    # ---- 6. 组织回答 ----
    source = near.get("source")
    src_note = "（演示样例数据，非高德实时）" if source == "mock" else ""
    lines: list[str] = [BANNER]

    lines.append(f"**结论**：推荐 **{best['mall']['name']}**，直线距离约 {_fmt_m(best['mall']['distance_m'])}{src_note}。\n")
    if brands:
        lines.append(f"筛选口径：{mode_note}（{'、'.join(brands)}）。\n")

    head = "| 商场 | " + " | ".join(brands) + " | 直线距离 |" if brands else "| 商场 | 直线距离 |"
    sep = "|---|" + "---|" * len(brands) + "---|" if brands else "|---|---|"
    lines.append(head)
    lines.append(sep)
    for row in picked:
        cells = [row["mall"]["name"]]
        for brand in brands:
            cells.append("✅" if row["hits"].get(brand) else "❌")
        cells.append(_fmt_m(row["mall"]["distance_m"]))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    if dist.get("distance_m"):
        lines.append(
            f"到 {best['mall']['name']} 驾车约 {_fmt_m(dist['distance_m'])}"
            f"（{dist['duration_min']} 分钟）。\n"
        )

    reasons: list[str] = []
    if brands and not any_mode:
        reasons.append(f"是唯一同时有 {'、'.join(brands)} 的候选")
    elif brands:
        reasons.append(f"在命中 {'、'.join(b for b in brands if best['hits'].get(b))} 的候选里距离最近")
    reasons.append(f"位于 {geo.get('district') or geo.get('city') or place}")
    lines.append("**理由**：" + "；".join(reasons) + "。")

    skipped = [row for row in matrix if row not in picked]
    if skipped:
        lines.append(
            "\n**没入选的**："
            + "、".join(
                f"{row['mall']['name']}（{'、'.join(b for b, ok in row['hits'].items() if not ok)} 未命中）"
                for row in skipped
            )
            + "。"
        )

    if source == "mock":
        lines.append("\n> 数据来源：内置演示样例（`AMAP_MOCK=1`）。填上真实高德 Key 后同一套工具会返回实时结果。")

    async for frame in _speak("\n".join(lines)):
        yield frame


async def _speak(text: str) -> AsyncGenerator[str, None]:
    """把整段回答按小块推给前端，模拟模型的逐字流式输出。"""
    for i in range(0, len(text), CHUNK):
        yield sse("text_delta", {"delta": text[i : i + CHUNK]})
        await asyncio.sleep(STREAM_DELAY)


def enabled(api_key: str) -> bool:
    """有真 Key 就走真模型；LOCAL_DEMO=0 强制关闭本兜底。"""
    import os

    flag = (os.getenv("LOCAL_DEMO") or "").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    placeholder = {"", "your-api-key", "your_key", "sk-xxx", "xxx"}
    return (api_key or "").strip() in placeholder
