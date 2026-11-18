# Telegram travel packages mini app

Safar paketlari ro'yxati Telegram mini app sifatida.

## VPS da ishga tushirish

    python3 app.py          # http://0.0.0.0:8740
    # nginx orqali HTTPS berish kerak (Telegram mini app HTTPS talab qiladi)

Paketlar `packages.json` (yoki `static/packages.json`) da; narxlarni shu faylda yangilang.

## Bot (Telegram Business agent)

Bot kodi `bot/` papkasida. Ishga tushirish:

    cd bot
    cp config.example.json config.json   # tokenlaringizni config.json ga yozing
    bash run_bot.sh                      # fon rejimida ishga tushiradi (bot.pid/bot.log)

Fayllar: `bot.py` (asosiy bot), `agent_run.py` (AI javob rejimi), `agent_prompt.md` + `responses.md` + `travel_kb.md` (billet va javoblar bazasi), `mcp_server.py` + `run_mcp.sh` (MCP server, MCP_TOKEN bilan qo'riqlangan). `config.json` (tokenlar) git ga kirmaydi, `.gitignore` da.
