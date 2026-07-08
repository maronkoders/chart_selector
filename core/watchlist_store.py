"""Watchlist persistence, shared across the Dashboard and Indices Advisor pages."""
import json
from pathlib import Path

import streamlit as st

WATCHLIST_FILE = Path(__file__).resolve().parent.parent / "watchlist.json"


def load_watchlist() -> set[str]:
    if WATCHLIST_FILE.exists():
        try:
            return set(json.loads(WATCHLIST_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_watchlist(watchlist: set[str]) -> None:
    WATCHLIST_FILE.write_text(
        json.dumps(sorted(watchlist), indent=2),
        encoding="utf-8",
    )


def init_watchlist() -> set[str]:
    if "watchlist" not in st.session_state:
        st.session_state.watchlist = load_watchlist()
    return st.session_state.watchlist


def add_to_watchlist(asset: str) -> None:
    st.session_state.watchlist.add(asset)
    save_watchlist(st.session_state.watchlist)


def remove_from_watchlist(asset: str) -> None:
    st.session_state.watchlist.discard(asset)
    save_watchlist(st.session_state.watchlist)