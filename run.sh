#!/bin/bash
cd "$(dirname "$0")"
PORT=8740 nohup python3 app.py > server.log 2>&1 &
echo "started pid $!"
