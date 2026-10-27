"""
离线自检 —— 不联网、不需要真实 Key。

验证三件事：
1. 四个工具都被 @function_tool 正确注册，名字和参数 schema 符合预期
2. 走真实 _call 链路的响应解析正确（用 httpx.MockTransport 伪造高德响应）
3. 高德业务错误 / 空结果 / 缺 Key / 网络异常时，返回的都是
   {"error","hint"}，不会把异常抛给 Agent 层

运行：
    ./.venv/Scripts/python.exe tests/offline_check.py
"""

import asyncio
import importlib.util
import json
import os
import sys
from types import SimpleNamespace

import httpx as httpx_mod

# 伪造一个 Key，避免 _api_key() 直接失败；真实请求不会发出（transport 是 mock）
os.environ.setdefault("AMAP_API_KEY", "offline-test-key")

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS_PATH = os.path.join(HERE, "..", "agents", "_tools.py")

# 用文件路径加载，绕开「项目 agents/ 目录 vs SDK agents 包」的同名问题
spec = importlib.util.spec_from_file_location("_tools_under_test", TOOLS_PATH)
tools_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools_mod)

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def use_transport(handler) -> None:
    """把被测模块里的 httpx.AsyncClient 换成挂了 MockTransport 的版本。

    只替换 tools_mod 看到的 httpx，不影响全局 httpx。
    """
    transport = httpx_mod.MockTransport(handler)

    class MockedClient(httpx_mod.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    tools_mod.httpx = SimpleNamespace(AsyncClient=MockedClient)


def json_handler(payload: dict, status_code: int = 200):
    def handler(request: httpx_mod.Request) -> httpx_mod.Response:
        return httpx_mod.Response(status_code, json=payload)

    return handler


async def invoke(tool, args: dict) -> str:
    """调用一个 @function_tool 包装后的工具。

    SDK 0.24 的 on_invoke_tool 需要真实 ToolContext（会读 ctx.tool_name /
    ctx.run_config），所以这里造一个最小可用的上下文。
    """
    from agents import RunConfig
    from agents.tool_context import ToolContext

    payload = json.dumps(args, ensure_ascii=False)
    ctx = ToolContext(
        None,
        tool_name=tool.name,
        tool_call_id="offline-test",
        tool_arguments=payload,
        run_config=RunConfig(),
    )
    return await tool.on_invoke_tool(ctx, payload)


# ---------- 1. 工具注册检查 ----------
print("\n=== 1. 工具注册 ===")
expected = [
    "resolve_location",
    "search_nearby_malls",
    "search_brand_in_mall",
    "measure_distance",
    "plan_walking_route",
]
names = [t.name for t in tools_mod.TRAVEL_TOOLS]
check("五个工具数量正确", len(names) == 5, f"实际 {names}")
check("工具名与提示词一致", names == expected, f"实际 {names}")

for tool in tools_mod.TRAVEL_TOOLS:
    props = list(tool.params_json_schema.get("properties", {}).keys())
    check(f"{tool.name} 描述足够长", bool(tool.description and len(tool.description) > 20))
    print(f"        参数: {props}")


# ---------- 2. 正常响应解析（走真实 _call） ----------
MALL_RESPONSE = {
    "status": "1",
    "info": "OK",
    "pois": [
        {
            "name": "西单大悦城",
            "address": "西单北大街131号",
            "distance": "820",
            "location": "116.374,39.912",
            "type": "购物中心;商场",
            "biz_ext": {"rating": "4.5"},
        },
        {
            "name": "老佛爷百货",
            "address": "西单北大街110号",
            "distance": "1250",
            "location": "116.371,39.913",
            "type": "购物中心;商场",
            "biz_ext": {"rating": "4.3"},
        },
    ],
}

BRAND_HIT = {
    "status": "1",
    "info": "OK",
    "pois": [
        {
            "name": "倍轻松(西单大悦城店)",
            "address": "西单北大街131号西单大悦城B1",
            "distance": "45",
            "location": "116.3741,39.9121",
            "type": "购物中心;专卖店",
        }
    ],
}

GEO_RESPONSE = {
    "status": "1",
    "info": "OK",
    "geocodes": [
        {
            "formatted_address": "北京市西城区红莲南路",
            "province": "北京市",
            "city": "北京市",
            "district": "西城区",
            "location": "116.341,39.884",
            "level": "地铁站",
        }
    ],
}

DIST_RESPONSE = {"status": "1", "info": "OK", "results": [{"distance": "2100", "duration": "720"}]}

WALK_RESPONSE = {
    "status": "1",
    "info": "OK",
    "count": "1",
    "route": {
        "paths": [
            {
                "distance": "1800",
                "duration": "1440",
                "steps": [
                    {"instruction": "向南步行", "distance": "500", "duration": "400"},
                    {"instruction": "右转", "distance": "1300", "duration": "1040"},
                ],
            }
        ]
    },
}


async def run_parse_tests():
    print("\n=== 2. 正常响应解析 ===")

    use_transport(json_handler(MALL_RESPONSE))
    raw = await invoke(tools_mod.search_nearby_malls, {"location": "116.341,39.884", "radius": 3000})
    data = json.loads(raw)
    check("商场数正确", data.get("count") == 2, raw[:120])
    check("按距离取到 820m", data["malls"][0]["distance_m"] == 820)
    check("返回可回传的坐标", data["malls"][0]["location"] == "116.374,39.912")

    use_transport(json_handler(BRAND_HIT))
    raw = await invoke(
        tools_mod.search_brand_in_mall, {"brand": "倍轻松", "mall_location": "116.374,39.912"}
    )
    data = json.loads(raw)
    check("品牌命中 matched=true", data.get("matched") is True, raw[:120])
    check("门店距离正确", data["stores"][0]["distance_m"] == 45)

    use_transport(json_handler({"status": "1", "info": "OK", "pois": []}))
    raw = await invoke(
        tools_mod.search_brand_in_mall, {"brand": "西厅村屋", "mall_location": "116.374,39.912"}
    )
    data = json.loads(raw)
    check("未命中 matched=false", data.get("matched") is False)
    check("未命中带 limitation 说明", "limitation" in data)

    use_transport(json_handler(GEO_RESPONSE))
    raw = await invoke(tools_mod.resolve_location, {"address": "红莲南路地铁站"})
    data = json.loads(raw)
    check("坐标解析正确", data.get("location") == "116.341,39.884", raw[:120])
    check("城市识别正确", data.get("city") == "北京市")

    use_transport(json_handler(DIST_RESPONSE))
    raw = await invoke(
        tools_mod.measure_distance, {"origin": "116.341,39.884", "destination": "116.374,39.912"}
    )
    data = json.loads(raw)
    check("距离 2100m", data.get("distance_m") == 2100)
    check("耗时换算 12.0 分钟", data.get("duration_min") == 12.0)

    use_transport(json_handler(WALK_RESPONSE))
    raw = await invoke(
        tools_mod.plan_walking_route, {"origin": "116.341,39.884", "destination": "116.374,39.912"}
    )
    data = json.loads(raw)
    check("步行距离 1800m", data.get("distance_m") == 1800, raw[:120])
    check("步行耗时 24.0 分钟", data.get("duration_min") == 24.0, raw[:120])
    check("分段指引只回传前 6 段", data.get("step_count") == 2 and len(data.get("steps", [])) == 2)
    check("未截断时不带误导标记", data.get("steps_truncated") is False)

    # 空路线（如跨海/超远）要返回 error，不能编路径
    use_transport(json_handler({"status": "1", "info": "OK", "count": "0", "route": {"paths": []}}))
    raw = await invoke(
        tools_mod.plan_walking_route, {"origin": "116.3,39.8", "destination": "121.4,31.2"}
    )
    data = json.loads(raw)
    check("无步行路线返回 error", "error" in data, raw[:120])
    check("error 附带可执行 hint", bool(data.get("hint")))


# ---------- 3. 异常处理 ----------
async def run_error_tests():
    print("\n=== 3. 异常处理 ===")

    # 高德业务错误（HTTP 200 但 status=0）
    use_transport(json_handler({"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001"}))
    raw = await invoke(tools_mod.resolve_location, {"address": "某地"})
    data = json.loads(raw)
    check("业务错误转成 error 字段", "error" in data, raw[:160])
    check("错误信息保留高德原因", "INVALID_USER_KEY" in data.get("error", ""), raw[:160])
    check("附带可执行 hint", bool(data.get("hint")))

    # HTTP 500
    use_transport(json_handler({"message": "boom"}, status_code=500))
    raw = await invoke(tools_mod.search_nearby_malls, {"location": "116.3,39.8"})
    data = json.loads(raw)
    check("HTTP 500 也转成 error", "error" in data, raw[:160])

    # 网络异常
    def raise_error(request):
        raise httpx_mod.ConnectError("connection refused")

    use_transport(raise_error)
    raw = await invoke(tools_mod.search_nearby_malls, {"location": "116.3,39.8"})
    data = json.loads(raw)
    check("网络异常不抛出，转成 error", "error" in data, raw[:160])

    # 空结果
    use_transport(json_handler({"status": "1", "info": "OK", "pois": []}))
    raw = await invoke(tools_mod.search_nearby_malls, {"location": "116.3,39.8"})
    data = json.loads(raw)
    check("空结果不给假数据", "error" in data and "malls" not in data)

    # 缺 Key
    saved = os.environ.pop("AMAP_API_KEY", None)
    raw = await invoke(tools_mod.resolve_location, {"address": "某地"})
    data = json.loads(raw)
    check("缺 Key 返回明确错误", "AMAP_API_KEY" in data.get("error", ""), raw[:160])
    if saved:
        os.environ["AMAP_API_KEY"] = saved


async def main():
    await run_parse_tests()
    await run_error_tests()


asyncio.run(main())

print(f"\n{'=' * 40}")
print(f"通过 {PASS} 项，失败 {FAIL} 项")
sys.exit(1 if FAIL else 0)
