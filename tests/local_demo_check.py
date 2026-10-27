"""
本地演示模式自检（无模型 Key、无高德 Key）
==================================================

验证 local_planner 这条降级路径：
1. 第一轮能把「位置 + 两个品牌」解析出来，跑完四个工具，给出唯一答案
2. 第二轮（不带位置）能复用上一轮上下文，改判"只要一个品牌"的口径
3. 缺位置时会主动追问，而不是瞎猜坐标
4. 输出的 SSE 帧格式与 agents/chat/index.py 一致（前端不用改）

运行：
    ./.venv/Scripts/python.exe tests/local_demo_check.py
"""

import asyncio
import importlib.util
import json
import os
import sys
import types

os.environ["AMAP_MOCK"] = "1"
os.environ.pop("AMAP_API_KEY", None)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AGENTS_DIR = os.path.join(ROOT, "agents")

pkg = types.ModuleType("demopkg")
pkg.__path__ = [AGENTS_DIR]
sys.modules["demopkg"] = pkg

spec = importlib.util.spec_from_file_location("demopkg._tools", os.path.join(AGENTS_DIR, "_tools.py"))
tools_mod = importlib.util.module_from_spec(spec)
sys.modules["demopkg._tools"] = tools_mod
spec.loader.exec_module(tools_mod)

spec2 = importlib.util.spec_from_file_location("local_planner", os.path.join(ROOT, "local_planner.py"))
planner = importlib.util.module_from_spec(spec2)
sys.modules["local_planner"] = planner
spec2.loader.exec_module(planner)

TOOLS = {t.name: t for t in tools_mod.TRAVEL_TOOLS}
PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


async def run_turn(message, history):
    """跑一轮，返回 (回答正文, 点亮的工具序列, 事件名列表)。"""
    text, tools, events = [], [], []
    async for frame in planner.stream(TOOLS, message, history):
        if not frame.startswith("event: "):
            return "", [], False
        name = frame.split("\n", 1)[0][len("event: "):]
        events.append(name)
        payload = json.loads(frame.split("data: ", 1)[1].strip())
        if name == "text_delta":
            text.append(payload.get("delta", ""))
        elif name == "tool_called":
            tools.append(payload.get("tool"))
    return "".join(text), tools, events


async def main():
    q1 = "我在红莲南路地铁站附近，我想要去一个既有倍轻松又有西厅村屋的离得近的商场，帮我推荐。"
    q2 = "如果不要求两个品牌同时存在，还有没有距离更近的选择？"

    print("\n=== 第一轮：信息完整 ===")
    t1, tools1, ev1 = await run_turn(q1, [])
    print(t1)
    check("只发 text_delta / tool_called 两种帧（done 由 local_dev 统一补）",
          set(ev1) <= {"text_delta", "tool_called"}, str(set(ev1)))
    check("工具顺序 = 定位→商场→品牌×N→距离→步行",
          tools1[0] == "resolve_location"
          and tools1[1] == "search_nearby_malls"
          and tools1[-2] == "measure_distance"
          and tools1[-1] == "plan_walking_route"
          and set(tools1[2:-2]) == {"search_brand_in_mall"}, str(tools1))
    check("推荐唯一同时命中两个品牌的商场", "广安门华联购物中心" in t1)
    check("表格里两个品牌都打勾", "✅ | ✅" in t1, t1[-300:])
    check("标注了演示数据来源", "演示样例" in t1)
    check("没有把未命中的商场当答案", "推荐 **天虹商场(广安门店)**" not in t1)

    print("\n=== 第二轮：连续追问（不带位置） ===")
    history = [
        {"role": "user", "content": q1},
        {"role": "assistant", "content": t1},
    ]
    t2, tools2, ev2 = await run_turn(q2, history)
    print(t2)
    check("第二轮帧格式同样合法", set(ev2) <= {"text_delta", "tool_called"}, str(set(ev2)))
    check("复用了上一轮位置（没有重新追问地址）", "请先告诉我你在哪儿" not in t2)
    check("口径改成「至少命中一个」", "至少命中一个品牌" in t2)
    check("换成更近的天虹", "推荐 **天虹商场(广安门店)**" in t2)

    print("\n=== 第三轮：只给一句话，没位置 ===")
    t3, tools3, ev3 = await run_turn("帮我找个有倍轻松的商场", [])
    print(t3)
    check("主动追问位置", "请先告诉我你在哪儿" in t3)
    check("没位置时不调用任何工具", tools3 == [], str(tools3))

    print(f"\n{'=' * 44}")
    print(f"通过 {PASS} 项，失败 {FAIL} 项")
    return 1 if FAIL else 0


sys.exit(asyncio.run(main()))
