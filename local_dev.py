"""
本地开发运行时（不依赖 EdgeOne CLI）
==================================================

为什么需要这个文件
------------------
平台部署时由 EdgeOne Makers 运行时提供 `context`（请求体、取消信号、会话存储）。
本地没有该运行时，`edgeone makers dev` 又依赖 CLI + 账号登录，网络受限时走不通。
本文件用标准库复刻一份最小可用的 `context`，直接加载 `agents/chat/index.py` 里
**原封不动**的 `handler()`，因此本地跑通即等于平台代码跑通（只差部署环境）。

启动方式
--------
    .venv\\Scripts\\python.exe local_dev.py

默认 http://127.0.0.1:8080
    /chat  /stop  /history  /conversations  /clear-history  /delete-conversation
静态页面优先用 `dist/`（npm run build 的产物），没有则回退到 local_preview.html。

设计要点
--------
1. 目录名 `agents/` 与已安装的 `openai-agents` 包同名，直接 import 会冲突。
   这里用「包别名」把 agents/ 注册成 local_agents，相对导入 `from .._tools` 依然成立。
2. HTTP 用 HTTP/1.0 + Connection: close，浏览器可以边收边渲染 SSE 流。
3. 每个请求独占一个事件循环，`asyncio.Event` 充当取消信号，/stop 跨线程触发。
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import mimetypes
import os
import sqlite3
import sys
import threading
import time
import types
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
HOST = os.getenv("LOCAL_HOST", "127.0.0.1")
# 8080 常被 PHPStudy / Apache / 其他 dev server 占用，默认换 8787
PORT = int(os.getenv("LOCAL_PORT", "8787"))
DIST = ROOT / "dist"
DATA_DIR = ROOT / ".local"
DB_PATH = DATA_DIR / "local.db"

load_dotenv(ROOT / ".env")

PLACEHOLDER_KEYS = {"", "your-api-key", "your_key", "sk-xxx", "xxx"}


# ============================================================
# 一、加载 Agent 模块（绕开 agents 同名冲突）
# ============================================================
def load_agent_module():
    """把 agents/ 目录注册成包 local_agents，再按文件加载 chat/index.py。"""
    pkg = types.ModuleType("local_agents")
    pkg.__path__ = [str(ROOT / "agents")]
    sys.modules["local_agents"] = pkg

    for mod_name in ("_logger", "_tools"):
        spec = importlib.util.spec_from_file_location(
            f"local_agents.{mod_name}", ROOT / "agents" / f"{mod_name}.py"
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"local_agents.{mod_name}"] = mod
        spec.loader.exec_module(mod)

    chat_pkg = types.ModuleType("local_agents.chat")
    chat_pkg.__path__ = [str(ROOT / "agents" / "chat")]
    sys.modules["local_agents.chat"] = chat_pkg

    spec = importlib.util.spec_from_file_location(
        "local_agents.chat.index", ROOT / "agents" / "chat" / "index.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["local_agents.chat.index"] = mod
    spec.loader.exec_module(mod)
    return mod


# ============================================================
# 二、本地存储（复刻 context.store 的三个方法）
# ============================================================
class LocalStore:
    """内存会话索引 + SQLite 消息表，接口对齐 EdgeOne 的 built-in store。"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    user_id       TEXT,
                    role          TEXT NOT NULL,
                    content       TEXT NOT NULL,
                    created_at    INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conv ON messages(conversation_id, id)"
            )

    # --- 平台接口 1：给 Agents SDK 用的会话 ---
    def openai_session(self, conversation_id: str):
        from agents.memory import SQLiteSession

        return SQLiteSession(session_id=conversation_id, db_path=self.db_path)

    # --- 平台接口 2：读消息 ---
    async def get_messages(self, conversation_id: str, limit: int = 50, **_):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, role, content, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY id ASC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # --- 平台接口 3：写消息 ---
    async def append_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        user_id: str | None = None,
        **_,
    ) -> str:
        msg_id = uuid.uuid4().hex
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO messages(conversation_id, user_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (conversation_id, user_id, role, content, int(time.time() * 1000)),
            )
        return msg_id

    # --- 前端额外用到的几个查询 ---
    def history(self, conversation_id: str, limit: int = 200) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, role, content, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY id ASC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        return [
            {
                "id": str(r["id"]),
                "role": r["role"],
                "content": r["content"],
                "timestamp": r["created_at"],
            }
            for r in rows
        ]

    def conversations(self, user_id: str | None, limit: int = 20) -> list[dict]:
        sql = (
            "SELECT conversation_id, COUNT(*) AS cnt, MAX(created_at) AS last_at, "
            "MAX(user_id) AS uid FROM messages "
        )
        params: list = []
        if user_id:
            sql += "WHERE user_id = ? "
            params.append(user_id)
        sql += "GROUP BY conversation_id ORDER BY last_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            first = conn_first = None
            with self._conn() as conn:
                conn_first = conn.execute(
                    "SELECT content FROM messages WHERE conversation_id = ? "
                    "ORDER BY id ASC LIMIT 1",
                    (r["conversation_id"],),
                ).fetchone()
            first = conn_first["content"] if conn_first else ""
            out.append(
                {
                    "id": r["conversation_id"],
                    "title": (first or "新对话")[:24],
                    "preview": first[:60],
                    "lastMessageAt": r["last_at"],
                    "messageCount": r["cnt"],
                    "userId": r["uid"],
                }
            )
        return out

    def clear(self, conversation_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))

    def delete(self, conversation_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            conn.execute(
                "DELETE FROM agent_messages WHERE session_id = ?", (conversation_id,)
            )


# ============================================================
# 三、复刻 platform context
# ============================================================
class Request:
    def __init__(self, body: dict, signal: asyncio.Event):
        self.body = body
        self.signal = signal


class Context:
    def __init__(self, request: Request, conversation_id: str, run_id: str, store: LocalStore):
        self.request = request
        self.conversation_id = conversation_id
        self.run_id = run_id
        self.store = store


STORE = LocalStore(DB_PATH)
AGENT = load_agent_module()
CANCEL: dict[str, tuple[threading.Event, asyncio.Event, asyncio.AbstractEventLoop]] = {}
CANCEL_LOCK = threading.Lock()

# 工具名 → 工具对象，给「无模型本地演示」用
TOOLS = {t.name: t for t in AGENT.TRAVEL_TOOLS}


def _demo_enabled() -> bool:
    """没有可用模型 Key 时，自动切到本地规则演示（LOCAL_DEMO=0 可关掉）。"""
    try:
        import local_planner as planner
    except ImportError:
        return False
    return planner.enabled(os.getenv("AI_GATEWAY_API_KEY", ""))


async def _demo_stream(message: str, cid: str, body: dict):
    """把规则演示的回答按 Agent 同样的 SSE 协议推出去，并写回会话历史。"""
    import local_planner as planner

    user_id = str(body.get("userId") or body.get("user_id") or "").strip() or None
    history = STORE.history(cid)
    await STORE.append_message(cid, role="user", content=message, user_id=user_id)

    spoken: list[str] = []
    try:
        async for frame in planner.stream(TOOLS, message, history):
            if frame.startswith("event: text_delta"):
                try:
                    spoken.append(json.loads(frame.split("data: ", 1)[1]).get("delta", ""))
                except (IndexError, json.JSONDecodeError):
                    pass
            yield frame
    except Exception as exc:  # noqa: BLE001
        print(f"[demo] error: {type(exc).__name__}: {exc}", flush=True)
        yield f'event: error\ndata: {json.dumps({"message": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)}\n\n'
    finally:
        if spoken:
            await STORE.append_message(cid, role="assistant", content="".join(spoken))
        yield 'event: done\ndata: {"stopped": false}\n\n'


DEMO_MODE = _demo_enabled()
# 地图数据是否来自内置样例（和 agents/_tools.py 的 AMAP_MOCK 同一开关）
MOCK_MODE = (os.getenv("AMAP_MOCK") or "").strip().lower() in {"1", "true", "yes", "on"}


# ============================================================
# 四、HTTP 层
# ============================================================
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # 关闭长连接，SSE 用 EOF 结束

    # --- 通用 ---
    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}", flush=True)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, makers-conversation-id")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, obj, status=200):
        payload = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self._cors()
        self.end_headers()
        self.wfile.write(payload)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        # Windows 终端（GBK）直接 curl 中文时编码不是 UTF-8，先宽容解码
        for enc in ("utf-8", "gb18030"):
            try:
                return json.loads(raw.decode(enc) or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
        return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    # --- 路由 ---
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/status":
            return self._json(
                {
                    "demo": DEMO_MODE,
                    "mock": MOCK_MODE,
                    "conversation_ttl": None,
                }
            )
        if path in ("/", "/index.html"):
            return self._serve_index()
        return self._serve_static(path)

    def do_POST(self):
        # 兜底：单个请求出错不能让线程抛栈到客户端变成「空响应」
        try:
            self._route_post()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001
            print(f"[error] {type(exc).__name__}: {exc}", flush=True)
            try:
                self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
            except Exception:
                pass

    def _route_post(self):
        path = self.path.split("?")[0]
        cid = self.headers.get("makers-conversation-id") or ""

        if path == "/chat":
            return self._chat(self._body(), cid)
        if path == "/stop":
            return self._stop(self._body(), cid)
        if path == "/history":
            body = self._body()
            conv = body.get("conversation_id") or cid
            return self._json({"messages": STORE.history(conv) if conv else []})
        if path == "/conversations":
            body = self._body()
            return self._json(
                {"conversations": STORE.conversations(body.get("user_id"), body.get("limit") or 20)}
            )
        if path == "/clear-history":
            body = self._body()
            conv = body.get("conversation_id") or cid
            if conv:
                STORE.clear(conv)
            return self._json({"ok": True})
        if path == "/delete-conversation":
            body = self._body()
            conv = body.get("conversation_id") or cid
            if conv:
                STORE.delete(conv)
            return self._json({"ok": True})
        return self._json({"error": "not found"}, 404)

    # --- /chat：SSE ---
    def _chat(self, body: dict, header_cid: str):
        message = (body.get("message") or "").strip()
        cid = header_cid or body.get("conversationId") or uuid.uuid4().hex

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self._cors()
        self.end_headers()

        if not message:
            self._write_sse('event: error\ndata: {"message":"message is required"}\n\n')
            self._write_sse("event: done\ndata: {}\n\n")
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        cancel_event = asyncio.Event()
        stop_flag = threading.Event()
        with CANCEL_LOCK:
            CANCEL[cid] = (stop_flag, cancel_event, loop)

        ctx = Context(Request(body, cancel_event), cid, uuid.uuid4().hex, STORE)
        if DEMO_MODE:
            gen = _demo_stream(message, cid, body)
        else:
            gen = AGENT.handler(ctx)

        try:
            while True:
                if stop_flag.is_set():
                    break
                try:
                    chunk = loop.run_until_complete(gen.__anext__())
                except StopAsyncIteration:
                    break
                except Exception as exc:  # handler 内已兜底，这里只防御
                    print(f"[chat] generator error: {type(exc).__name__}: {exc}", flush=True)
                    break
                if not self._write_sse(chunk):
                    break
        finally:
            with CANCEL_LOCK:
                CANCEL.pop(cid, None)
            try:
                loop.run_until_complete(gen.aclose())
            except Exception:
                pass
            loop.close()

    def _write_sse(self, chunk: str) -> bool:
        try:
            self.wfile.write(chunk.encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    # --- /stop ---
    def _stop(self, body: dict, header_cid: str):
        cid = body.get("conversation_id") or body.get("conversationId") or header_cid
        hit = False
        with CANCEL_LOCK:
            entry = CANCEL.get(cid) if cid else None
        if entry:
            stop_flag, cancel_event, loop = entry
            stop_flag.set()
            try:
                loop.call_soon_threadsafe(cancel_event.set)
            except RuntimeError:
                pass
            hit = True
        return self._json({"ok": hit})

    # --- 静态资源 ---
    def _serve_index(self):
        index = DIST / "index.html"
        if index.exists():
            return self._send_file(index)
        fallback = ROOT / "local_preview.html"
        if fallback.exists():
            return self._send_file(fallback)
        return self._json({"error": "dist/index.html 不存在，且缺少 local_preview.html"}, 404)

    def _serve_static(self, path: str):
        if not DIST.exists():
            return self._json({"error": "静态目录不存在"}, 404)
        target = (DIST / path.lstrip("/")).resolve()
        try:
            target.relative_to(DIST.resolve())
        except ValueError:
            return self._json({"error": "forbidden"}, 403)
        if target.is_file():
            return self._send_file(target)
        return self._send_file(DIST / "index.html")

    def _send_file(self, path: Path):
        data = path.read_bytes()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix in (".js", ".mjs"):
            ctype = "text/javascript"
        if path.suffix == ".css":
            ctype = "text/css"
        self.send_response(200)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8" if ctype.startswith("text") or "javascript" in ctype else ctype)
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)


# ============================================================
# 五、启动前自检
# ============================================================
def preflight() -> bool:
    print("=" * 58)
    print(" 出行决策 Agent · 本地运行时")
    print("=" * 58)

    key = (os.getenv("AI_GATEWAY_API_KEY") or "").strip()
    base = (os.getenv("AI_GATEWAY_BASE_URL") or "").strip()
    model = (os.getenv("AI_GATEWAY_MODEL") or "").strip()
    amap = (os.getenv("AMAP_API_KEY") or "").strip()
    mock = (os.getenv("AMAP_MOCK") or "").strip().lower() in {"1", "true", "yes", "on"}

    def mark(ok: bool) -> str:
        return "OK  " if ok else "缺失"

    print(f"  [{mark(key and key not in PLACEHOLDER_KEYS)}] AI_GATEWAY_API_KEY")
    print(f"  [{mark(bool(base))}] AI_GATEWAY_BASE_URL  {base or '-'}")
    print(f"  [{mark(bool(model))}] AI_GATEWAY_MODEL     {model or '-'}")
    if mock:
        # 演示模式优先：没 Key 也能把四个工具跑通
        print("  [OK  ] 地图数据源          演示模式（AMAP_MOCK=1，内置样例数据）")
    else:
        print(f"  [{mark(bool(amap))}] AMAP_API_KEY")
    print(f"  [OK  ] 前端页面          {'dist/ 已构建' if (DIST / 'index.html').exists() else 'local_preview.html 回退页'}")

    ready = True
    if not key or key in PLACEHOLDER_KEYS:
        print("\n  ! AI_GATEWAY_API_KEY 没填，走本地规则演示（无模型，回答是模板拼接）。")
        print("    填上真实 Key 后自动切回模型对话，代码不需要改。")
        ready = False
    if not amap and not mock:
        print("\n  ! AMAP_API_KEY 没填，定位/找商场/核品牌/量距离四个工具全部不可用。")
        print("    想先看效果：在 .env 里加一行 AMAP_MOCK=1 走内置演示数据。")
        ready = False
    if mock:
        print("\n  i 当前是演示模式：回答里的地点/距离来自内置样例，不是高德实时结果。")
        print("    拿到真实 Key 后把 AMAP_MOCK 删掉或改 0 即可恢复真实查询。")

    print(f"\n  对话引擎：{'本地规则演示（无模型）' if DEMO_MODE else 'AI Gateway 模型'}")
    print()
    return ready


def _bind(preferred: int) -> tuple[ThreadingHTTPServer, int]:
    """端口被占用时自动向后顺延，避免和 PHPStudy 之类打架。"""
    last_err: Exception | None = None
    for port in range(preferred, preferred + 20):
        try:
            return ThreadingHTTPServer((HOST, port), Handler), port
        except OSError as exc:  # WinError 10013 / 10048 都算
            last_err = exc
            print(f"  端口 {port} 不可用，尝试 {port + 1} …")
    raise SystemExit(f"连续 20 个端口都绑定失败：{last_err}")


def main():
    ready = preflight()
    if not ready:
        print("  仍可启动，用于验证 UI 与错误处理路径。\n")

    server, port = _bind(PORT)
    server.daemon_threads = True
    print(f"  服务已启动 → http://{HOST}:{port}")
    print(f"  会话数据库 → {DB_PATH}")
    print("  Ctrl+C 退出\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
