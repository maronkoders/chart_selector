"""Hidden-assets persistence for the Indices Advisor scanner.

Assets hidden from the scanner stay hidden across reruns and sessions until
explicitly unhidden (individually) or cleared (all at once).

Storage is keyed by broker profile so Deriv hides do not leak into Weltrade
(and vice versa). Legacy list-shaped files are migrated under "_legacy".
"""
import json
from pathlib import Path

import streamlit as st

HIDDEN_ASSETS_FILE = Path(__file__).resolve().parent.parent / "hidden_assets.json"
LEGACY_KEY = "_legacy"


def _read_store() -> dict:
    if not HIDDEN_ASSETS_FILE.exists():
        return {}
    try:
        data = json.loads(HIDDEN_ASSETS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    if isinstance(data, list):
        return {LEGACY_KEY: sorted(set(data))}
    if isinstance(data, dict):
        normalized = {}
        for key, value in data.items():
            if isinstance(value, list):
                normalized[key] = sorted(set(value))
        return normalized
    return {}


def _write_store(store: dict) -> None:
    HIDDEN_ASSETS_FILE.write_text(json.dumps(store, indent=2), encoding="utf-8")


def _profile_key(profile_name: str | None) -> str:
    return profile_name or LEGACY_KEY


def load_hidden_assets(profile_name: str | None = None) -> set[str]:
    store = _read_store()
    key = _profile_key(profile_name)
    if key in store:
        return set(store[key])
    # First time for this profile: do not inherit another broker's hides.
    return set()


def save_hidden_assets(hidden: set[str], profile_name: str | None = None) -> None:
    store = _read_store()
    store[_profile_key(profile_name)] = sorted(hidden)
    _write_store(store)


def init_hidden_assets(profile_name: str | None = None) -> set[str]:
    active = profile_name
    if active is None:
        active = st.session_state.get("mt5_connected_profile") or st.session_state.get(
            "app_config", {}
        ).get("active_profile")

    cached_profile = st.session_state.get("hidden_assets_profile")
    if "hidden_assets" not in st.session_state or cached_profile != active:
        st.session_state.hidden_assets = load_hidden_assets(active)
        st.session_state.hidden_assets_profile = active
    return st.session_state.hidden_assets


def hide_asset(asset: str, profile_name: str | None = None) -> None:
    st.session_state.hidden_assets.add(asset)
    save_hidden_assets(
        st.session_state.hidden_assets,
        profile_name or st.session_state.get("hidden_assets_profile"),
    )


def unhide_asset(asset: str, profile_name: str | None = None) -> None:
    st.session_state.hidden_assets.discard(asset)
    save_hidden_assets(
        st.session_state.hidden_assets,
        profile_name or st.session_state.get("hidden_assets_profile"),
    )


def clear_hidden_assets(profile_name: str | None = None) -> None:
    st.session_state.hidden_assets = set()
    save_hidden_assets(
        st.session_state.hidden_assets,
        profile_name or st.session_state.get("hidden_assets_profile"),
    )
