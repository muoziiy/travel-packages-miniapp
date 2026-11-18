#!/usr/bin/env python3
"""Fo-as-agent runner for Muoziiy's Telegram Business bot.
list                  -> JSON of unanswered messages with chat context
answer <id> --file f  -> send f's content as Muoziiy, mark answered
forward <id>          -> hand the message to Muoziiy personally instead
"""
import json, os, sqlite3, sys, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json")))
TOKEN = CFG["bot_token"]
ADMIN = int(CFG["admin_chat_id"])
API = "https://api.telegram.org/bot" + TOKEN + "/{}"

def tg(method, payload):
    req = urllib.request.Request(API.format(method), data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.loads(r.read().decode())
    if not out.get("ok"):
        raise RuntimeError(f"{method}: {out}")
    return out["result"]

def db():
    return sqlite3.connect(os.path.join(HERE, "agent.db"))

def list_pending():
    conn = db()
    rows = conn.execute("""SELECT id, ts, conn_id, chat_id, msg_id, sender, text
        FROM msgs WHERE reply IS NULL ORDER BY id ASC""").fetchall()
    out = []
    for id_, ts, conn_id, chat_id, msg_id, sender, text in rows:
        ctx = conn.execute("SELECT sender,text,reply FROM msgs WHERE chat_id=? AND id<? ORDER BY id DESC LIMIT 6",
                           (chat_id, id_)).fetchall()
        ctx.reverse()
        out.append({"id": id_, "minutes_ago": round((time.time() - ts) / 60), "conn_id": conn_id,
                    "chat_id": chat_id, "msg_id": msg_id, "sender": sender, "text": text,
                    "context": [{"sender": s, "text": t, "muoziiy_reply": r} for s, t, r in ctx]})
    print(json.dumps(out, ensure_ascii=False, indent=1))

def draft(msg_db_id, options):
    if not claim(msg_db_id):
        print("already handled"); return
    conn = db()
    sender, orig = conn.execute("SELECT sender, text FROM msgs WHERE id=?", (msg_db_id,)).fetchone()
    opt1 = options[0] if len(options) > 0 else ""
    opt2 = options[1] if len(options) > 1 else ""
    conn.execute("INSERT INTO drafts(msg_id, opt1, opt2) VALUES(?,?,?) "
                 "ON CONFLICT(msg_id) DO UPDATE SET opt1=excluded.opt1, opt2=excluded.opt2",
                 (msg_db_id, opt1, opt2))
    conn.commit()
    did = conn.execute("SELECT id FROM drafts WHERE msg_id=?", (msg_db_id,)).fetchone()[0]
    kb = {"inline_keyboard": []}
    btns = []
    if opt1: btns.append({"text": "1 Send", "callback_data": f"dsend:{did}:1"})
    if opt2: btns.append({"text": "2 Send", "callback_data": f"dsend:{did}:2"})
    if btns: kb["inline_keyboard"].append(btns)
    kb["inline_keyboard"].append([{"text": "✖️ Skip", "callback_data": f"dskip:{did}"}])
    body = f"Draft for {sender} (msg {msg_db_id}):\n— {orig[:200]}\n\n1) {opt1}"
    if opt2:
        body += f"\n\n2) {opt2}"
    try:
        tg("sendMessage", {"chat_id": ADMIN, "text": body,
                           "disable_web_page_preview": True, "reply_markup": kb})
        print("drafted")
    except Exception as e:
        conn.execute("UPDATE msgs SET reply=NULL WHERE id=?", (msg_db_id,)); conn.commit()
        print("FAILED:", e)


def ignore(msg_db_id):
    conn = db()
    conn.execute("DELETE FROM drafts WHERE msg_id=?", (msg_db_id,))
    cur = conn.execute("UPDATE msgs SET reply='[ignored]' WHERE id=? AND reply IS NULL", (msg_db_id,))
    conn.commit()
    print("ignored" if cur.rowcount else "already handled")


def claim(msg_id):
    conn = db()
    cur = conn.execute("UPDATE msgs SET reply='[sending]' WHERE id=? AND reply IS NULL", (msg_id,))
    conn.commit()
    return cur.rowcount == 1

def answer(msg_id, text):
    if not claim(msg_id):
        print("already handled"); return
    conn = db()
    conn_id, chat_id, sender = conn.execute(
        "SELECT conn_id, chat_id, sender FROM msgs WHERE id=?", (msg_id,)).fetchone()
    try:
        tg("sendMessage", {"business_connection_id": conn_id, "chat_id": chat_id, "text": text})
        conn.execute("UPDATE msgs SET reply=? WHERE id=?", (text, msg_id))
        conn.commit(); print("sent")
        try:  # mirror what went out on Muoziiy's behalf into his chat
            tg("sendMessage", {"chat_id": ADMIN,
                               "text": f"\u2705 answered as you to {sender}:\n{text}"})
        except Exception:
            pass
    except Exception as e:
        conn.execute("UPDATE msgs SET reply=NULL WHERE id=?", (msg_id,)); conn.commit()
        print("FAILED:", e)

def forward(msg_id):
    if not claim(msg_id):
        print("already handled"); return
    conn = db()
    sender, text = conn.execute("SELECT sender, text FROM msgs WHERE id=?", (msg_id,)).fetchone()
    try:
        tg("sendMessage", {"chat_id": ADMIN, "disable_web_page_preview": True,
            "text": f"Personal chat for you, {sender}:\n{text}\n\nYour agent left this one to you."})
        conn.execute("UPDATE msgs SET reply='[left to Muoziiy]' WHERE id=?", (msg_id,))
        conn.commit(); print("forwarded")
    except Exception as e:
        conn.execute("UPDATE msgs SET reply=NULL WHERE id=?", (msg_id,)); conn.commit()
        print("FAILED:", e)

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        list_pending()
    elif cmd == "answer":
        mid = int(sys.argv[2])
        text = open(sys.argv[sys.argv.index("--file") + 1]).read() if "--file" in sys.argv else " ".join(sys.argv[3:])
        answer(mid, text.strip())
    elif cmd == "forward":
        forward(int(sys.argv[2]))
    elif cmd == "ignore":
        ignore(int(sys.argv[2]))
    elif cmd == "draft":
        mid = int(sys.argv[2])
        opts = []
        if "--file" in sys.argv:
            idxs = [i for i, a in enumerate(sys.argv) if a == "--file"]
            for i in idxs:
                opts.append(open(sys.argv[i + 1]).read().strip())
        else:
            opts = " ".join(sys.argv[3:]).split(" ||| ")
        draft(mid, [o for o in opts if o])
    else:
        print(__doc__)
