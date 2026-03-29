"""텔레그램 알림 전송 (D:\\upbit notifier.py 패턴 기반)."""
import os
import re
import logging

logger = logging.getLogger(__name__)


def send_telegram(message: str):
    """텔레그램 봇으로 메시지 전송. 토큰/챗ID 없으면 무시."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return

    # 토큰 정규화
    token = re.sub(r"\s+", "", token).strip('"').strip("'")
    if token.lower().startswith("bot"):
        token = token[3:]

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        import urllib.request
        import json
        for i in range(0, len(message), 4000):
            chunk = message[i:i + 4000]
            # HTML 태그 안전 처리
            safe = re.sub(r"<(?!/?(b|i|u|s|code|pre|a)\b)[^>]+>", "", chunk)
            body = json.dumps({
                "chat_id": chat_id,
                "text": safe,
                "parse_mode": "HTML",
            }).encode()
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    logger.info("텔레그램 전송 성공")
                else:
                    logger.warning(f"텔레그램 전송 실패: HTTP {resp.status}")
    except Exception as e:
        logger.warning(f"텔레그램 전송 실패: {e}")
