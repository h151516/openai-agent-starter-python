"""
本地冒烟测试：用桩模型跑通 handler → Runner → SSE 全链路
==========================================================

目的
----
不消耗 API 额度、不需要任何 Key，验证：
  1. local_dev.py 能正确加载 agents/chat/index.py（包别名、相对导入）
  2. context 契约（request.body / signal / conversation_id / store）被正确满足
  3. Runner.run_streamed → stream_events → sse_event 的帧格式正确
  4. 会话记忆（SQLiteSession）写入与读取正常
  5. 最终 SSE 帧以 done 收尾

它不能证明模型回答质量——那需要真实 Key。它证明的是"接线"全部正确。

运行: .venv\\Scripts\\python.exe tests/local_smoke.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import local_dev  # noqa: E402  加载 agent 模块与本地 store

from agents.models.interface import Model  # noqa: E402
from openai.types.responses import (  # noqa: E402
    Response,
    ResponseCompletedEvent,
    ResponseCreatedEvent,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseTextDeltaEvent,
)

REPLY = "我在深圳大学粤海校区附近找到 2 个候选商场，推荐优先级如下。"


class StubModel(Model):
    """按脚本吐出「一段文字」的假模型。"""

    def __init__(self) -> None:
        self.calls = 0

    async def get_response(self, *args, **kwargs):  # pragma: no cover - 不用于流式路径
        raise NotImplementedError("冒烟测试只走 stream_response")

    async def stream_response(
        self,
        system_instructions,
        input,
        model_settings,
        tools,
        output_schema,
        handoffs,
        tracing,
        **kwargs,
    ):
        self.calls += 1
        msg = ResponseOutputMessage(
            id="msg_stub",
            type="message",
            role="assistant",
            status="completed",
            content=[ResponseOutputText(type="output_text", text=REPLY, annotations=[])],
        )
        created = Response(
            id="resp_stub",
            created_at=0,
            model="stub",
            object="response",
            output=[],
            parallel_tool_calls=False,
            tool_choice="auto",
            tools=[],
            status="in_progress",
        )
        completed = created.model_copy(update={"output": [msg], "status": "completed"})

        yield ResponseCreatedEvent(
            type="response.created", response=created, sequence_number=0
        )
        # 逐字吐出，模拟真实流式
        for i, ch in enumerate(REPLY):
            yield ResponseTextDeltaEvent(
                type="response.output_text.delta",
                delta=ch,
                content_index=0,
                item_id="msg_stub",
                output_index=0,
                sequence_number=i + 1,
                logprobs=[],
            )
        yield ResponseCompletedEvent(
            type="response.completed", response=completed, sequence_number=len(REPLY) + 1
        )


async def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    # ---- 模块加载 ----
    check("agent 模块加载", local_dev.AGENT.agent.name == "出行决策助手", local_dev.AGENT.agent.name)
    tool_names = sorted(t.name for t in local_dev.AGENT.agent.tools)
    expected = sorted(
        ["resolve_location", "search_nearby_malls", "search_brand_in_mall", "measure_distance"]
    )
    check("四个高德工具已注册", tool_names == expected, str(tool_names))

    # ---- 换桩模型 ----
    stub = StubModel()
    local_dev.AGENT.agent.model = stub

    # ---- 构造 context，驱动 handler ----
    cid = "smoke-test-conv"
    local_dev.STORE.clear(cid)
    # userId 必传：handler 只在 user_id 与 conversation_id 同时存在时写用户索引，
    # 这也是 /conversations 与 /history 能查到记录的前提。
    req = local_dev.Request(
        {"message": "我在深圳大学粤海校区，想逛有 Nike 的商场", "userId": "smoke-user"},
        asyncio.Event(),
    )
    ctx = local_dev.Context(req, cid, "run-1", local_dev.STORE)

    frames: list[str] = []
    async for frame in local_dev.AGENT.handler(ctx):
        frames.append(frame)

    check("模型被调用", stub.calls == 1, f"calls={stub.calls}")
    check("产出 SSE 帧", len(frames) > 0, f"frames={len(frames)}")

    text = "".join(
        __import__("json").loads(f.split("data: ", 1)[1].split("\n\n", 1)[0])["delta"]
        for f in frames
        if f.startswith("event: text_delta")
    )
    check("text_delta 拼回完整文本", text == REPLY, repr(text[:30]))

    has_error = any(f.startswith("event: error") for f in frames)
    check("无 error 帧", not has_error)
    check("以 done 收尾", frames[-1].startswith("event: done"), frames[-1].replace("\n", " ")[:40])

    # ---- 会话记忆 ----
    session = local_dev.STORE.openai_session(cid)
    items = await session.get_items()
    roles = [i.get("role") for i in items if isinstance(i, dict)]
    check("会话记忆已写入", len(items) >= 2, f"items={len(items)} roles={roles}")

    db_msgs = local_dev.STORE.history(cid)
    check("/history 能读到消息", len(db_msgs) >= 1, f"rows={len(db_msgs)}")

    # ---- 输出 ----
    print("=" * 56)
    print(" 本地冒烟测试")
    print("=" * 56)
    passed = 0
    for name, ok, detail in checks:
        print(f" [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
        passed += ok
    print("-" * 56)
    print(f" {passed}/{len(checks)} 项通过")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
