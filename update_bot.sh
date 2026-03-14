#!/bin/bash
# 1. 이동
cd /home/doukui7/upbit-bot

# 2. 깃허브에서 원격 정보를 가져옴 (실제로 받지는 않음)
git fetch origin main

# 3. 로컬 버전과 원격 버전 비교
LOCAL=$(git rev-parse @)
REMOTE=$(git rev-parse @{u})

if [ $LOCAL != $REMOTE ]; then
    echo "[$(date)] New changes detected! Updating..."
    # 4. 코드 내려받기
    git pull origin main
    # 5. 서비스 재시작
    sudo systemctl restart upbit-bot
    echo "Update complete and service restarted."
else
    # echo "[$(date)] No changes."
    exit 0
fi
