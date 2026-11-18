#!/usr/bin/env python3
"""MCP server for Muoziiy's business-agent bot.

Lets Fo work the bot from a hosted server instead of a shared filesystem:
list pending chats, read history, post draft replies (Send/Skip buttons),
send an approved reply as Muoziiy, ignore non-travel messages, or forward
one to Muoziiy. Bearer-token protected; run next to the bot (same folder,
same agent.db). Token lives in config.json as mcp_token.
"""
import io, json, os, sqlite3, sys
from contextlib import asynccontextmanager, redirect_stdout

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import agent_run as ar

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse
from starlette.routing import Mount

mcp = FastMCP("muoziiy-business-agent",
              host=ar.CFG.get("mcp_host", "127.0.0.1"),
              port=int(ar.CFG.get("mcp_port", 8790)))


def q(sql, args=()):
    conn = sqlite3.connect(os.path.join(BASE, "agent.db"), timeout=15)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _run(fn, *a):
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn(*a)
    return buf.getvalue().strip() or "done"


@mcp.tool()
def list_pending() -> str:
    """Unanswered client chats waiting on Muoziiy's travel-agency line: id, sender, chat_id, text, minutes_ago, recent context."""
    return json.dumps(ar.list_pending(), ensure_ascii=False)


@mcp.tool()
def get_history(chat_id: str, limit: int = 10) -> str:
    """Recent messages of one client chat, oldest first, for drafting context."""
    rows = q("SELECT id, sender, text, reply FROM msgs WHERE chat_id=? "
             "ORDER BY id DESC LIMIT ?", (str(chat_id), int(limit)))
    rows.reverse()
    return json.dumps([{"id": r[0], "sender": r[1], "text": r[2],
                        "muoziiy_reply": r[3]} for r in rows], ensure_ascii=False)


@mcp.tool()
def draft_reply(msg_id: int, options: list) -> str:
    """Post 1-2 draft reply options to Muoziiy's private chat with Send/Skip buttons. Drafts only: nothing reaches the client until Muoziiy taps Send."""
    if not (1 <= len(options) <= 2):
        return "pass 1 or 2 options"
    return _run(ar.draft, msg_id, options)


@mcp.tool()
def send_reply(msg_id: int, text: str) -> str:
    """Send one reply to the client as Muoziiy. Use ONLY for text Muoziiy approved; draft-first is the default."""
    rows = q("SELECT conn_id, chat_id FROM msgs WHERE id=?", (msg_id,))
    if not rows:
        return "no such message"
    conn_id, chat_id = rows[0]
    import bot as b
    b.send_as_user(conn_id, chat_id, text)
    conn = sqlite3.connect(os.path.join(BASE, "agent.db"), timeout=15)
    conn.execute("DELETE FROM drafts WHERE msg_id=?", (msg_id,))
    conn.execute("UPDATE msgs SET reply=? WHERE id=?", (text, msg_id))
    conn.commit()
    conn.close()
    return "sent as Muoziiy"


@mcp.tool()
def ignore_message(msg_id: int) -> str:
    """Mark a message unrelated to the travel agency as ignored (no reply, no draft)."""
    return _run(ar.ignore, msg_id)


@mcp.tool()
def forward_to_muoziiy(msg_id: int) -> str:
    """Forward a message to Muoziiy's private chat for personal handling."""
    return _run(ar.forward, msg_id)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        want = "Bearer " + ar.CFG.get("mcp_token", "")
        if request.headers.get("authorization", "") != want:
            return PlainTextResponse("unauthorized", status_code=401)
        return await call_next(request)


inner = mcp.streamable_http_app()


@asynccontextmanager
async def _lifespan(app):
    # the MCP session manager needs its own lifespan (task group) started
    async with inner.router.lifespan_context(inner):
        yield


app = Starlette(routes=[Mount("/", app=inner)],
                middleware=[Middleware(AuthMiddleware)],
                lifespan=_lifespan)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=ar.CFG.get("mcp_host", "127.0.0.1"),
                port=int(ar.CFG.get("mcp_port", 8790)), log_level="warning")
