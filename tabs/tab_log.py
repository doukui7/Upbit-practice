"""
Tab: Log
All trading activity logs stored in session_state.
"""
import os
import streamlit as st
from datetime import datetime
from streamlit_autorefresh import st_autorefresh


def add_log(message: str, level: str = "INFO"):
    """Add a log entry to session_state. Call from any tab."""
    if "logs" not in st.session_state:
        st.session_state.logs = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.logs.append({
        "time": timestamp,
        "level": level,
        "message": message,
    })


def render():
    # Auto-refresh every 3 s so new log entries from other fragments appear quickly
    st_autorefresh(interval=3_000, key="log_autorefresh")

    st.subheader("📋 작업 로그")

    if "logs" not in st.session_state or not st.session_state.logs:
        st.info("아직 기록된 로그가 없습니다.")
        return

    # Filter controls
    col1, col2 = st.columns([2, 1])
    with col1:
        keyword = st.text_input("🔍 로그 검색", placeholder="검색어 입력...")
    with col2:
        level_filter = st.selectbox(
            "레벨 필터",
            ["전체", "INFO", "WARNING", "ERROR", "ORDER", "DEBUG"],
        )

    # Action buttons
    btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 2])

    with btn_col1:
        if st.button("🗑 로그 초기화", type="secondary"):
            st.session_state.logs = []
            st.rerun()

    # 세션 로그 다운로드
    with btn_col2:
        log_text = "\n".join(
            f"[{e['time']}] [{e['level']}] {e['message']}"
            for e in st.session_state.logs
        )
        st.download_button(
            "📥 세션 로그 다운로드",
            data=log_text,
            file_name=f"session_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            mime="text/plain",
        )

    # trade.log 파일 다운로드
    with btn_col3:
        trade_log_path = "trade.log"
        if os.path.exists(trade_log_path):
            with open(trade_log_path, "r", encoding="utf-8") as f:
                trade_log_content = f.read()
            st.download_button(
                "📥 trade.log 다운로드",
                data=trade_log_content,
                file_name=f"trade_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                mime="text/plain",
            )

    st.divider()

    # Display logs (newest first), hide DEBUG by default
    logs = list(reversed(st.session_state.logs))

    if level_filter == "전체":
        logs = [l for l in logs if l["level"] != "DEBUG"]
    elif level_filter == "DEBUG":
        logs = [l for l in logs if l["level"] == "DEBUG"]
    else:
        logs = [l for l in logs if l["level"] == level_filter]
    if keyword:
        logs = [l for l in logs if keyword.lower() in l["message"].lower()]

    if not logs:
        st.warning("조건에 맞는 로그가 없습니다.")
        return

    level_colors = {
        "INFO":    "🔵",
        "WARNING": "🟡",
        "ERROR":   "🔴",
        "ORDER":   "🟢",
    }

    for entry in logs:
        icon = level_colors.get(entry["level"], "⚪")
        st.markdown(
            f"`{entry['time']}` {icon} **[{entry['level']}]** {entry['message']}"
        )
