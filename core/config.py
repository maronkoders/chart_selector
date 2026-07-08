"""Shared configuration: broker login profiles and risk parameters.

Stored in broker_config.json next to app.py. This file is read/written by
every page so that broker credentials and risk settings stay in sync across
the Dashboard, Indices Advisor, Journal, and Settings pages.
"""
import copy
import json
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parent.parent / "broker_config.json"

DEFAULT_CONFIG = {
    "profiles": {},
    # name of the currently active entry in "profiles"
    "active_profile": None,
    "risk": {
        "account_size": 1000.0,
        "risk_percentage": 50.0,
    },
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return copy.deepcopy(DEFAULT_CONFIG)

        merged = copy.deepcopy(DEFAULT_CONFIG)
        merged.update(data)
        merged.setdefault("profiles", {})
        merged.setdefault("risk", {})
        for key, value in DEFAULT_CONFIG["risk"].items():
            merged["risk"].setdefault(key, value)
        return merged

    return copy.deepcopy(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def get_active_profile(cfg: dict):
    """Returns (profile_name, profile_dict) or (None, None) if none is active."""
    name = cfg.get("active_profile")
    profiles = cfg.get("profiles", {})
    if name and name in profiles:
        return name, profiles[name]
    return None, None


def upsert_profile(cfg: dict, name: str, terminal_path: str, login: str, password: str, server: str) -> None:
    cfg.setdefault("profiles", {})
    cfg["profiles"][name] = {
        "terminal_path": terminal_path.strip(),
        "login": login.strip(),
        "password": password,
        "server": server.strip(),
    }
    save_config(cfg)


def delete_profile(cfg: dict, name: str) -> None:
    cfg.get("profiles", {}).pop(name, None)
    if cfg.get("active_profile") == name:
        cfg["active_profile"] = None
    save_config(cfg)


def set_active_profile(cfg: dict, name: str | None) -> None:
    cfg["active_profile"] = name
    save_config(cfg)


def set_risk_params(cfg: dict, account_size: float, risk_percentage: float) -> None:
    cfg["risk"]["account_size"] = account_size
    cfg["risk"]["risk_percentage"] = risk_percentage
    save_config(cfg)