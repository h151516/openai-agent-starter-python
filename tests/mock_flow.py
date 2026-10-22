"""
离线全链路演练（AMAP_MOCK=1，不需要任何 Key、不联网）
==================================================

作用：把 Agent 应当执行的工具调用序列**手工跑一遍**，证明"工具层给出的数据
确实能推导出手册 6.1 / 6.2 两个场景的答案"。它不代替真实对话，但能在没有
高德 Key、没有模型 Key 的情况下验证业务逻辑是否正确。

场景一：红莲南路地铁站附近，既要倍轻松又要西厅村屋 → 应只剩一个候选
场景二：不要求两个品牌同时存在，只看距离最近 → 应比场景一更近

运行：
    ./.venv/Scripts/python.exe tests/mock_flow.py
"""

import asyncio
import importlib.util
import json
import os
import sys
from types import SimpleNamespace

os.environ["AMAP_MOCK"] = "1"
os.environ.pop("AMAP_API_KEY", None)  # 故意清空，证明演示模式不需要 Key

HERE = os.path.dirname(os.path.abspath(__file__))
AGENTS_DIR = os.path.join(HERE, "..", "agents")

# 先按包的形式挂载 agents/，让 _tools.py 里的 `from . import _fixtures` 成立
import types  # noqa: E402

pkg = types.ModuleType("flowpkg")
pkg.__path__ = [AGENTS_DIR]
sys.modules["flowpkg"] = pkg

spec = importlib.util.spec_from_file_location("flowpkg._tools", os.path.join(AGENTS_DIR, "_tools.py"))
tools_mod = importlib.util.module_from_spec(spec)
sys.modules["flowpkg._tools"] = tools_mod
spec.loader.exec_module(tools_mod)

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


async def invoke(tool, args: dict) -> dict:
    """调用 @function_tool 包装后的工具，返回解析好的 dict。"""
    from agents import RunConfig
    from agents.tool_context import ToolContext

    payload = json.dumps(args, ensure_ascii=False)
    ctx = ToolContext(
        None,
        tool_name=tool.name,
        tool_call_id="mock-flow",
        tool_arguments=payload,
        run_config=RunConfig(),
    )
    return json.loads(await tool.on_invoke_tool(ctx, payload))


async def main():
    print("\n=== 0. 演示模式开关 ===")
    check("AMAP_MOCK 生效", tools_mod.mock_enabled() is True)
    check("无 AMAP_API_KEY 也能调用", True)

    print("\n=== 1. 地点解析 ===")
    geo = await invoke(tools_mod.resolve_location, {"address": "红莲南路地铁站"})
    check("解析出坐标", geo.get("location") == "116.3359,39.8835", str(geo)[:120])
    check("识别城市为北京市", geo.get("city") == "北京市", str(geo)[:120])
    check("标注数据来源为 mock", geo.get("source") == "mock", str(geo)[:120])
    origin = geo["location"]

    print("\n=== 2. 周边商场（3km） ===")
    malls = await invoke(tools_mod.search_nearby_malls, {"location": origin, "radius": 3000})
    names = [m["name"] for m in malls.get("malls", [])]
    print(f"        命中 {malls.get('count')} 个：")
    for m in malls["malls"]:
        print(f"          {m['name']}  {m['distance_m']}m")
    check("返回 3 个商场（3km 内，半径过滤生效）", malls.get("count") == 3, str(names))
    check("按距离升序", [m["distance_m"] for m in malls["malls"]] == sorted(m["distance_m"] for m in malls["malls"]))
    check("最近的不是最终答案（证明需要核品牌）", names[0] != "广安门华联购物中心", str(names))

    wider = await invoke(tools_mod.search_nearby_malls, {"location": origin, "radius": 5000})
    check("放大到 5km 后多出庄胜崇光（半径参数真的在起作用）",
          "庄胜崇光百货(SOGO)" in [m["name"] for m in wider["malls"]],
          str([m["name"] for m in wider["malls"]]))

    print("\n=== 3. 场景一：两个品牌都要 ===")
    brands = ["倍轻松", "西厅村屋"]
    both, either = [], []
    for m in malls["malls"]:
        hit = {}
        for b in brands:
            r = await invoke(
                tools_mod.search_brand_in_mall, {"brand": b, "mall_location": m["location"]}
            )
            hit[b] = r.get("matched")
        mark = "".join("✓" if hit[b] else "✗" for b in brands)
        print(f"          {m['name']:<22} 倍轻松{'✓' if hit['倍轻松'] else '✗'} "
              f"西厅村屋{'✓' if hit['西厅村屋'] else '✗'}   {m['distance_m']}m")
        if all(hit.values()):
            both.append(m)
        if any(hit.values()):
            either.append(m)

    check("场景一唯一答案 = 广安门华联购物中心",
          [m["name"] for m in both] == ["广安门华联购物中心"], str([m["name"] for m in both]))

    print("\n=== 4. 场景二：只要一个品牌也行，比谁更近 ===")
    either.sort(key=lambda m: m["distance_m"])
    nearest = either[0]
    print(f"        最近且有品牌的：{nearest['name']}  {nearest['distance_m']}m")
    check("场景二答案 = 天虹商场(广安门店)", nearest["name"] == "天虹商场(广安门店)", nearest["name"])
    check("场景二比场景一更近", nearest["distance_m"] < both[0]["distance_m"],
          f"{nearest['distance_m']} vs {both[0]['distance_m']}")

    print("\n=== 5. 路网距离 ===")
    dist = await invoke(
        tools_mod.measure_distance,
        {"origin": origin, "destination": nearest["location"]},
    )
    print(f"        {nearest['name']}：驾车 {dist.get('distance_m')}m / {dist.get('duration_min')} 分钟")
    check("驾车距离 > 直线距离（绕路系数）", dist.get("distance_m", 0) > nearest["distance_m"])
    check("耗时换算为正数", dist.get("duration_min", 0) > 0)

    print(f"\n{'=' * 44}")
    print(f"通过 {PASS} 项，失败 {FAIL} 项")
    return 1 if FAIL else 0


sys.exit(asyncio.run(main()))
