"""
Agent Tools — 出行决策 Agent 的地图工具集

所有工具都封装高德地图 Web 服务接口（https://restapi.amap.com/v3）。
密钥只从环境变量 AMAP_API_KEY 读取，禁止硬编码。

为什么用 async：
  /chat 是 SSE 流式接口，整条链路在同一个事件循环里跑。
  同步 httpx 调用会阻塞事件循环，导致流式输出卡顿，因此这里统一用
  AsyncClient；Agent SDK 的 @function_tool 原生支持 async 函数。

返回约定：
  - 成功：JSON 字符串，字段已裁剪到模型真正需要的部分
  - 失败：{"error": "...", "hint": "..."}，让模型据此向用户说明原因，
          而不是自己编造地点或距离。
"""

import asyncio
import json
import os
from typing import Annotated

import httpx
from agents import function_tool

try:  # 作为包导入（本地运行时 / 平台运行时）
    from . import _fixtures
except ImportError:  # 单文件直跑（tests/offline_check.py 用 spec_from_file_location 加载）
    import importlib.util
    import pathlib

    _spec = importlib.util.spec_from_file_location(
        "_fixtures", pathlib.Path(__file__).with_name("_fixtures.py")
    )
    _fixtures = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_fixtures)

AMAP_BASE = "https://restapi.amap.com/v3"
HTTP_TIMEOUT = 10.0

# 高德 POI 分类码：060100 = 购物中心（商场）
MALL_TYPES = "060100"

# 演示模式每次工具的假延迟（秒）：让前端的"工具灯牌依次点亮"看得出先后顺序
MOCK_LATENCY = 0.25

# 识别为"已配置"的占位值，避免把模板里的假 Key 当成真的
PLACEHOLDER_KEYS = {"", "your-api-key", "your_key", "sk-xxx", "xxx"}


# ========== 内部工具函数 ==========
def mock_enabled() -> bool:
    """AMAP_MOCK=1/true/yes/on 时走内置演示数据，不需要高德 Key。"""
    return (os.getenv("AMAP_MOCK") or "").strip().lower() in {"1", "true", "yes", "on"}


def _api_key() -> str:
    """读取高德 Key，缺失时抛出可读错误。"""
    key = (os.getenv("AMAP_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("AMAP_API_KEY 未配置：请在 .env 中填写高德 Web 服务 Key")
    return key


async def _call(path: str, params: dict) -> dict:
    """异步调用高德接口并统一处理业务错误码。

    高德返回 status=1 表示成功；status=0 时 info 里是错误原因
    （常见：INVALID_USER_KEY / DAILY_QUERY_OVER_LIMIT / INVALID_PARAMS）。

    AMAP_MOCK=1 时不发请求，改用内置演示数据（见 _fixtures.py），
    返回结构与真实接口一致，只是多一个 `_mock: True` 标记。
    """
    if mock_enabled():
        await asyncio.sleep(MOCK_LATENCY)
        return {**_fixtures.route(path, params), "_mock": True}

    payload = {"key": _api_key(), "output": "JSON", **params}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.get(f"{AMAP_BASE}{path}", params=payload)
        resp.raise_for_status()
        data = resp.json()

    if str(data.get("status")) != "1":
        info = data.get("info", "UNKNOWN_ERROR")
        raise RuntimeError(f"高德接口返回错误：{info}（infocode={data.get('infocode')}）")
    return data


def _dump(payload: dict, data: dict | None = None) -> str:
    """统一的 JSON 序列化出口；演示模式下补上 source 标记。

    带 source 的意义：模型看到 "mock" 就知道这不是真实高德结果，
    会在回答里注明"演示数据"；同时前端调试面板也能一眼看出数据来源。
    """
    if data and data.get("_mock"):
        payload["source"] = "mock"
        payload["source_note"] = "内置演示数据（AMAP_MOCK=1），非高德实时查询结果"
    return json.dumps(payload, ensure_ascii=False)


def _err(e: Exception, hint: str) -> str:
    """把异常转成模型可读的 JSON 错误对象。"""
    return json.dumps(
        {"error": f"{type(e).__name__}: {e}", "hint": hint},
        ensure_ascii=False,
    )


def _coord(poi: dict) -> str:
    """取 POI 的 location 字段（"lng,lat" 字符串）。"""
    return poi.get("location", "")


def _to_int(value) -> int:
    """高德部分字段以字符串返回，统一转 int，失败返回 0。"""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _text(value) -> str:
    """高德空字段有时返回 []，统一转成字符串。"""
    return value if isinstance(value, str) else ""


# ========== 工具 1：地址解析 ==========
@function_tool
async def resolve_location(
    address: Annotated[str, "用户提到的地点原文，例如「红莲南路地铁站」「深圳北站」「万象城」"],
    city: Annotated[str, "限定城市名，可为空。用户没说城市时留空，由高德从地址推断"] = "",
) -> str:
    """把用户描述的地点解析成经纬度和所在城市。

    任何涉及「我在哪里」「附近」的请求都必须先调用本工具拿到坐标，
    不得凭常识猜测坐标。返回后用其中的 location 字段（"经度,纬度"）
    作为 search_nearby_malls / search_brand_in_mall / measure_distance 的坐标参数。
    """
    try:
        data = await _call("/geocode/geo", {"address": address, "city": city})
        geocodes = data.get("geocodes") or []
        if not geocodes:
            return _dump(
                {
                    "error": f"未找到地点「{address}」",
                    "hint": "请让用户补充更精确的位置（加城市名或附近地标）",
                },
                data,
            )

        top = geocodes[0]
        return _dump(
            {
                "input": address,
                "formatted_address": top.get("formatted_address"),
                "province": top.get("province"),
                "city": top.get("city") or top.get("province"),
                "district": top.get("district"),
                "location": top.get("location"),  # "lng,lat"
                "level": top.get("level"),
                "candidates": [
                    {
                        "formatted_address": g.get("formatted_address"),
                        "location": g.get("location"),
                        "district": g.get("district"),
                    }
                    for g in geocodes[1:4]
                ],
            },
            data,
        )
    except Exception as e:
        return _err(e, "检查 AMAP_API_KEY 是否有效、是否开通了「地理编码」服务")


# ========== 工具 2：周边商场检索 ==========
@function_tool
async def search_nearby_malls(
    location: Annotated[str, "起点坐标，格式为「经度,纬度」，来自 resolve_location 的 location 字段"],
    radius: Annotated[int, "搜索半径（米），默认 3000，最大 50000"] = 3000,
    keyword: Annotated[str, "商场关键词，默认「商场」，可换成「购物中心」「百货」等"] = "商场",
) -> str:
    """以给定坐标为圆心搜索附近的商场，按距离由近到远返回。

    返回每个商场的名称、地址、直线距离（米）、坐标，供后续逐个核对品牌门店。
    推荐时的远近排序应以本工具返回的 distance_m 为依据，不要自行估算。
    """
    try:
        data = await _call(
            "/place/around",
            {
                "location": location,
                "keywords": keyword,
                "types": MALL_TYPES,
                "radius": min(int(radius), 50000),
                "offset": 20,
                "page": 1,
                "extensions": "base",
                "sortrule": "distance",
            },
        )

        pois = data.get("pois") or []
        malls = []
        for poi in pois:
            biz_ext = poi.get("biz_ext") or {}
            malls.append(
                {
                    "name": poi.get("name"),
                    "address": _text(poi.get("address")),
                    "distance_m": _to_int(poi.get("distance")),
                    "location": _coord(poi),
                    "type": _text(poi.get("type")),
                    "rating": biz_ext.get("rating") or "",
                }
            )

        if not malls:
            return _dump(
                {
                    "error": "该范围内没有搜到商场",
                    "hint": "建议放大 radius 后重试，或改用「购物中心」「百货」等关键词",
                },
                data,
            )

        return _dump(
            {"origin": location, "radius": radius, "count": len(malls), "malls": malls},
            data,
        )
    except Exception as e:
        return _err(e, "检查坐标格式是否为「经度,纬度」，以及周边搜索配额是否用尽")


# ========== 工具 3：商场内品牌核对 ==========
@function_tool
async def search_brand_in_mall(
    brand: Annotated[str, "要高德检索的品牌名，例如「倍轻松」「西厅村屋」"],
    mall_location: Annotated[str, "商场坐标，格式为「经度,纬度」，来自 search_nearby_malls 的 location 字段"],
    radius: Annotated[int, "以商场坐标为中心的核对半径（米），默认 500"] = 500,
) -> str:
    """核对指定商场附近（通常是商场内部）是否存在某个品牌的门店。

    高德没有「商场内品牌清单」接口，因此以商场坐标为圆心做 POI 周边检索来近似判断。
    返回 matched 字段：true 表示命中，false 表示半径内无该品牌门店。
    判断「既有 A 又有 B」这类需求时，必须对每个品牌分别调用本工具。
    """
    try:
        data = await _call(
            "/place/around",
            {
                "location": mall_location,
                "keywords": brand,
                "radius": min(int(radius), 50000),
                "offset": 10,
                "page": 1,
                "extensions": "base",
                "sortrule": "distance",
            },
        )

        pois = data.get("pois") or []
        stores = [
            {
                "name": poi.get("name"),
                "address": _text(poi.get("address")),
                "distance_m": _to_int(poi.get("distance")),
                "location": _coord(poi),
                "type": _text(poi.get("type")),
            }
            for poi in pois
        ]

        return _dump(
            {
                "brand": brand,
                "mall_location": mall_location,
                "radius": radius,
                "matched": bool(stores),
                "store_count": len(stores),
                "stores": stores[:5],
                "note": "distance_m 是门店到商场坐标的直线距离，可用于判断是否在商场内",
                "limitation": "半径检索是近似判断：命中不代表一定在商场内部，未命中也不代表商场内没有专柜",
            },
            data,
        )
    except Exception as e:
        return _err(e, "检查品牌名是否过于生僻，或周边搜索配额是否用尽")


# ========== 工具 4：距离测量 ==========
@function_tool
async def measure_distance(
    origin: Annotated[str, "起点坐标，格式为「经度,纬度」"],
    destination: Annotated[str, "终点坐标，格式为「经度,纬度」"],
) -> str:
    """测量起点到终点的驾车距离和预计耗时。

    当用户问「哪个更近」「过去要多久」时调用，作为排序和说明的量化依据。
    search_nearby_malls 给的是直线距离，本工具给的是实际路网距离，两者不要混用。
    """
    try:
        data = await _call(
            "/distance",
            {"origins": origin, "destination": destination, "type": 1},
        )
        results = data.get("results") or []
        if not results:
            return _dump(
                {"error": "未返回距离结果", "hint": "坐标可能超出国内范围或格式有误"},
                data,
            )

        first = results[0]
        duration = _to_int(first.get("duration"))
        return _dump(
            {
                "origin": origin,
                "destination": destination,
                "distance_m": _to_int(first.get("distance")),
                "duration_s": duration,
                "duration_min": round(duration / 60, 1),
                "mode": "驾车（高德默认路线规划）",
            },
            data,
        )
    except Exception as e:
        return _err(e, "检查起终点坐标格式，距离测量接口单次仅支持一个终点")


# 注册给 Agent 的工具清单
TRAVEL_TOOLS = [
    resolve_location,
    search_nearby_malls,
    search_brand_in_mall,
    measure_distance,
]
