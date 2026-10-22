"""
离线演示数据（AMAP_MOCK=1 时启用）
========================================

为什么需要这个文件
------------------
高德 Web 服务 Key 要实名 + 建应用，课上/课前经常拿不到；没有 Key 时四个工具
全部返回 error，Agent 只能演示"报错路径"，没法演示真实推荐效果。

本文件内置一套**北京西城区红莲南路地铁站**周边的样例数据（手册 6.1 / 6.2
两个场景的取景地），在 `_call()` 里按接口路径 + 关键词分流，返回与高德
`/v3` 接口**完全同构**的 JSON。因此：

  - 工具层、Agent 层、前端、SSE 全链路一行都不用改；
  - 命中规则（半径过滤、按距离排序、品牌命中判定）走的是真实代码路径，
    只是数据源换成了本地字典；
  - 所有结果都会带 `source: "mock"` 标记，模型会在回答里说明是演示数据，
    不会把样例当成真实地点汇报给用户。

数据不是真实高德的快照，只保证「场景一 / 场景二 有确定答案」：

  场景一（既有倍轻松又有西厅村屋）→ 广安门华联购物中心（约 790m）
  场景二（不要求两个品牌，只看近）→ 天虹商场(广安门店)（约 600m）

关掉方式：把 `.env` 里的 `AMAP_MOCK` 删掉或设为 0，即恢复真实高德调用。
"""

from __future__ import annotations

import math

# 演示圆心：红莲南路地铁站（北京西城区）
DEMO_CENTER = "116.3359,39.8835"
DEMO_CENTER_NAME = "红莲南路地铁站"

# ========== 地理编码 ==========
GEOCODES = {
    "红莲南路": {
        "formatted_address": "北京市西城区红莲南路",
        "province": "北京市",
        "city": "北京市",
        "district": "西城区",
        "location": DEMO_CENTER,
        "level": "地铁站",
    },
    "深圳大学": {
        "formatted_address": "广东省深圳市南山区南海大道3688号",
        "province": "广东省",
        "city": "深圳市",
        "district": "南山区",
        "location": "113.9343,22.5333",
        "level": "兴趣点",
    },
}

# ========== 商场（type 060100 购物中心） ==========
MALLS = [
    {
        "name": "天虹商场(广安门店)",
        "address": "西城区广安门外大街305号",
        "location": "116.3405,39.8862",
        "type": "购物中心;商场",
        "biz_ext": {"rating": "4.2"},
    },
    {
        "name": "广安门华联购物中心",
        "address": "西城区广安门内大街202号",
        "location": "116.3320,39.8899",
        "type": "购物中心;商场",
        "biz_ext": {"rating": "4.4"},
    },
    {
        "name": "国华商场",
        "address": "西城区宣武门西大街甲129号",
        "location": "116.3300,39.8780",
        "type": "购物中心;商场",
        "biz_ext": {"rating": "3.9"},
    },
    {
        "name": "庄胜崇光百货(SOGO)",
        "address": "西城区宣武门外大街8号",
        "location": "116.3665,39.8993",
        "type": "购物中心;商场",
        "biz_ext": {"rating": "4.1"},
    },
    {
        "name": "西单大悦城",
        "address": "西城区西单北大街131号",
        "location": "116.3730,39.9120",
        "type": "购物中心;商场",
        "biz_ext": {"rating": "4.6"},
    },
]

# ========== 品牌门店（keywords 精确匹配，模拟"/place/around?keywords=品牌"） ==========
BRAND_STORES = {
    "倍轻松": [
        {
            "name": "倍轻松(天虹商场广安门店)",
            "address": "西城区广安门外大街305号天虹商场B1",
            "location": "116.3406,39.8861",
            "type": "购物中心;专卖店",
        },
        {
            "name": "倍轻松(广安门华联店)",
            "address": "西城区广安门内大街202号华联购物中心3F",
            "location": "116.3321,39.8898",
            "type": "购物中心;专卖店",
        },
        {
            "name": "倍轻松(西单大悦城店)",
            "address": "西城区西单北大街131号西单大悦城5F",
            "location": "116.3731,39.9119",
            "type": "购物中心;专卖店",
        },
    ],
    "西厅村屋": [
        {
            "name": "西厅村屋(广安门华联店)",
            "address": "西城区广安门内大街202号华联购物中心2F",
            "location": "116.3319,39.8900",
            "type": "购物中心;专卖店",
        },
        {
            "name": "西厅村屋(庄胜崇光店)",
            "address": "西城区宣武门外大街8号SOGO 4F",
            "location": "116.3664,39.8992",
            "type": "购物中心;专卖店",
        },
    ],
    "Nike": [
        {
            "name": "Nike(西单大悦城店)",
            "address": "西城区西单北大街131号西单大悦城4F",
            "location": "116.3732,39.9121",
            "type": "购物中心;专卖店",
        }
    ],
}


# ========== 内部工具 ==========
def _parse(location: str) -> tuple[float, float]:
    """"经度,纬度" → (lng, lat)；格式不对抛 ValueError，交给工具层的异常兜底。"""
    lng_s, lat_s = location.split(",")
    return float(lng_s), float(lat_s)


def _haversine_m(a: str, b: str) -> int:
    """两点直线距离（米）。用真实球面公式，半径过滤才有意义。"""
    lng1, lat1 = _parse(a)
    lng2, lat2 = _parse(b)
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return int(2 * r * math.asin(math.sqrt(h)))


def _with_distance(items: list[dict], origin: str) -> list[dict]:
    """给每条 POI 补上 distance 字段并按距离升序（对齐高德 sortrule=distance）。"""
    out = []
    for item in items:
        row = dict(item)
        row["distance"] = str(_haversine_m(origin, item["location"]))
        out.append(row)
    out.sort(key=lambda r: int(r["distance"]))
    return out


# ========== 对外：按接口路径返回同构响应 ==========
def route(path: str, params: dict) -> dict:
    """模拟高德 /v3 接口。参数与原接口一致，返回值也一致（status/info/...）。"""

    # ---- 1. 地理编码 ----
    if path == "/geocode/geo":
        address = (params.get("address") or "").strip()
        hit = next(
            (v for k, v in GEOCODES.items() if k and k in address),
            None,
        )
        if hit is None:
            return {"status": "1", "info": "OK", "count": "0", "geocodes": []}
        return {"status": "1", "info": "OK", "count": "1", "geocodes": [dict(hit)]}

    # ---- 2. 周边检索（商场 / 品牌共用） ----
    if path == "/place/around":
        origin = params.get("location") or DEMO_CENTER
        radius = int(params.get("radius") or 3000)
        keyword = (params.get("keywords") or "").strip()

        source = BRAND_STORES.get(keyword)
        if source is None:
            # 非品牌关键词：按商场集合返回，顺带兼容"购物中心""百货"等写法
            source = MALLS

        pois = [p for p in _with_distance(source, origin) if int(p["distance"]) <= radius]
        return {"status": "1", "info": "OK", "count": str(len(pois)), "pois": pois}

    # ---- 3. 距离测量 ----
    if path == "/distance":
        origin = params.get("origins") or ""
        dest = params.get("destination") or ""
        straight = _haversine_m(origin, dest)
        # 驾车距离 ≈ 直线 × 1.35，速度按 28km/h 折算，数字看起来才像真的
        drive = int(straight * 1.35)
        duration = int(drive / (28 * 1000 / 3600))
        return {
            "status": "1",
            "info": "OK",
            "results": [{"origin_id": "1", "dest_id": "1", "distance": str(drive), "duration": str(duration)}],
        }

    raise RuntimeError(f"mock 未覆盖的接口：{path}")
