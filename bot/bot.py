#!/usr/bin/env python3
"""Muoziiy's Telegram Business agent bot.

A bot connected to Muoziiy's personal account via Telegram Business
("connected business bot"). It receives messages sent to his account in the
chats he picked at connect time, and can reply AS HIM (clients see his
account, with a small "via bot" label).

Modes:
  manual (default) - every incoming chat message is forwarded to the admin
                     chat with an AI-suggested reply; the reply only goes out
                     when he taps "Send".
  auto             - the AI reply is sent as him immediately, then the
                     incoming message is marked as read.

Admin commands (in the admin chat): /status /auto /manual /read /off
"""

import json, os, re, sqlite3, sys, time, threading, logging

import urllib.request

API = "https://api.telegram.org/bot{token}/{method}"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent.db")
CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bizbot")

DEFAULT_CFG = {
    "bot_token": "",
    "admin_chat_id": 5635746788,
    "mode": "manual",          # manual | auto
    "read_receipts": False,    # mark incoming as read
    "gemini_key": "",
    "intro_text": (
        "Muoziiy Baxtiyorjon - builder, operator, technologist.\n\n"
        "I build systems, run operations and ship products that hold up under "
        "real load: AI agent workflows, e-commerce automation and high-touch travel.\n\n"
        "This assistant is private for now. Reach Muoziiy directly on Telegram "
        "@muoziiy."
    ),
    "system_prompt": (
        "You answer chats on behalf of Muoziiy. Reply in the SAME language the "
        "message uses. Keep replies short, warm and human, 1-3 sentences. You are "
        "a real person's assistant: never promise payments, prices, dates or "
        "bookings on Muoziiy's behalf; if asked for those, say he will confirm "
        "details himself. Sign nothing."
    ),
}


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    if os.path.exists(CFG_PATH):
        try:
            cfg.update(json.load(open(CFG_PATH)))
        except Exception as e:
            log.warning("config unreadable: %s", e)
    env = os.environ.get("TELEGRAM_BOT_TOKEN")
    if env:
        cfg["bot_token"] = env
    return cfg


CFG = load_cfg()
TOKEN = CFG["bot_token"]
ADMIN = int(CFG["admin_chat_id"])

_lock = threading.Lock()


def db():
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS msgs(
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 ts INTEGER, conn_id TEXT, chat_id TEXT, msg_id INTEGER,
                 sender TEXT, text TEXT, mode TEXT, reply TEXT)""")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS drafts(
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 msg_id INTEGER UNIQUE, opt1 TEXT, opt2 TEXT)""")
        conn.commit()
        return conn


def tg(method, payload=None, timeout=60):
    """Call the Bot API; returns the parsed result or raises RuntimeError."""
    if not TOKEN:
        raise RuntimeError("no bot token configured")
    url = API.format(token=TOKEN, method=method)
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())
    if not out.get("ok"):
        raise RuntimeError(f"{method}: {out.get('description', out)}")
    return out["result"]


# ---------------------------------------------------------------- AI reply

def _system_text():
    """System prompt = agent prompt file + travel knowledge base."""
    here = os.path.dirname(os.path.abspath(__file__))
    parts = []
    f = CFG.get("system_prompt_file", "agent_prompt.md")
    if os.path.exists(os.path.join(here, f)):
        parts.append(open(os.path.join(here, f)).read())
    else:
        parts.append(CFG.get("system_prompt", ""))
    kb = CFG.get("kb_file", "travel_kb.md")
    if os.path.exists(os.path.join(here, kb)):
        parts.append(open(os.path.join(here, kb)).read())
    return "\n\n".join(parts)


def ai_reply(user_text, sender_name="", history=None):
    """Generate a reply. Returns None when no AI is configured or it fails."""
    key = CFG.get("gemini_key") or os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return None
    body = {
        "system_instruction": {"parts": [{"text": _system_text()}]},
        "contents": [],
    }
    for role, text in (history or [])[-8:]:
        if text:
            body["contents"].append({"role": "user" if role == "in" else "model",
                                     "parts": [{"text": text}]})
    who = f" (name: {sender_name})" if sender_name else ""
    body["contents"].append(
        {"role": "user", "parts": [{"text": f"Message from a chat{who}: {user_text}"}]})
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           "gemini-2.0-flash:generateContent?key=" + key)
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            out = json.loads(r.read().decode())
        text = out["candidates"][0]["content"]["parts"][0]["text"].strip()
        return text or None
    except Exception as e:
        log.error("ai failed: %s", e)
        return None


# ---------------------------------------------------------------- send paths

def send_as_user(conn_id, chat_id, text):
    """Send a message as Muoziiy through the business connection."""
    return tg("sendMessage", {"business_connection_id": conn_id,
                              "chat_id": chat_id, "text": text})


def mark_read(conn_id, chat_id, message_id):
    try:
        tg("readBusinessMessage", {"business_connection_id": conn_id,
                                   "chat_id": chat_id, "message_id": message_id})
        return True
    except Exception as e:
        log.error("readBusinessMessage: %s", e)
        return False


def typing(conn_id, chat_id):
    try:
        tg("sendChatAction", {"business_connection_id": conn_id,
                              "chat_id": chat_id, "action": "typing"})
    except Exception as e:
        log.debug("typing failed: %s", e)


def tell_admin(text, reply_markup=None):
    payload = {"chat_id": ADMIN, "text": text,
               "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg("sendMessage", payload)


PKG_WORDS = ("narx", "qancha", "price", "paket", "package", "umra", "harga",
             "tour", "sayohat", "цена", "стоимость", "сколько", "cost", "how much")


def _package_ask(text):
    t = text.lower()
    return any(w in t for w in PKG_WORDS)


def _holding_text(text):
    if any(0x0400 <= ord(c) <= 0x04FF for c in text):
        return ("Здравствуйте! Спасибо за запрос. Muoziiy ответит вам "
                "пакетами и точными ценами в ближайшее время.")
    return ("Assalomu alaykum! Rahmat, so'rovingiz qabul qilindi. "
            "Muoziiy sizga paketlar bilan to'liq javob beradi.")


def handle_draft_callback(q, data):
    if q["from"]["id"] != ADMIN:
        try:
            tg("answerCallbackQuery", {"callback_query_id": q["id"], "text": "Admin only."})
        except Exception:
            pass
        return
    parts = data.split(":")
    action, did = parts[0], int(parts[1])
    conn = db()
    row = conn.execute("SELECT msg_id, opt1, opt2 FROM drafts WHERE id=?", (did,)).fetchone()
    if not row:
        try:
            tg("answerCallbackQuery", {"callback_query_id": q["id"], "text": "Already handled."})
        except Exception:
            pass
        return
    msg_db_id, opt1, opt2 = row
    if action == "dskip":
        conn.execute("DELETE FROM drafts WHERE id=?", (did,))
        conn.execute("UPDATE msgs SET reply='[left to Muoziiy]' WHERE id=?", (msg_db_id,))
        conn.commit()
        tg("answerCallbackQuery", {"callback_query_id": q["id"]})
        tg("editMessageText", {"chat_id": ADMIN, "message_id": q["message"]["message_id"],
                               "text": "✖️ skipped"})
        return
    opt = opt1 if parts[-1] == "1" else opt2
    if not opt:
        tg("answerCallbackQuery", {"callback_query_id": q["id"], "text": "No text."})
        return
    conn_id, chat_id = conn.execute(
        "SELECT conn_id, chat_id FROM msgs WHERE id=?", (msg_db_id,)).fetchone()
    try:
        send_as_user(conn_id, chat_id, opt)
        conn.execute("DELETE FROM drafts WHERE id=?", (did,))
        conn.execute("UPDATE msgs SET reply=? WHERE id=?", (opt, msg_db_id))
        conn.commit()
        tg("answerCallbackQuery", {"callback_query_id": q["id"], "text": "Sent as you ✅"})
        tg("editMessageText", {"chat_id": ADMIN, "message_id": q["message"]["message_id"],
                               "text": "✅ sent as you:\n" + opt})
    except Exception as e:
        log.error("draft send: %s", e)
        try:
            tg("answerCallbackQuery", {"callback_query_id": q["id"], "text": f"failed: {e}"})
        except Exception:
            pass


INTROS = {
    "en": (
        "Muoziiy Baxtiyorjon - builder, operator, technologist.\n\n"
        "I build systems, run operations and ship products that hold up under "
        "real load: AI agent workflows, e-commerce automation and high-touch travel.\n\n"
        "This assistant is private for now. Reach Muoziiy directly on Telegram "
        "@muoziiy."
    ),
    "uz": (
        "Muoziiy Baxtiyorjon — tadbirkor, operatsion menejer va texnolog.\n\n"
        "Men tizimlar quraman, operatsiyalarni boshqaraman va real yuklamada "
        "ishlaydigan mahsulot chiqaraman: AI agent tizimlari, e-commerce "
        "avtomatlashtirish va yuqori darajadagi sayohat xizmati.\n\n"
        "Bu yordamchi hozircha shaxsiy. Muoziiy bilan to'g'ridan-to'g'ri "
        "Telegram @muoziiy orqali bog'laning."
    ),
    "ru": (
        "Muoziiy Baxtiyorjon — разработчик, операционный менеджер и технолог.\n\n"
        "Я строю системы, управляю операциями и выпускаю продукты, выдерживающие "
        "реальную нагрузку: AI-агенты, автоматизация e-commerce и премиальные "
        "путешествия.\n\n"
        "Этот помощник пока личный. Напишите Muoziiy напрямую в Telegram @muoziiy "
        "."
    ),
    "tr": (
        "Muoziiy Baxtiyorjon — geliştirici, operasyon yöneticisi ve teknoloji uzmanı.\n\n"
        "Gerçek yük altında ayakta kalan sistemler kurar, operasyonları yönetir ve "
        "ürünler çıkarırım: AI ajan sistemleri, e-ticaret otomasyonu ve yüksek "
        "standartlı seyahat hizmeti.\n\n"
        "Bu asistan şu an özel. Muoziiy'ye doğrudan Telegram'da @muoziiy üzerinden "
        "ulaşın."
    ),
    "ar": (
        "Muoziiy Baxtiyorjon — مطوّر ومدير عمليات وخبير تقنية.\n\n"
        "أبني أنظمة وأدير العمليات وأطلق منتجات تتحمل الضغط الحقيقي: وكلاء الذكاء "
        "الاصطناعي، وأتمتة التجارة الإلكترونية، وخدمات السفر عالية المستوى.\n\n"
        "هذا المساعد خاص حاليًا. تواصل مع Muoziiy مباشرة على تيليجرام @muoziiy "
        "."
    ),
}


GENTLE = {
    "uz": ("Assalomu alaykum! Qaysi yo'nalish bo'yicha ma'lumot kerak? "
           "Necha kishi va qachon ketmoqchisiz? To'liq ma'lumot va narxlar bilan tanishtiraman."),
    "ru": ("Здравствуйте! Каким направлением интересуетесь? Сколько человек "
           "и на какие даты? Расскажу детали и цены."),
    "en": ("Hello! Which destination are you interested in? How many people "
           "and what dates? I'll share full details and prices."),
    "tr": ("Merhaba! Hangi destinasyonla ilgileniyorsunuz? Kaç kişi ve hangi "
           "tarihler? Detayları ve fiyatları paylaşayım."),
    "ar": ("السلام عليكم! أي وجهة تهمك؟ كم شخصاً وفي أي تواريخ؟ سأرسل لك التفاصيل والأسعار."),
}


def _gentle_for(lang_code):
    base = (lang_code or "en").split("-")[0].lower()
    return GENTLE.get(base, GENTLE["en"])


def _intro_for(lang_code):
    base = (lang_code or "en").split("-")[0].lower()
    return INTROS.get(base, INTROS["en"])


BTN_SEND = "send:{chat_id}:{msg_id}:{conn_id}"
BTN_SKIP = "skip:{chat_id}:{msg_id}:{conn_id}"


def notify_admin(msg, conn_id, suggestion):
    """Forward the incoming chat to the admin chat with a Send button."""
    sender = msg.get("from", {})
    name = " ".join(filter(None, [sender.get("first_name"), sender.get("last_name")])) \
           or sender.get("username") or str(sender.get("id", "?"))
    text = msg.get("text") or msg.get("caption") or "(no text: %s)" % \
        (", ".join(k for k in ("photo", "voice", "video", "document", "sticker")
                   if k in msg) or "other media")
    body = f"💬 {name}:\n{text}"
    if suggestion:
        body += "\n\n🤖 suggested reply:\n" + suggestion
        kb = {"inline_keyboard": [[
            {"text": "✅ Send as me", "callback_data":
                BTN_SEND.format(chat_id=msg["chat"]["id"], msg_id=msg["message_id"],
                                conn_id=conn_id)},
            {"text": "✖️ Skip", "callback_data":
                BTN_SKIP.format(chat_id=msg["chat"]["id"], msg_id=msg["message_id"],
                                conn_id=conn_id)}]]}
    else:
        kb = None
    tell_admin(body, kb)


# ---------------------------------------------------------------- main loop

conn_cache = {}   # connection_id -> business_connection payload
pending = {}      # (chat_id, msg_id) -> {"conn_id", "suggestion", "text", "sender"}


def handle_business_message(update):
    msg = update["business_message"]
    conn_id = msg.get("business_connection_id") or update.get("business_connection_id")
    if conn_id not in conn_cache and update.get("business_connection"):
        conn_cache[conn_id] = update["business_connection"]
    chat_id = msg["chat"]["id"]
    sender = msg.get("from", {})
    name = " ".join(filter(None, [sender.get("first_name"), sender.get("last_name")])) \
           or sender.get("username") or str(sender.get("id", "?"))
    text = msg.get("text") or msg.get("caption") or ""
    conn = db()
    with _lock:
        conn.execute(
            "INSERT INTO msgs(ts,conn_id,chat_id,msg_id,sender,text,mode,reply) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (int(time.time()), conn_id, str(chat_id), msg["message_id"], name,
             text, CFG.get("mode"), None))
        conn.commit()

    if CFG.get("mode") == "agent":
        # AUTO MESSAGES OFF (Muoziiy, Nov 8): the bot never sends anything to
        # clients automatically. No holding line, no /start opener. Everything
        # is queued for Fo to draft; Muoziiy's tap is the only way a client
        # gets a reply.
        try:
            tell_admin(f"💬 {name}:\n{text or '(media)'}")
        except Exception as e:
            log.error("admin notify: %s", e)
        log.info("queued for Fo: %s: %s", name, text[:80])
        return

    if CFG.get("read_receipts"):
        mark_read(conn_id, chat_id, msg["message_id"])

    history = []
    conn2 = db()
    with _lock:
        for ts, sender, txt, reply in conn2.execute(
                "SELECT ts,sender,text,reply FROM msgs WHERE chat_id=? ORDER BY id DESC LIMIT 8",
                (str(chat_id),)):
            if reply:
                history.append(("out", reply))
            if txt:
                history.append(("in", txt))
        history.reverse()
    suggestion = ai_reply(text, name, history) if text else None
    if CFG.get("mode") == "auto" and suggestion and \
            suggestion.strip().upper().startswith("FORWARD"):
        # not a travel question: hand it to Muoziiy instead of answering
        suggestion = None
    if CFG.get("mode") == "auto" and suggestion:
        typing(conn_id, chat_id)
        try:
            send_as_user(conn_id, chat_id, suggestion)
            with _lock:
                conn.execute("UPDATE msgs SET reply=? WHERE chat_id=? AND msg_id=?",
                             (suggestion, str(chat_id), msg["message_id"]))
                conn.commit()
            log.info("auto-replied to %s in %s", name, chat_id)
        except Exception as e:
            log.error("auto reply failed: %s", e)
            tell_admin(f"⚠️ couldn't send the reply to {name}: {e}")
    else:
        pending[(str(chat_id), msg["message_id"])] = {
            "conn_id": conn_id, "suggestion": suggestion, "text": text, "name": name}
        notify_admin(msg, conn_id, suggestion)


def handle_callback(update):
    q = update["callback_query"]
    data = q.get("data", "")
    if data.startswith("dsend:") or data.startswith("dskip:"):
        handle_draft_callback(q, data)
        return
    if not (data.startswith("send:") or data.startswith("skip:")):
        try:
            tg("answerCallbackQuery", {"callback_query_id": q["id"]})
        except Exception:
            pass
        return
    if q["from"]["id"] != ADMIN:
        try:
            tg("answerCallbackQuery", {"callback_query_id": q["id"],
                                       "text": "Admin only."})
        except Exception:
            pass
        return
    parts = data.split(":")
    action, chat_id, msg_id, conn_id = parts[0], parts[1], int(parts[2]), parts[3]
    item = pending.pop((chat_id, msg_id), None)
    if action == "skip":
        try:
            tg("answerCallbackQuery", {"callback_query_id": q["id"]})
            tg("editMessageText", {"chat_id": ADMIN, "message_id":
                                   q["message"]["message_id"],
                                   "text": "✖️ skipped"})
        except Exception as e:
            log.error("skip: %s", e)
        return
    reply = (item or {}).get("suggestion")
    if not reply:
        reply = "Hi! This is an automated note from Muoziiy's assistant: " \
                "I'm not able to answer this one right now."
    typing(conn_id, chat_id)
    try:
        send_as_user(conn_id, chat_id, reply)
        conn = db()
        with _lock:
            conn.execute("UPDATE msgs SET reply=? WHERE chat_id=? AND msg_id=?",
                         (reply, chat_id, msg_id))
            conn.commit()
        tg("answerCallbackQuery", {"callback_query_id": q["id"],
                                   "text": "Sent as you ✅"})
        tg("editMessageText", {"chat_id": ADMIN, "message_id":
                               q["message"]["message_id"],
                               "text": "✅ sent as you:\n" + reply})
    except Exception as e:
        log.error("send: %s", e)
        try:
            tg("answerCallbackQuery", {"callback_query_id": q["id"],
                                       "text": f"failed: {e}"})
        except Exception:
            pass


ADMIN_CMDS = {
    "/start": "Business agent bot. Commands: /status /auto /manual /read",
    "/status": None,   # rendered live
    "/auto": "Auto mode on: I answer incoming chats as you without asking.",
    "/manual": "Manual mode: I draft, you approve with ✅ before anything is sent.",
    "/read": "Read receipts on: incoming messages get marked as read.",
    "/off": "Read receipts off.",
}


def handle_admin_message(msg):
    text = (msg.get("text") or "").strip()
    if not text.startswith("/"):
        return
    cmd = text.split()[0].lower()
    if cmd in ("/start", "/status"):
        n = 0
        conn = db()
        with _lock:
            n = conn.execute("SELECT COUNT(*) FROM msgs").fetchone()[0]
        tell_admin(
            f"🤖 business agent\nmode: {CFG.get('mode')}\n"
            f"read receipts: {'on' if CFG.get('read_receipts') else 'off'}\n"
            f"ai replies: {'on' if ai_reply('ping') is not None else 'off (no key yet)'}\n"
            f"connections: {len(conn_cache)}\n"
            f"messages logged: {n}")
        return
    if cmd == "/auto":
        CFG["mode"] = "auto"
    elif cmd == "/manual":
        CFG["mode"] = "manual"
    elif cmd == "/read":
        CFG["read_receipts"] = True
    elif cmd == "/off":
        CFG["read_receipts"] = False
    else:
        tell_admin(ADMIN_CMDS.get("/start"))
        return
    save_cfg()
    tell_admin(ADMIN_CMDS.get(cmd, cmd))


def save_cfg():
    try:
        json.dump({k: CFG[k] for k in DEFAULT_CFG}, open(CFG_PATH, "w"), indent=2)
    except Exception as e:
        log.warning("save_cfg: %s", e)


def main():
    if not TOKEN:
        print("no bot token: put it in config.json (bot_token) or env TELEGRAM_BOT_TOKEN")
        sys.exit(1)
    me = tg("getMe", timeout=10)
    log.info("running as @%s (id %s)", me["username"], me["id"])
    offset = 0
    allowed = ["business_message", "edited_business_message",
               "deleted_business_messages", "business_connection",
               "message", "callback_query"]
    while True:
        try:
            updates = tg("getUpdates", {"timeout": 50, "offset": offset,
                                        "allowed_updates": allowed}, timeout=60)
            for upd in updates:
                offset = upd["update_id"] + 1
                try:
                    if "business_message" in upd:
                        handle_business_message(upd)
                    elif "business_connection" in upd:
                        bc = upd["business_connection"]
                        conn_cache[bc["id"]] = bc
                        log.info("connection %s user_chat=%s enabled=%s",
                                 bc["id"], bc.get("user_chat_id"), bc.get("is_enabled"))
                        tell_admin(f"🔗 business connection "
                                   f"{'enabled' if bc.get('is_enabled') else 'DISABLED'}"
                                   f" (user chat {bc.get('user_chat_id')})")
                    elif "callback_query" in upd:
                        handle_callback(upd)
                    elif "message" in upd:
                        m = upd["message"]
                        chat = m.get("chat", {})
                        if chat.get("type") != "private":
                            continue  # never use or message groups
                        if chat.get("id") == ADMIN:
                            handle_admin_message(m)
                        elif (m.get("text") or "").strip().lower().startswith(("/start", "/help")):
                            tg("sendMessage", {"chat_id": chat["id"],
                                               "text": _intro_for(m.get("from", {}).get("language_code")),
                                               "disable_web_page_preview": True})
                        # everyone else: silent, admin only
                except Exception:
                    log.exception("update handling failed")
        except RuntimeError as e:
            log.error("api: %s", e)
            time.sleep(5)
        except Exception:
            log.exception("poll loop failed")
            time.sleep(5)


if __name__ == "__main__":
    main()
