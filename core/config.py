"""Shared configuration: broker login profiles and risk parameters.

Stored in broker_config.json next to app.py. This file is read/written by
every page so that broker credentials and risk settings stay in sync across
the Dashboard, Indices Advisor, Journal, and Settings pages.
"""
import copy
import json
import os
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parent.parent / "broker_config.json"

DEFAULT_CONFIG = {
    "profiles": {},
    "active_profile": None,
    "risk": {
        "account_size": 1000.0,
        "risk_percentage": 50.0,
    },
    "trading_plans": {},
    "screenshot_folder": "",
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
        merged.setdefault("trading_plans", {})
        merged.setdefault("screenshot_folder", "")
        for key, value in DEFAULT_CONFIG["risk"].items():
            merged["risk"].setdefault(key, value)
        return merged

    return copy.deepcopy(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def get_active_profile(cfg: dict):
    name = cfg.get("active_profile")
    profiles = cfg.get("profiles", {})
    if name and name in profiles:
        return name, profiles[name]
    return None, None


def upsert_profile(cfg: dict, name: str, terminal_path: str, login: str, password: str, server: str) -> None:
    cfg.setdefault("profiles", {})
    existing = dict(cfg["profiles"].get(name) or {})
    existing.update({
        "terminal_path": terminal_path.strip(),
        "login": login.strip(),
        "password": password,
        "server": server.strip(),
    })
    cfg["profiles"][name] = existing
    save_config(cfg)


def set_enabled_index_classes(cfg: dict, profile_name: str, classes: list[str]) -> None:
    profiles = cfg.setdefault("profiles", {})
    if profile_name not in profiles:
        return
    profiles[profile_name]["enabled_index_classes"] = list(classes)
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


def save_trading_plan(cfg: dict, plan_name: str, start_capital: float, trading_days: int, tp_percentage: float, start_date: str = None, challenge_duration: int = 1) -> None:
    cfg.setdefault("trading_plans", {})
    cfg["trading_plans"][plan_name] = {
        "start_capital": start_capital,
        "trading_days": trading_days,
        "tp_percentage": tp_percentage,
        "start_date": start_date,
        "challenge_duration": challenge_duration,
        "linked_profile": None,
    }
    save_config(cfg)


def delete_trading_plan(cfg: dict, plan_name: str) -> None:
    cfg.get("trading_plans", {}).pop(plan_name, None)
    for profile_name, profile_data in cfg.get("profiles", {}).items():
        if profile_data.get("trading_plan") == plan_name:
            profile_data["trading_plan"] = None
    save_config(cfg)


def link_plan_to_profile(cfg: dict, plan_name: str, profile_name: str) -> None:
    if profile_name in cfg.get("profiles", {}) and plan_name in cfg.get("trading_plans", {}):
        cfg["profiles"][profile_name]["trading_plan"] = plan_name
        cfg["trading_plans"][plan_name]["linked_profile"] = profile_name
        save_config(cfg)


def unlink_plan_from_profile(cfg: dict, profile_name: str) -> None:
    if profile_name in cfg.get("profiles", {}):
        plan_name = cfg["profiles"][profile_name].get("trading_plan")
        if plan_name and plan_name in cfg.get("trading_plans", {}):
            cfg["trading_plans"][plan_name]["linked_profile"] = None
        cfg["profiles"][profile_name]["trading_plan"] = None
        save_config(cfg)


def get_profile_plan(cfg: dict, profile_name: str):
    if profile_name in cfg.get("profiles", {}):
        plan_name = cfg["profiles"][profile_name].get("trading_plan")
        if plan_name and plan_name in cfg.get("trading_plans", {}):
            return plan_name, cfg["trading_plans"][plan_name]
    return None, None


def calculate_plan_progress(plan: dict, current_balance: float = None, trade_history=None) -> dict:
    import datetime as dt
    import pandas as pd
    import math
    
    start_capital = plan["start_capital"]
    trading_days = plan["trading_days"]
    tp_percentage = plan["tp_percentage"]
    saved_start_date = plan.get("start_date")
    
    start_date = None
    if trade_history is not None and not trade_history.empty:
        earliest_trade_date = trade_history['Time'].min().date()
        start_date = earliest_trade_date.replace(day=1)
    
    if not start_date and saved_start_date:
        try:
            start_date = dt.datetime.strptime(saved_start_date, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            start_date = dt.date.today()
    
    if not start_date:
        start_date = dt.date.today()
    
    # Day N means the Day-N target has been reached:
    # start * growth^N <= balance < start * growth^(N+1).
    # e.g. $1 start @ 100% TP → Day 1 is [$2, $4), Day 2 is [$4, $8), etc.
    # Day 0 = still below the first target (including below start capital).
    growth_factor = 1 + tp_percentage / 100
    current_day = 0
    if current_balance and current_balance > 0 and growth_factor > 1 and start_capital > 0:
        ratio = current_balance / start_capital
        if ratio >= growth_factor:
            # Floor log maps balance into completed-day bands; epsilon
            # keeps exact milestone balances (e.g. $4.00) on the higher day.
            current_day = math.floor(math.log(ratio, growth_factor) + 1e-12)
            current_day = max(0, min(current_day, trading_days))

    expected_balance = start_capital * (growth_factor ** current_day)
    final_balance = start_capital * (growth_factor ** trading_days)
    remaining_days = max(0, trading_days - current_day)
    
    return {
        "current_day": current_day,
        "expected_balance": expected_balance,
        "final_balance": final_balance,
        "remaining_days": remaining_days,
        "total_days": trading_days,
        "start_capital": start_capital,
        "tp_percentage": tp_percentage,
        "start_date": start_date,
    }


def set_screenshot_folder(cfg: dict, folder_path: str) -> None:
    cfg["screenshot_folder"] = os.path.normpath(folder_path)
    save_config(cfg)


def get_screenshot_folder(cfg: dict) -> str | None:
    return cfg.get("screenshot_folder")


def calculate_weekly_frequency(plan: dict, year: int, month: int) -> list:
    import calendar
    import datetime as dt
    
    trading_days = plan["trading_days"]
    challenge_duration = plan.get("challenge_duration", 1)
    
    cal = calendar.monthcalendar(year, month)
    
    week_lengths = []
    for week in cal:
        days_in_week = sum(1 for day in week if day != 0)
        if days_in_week > 0:
            week_lengths.append(days_in_week)
    
    total_weight = sum(week_lengths)
    
    weekly_distribution = []
    remaining_days = trading_days
    
    for i, week_length in enumerate(week_lengths):
        if i == len(week_lengths) - 1:
            trades_this_week = remaining_days
        else:
            weight = week_length / total_weight
            trades_this_week = max(0, round(trading_days * weight))
            remaining_days -= trades_this_week
        
        weekly_distribution.append(trades_this_week)
    
    return weekly_distribution