"""Shared MetaTrader 5 connection + data helpers.

Centralizes connect/disconnect so every page (Dashboard, Indices Advisor,
Journal) uses the same active broker profile from core.config, and only
reconnects once per session unless forced.
"""
import MetaTrader5 as mt5
import pandas as pd
import streamlit as st

from core.config import get_active_profile


def connect(cfg: dict) -> tuple[bool, str]:
    """Initialize (and log in to, if credentials are set) the MT5 terminal."""
    profile_name, profile = get_active_profile(cfg)

    terminal_path = (profile or {}).get("terminal_path") or None
    login = (profile or {}).get("login")
    password = (profile or {}).get("password")
    server = (profile or {}).get("server")

    init_kwargs = {}
    if terminal_path:
        init_kwargs["path"] = terminal_path

    if not mt5.initialize(**init_kwargs):
        return False, f"MT5 initialize failed: {mt5.last_error()}"

    if login and password and server:
        try:
            login_int = int(login)
        except (TypeError, ValueError):
            return False, "Broker profile login must be numeric. Check Settings."
        if not mt5.login(login_int, password=password, server=server):
            return False, f"MT5 login failed: {mt5.last_error()}"
        return True, f"Connected as profile '{profile_name}' (login {login_int})."

    return True, "Connected to the already logged-in MT5 terminal (no stored credentials used)."


def ensure_connection(cfg: dict, force: bool = False) -> tuple[bool, str]:
    """Connects once per Streamlit session unless force=True, not yet connected,
    or the active broker profile has changed since the last connect (e.g. the
    user switched profiles in Settings) — in which case we always reconnect so
    stale data from a previous account never leaks into later pages.
    """
    active_profile_name, _ = get_active_profile(cfg)
    profile_changed = st.session_state.get("mt5_connected_profile") != active_profile_name

    if force or profile_changed or not st.session_state.get("mt5_connected"):
        ok, msg = connect(cfg)
        st.session_state.mt5_connected = ok
        st.session_state.mt5_status_message = msg
        st.session_state.mt5_connected_profile = active_profile_name if ok else None
        if profile_changed:
            # Drop broker-specific scan state so Indices Advisor rescans the new account.
            for key in (
                "asset_data",
                "asset_directions",
                "hidden_assets",
                "hidden_assets_profile",
                "asset_page",
                "asset_filter_key",
            ):
                st.session_state.pop(key, None)
        return ok, msg
    return True, st.session_state.get("mt5_status_message", "Connected.")


def disconnect() -> None:
    mt5.shutdown()
    st.session_state.mt5_connected = False
    st.session_state.mt5_connected_profile = None
    st.session_state.mt5_status_message = "Disconnected."


def purge_excluded_from_market_watch(universe: dict) -> list[str]:
    """Fast pass: deselect any currently-visible symbols matching exclude keywords.

    Wildcards like *Step* / *Boom* can leave Multi Step, Vol over Boom, etc. in
    Market Watch even when the advisor never scans them. Call this on page load.
    """
    exclude_keywords = [str(k).lower() for k in (universe.get("exclude_keywords") or [])]
    if not exclude_keywords:
        return []

    removed: list[str] = []
    for sym in mt5.symbols_get() or []:
        if not getattr(sym, "visible", False):
            continue
        name_lower = sym.name.lower()
        if not any(k in name_lower for k in exclude_keywords):
            continue
        if mt5.symbol_select(sym.name, False):
            removed.append(sym.name)
    return removed


def sync_universe_to_market_watch(universe: dict) -> dict:
    """Replace Market Watch with exactly the enabled universe symbols.

    Desired synthetics are selected; every other currently-visible symbol is
    deselected (forex/stocks/banned families included). That keeps MW aligned
    with the advisor instead of accumulating hundreds of unrelated instruments.
    """
    from core.broker_universe import available_index_classes, get_index_class, is_symbol_allowed

    catalog = dict(universe)
    catalog.pop("enabled_index_classes", None)
    known_classes = set(available_index_classes(catalog))
    exclude_keywords = [str(k).lower() for k in (catalog.get("exclude_keywords") or [])]

    if "enabled_index_classes" in universe:
        enabled = set(universe.get("enabled_index_classes") or [])
    else:
        enabled = set(known_classes)

    # Only the configured universe groups — do NOT add masks like *Dex* / *Spot*
    # (*Dex* matches the substring inside "Index" and pulls in huge junk sets).
    groups = list(catalog.get("mt5_groups") or ["*"])

    seen: set[str] = set()
    relevant = []
    for group in groups:
        for sym in mt5.symbols_get(group=group) or []:
            if sym.name in seen:
                continue
            seen.add(sym.name)
            relevant.append(sym)

    desired: list[str] = []
    skipped: list[str] = []
    for sym in relevant:
        path = getattr(sym, "path", "") or ""
        name_lower = sym.name.lower()
        cls = get_index_class(sym.name, catalog)
        is_excluded = any(k in name_lower for k in exclude_keywords)
        if (
            not is_excluded
            and is_symbol_allowed(sym.name, path, universe)
            and cls in known_classes
            and cls in enabled
        ):
            desired.append(sym.name)

    desired_set = set(desired)
    added: list[str] = []
    for name in desired:
        info = mt5.symbol_info(name)
        already = bool(info and info.visible)
        if mt5.symbol_select(name, True):
            if not already:
                added.append(name)
        else:
            skipped.append(name)

    # Exact set: strip everything else currently showing in Market Watch.
    removed: list[str] = []
    for sym in mt5.symbols_get() or []:
        if not getattr(sym, "visible", False):
            continue
        if sym.name in desired_set:
            continue
        if mt5.symbol_select(sym.name, False):
            removed.append(sym.name)

    return {
        "added": added,
        "removed": removed,
        "skipped": skipped,
        "desired": desired,
        "enabled_classes": sorted(enabled),
    }


def get_account_info() -> dict | None:
    info = mt5.account_info()
    return info._asdict() if info else None


def get_open_positions_df() -> pd.DataFrame:
    positions = mt5.positions_get()
    if not positions:
        return pd.DataFrame()

    rows = []
    for p in positions:
        rows.append({
            "Ticket": p.ticket,
            "Symbol": p.symbol,
            "Type": "Buy" if p.type == mt5.ORDER_TYPE_BUY else "Sell",
            "Volume": p.volume,
            "Open Price": p.price_open,
            "Current Price": p.price_current,
            "SL": p.sl,
            "TP": p.tp,
            "Profit": p.profit,
            "Open Time": pd.to_datetime(p.time, unit="s"),
        })
    return pd.DataFrame(rows)


def _deal_position_direction(d) -> str:
    """Returns the ORIGINAL position's direction (Buy/Sell) for a deal.

    A deal's own `type` reflects the action of that specific deal, not
    necessarily the position it belongs to. Closing a Sell position requires
    executing a Buy deal (and closing a Buy position requires a Sell deal),
    so for closing deals (Entry OUT / OUT_BY) the raw type is the *opposite*
    of the position's real direction and must be inverted. Opening deals
    (Entry IN, or INOUT for hedged positions) already match the position's
    direction directly.
    """
    if d.type == mt5.DEAL_TYPE_BUY:
        raw = "Buy"
    elif d.type == mt5.DEAL_TYPE_SELL:
        raw = "Sell"
    else:
        return "Other"

    is_closing = d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY)
    if is_closing:
        return "Sell" if raw == "Buy" else "Buy"
    return raw


def get_history_deals_df(from_date, to_date) -> pd.DataFrame:
    deals = mt5.history_deals_get(from_date, to_date)
    if not deals:
        return pd.DataFrame()

    rows = []
    for d in deals:
        rows.append({
            "Ticket": d.ticket,
            "Order": d.order,
            "Time": pd.to_datetime(d.time, unit="s"),
            "Symbol": d.symbol,
            "Type": _deal_position_direction(d),
            "Volume": d.volume,
            "Price": d.price,
            "Profit": d.profit,
            "Commission": d.commission,
            "Swap": d.swap,
            "Entry": d.entry,  # 0 = IN (open), 1 = OUT (close), 2 = INOUT, 3 = OUT_BY
        })
    return pd.DataFrame(rows)