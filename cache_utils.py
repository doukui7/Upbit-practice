"""
Cache Utilities — 파일 기반 캐시 읽기/쓰기 + GitHub 동기화
- VM(api_server.py): save_* / push_file_via_api 사용
- 로컬(Streamlit): load_* / sync_cache_from_github 사용
"""
import os
import json
import time
import base64
import logging
import subprocess
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# 프로젝트 루트 기준 cache 디렉토리
PROJECT_DIR = Path(__file__).parent
CACHE_DIR = PROJECT_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# 동기화 상태 (로컬에서 중복 fetch 방지)
_last_sync_time = 0
SYNC_INTERVAL = 120  # 2분


# ══════════════════════════════════════════════════════════════════════
# 읽기 (로컬 Streamlit + VM 공통)
# ══════════════════════════════════════════════════════════════════════

def load_balance_cache():
    """잔고 캐시 읽기"""
    return _load_json(CACHE_DIR / "balance_cache.json", default={})


def load_signal_state():
    """신호 상태 읽기"""
    return _load_json(CACHE_DIR / "signal_state.json", default={})


def load_trade_log(limit=50):
    """거래 기록 읽기 (최신 limit건)"""
    data = _load_json(CACHE_DIR / "trade_log.json", default=[])
    return data[-limit:] if isinstance(data, list) else []


def load_scheduler_state():
    """스케줄러 상태 읽기"""
    return _load_json(CACHE_DIR / "scheduler_state.json", default={})


def _load_json(path, default=None):
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Cache read error ({path.name}): {e}")
    return default if default is not None else {}


# ══════════════════════════════════════════════════════════════════════
# 쓰기 (VM api_server.py에서 사용)
# ══════════════════════════════════════════════════════════════════════

def save_balance_cache(data):
    """잔고 캐시 저장"""
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_json(CACHE_DIR / "balance_cache.json", data)


def save_signal_state(data):
    """신호 상태 저장"""
    _save_json(CACHE_DIR / "signal_state.json", data)


def save_scheduler_state(data):
    """스케줄러 상태 저장 (D:\\upbit 하트비트 패턴)"""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Seoul"))
    except Exception:
        now = datetime.now()
    data["__heartbeat_kst"] = now.strftime("%Y-%m-%d %H:%M:%S")
    data["__heartbeat_epoch"] = f"{time.time():.3f}"
    if "__started_at_kst" not in data:
        data["__started_at_kst"] = now.strftime("%Y-%m-%d %H:%M:%S")
    _save_json(CACHE_DIR / "scheduler_state.json", data)


def append_trade_log(entry, max_entries=200):
    """거래 기록 추가 (최대 max_entries건 유지)"""
    entry["logged_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data = _load_json(CACHE_DIR / "trade_log.json", default=[])
    if not isinstance(data, list):
        data = []
    data.append(entry)
    if len(data) > max_entries:
        data = data[-max_entries:]
    _save_json(CACHE_DIR / "trade_log.json", data)


def append_execution_log(entry, max_entries=200):
    """실행 기록 추가 (전략 계산, 스케줄 실행 등)"""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Seoul"))
    except Exception:
        now = datetime.now()
    entry["logged_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
    data = _load_json(CACHE_DIR / "execution_log.json", default=[])
    if not isinstance(data, list):
        data = []
    data.append(entry)
    if len(data) > max_entries:
        data = data[-max_entries:]
    _save_json(CACHE_DIR / "execution_log.json", data)


def load_execution_log(limit=50):
    """실행 기록 읽기"""
    data = _load_json(CACHE_DIR / "execution_log.json", default=[])
    return data[-limit:] if isinstance(data, list) else []


def record_scheduler_error(state, mode, error_msg):
    """스케줄러 에러 기록 (D:\\upbit 패턴: 연속 실패 카운트 + 마지막 에러)"""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Seoul"))
    except Exception:
        now = datetime.now()
    fails = int(state.get("__consecutive_failures", 0)) + 1
    state["__consecutive_failures"] = str(fails)
    state["__last_error"] = f"{now.strftime('%Y-%m-%d %H:%M:%S')} | {mode}: {str(error_msg)[:200]}"
    save_scheduler_state(state)
    return fails


def record_scheduler_success(state, mode):
    """스케줄러 성공 기록 (연속 실패 초기화 + 마지막 실행 기록)"""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Seoul"))
    except Exception:
        now = datetime.now()
    state["__consecutive_failures"] = "0"
    state["__last_trade_kst"] = now.strftime("%Y-%m-%d %H:%M:%S")
    state["__last_trade_epoch"] = f"{time.time():.3f}"
    state["__last_trade_mode"] = mode
    state[mode] = now.strftime("%Y%m%d%H")
    save_scheduler_state(state)


def _save_json(path, data):
    """atomic write (tmp → rename) — 동시 쓰기 데이터 손실 방지"""
    tmp_path = path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp_path.replace(path)
    except IOError as e:
        logger.error(f"Cache write error ({path.name}): {e}")
        if tmp_path.exists():
            tmp_path.unlink()


# ══════════════════════════════════════════════════════════════════════
# GitHub 동기화
# ══════════════════════════════════════════════════════════════════════

CACHE_FILES = [
    "cache/balance_cache.json",
    "cache/signal_state.json",
    "cache/trade_log.json",
    "cache/scheduler_state.json",
    "cache/execution_log.json",
    "cache/reserve_orders.json",
]


def sync_cache_from_github(force=False):
    """GitHub에서 cache 파일 동기화 (로컬 Streamlit용, 2분 간격)"""
    global _last_sync_time
    now = time.time()
    if not force and (now - _last_sync_time) < SYNC_INTERVAL:
        return False

    try:
        subprocess.run(
            ["git", "fetch", "origin", "--quiet"],
            cwd=str(PROJECT_DIR), timeout=10,
            capture_output=True,
        )
        for f in CACHE_FILES:
            subprocess.run(
                ["git", "checkout", "origin/main", "--", f],
                cwd=str(PROJECT_DIR), timeout=5,
                capture_output=True,
            )
        _last_sync_time = now
        logger.info("Cache synced from GitHub")
        return True
    except Exception as e:
        logger.warning(f"GitHub sync failed: {e}")
        return False


def self_heal_reset(consecutive_failures: int):
    """연속 실패 시 자가 복구 (D:\\upbit 패턴).
    상태 파일 백업 → git reset → 상태 복원."""
    import shutil
    import subprocess

    logger.warning(f"자가복구 발동: 연속 {consecutive_failures}회 실패")

    backup_dir = Path("/tmp/_trade_backup")
    backup_dir.mkdir(exist_ok=True)

    preserve = ["signal_state.json", "balance_cache.json", "trade_log.json",
                 "execution_log.json", "portfolio.json"]
    for fname in preserve:
        src = CACHE_DIR / fname
        if src.exists():
            shutil.copy2(str(src), str(backup_dir / fname))

    try:
        subprocess.run(["git", "fetch", "origin"], cwd=str(PROJECT_DIR),
                        timeout=30, capture_output=True)
        subprocess.run(["git", "reset", "--hard", "origin/main"],
                        cwd=str(PROJECT_DIR), timeout=30, capture_output=True)
        logger.info("git reset --hard origin/main 완료")
    except Exception as e:
        logger.error(f"git reset 실패: {e}")

    for fname in preserve:
        bk = backup_dir / fname
        if bk.exists():
            shutil.copy2(str(bk), str(CACHE_DIR / fname))

    try:
        from notifier import send_telegram
        send_telegram(f"<b>자가복구 완료</b>\n연속 {consecutive_failures}회 실패 후 git reset 실행")
    except Exception:
        pass


def push_file_via_api(gh_pat, filepath, commit_msg="auto-update cache"):
    """GitHub Contents API로 단일 파일 push (VM용, D:\\upbit 패턴 재사용)"""
    import urllib.request
    import urllib.error

    repo = os.getenv("GH_REPO", "doukui7/Upbit-practice")
    api_url = f"https://api.github.com/repos/{repo}/contents/{filepath}"
    headers = {
        "Authorization": f"token {gh_pat}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "auto-trade-bot",
    }

    local_path = PROJECT_DIR / filepath
    if not local_path.exists():
        return False

    content = local_path.read_bytes()
    encoded = base64.b64encode(content).decode()

    try:
        # GET: 현재 SHA 조회
        req = urllib.request.Request(api_url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                sha = data.get("sha", "")
                remote = base64.b64decode(data.get("content", "").replace("\n", ""))
                if remote == content:
                    return False  # 변경 없음
        except urllib.error.HTTPError as e:
            sha = "" if e.code == 404 else None
            if sha is None:
                logger.warning(f"Contents API GET failed ({filepath}): {e}")
                return False

        # PUT: 파일 업데이트
        body = json.dumps({
            "message": commit_msg,
            "content": encoded,
            "sha": sha,
            "committer": {"name": "auto-trade-bot", "email": "bot@auto-trade"},
        }).encode()
        req = urllib.request.Request(api_url, data=body, headers=headers, method="PUT")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status in (200, 201)
    except Exception as e:
        logger.warning(f"Contents API PUT failed ({filepath}): {e}")
        return False


def push_all_cache(gh_pat):
    """모든 캐시 파일을 GitHub에 push"""
    pushed = 0
    for f in CACHE_FILES:
        if push_file_via_api(gh_pat, f, f"update {f}"):
            pushed += 1
    if pushed:
        logger.info(f"GitHub push: {pushed}/{len(CACHE_FILES)} files updated")
    return pushed
