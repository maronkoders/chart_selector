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
    "trading_plans": {},
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


def save_trading_plan(cfg: dict, plan_name: str, start_capital: float, trading_days: int, tp_percentage: float, start_date: str = None, challenge_duration: int = 1) -> None:
    """Save a trading plan to the configuration."""
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
    """Delete a trading plan from the configuration."""
    cfg.get("trading_plans", {}).pop(plan_name, None)
    # Remove link from any profile that has this plan
    for profile_name, profile_data in cfg.get("profiles", {}).items():
        if profile_data.get("trading_plan") == plan_name:
            profile_data["trading_plan"] = None
    save_config(cfg)


def link_plan_to_profile(cfg: dict, plan_name: str, profile_name: str) -> None:
    """Link a trading plan to a broker profile."""
    if profile_name in cfg.get("profiles", {}) and plan_name in cfg.get("trading_plans", {}):
        cfg["profiles"][profile_name]["trading_plan"] = plan_name
        cfg["trading_plans"][plan_name]["linked_profile"] = profile_name
        save_config(cfg)


def unlink_plan_from_profile(cfg: dict, profile_name: str) -> None:
    """Unlink a trading plan from a broker profile."""
    if profile_name in cfg.get("profiles", {}):
        plan_name = cfg["profiles"][profile_name].get("trading_plan")
        if plan_name and plan_name in cfg.get("trading_plans", {}):
            cfg["trading_plans"][plan_name]["linked_profile"] = None
        cfg["profiles"][profile_name]["trading_plan"] = None
        save_config(cfg)


def get_profile_plan(cfg: dict, profile_name: str):
    """Get the trading plan linked to a profile."""
    if profile_name in cfg.get("profiles", {}):
        plan_name = cfg["profiles"][profile_name].get("trading_plan")
        if plan_name and plan_name in cfg.get("trading_plans", {}):
            return plan_name, cfg["trading_plans"][plan_name]
    return None, None


def calculate_plan_progress(plan: dict, current_balance: float = None, trade_history=None) -> dict:
    """Calculate the current progress of a trading plan.
    
    Args:
        plan: Trading plan dictionary
        current_balance: Current account balance (optional)
        trade_history: DataFrame of trade history for automatic tracking (optional)
    """
    import datetime as dt
    import pandas as pd
    import math
    
    start_capital = plan["start_capital"]
    trading_days = plan["trading_days"]
    tp_percentage = plan["tp_percentage"]
    saved_start_date = plan.get("start_date")
    
    # Determine start_date dynamically from trade history if available
    start_date = None
    if trade_history is not None and not trade_history.empty:
        # Get the earliest trade date from the history
        earliest_trade_date = trade_history['Time'].min().date()
        # Set start_date to the first day of that month
        start_date = earliest_trade_date.replace(day=1)
    
    # If no trade history or couldn't determine from trades, use saved start_date
    if not start_date and saved_start_date:
        try:
            start_date = dt.datetime.strptime(saved_start_date, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            start_date = dt.date.today()
    
    # Default to today if still no start_date
    if not start_date:
        start_date = dt.date.today()
    
    # Calculate current day based on current balance using the trading plan scale
    # Formula: balance = start_capital * (1 + tp_percentage/100)^current_day
    # Solving for current_day: current_day = log(balance / start_capital) / log(1 + tp_percentage/100)
    current_day = 1
    if current_balance and current_balance > 0:
        if current_balance >= start_capital:
            growth_factor = 1 + tp_percentage / 100
            if growth_factor > 1:
                current_day = math.log(current_balance / start_capital, growth_factor)
                current_day = max(1, min(round(current_day), trading_days))
            else:
                current_day = 1
        else:
            current_day = 1
    
    # Calculate expected balance for current day
    expected_balance = start_capital * ((1 + tp_percentage / 100) ** current_day)
    final_balance = start_capital * ((1 + tp_percentage / 100) ** trading_days)
    
    # Calculate remaining days
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
    """Save the screenshot folder path to config."""
    cfg["screenshot_folder"] = os.path.normpath(folder_path)
    save_config(cfg)

def get_screenshot_folder(cfg: dict) -> str | None:
    """Get the configured screenshot folder path."""
    return cfg.get("screenshot_folder")

def calculate_weekly_frequency(plan: dict, year: int, month: int) -> list:
    """Calculate weekly trading frequency distribution for a specific month.
    
    Distributes trading days across weeks based on actual week lengths.
    Longer weeks (7 days) get more trades than shorter weeks at month boundaries.
    
    Args:
        plan: Trading plan dictionary
        year: Year for the calendar
        month: Month for the calendar
        
    Returns:
        List of trading days per week for the month
    """
    import calendar
    import datetime as dt
    
    trading_days = plan["trading_days"]
    challenge_duration = plan.get("challenge_duration", 1)
    
    # Get calendar for the month
    cal = calendar.monthcalendar(year, month)
    
    # Calculate actual week lengths (number of days in each week that belong to this month)
    week_lengths = []
    for week in cal:
        # Count non-zero days (days that belong to this month)
        days_in_week = sum(1 for day in week if day != 0)
        if days_in_week > 0:
            week_lengths.append(days_in_week)
    
    # Calculate total weeks in challenge duration
    total_weeks = challenge_duration * 4  # Approximate 4 weeks per month
    
    # Calculate weight for each week based on length
    total_weight = sum(week_lengths)
    
    # Distribute trading days across weeks proportionally to week length
    weekly_distribution = []
    remaining_days = trading_days
    
    for i, week_length in enumerate(week_lengths):
        if i == len(week_lengths) - 1:
            # Last week gets remaining days
            trades_this_week = remaining_days
        else:
            # Calculate proportional trades based on week length
            weight = week_length / total_weight
            trades_this_week = max(0, round(trading_days * weight))
            remaining_days -= trades_this_week
        
        weekly_distribution.append(trades_this_week)
    
    return weekly_distribution