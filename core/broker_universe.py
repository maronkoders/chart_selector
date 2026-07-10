"""Instrument universes and feature flags per broker profile.

Deriv and Weltrade both expose synthetic indices, but with different symbol
names and MT5 paths. Profiles can override these defaults via
`broker_type` / `universe` / `features` in broker_config.json.
"""
from __future__ import annotations

from typing import Any

BROKER_TYPE_DERIV = "deriv_synthetics"
BROKER_TYPE_WELTRADE = "weltrade_synthetics"
BROKER_TYPE_GENERIC = "generic"

UNIVERSES: dict[str, dict[str, Any]] = {
    BROKER_TYPE_DERIV: {
        "mt5_groups": [
            "*Volatility*",
            "*Step*",
            "*Jump*",
            "*Crash*",
            "*Boom*",
            # "*Dex*",
            # "*Range*",
        ],
        "path_contains": [],
        "exclude_keywords": ["vol over", "spot up", "spot down", "skew"],
        "crash_boom_numbers": ["300", "500", "600", "900", "1000"],
        "index_class_keywords": [
            ["Volatility", "volatility"],
            ["Boom", "boom"],
            ["Crash", "crash"],
            ["Step", "step"],
            ["Jump", "jump"],
        ],
    },
    BROKER_TYPE_WELTRADE: {
        # Weltrade synthetics live under the Synthetics\\ path (FX Vol, GainX, …).
        "mt5_groups": ["*"],
        "path_contains": ["Synthetics"],
        "exclude_keywords": [],
        "crash_boom_numbers": [],
        "index_class_keywords": [
            ["FX Vol", "fx vol"],
            ["SFX Vol", "sfx vol"],
            ["BreakX", "breakx"],
            ["GainX", "gainx"],
            ["PainX", "painx"],
            ["FlipX", "flipx"],
            ["SwitchX", "switchx"],
            ["TrendX", "trendx"],
            ["FiboX", "fibox"],
            ["PlusX", "plusx"],
            ["QuadX", "quadx"],
        ],
    },
    BROKER_TYPE_GENERIC: {
        "mt5_groups": ["*"],
        "path_contains": [],
        "exclude_keywords": [],
        "crash_boom_numbers": [],
        "index_class_keywords": [],
    },
}

DEFAULT_FEATURES: dict[str, Any] = {
    "indices_advisor": True,
    "bias_filter": True,
    # "auto" = prefer exporter JSON, then live MT5 EMA bias (same rules as MOLD_EMPIRE).
    "bias_source": "auto",
}


def infer_broker_type(profile: dict | None) -> str:
    if not profile:
        return BROKER_TYPE_GENERIC
    explicit = profile.get("broker_type")
    if explicit in UNIVERSES:
        return explicit

    server = (profile.get("server") or "").lower()
    name = ""  # filled by caller sometimes
    blob = f"{server} {name}"
    if "weltrade" in server:
        return BROKER_TYPE_WELTRADE
    if "deriv" in server:
        return BROKER_TYPE_DERIV
    return BROKER_TYPE_GENERIC


def get_profile_broker_type(profile_name: str | None, profile: dict | None) -> str:
    if profile and profile.get("broker_type") in UNIVERSES:
        return profile["broker_type"]
    if profile:
        server = (profile.get("server") or "").lower()
        pname = (profile_name or "").lower()
        if "weltrade" in server or "weltrade" in pname:
            return BROKER_TYPE_WELTRADE
        if "deriv" in server or "deriv" in pname:
            return BROKER_TYPE_DERIV
    return BROKER_TYPE_GENERIC


def get_profile_universe(profile_name: str | None, profile: dict | None) -> dict[str, Any]:
    if profile and isinstance(profile.get("universe"), dict) and profile["universe"]:
        base = dict(UNIVERSES[get_profile_broker_type(profile_name, profile)])
        base.update(profile["universe"])
        return base
    return dict(UNIVERSES[get_profile_broker_type(profile_name, profile)])


def get_profile_features(profile: dict | None) -> dict[str, Any]:
    features = dict(DEFAULT_FEATURES)
    if profile and isinstance(profile.get("features"), dict):
        features.update(profile["features"])
    return features


def is_symbol_allowed(symbol_name: str, symbol_path: str, universe: dict[str, Any]) -> bool:
    import re

    name_lower = symbol_name.lower()
    path_lower = (symbol_path or "").lower()

    path_filters = universe.get("path_contains") or []
    if path_filters and not any(p.lower() in path_lower for p in path_filters):
        return False

    for keyword in universe.get("exclude_keywords") or []:
        if keyword.lower() in name_lower:
            return False

    allowed_numbers = set(universe.get("crash_boom_numbers") or [])
    if allowed_numbers and ("crash" in name_lower or "boom" in name_lower):
        numbers = re.findall(r"\d+", symbol_name)
        if not numbers or numbers[0] not in allowed_numbers:
            return False

    return True


def get_index_class(asset_name: str, universe: dict[str, Any]) -> str:
    name_lower = asset_name.lower()
    for pair in universe.get("index_class_keywords") or []:
        if len(pair) >= 2 and pair[1].lower() in name_lower:
            return pair[0]
    return "Other"


def advisor_title(broker_type: str) -> str:
    if broker_type == BROKER_TYPE_WELTRADE:
        return "🎯 Weltrade Synthetic Indices Advisor"
    if broker_type == BROKER_TYPE_DERIV:
        return "🎯 Deriv Synthetic Indices Advisor"
    return "🎯 Indices Advisor"
