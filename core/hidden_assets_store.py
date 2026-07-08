"""Hidden-assets persistence for the Indices Advisor scanner.

Assets hidden from the scanner stay hidden across reruns and sessions until
explicitly unhidden (individually) or cleared (all at once).
"""
import json
from pathlib import Path

import streamlit as st

HIDDEN_ASSETS_FILE = Path(__file__).resolve().parent.parent / "hidden_assets.json"


def load_hidden_assets() -> set[str]:
    if HIDDEN_ASSETS_FILE.exists():
        try:
            return set(json.loads(HIDDEN_ASSETS_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_hidden_assets(hidden: set[str]) -> None:
    HIDDEN_ASSETS_FILE.write_text(
        json.dumps(sorted(hidden), indent=2),
        encoding="utf-8",
    )


def init_hidden_assets() -> set[str]:
    if "hidden_assets" not in st.session_state:
        st.session_state.hidden_assets = load_hidden_assets()
    return st.session_state.hidden_assets


def hide_asset(asset: str) -> None:
    st.session_state.hidden_assets.add(asset)
    save_hidden_assets(st.session_state.hidden_assets)


def unhide_asset(asset: str) -> None:
    st.session_state.hidden_assets.discard(asset)
    save_hidden_assets(st.session_state.hidden_assets)


def clear_hidden_assets() -> None:
    st.session_state.hidden_assets = set()
    save_hidden_assets(st.session_state.hidden_assets)