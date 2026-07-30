"""Shared MetaTrader 5 connection + data helpers.

Centralizes connect/disconnect so every page (Dashboard, Indices Advisor,
Journal) uses the same active broker profile from core.config, and only
reconnects once per session unless forced.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import MetaTrader5 as mt5
import pandas as pd
import streamlit as st

from core.config import get_active_profile

# Written for the ChartSelectorLoader MT5 service (mql_expert_advisor/).
CHART_REQUEST_REL = Path("chart_selector") / "open_charts.request"
CHART_STATUS_REL = Path("chart_selector") / "open_charts.status"
CHART_HEARTBEAT_REL = Path("chart_selector") / "loader.heartbeat"
CHART_TEMPLATE_NAME = "chart_selector_new_me.tpl"
LOADER_HEARTBEAT_MAX_AGE_SEC = 5.0
_REPO_ROOT = Path(__file__).resolve().parent.parent
_REPO_TEMPLATE = _REPO_ROOT / "mql_expert_advisor" / "templates" / CHART_TEMPLATE_NAME
_REPO_LOADER_MQ5 = _REPO_ROOT / "mql_expert_advisor" / "ChartSelectorLoader.mq5"


def _shutdown_mt5(pause_sec: float = 0.75) -> None:
    """Drop the IPC link so the next initialize() does not reuse a stale login."""
    try:
        mt5.shutdown()
    except Exception:
        pass
    if pause_sec > 0:
        time.sleep(pause_sec)


def _parse_login(login) -> int | None:
    if login is None or login == "":
        return None
    try:
        return int(login)
    except (TypeError, ValueError):
        return None


def _connected_login() -> int | None:
    info = mt5.account_info()
    if info is None:
        return None
    try:
        return int(info.login)
    except (TypeError, ValueError):
        return None


def _login_to_account(login_int: int, password: str, server: str) -> tuple[bool, str]:
    """Switch the already-initialized terminal onto the requested account."""
    if not mt5.login(login_int, password=password, server=server):
        return False, f"MT5 login failed: {mt5.last_error()}"
    actual = _connected_login()
    if actual != login_int:
        return (
            False,
            f"MT5 login reported success but account is {actual}, expected {login_int}.",
        )
    return True, ""


def connect_to_profile(profile_name: str | None, profile: dict | None) -> tuple[bool, str]:
    """Initialize MT5 and log in using an explicit broker profile dict.

    Always clears any previous Python↔terminal session first. Without that,
    initialize() reuses the terminal's last account and can fail with
    (-6, 'Terminal: Authorization failed') before the new credentials are applied.
    """
    profile = profile or {}
    terminal_path = (profile.get("terminal_path") or "").strip() or None
    password = profile.get("password") or ""
    server = (profile.get("server") or "").strip()
    login_int = _parse_login(profile.get("login"))
    if profile.get("login") not in (None, "") and login_int is None:
        return False, "Broker profile login must be numeric. Check Settings."

    has_creds = login_int is not None and bool(password) and bool(server)
    label = profile_name or (str(login_int) if login_int is not None else "terminal")

    def _bare_init_kwargs() -> dict:
        kwargs: dict = {"timeout": 60_000}
        if terminal_path:
            kwargs["path"] = terminal_path
        return kwargs

    def _cred_init_kwargs() -> dict:
        return {
            **_bare_init_kwargs(),
            "login": login_int,
            "password": password,
            "server": server,
        }

    def _finish_ok() -> tuple[bool, str]:
        return True, f"Connected as profile '{label}' (login {login_int})."

    def _ensure_expected_account() -> tuple[bool, str]:
        actual = _connected_login()
        if actual == login_int:
            return True, ""
        return _login_to_account(login_int, password, server)

    # Wipe the old login trail before attaching to the (possibly different) account.
    _shutdown_mt5()

    if has_creds:
        errors: list[str] = []

        # 1) Authorize during initialize so MT5 never stays on the previous account.
        if mt5.initialize(**_cred_init_kwargs()):
            ok_login, err = _ensure_expected_account()
            if ok_login:
                return _finish_ok()
            errors.append(err)
            _shutdown_mt5(pause_sec=1.0)
        else:
            errors.append(f"initialize(creds): {mt5.last_error()}")
            _shutdown_mt5(pause_sec=1.0)

        # 2) Retry auth-in-init once after a longer clear (common after broker switches).
        if mt5.initialize(**_cred_init_kwargs()):
            ok_login, err = _ensure_expected_account()
            if ok_login:
                return _finish_ok()
            errors.append(err)
            _shutdown_mt5(pause_sec=1.0)
        else:
            errors.append(f"initialize(creds retry): {mt5.last_error()}")
            _shutdown_mt5(pause_sec=1.0)

        # 3) Last resort: attach to terminal, then switch account via login().
        if mt5.initialize(**_bare_init_kwargs()):
            ok_login, err = _login_to_account(login_int, password, server)
            if ok_login:
                return _finish_ok()
            errors.append(err)
            _shutdown_mt5(pause_sec=0.5)
        else:
            errors.append(f"initialize(bare): {mt5.last_error()}")
            _shutdown_mt5(pause_sec=0.5)

        return False, "MT5 broker switch failed: " + " | ".join(errors)

    if not mt5.initialize(**_bare_init_kwargs()):
        return False, f"MT5 initialize failed: {mt5.last_error()}"
    return True, "Connected to the already logged-in MT5 terminal (no stored credentials used)."


def connect(cfg: dict) -> tuple[bool, str]:
    """Initialize (and log in to, if credentials are set) the MT5 terminal."""
    profile_name, profile = get_active_profile(cfg)
    return connect_to_profile(profile_name, profile)


def ensure_connection(cfg: dict, force: bool = False) -> tuple[bool, str]:
    """Connects once per Streamlit session unless force=True, not yet connected,
    or the active broker profile has changed since the last connect (e.g. the
    user switched profiles in Settings) — in which case we always reconnect so
    stale data from a previous account never leaks into later pages.
    """
    active_profile_name, _ = get_active_profile(cfg)
    profile_changed = st.session_state.get("mt5_connected_profile") != active_profile_name

    if force or profile_changed or not st.session_state.get("mt5_connected"):
        # Clear Streamlit connection flags up front so a failed switch cannot
        # leave pages believing they are still on the previous broker login.
        if force or profile_changed:
            st.session_state.mt5_connected = False
            st.session_state.mt5_connected_profile = None
            st.session_state.mt5_status_message = "Reconnecting…"

        ok, msg = connect(cfg)
        st.session_state.mt5_connected = ok
        st.session_state.mt5_status_message = msg
        st.session_state.mt5_connected_profile = active_profile_name if ok else None
        if profile_changed:
            # Drop broker-specific scan state so Indices Advisor rescans the new account.
            # Chart open/close is NOT triggered here — only Dashboard/Settings sync does that.
            for key in (
                "asset_data",
                "asset_data_profile",
                "asset_directions",
                "hidden_assets",
                "hidden_assets_profile",
                "asset_page",
                "asset_filter_key",
                "asset_scan_last_run_at",
                "asset_filter_last_run_at",
                "asset_filter_last_trigger",
                "last_system_sync",
            ):
                st.session_state.pop(key, None)
            st.session_state.pop("mt5_needs_chart_sync", None)
        if ok:
            # Keep portfolio_profile.json fresh for whichever profile we just entered.
            try:
                from core.portfolio_store import refresh_active_profile

                refresh_active_profile(cfg, force=profile_changed or force)
            except Exception:
                pass
        return ok, msg

    # Already connected: still refresh portfolio cache on a throttle.
    try:
        from core.portfolio_store import refresh_active_profile

        refresh_active_profile(cfg, force=False)
    except Exception:
        pass
    return True, st.session_state.get("mt5_status_message", "Connected.")


def disconnect() -> None:
    _shutdown_mt5(pause_sec=0.25)
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


def _mt5_data_path() -> Path | None:
    info = mt5.terminal_info()
    if not info:
        return None
    data_path = getattr(info, "data_path", None)
    return Path(data_path) if data_path else None


def _mt5_files_dir() -> Path | None:
    data = _mt5_data_path()
    return (data / "MQL5" / "Files") if data else None


def ensure_chart_loader_installed() -> dict:
    """Copy the chart template + loader EA into the connected terminal data folder.

    Installed next to the user's indicators at ``MQL5/Experts/new_me/``.
    """
    data = _mt5_data_path()
    if data is None:
        return {"ok": False, "error": "MT5 terminal path unavailable."}

    result = {"ok": True, "template": None, "loader_mq5": None, "error": None}
    templates_dir = data / "MQL5" / "Profiles" / "Templates"
    experts_dir = data / "MQL5" / "Experts" / "new_me"
    templates_dir.mkdir(parents=True, exist_ok=True)
    experts_dir.mkdir(parents=True, exist_ok=True)

    if _REPO_TEMPLATE.exists():
        dest = templates_dir / CHART_TEMPLATE_NAME
        shutil.copy2(_REPO_TEMPLATE, dest)
        result["template"] = str(dest)
    else:
        result["ok"] = False
        result["error"] = f"Missing template: {_REPO_TEMPLATE}"

    if _REPO_LOADER_MQ5.exists():
        dest = experts_dir / _REPO_LOADER_MQ5.name
        shutil.copy2(_REPO_LOADER_MQ5, dest)
        result["loader_mq5"] = str(dest)
    else:
        result["ok"] = False
        result["error"] = (result.get("error") or "") + f" Missing loader: {_REPO_LOADER_MQ5}"

    return result


def request_watchlist_charts(
    symbols: list[str] | None = None,
    *,
    timeframe: str = "M1",
    from_market_watch: bool = False,
    wait_seconds: float = 25.0,
) -> dict:
    """Ask ChartSelectorLoader to close all charts, then open watchlist charts.

    Writes ``MQL5/Files/chart_selector/open_charts.request``. The EA must be
    attached once: Navigator > Expert Advisors > new_me > ChartSelectorLoader
    (drag onto any one chart and leave it running).
    """
    files_dir = _mt5_files_dir()
    if files_dir is None:
        return {"ok": False, "error": "MT5 Files folder unavailable.", "queued": False}

    ensure_chart_loader_installed()

    clean = [str(s).strip() for s in (symbols or []) if str(s).strip()]
    if not from_market_watch and not clean:
        return {"ok": False, "error": "No symbols to open.", "queued": False}

    req_dir = files_dir / "chart_selector"
    req_dir.mkdir(parents=True, exist_ok=True)
    request_path = files_dir / CHART_REQUEST_REL
    status_path = files_dir / CHART_STATUS_REL

    # Drop stale status so we can detect a fresh reply.
    if status_path.exists():
        try:
            status_path.unlink()
        except OSError:
            pass

    body_lines = [
        "action=reset",
        f"timeframe={timeframe}",
        f"template={CHART_TEMPLATE_NAME}",
        f"source={'market_watch' if from_market_watch else 'symbols'}",
        "symbols=" + ("*" if from_market_watch else "|".join(clean)),
        "",
    ]
    request_path.write_text("\n".join(body_lines), encoding="ascii", errors="replace")

    status: dict = {}
    deadline = time.time() + max(0.0, wait_seconds)
    while time.time() < deadline:
        if status_path.exists():
            status = _parse_kv_file(status_path)
            break
        time.sleep(0.25)

    symbol_count = len(clean) if clean else None
    if not status:
        return {
            "ok": False,
            "queued": True,
            "symbols": symbol_count,
            "error": (
                "Chart reset queued, but ChartSelectorLoader did not respond. "
                "In MT5: Navigator > Expert Advisors > new_me > ChartSelectorLoader — "
                "drag it onto any one chart, enable Algo Trading, and leave it running. "
                "If it is missing, right-click Expert Advisors > Refresh (or restart MT5)."
            ),
        }

    ok = status.get("ok") == "1" and not status.get("error")
    return {
        "ok": ok,
        "queued": True,
        "symbols": symbol_count if symbol_count is not None else int(status.get("opened") or 0),
        "opened": int(status.get("opened") or 0),
        "updated": int(status.get("updated") or 0),
        "closed": int(status.get("closed") or 0),
        "skipped": int(status.get("skipped") or 0),
        "error": status.get("error") or None,
        "status": status,
    }


def sync_universe_to_market_watch_and_charts(universe: dict) -> dict:
    """Sync Market Watch, then close all charts and open exactly that watchlist.

    Symbols with open charts (e.g. leftover EURUSD tiles) often cannot be
    deselected until those charts close. After a successful chart reset we
    purge Market Watch a second time so forex/junk locked by charts is removed.
    """
    mw = sync_universe_to_market_watch(universe)
    desired = list(mw.get("desired") or [])
    charts = request_watchlist_charts(desired)
    mw["charts"] = charts

    if charts.get("ok"):
        # Charts no longer hold stray symbols — finish the exact-set purge.
        mw2 = sync_universe_to_market_watch(universe)
        removed = list(mw.get("removed") or [])
        removed.extend(n for n in (mw2.get("removed") or []) if n not in removed)
        added = list(mw.get("added") or [])
        added.extend(n for n in (mw2.get("added") or []) if n not in added)
        mw["removed"] = removed
        mw["added"] = added
        mw["desired"] = list(mw2.get("desired") or desired)
        mw["skipped"] = list(mw2.get("skipped") or mw.get("skipped") or [])
        mw["enabled_classes"] = mw2.get("enabled_classes") or mw.get("enabled_classes")
        mw["charts"] = charts

    try:
        st.session_state.mt5_needs_chart_sync = False
    except Exception:
        pass
    return mw


def chart_loader_status() -> dict:
    """Return whether ChartSelectorLoader is alive (via heartbeat file)."""
    files_dir = _mt5_files_dir()
    if files_dir is None:
        return {"alive": False, "error": "MT5 Files folder unavailable."}

    ensure_chart_loader_installed()
    heartbeat = files_dir / CHART_HEARTBEAT_REL
    if not heartbeat.exists():
        return {
            "alive": False,
            "error": (
                "ChartSelectorLoader is not running. "
                "Attach it once: Navigator > Expert Advisors > new_me > ChartSelectorLoader."
            ),
            "experts_dir": str((_mt5_data_path() or Path()) / "MQL5" / "Experts" / "new_me"),
        }

    age = time.time() - heartbeat.stat().st_mtime
    kv = _parse_kv_file(heartbeat)
    alive = age <= LOADER_HEARTBEAT_MAX_AGE_SEC
    return {
        "alive": alive,
        "age_seconds": round(age, 1),
        "symbol": kv.get("symbol"),
        "chart_id": kv.get("chart_id"),
        "ts": kv.get("ts"),
        "error": None
        if alive
        else (
            "ChartSelectorLoader heartbeat is stale — re-attach the EA and enable Algo Trading."
        ),
        "experts_dir": str((_mt5_data_path() or Path()) / "MQL5" / "Experts" / "new_me"),
    }


def run_full_system_sync(cfg: dict, *, force_reconnect: bool = True) -> dict:
    """One-shot: connect MT5 → sync Market Watch → close charts → open watchlist.

    The ChartSelectorLoader EA must already be attached in MT5 (one-time setup).
    This is the central button entry-point used by the Dashboard.
    """
    from core.broker_universe import get_profile_universe

    result: dict = {
        "ok": False,
        "connect": None,
        "loader": None,
        "market_watch": None,
        "charts": None,
        "error": None,
    }

    ok, msg = ensure_connection(cfg, force=force_reconnect)
    result["connect"] = {"ok": ok, "message": msg}
    if not ok:
        result["error"] = msg
        return result

    install = ensure_chart_loader_installed()
    loader = chart_loader_status()
    result["loader"] = {**loader, "install": install}

    profile_name, profile = get_active_profile(cfg)
    universe = get_profile_universe(profile_name, profile)

    if not loader.get("alive"):
        result["error"] = loader.get("error") or "ChartSelectorLoader is not running."
        # Still sync Market Watch and queue the chart reset so re-attaching the
        # EA (with a pending request) opens synthetics instead of leftover forex.
        mw = sync_universe_to_market_watch(universe)
        charts = request_watchlist_charts(
            list(mw.get("desired") or []),
            wait_seconds=0.0,
        )
        result["market_watch"] = mw
        result["charts"] = charts
        return result

    mw = sync_universe_to_market_watch_and_charts(universe)
    result["market_watch"] = {
        "desired": len(mw.get("desired") or []),
        "added": len(mw.get("added") or []),
        "removed": len(mw.get("removed") or []),
        "enabled_classes": mw.get("enabled_classes") or [],
    }
    charts = mw.get("charts") or {}
    result["charts"] = charts
    result["ok"] = bool(charts.get("ok"))
    if not result["ok"]:
        result["error"] = charts.get("error") or "Chart reset did not complete."
    return result


def _parse_kv_file(path: Path) -> dict:
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


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


def get_open_positions_with_sl_df(max_risk_cash: float) -> pd.DataFrame:
    """Open positions enriched with risk-based SL cash, points, and price.

    *max_risk_cash* is split equally across positions so their SL Cash values
    sum to the risk budget. Points use each symbol's tick value / tick size.
    """
    from core.sl_risk import build_position_sl_rows

    positions = mt5.positions_get()
    if not positions:
        return pd.DataFrame()

    raw: list[dict] = []
    for p in positions:
        info = mt5.symbol_info(p.symbol)
        if info is None:
            mt5.symbol_select(p.symbol, True)
            info = mt5.symbol_info(p.symbol)

        tick_value = float(getattr(info, "trade_tick_value", 0) or 0) if info else 0.0
        tick_size = float(getattr(info, "trade_tick_size", 0) or 0) if info else 0.0
        point = float(getattr(info, "point", 0) or 0) if info else 0.0
        digits = int(getattr(info, "digits", 5) or 5) if info else 5

        raw.append({
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
            "tick_value": tick_value,
            "tick_size": tick_size,
            "point": point,
            "digits": digits,
        })

    enriched = build_position_sl_rows(raw, float(max_risk_cash))
    display_cols = [
        "Ticket", "Symbol", "Type", "Volume", "Open Price", "Current Price",
        "SL", "Suggested SL", "SL Points", "SL Cash", "TP", "Profit", "Open Time",
    ]
    df = pd.DataFrame(enriched)
    return df[[c for c in display_cols if c in df.columns]]


def modify_position_sltp(ticket: int, sl: float, tp: float | None = None, symbol: str | None = None) -> tuple[bool, str]:
    """Set stop-loss (and optionally TP) on an open position via TRADE_ACTION_SLTP."""
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        return False, f"Position #{ticket} not found."

    pos = positions[0]
    symbol = symbol or pos.symbol
    info = mt5.symbol_info(symbol)
    digits = int(getattr(info, "digits", 5) or 5) if info else 5

    sl_price = round(float(sl), digits)
    if tp is None:
        tp_price = float(pos.tp or 0.0)
    else:
        tp_price = round(float(tp), digits)

    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": int(ticket),
        "symbol": symbol,
        "sl": sl_price,
        "tp": tp_price,
    }
    result = mt5.order_send(request)
    if result is None:
        return False, f"#{ticket}: order_send returned None ({mt5.last_error()})"

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        comment = getattr(result, "comment", "") or ""
        return False, f"#{ticket}: {result.retcode} {comment}".strip()

    return True, f"#{ticket}: SL set to {sl_price}"


def apply_suggested_sls(rows: list[dict] | pd.DataFrame) -> dict:
    """Apply Suggested SL from each row onto the matching MT5 open position.

    Keeps each position's existing TP. Returns {ok, failed, results}.
    """
    if isinstance(rows, pd.DataFrame):
        records = rows.to_dict(orient="records")
    else:
        records = list(rows or [])

    results: list[dict] = []
    ok_count = 0
    fail_count = 0

    for row in records:
        ticket = row.get("Ticket")
        suggested = row.get("Suggested SL")
        symbol = row.get("Symbol")
        if ticket is None or suggested is None:
            fail_count += 1
            results.append({"ticket": ticket, "ok": False, "message": "Missing ticket or Suggested SL"})
            continue
        try:
            sl_val = float(suggested)
        except (TypeError, ValueError):
            fail_count += 1
            results.append({"ticket": ticket, "ok": False, "message": f"Invalid Suggested SL: {suggested}"})
            continue
        if sl_val <= 0:
            fail_count += 1
            results.append({"ticket": int(ticket), "ok": False, "message": "Suggested SL is zero / unset"})
            continue

        ok, msg = modify_position_sltp(int(ticket), sl_val, tp=None, symbol=symbol)
        results.append({"ticket": int(ticket), "ok": ok, "message": msg, "sl": sl_val})
        if ok:
            ok_count += 1
        else:
            fail_count += 1

    return {"ok": ok_count, "failed": fail_count, "results": results}

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