"""Portfolio Profile cache: per-broker monthly PnL across all login profiles.

Persisted in portfolio_profile.json. Updated whenever the app connects to a
profile (throttled), and can be fully rebuilt via sync_all_profiles().
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

PORTFOLIO_FILE = Path(__file__).resolve().parent.parent / "portfolio_profile.json"
HISTORY_MONTHS = 36
# Skip re-fetch for the same profile if updated within this window (seconds).
REFRESH_MIN_INTERVAL_SEC = 5 * 60

EMPTY_STORE: dict[str, Any] = {
    "updated_at": None,
    "profiles": {},
}


def load_portfolio() -> dict:
    if not PORTFOLIO_FILE.exists():
        return json.loads(json.dumps(EMPTY_STORE))
    try:
        data = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(EMPTY_STORE))
    if not isinstance(data, dict):
        return json.loads(json.dumps(EMPTY_STORE))
    data.setdefault("profiles", {})
    data.setdefault("updated_at", None)
    if not isinstance(data["profiles"], dict):
        data["profiles"] = {}
    return data


def save_portfolio(store: dict) -> None:
    store["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    PORTFOLIO_FILE.write_text(json.dumps(store, indent=2), encoding="utf-8")


def has_portfolio_data(store: dict | None = None) -> bool:
    store = store if store is not None else load_portfolio()
    profiles = store.get("profiles") or {}
    return any(isinstance(p, dict) and (p.get("months") or p.get("balance") is not None) for p in profiles.values())


def list_months(store: dict | None = None) -> list[str]:
    """Return sorted YYYY-MM keys present in the cache (newest first)."""
    store = store if store is not None else load_portfolio()
    months: set[str] = set()
    for entry in (store.get("profiles") or {}).values():
        if not isinstance(entry, dict):
            continue
        for key in (entry.get("months") or {}):
            months.add(str(key))
    return sorted(months, reverse=True)


def list_years(store: dict | None = None) -> list[int]:
    """Return sorted years present in the cache (newest first)."""
    years: set[int] = set()
    for key in list_months(store):
        try:
            years.add(int(str(key)[:4]))
        except (TypeError, ValueError):
            continue
    return sorted(years, reverse=True)


def months_for_year(year: int, *, through_current: bool = True) -> list[str]:
    """Return YYYY-MM keys from Jan..(Dec or current month) for *year*."""
    today = dt.date.today()
    last_month = 12
    if through_current and year == today.year:
        last_month = today.month
    elif year > today.year:
        last_month = 0
    return [f"{year}-{m:02d}" for m in range(1, last_month + 1)]


def aggregate_yearly_pnl(store: dict, year: int, *, through_current: bool = True) -> list[dict]:
    """Sum PnL across all profiles for each month of *year*.

    Returns rows with Month, Label, PnL, Net PnL, Trades — including months with
    zero activity so the line runs Jan→current (or Dec) with real negatives.
    """
    profiles = store.get("profiles") or {}
    keys = months_for_year(year, through_current=through_current)
    month_names = (
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    )
    rows: list[dict] = []
    for key in keys:
        month_num = int(key.split("-")[1])
        pnl = 0.0
        net = 0.0
        trades = 0
        for entry in profiles.values():
            if not isinstance(entry, dict):
                continue
            stats = (entry.get("months") or {}).get(key) or {}
            pnl += float(stats.get("pnl") or 0)
            net += float(stats.get("net_pnl") or 0)
            trades += int(stats.get("trades") or 0)
        rows.append({
            "Month": key,
            "Label": month_names[month_num - 1],
            "MonthNum": month_num,
            "PnL": round(pnl, 2),
            "Net PnL": round(net, 2),
            "Trades": trades,
            "Cumulative PnL": 0.0,
        })

    running = 0.0
    for row in rows:
        running += float(row["PnL"])
        row["Cumulative PnL"] = round(running, 2)
    return rows


def _aggregate_closing_deals(deals_df) -> dict[str, dict]:
    """Build {YYYY-MM: stats} from closing deals (Entry OUT), matching Dashboard PnL."""
    if deals_df is None or deals_df.empty:
        return {}

    closing = deals_df[deals_df["Entry"] == 1].copy()
    if closing.empty:
        return {}

    closing["month"] = closing["Time"].dt.strftime("%Y-%m")
    months: dict[str, dict] = {}
    for month, group in closing.groupby("month"):
        pnl = float(group["Profit"].sum())
        commission = float(group["Commission"].sum()) if "Commission" in group.columns else 0.0
        swap = float(group["Swap"].sum()) if "Swap" in group.columns else 0.0
        wins = int((group["Profit"] > 0).sum())
        losses = int((group["Profit"] < 0).sum())
        months[str(month)] = {
            "pnl": round(pnl, 4),
            "commission": round(commission, 4),
            "swap": round(swap, 4),
            "net_pnl": round(pnl + commission + swap, 4),
            "trades": int(len(group)),
            "wins": wins,
            "losses": losses,
        }
    return months


def fetch_profile_snapshot(profile_name: str, profile: dict) -> dict:
    """Read live account + history for the *currently logged-in* MT5 session."""
    from core import mt5_client

    account = mt5_client.get_account_info() or {}
    now = dt.datetime.now()
    # Start of month, HISTORY_MONTHS ago
    start_month = (now.replace(day=1) - dt.timedelta(days=HISTORY_MONTHS * 31)).replace(day=1)
    from_date = dt.datetime.combine(start_month.date(), dt.time.min)
    to_date = now + dt.timedelta(days=1)

    deals_df = mt5_client.get_history_deals_df(from_date, to_date)
    months = _aggregate_closing_deals(deals_df)

    return {
        "profile": profile_name,
        "login": str(profile.get("login") or account.get("login") or ""),
        "server": str(profile.get("server") or account.get("server") or ""),
        "balance": float(account["balance"]) if account.get("balance") is not None else None,
        "equity": float(account["equity"]) if account.get("equity") is not None else None,
        "updated_at": now.isoformat(timespec="seconds"),
        "months": months,
        "error": None,
    }


def upsert_profile_snapshot(snapshot: dict, store: dict | None = None) -> dict:
    store = store if store is not None else load_portfolio()
    name = snapshot.get("profile")
    if not name:
        return store
    store.setdefault("profiles", {})
    store["profiles"][name] = {
        "login": snapshot.get("login"),
        "server": snapshot.get("server"),
        "balance": snapshot.get("balance"),
        "equity": snapshot.get("equity"),
        "updated_at": snapshot.get("updated_at"),
        "months": snapshot.get("months") or {},
        "error": snapshot.get("error"),
    }
    save_portfolio(store)
    return store


def _profile_needs_refresh(store: dict, profile_name: str, min_interval_sec: float) -> bool:
    entry = (store.get("profiles") or {}).get(profile_name) or {}
    updated = entry.get("updated_at")
    if not updated:
        return True
    try:
        ts = dt.datetime.fromisoformat(str(updated))
    except ValueError:
        return True
    age = (dt.datetime.now() - ts).total_seconds()
    return age >= min_interval_sec


def refresh_active_profile(
    cfg: dict,
    *,
    force: bool = False,
    min_interval_sec: float = REFRESH_MIN_INTERVAL_SEC,
) -> dict | None:
    """Update portfolio_profile.json for the active connected profile."""
    from core.config import get_active_profile

    profile_name, profile = get_active_profile(cfg)
    if not profile_name or not profile:
        return None

    store = load_portfolio()
    if not force and not _profile_needs_refresh(store, profile_name, min_interval_sec):
        return store["profiles"].get(profile_name)

    try:
        snapshot = fetch_profile_snapshot(profile_name, profile)
    except Exception as exc:
        snapshot = {
            "profile": profile_name,
            "login": str(profile.get("login") or ""),
            "server": str(profile.get("server") or ""),
            "balance": None,
            "equity": None,
            "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "months": (store.get("profiles") or {}).get(profile_name, {}).get("months") or {},
            "error": str(exc),
        }
    upsert_profile_snapshot(snapshot, store)
    return snapshot


def sync_all_profiles(cfg: dict) -> dict:
    """Log into every broker profile, pull PnL history, save portfolio_profile.json.

    Restores the originally active profile connection at the end.
    """
    from core.config import get_active_profile
    from core.mt5_client import connect_to_profile

    profiles = cfg.get("profiles") or {}
    active_name, _ = get_active_profile(cfg)
    results: dict[str, Any] = {"ok": [], "failed": [], "store": None}

    if not profiles:
        results["error"] = "No broker profiles configured."
        return results

    store = load_portfolio()

    for name, profile in profiles.items():
        ok, msg = connect_to_profile(name, profile)
        if not ok:
            results["failed"].append({"profile": name, "error": msg})
            store.setdefault("profiles", {})
            prev = store["profiles"].get(name) or {}
            store["profiles"][name] = {
                **prev,
                "login": str(profile.get("login") or ""),
                "server": str(profile.get("server") or ""),
                "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
                "error": msg,
                "months": prev.get("months") or {},
            }
            continue
        try:
            snapshot = fetch_profile_snapshot(name, profile)
            upsert_profile_snapshot(snapshot, store)
            store = load_portfolio()
            results["ok"].append(name)
        except Exception as exc:
            results["failed"].append({"profile": name, "error": str(exc)})

    # Restore the user's active profile so the rest of the app stays on it.
    if active_name and active_name in profiles:
        connect_to_profile(active_name, profiles[active_name])
        try:
            import streamlit as st

            st.session_state.mt5_connected = True
            st.session_state.mt5_connected_profile = active_name
            st.session_state.mt5_status_message = f"Connected as profile '{active_name}'."
        except Exception:
            pass

    results["store"] = load_portfolio()
    return results


def table_rows_for_month(store: dict, month_key: str | None) -> list[dict]:
    """Build display rows for one month (or lifetime if month_key is None / 'All')."""
    rows = []
    for name, entry in sorted((store.get("profiles") or {}).items()):
        if not isinstance(entry, dict):
            continue
        months = entry.get("months") or {}
        if month_key and month_key not in ("All", "all", "*"):
            stats = months.get(month_key) or {
                "pnl": 0.0,
                "commission": 0.0,
                "swap": 0.0,
                "net_pnl": 0.0,
                "trades": 0,
                "wins": 0,
                "losses": 0,
            }
        else:
            stats = {
                "pnl": round(sum(float(m.get("pnl") or 0) for m in months.values()), 4),
                "commission": round(sum(float(m.get("commission") or 0) for m in months.values()), 4),
                "swap": round(sum(float(m.get("swap") or 0) for m in months.values()), 4),
                "net_pnl": round(sum(float(m.get("net_pnl") or 0) for m in months.values()), 4),
                "trades": sum(int(m.get("trades") or 0) for m in months.values()),
                "wins": sum(int(m.get("wins") or 0) for m in months.values()),
                "losses": sum(int(m.get("losses") or 0) for m in months.values()),
            }
        rows.append({
            "Profile": name,
            "Login": entry.get("login") or "",
            "Server": entry.get("server") or "",
            "Balance": entry.get("balance"),
            "Equity": entry.get("equity"),
            "PnL": stats.get("pnl", 0.0),
            "Commission": stats.get("commission", 0.0),
            "Swap": stats.get("swap", 0.0),
            "Net PnL": stats.get("net_pnl", 0.0),
            "Trades": stats.get("trades", 0),
            "Wins": stats.get("wins", 0),
            "Losses": stats.get("losses", 0),
            "Updated": entry.get("updated_at") or "",
            "Error": entry.get("error") or "",
        })
    return rows
