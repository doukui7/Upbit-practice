#!/bin/bash
WORKDIR="$(dirname "$(readlink -f "$0")")"
cd "$WORKDIR"

git fetch origin main

LOCAL=$(git rev-parse @)
REMOTE=$(git rev-parse @{u})

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "[$(date)] New changes detected! Updating..."
    # 로컬 변경사항 stash (setup.sh 등 충돌 방지)
    git stash --include-untracked
    git pull origin main
    # 서비스 재시작
    sudo systemctl restart upbit-bot
    echo "[$(date)] Update complete and service restarted."
else
    exit 0
fi
