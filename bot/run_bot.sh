#!/bin/bash
cd "$(dirname "$0")"
if [ -f bot.pid ] && kill -0 "$(cat bot.pid)" 2>/dev/null; then kill "$(cat bot.pid)"; sleep 1; fi
nohup python3 bot.py >> bot.log 2>&1 &
echo $! > bot.pid
echo "launched, pid $!"
