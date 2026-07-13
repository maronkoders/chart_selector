import math
import re

import streamlit as st
import MetaTrader5 as mt5
import pandas as pd

from core.mt5_sync import sync_assets, filter_assets_from_exports, get_export_directions
from core import mt5_client
from core.config import load_config, set_risk_params, get_active_profile
from core.broker_universe import (
    get_profile_broker_type,
    get_profile_universe,
    get_profile_features,
    is_symbol_allowed,
    get_index_class as universe_index_class,
    advisor_title,
)
from core.hidden_assets_store import (
    init_hidden_assets,
    hide_asset,
    unhide_asset,
    clear_hidden_assets,
    save_hidden_assets,
)
from core.volatile_store import (
    apply_volatile_edits,
    format_option_scale,
    load_options,
    load_volatile,
    option_labels,
    volatile_labels_for_account,
)

BIAS_ARROW = {
    "BUY": "↑",
    "SELL": "↓",
}


def format_bias_arrow(direction: str | None) -> str:
    if not direction:
        return "—"
    return BIAS_ARROW.get(direction, "—")


def style_bias_column(df: pd.DataFrame) -> "pd.io.formats.style.Styler":
    def _color_bias(value: str) -> str:
        if value == "↑":
            return "color: #3b82f6; font-weight: 700; font-size: 1.15rem;"
        if value == "↓":
            return "color: #ef4444; font-weight: 700; font-size: 1.15rem;"
        return "color: #94a3b8;"

    styler = df.style.map(_color_bias, subset=["Bias"])
    styler = styler.set_properties(subset=["Bias"], **{"text-align": "center"})
    return styler


def _ensure_symbol_selected(name: str):
    """Select a symbol only when it is missing or not visible in Market Watch."""
    info = mt5.symbol_info(name)
    if info is None or not info.visible:
        mt5.symbol_select(name, True)
        info = mt5.symbol_info(name)
    return info


INDEX_CLASS_KEYWORDS = [
    ("Volatility", "volatility"),
    ("Boom", "boom"),
    ("Crash", "crash"),
    ("Step", "step"),
    ("Jump", "jump"),
]


def discover_symbols(universe: dict):
    """Fetch MT5 symbols for the active broker universe."""
    groups = universe.get("mt5_groups") or ["*"]
    found = []
    seen = set()
    for group in groups:
        batch = mt5.symbols_get(group=group)
        if not batch and group != "*":
            continue
        for sym in batch or []:
            if sym.name in seen:
                continue
            seen.add(sym.name)
            path = getattr(sym, "path", "") or ""
            if is_symbol_allowed(sym.name, path, universe):
                found.append(sym)

    if not found and groups != ["*"]:
        # Last resort: scan all symbols through the same allow rules.
        for sym in mt5.symbols_get() or []:
            if sym.name in seen:
                continue
            path = getattr(sym, "path", "") or ""
            if is_symbol_allowed(sym.name, path, universe):
                found.append(sym)
    return found


def get_index_class(asset_name: str, universe: dict | None = None) -> str:
    if universe:
        return universe_index_class(asset_name, universe)
    name_lower = asset_name.lower()
    for label, keyword in INDEX_CLASS_KEYWORDS:
        if keyword in name_lower:
            return label
    return "Other"


def render_sidebar_hidden_assets(hidden_assets: set[str]) -> None:
    st.sidebar.divider()
    st.sidebar.subheader("Hidden Assets")
    st.sidebar.caption(f"{len(hidden_assets)} hidden asset(s)")

    if not hidden_assets:
        st.sidebar.info("Select a row in the watchlist and click 🙈 Hide to remove it from view.")
        return

    for asset in sorted(hidden_assets):
        label_col, remove_col = st.sidebar.columns([5, 1])
        with label_col:
            st.markdown(f"**{asset}**")
        with remove_col:
            if st.button("✕", key=f"unhide_{asset}", help="Unhide this asset"):
                unhide_asset(asset)
                st.rerun()

    if st.sidebar.button("🧹 Clear all hidden", width="stretch"):
        clear_hidden_assets()
        st.rerun()


cfg = st.session_state.setdefault("app_config", load_config())

# 1. CONNECT TO MT5 first — Account Balance below is read live from this connection.
ok, msg = mt5_client.ensure_connection(cfg)
if not ok:
    st.error(msg)
    st.page_link("app_pages/settings.py", label="Configure broker login in Settings →", icon="⚙️")
    st.stop()

profile_name, profile = get_active_profile(cfg)
broker_type = get_profile_broker_type(profile_name, profile)
universe = get_profile_universe(profile_name, profile)
features = get_profile_features(profile)
st.title(advisor_title(broker_type))
if profile_name:
    st.caption(f"Profile: {profile_name} · {broker_type.replace('_', ' ')}")

# 2. SIDEBAR RISK INPUTS (persisted to broker_config.json so Dashboard/Settings stay in sync)
st.sidebar.header("Account Parameters")

account_info = mt5_client.get_account_info()
if account_info:
    account_size = float(account_info["balance"])
else:
    # Fall back to the last known balance if MT5 is connected but the
    # account info call itself fails for some reason.
    account_size = float(cfg["risk"]["account_size"])
    st.sidebar.warning("Could not read live balance — using last saved value.")

st.sidebar.metric(label="Account Balance ($)", value=f"${account_size:,.2f}")
st.sidebar.caption("Pulled automatically from your connected MT5 account.")

risk_percentage = st.sidebar.slider(
    "Risk Tolerance (%)", min_value=1.0, max_value=100.0, value=float(cfg["risk"]["risk_percentage"])
)

if account_size != cfg["risk"]["account_size"] or risk_percentage != cfg["risk"]["risk_percentage"]:
    set_risk_params(cfg, account_size, risk_percentage)

max_risk_cash = account_size * (risk_percentage / 100.0)
st.sidebar.metric(label="Max Cash at Risk", value=f"${max_risk_cash:,.2f}")

# Keep Market Watch = exactly the allowed synthetics (strips forex/stocks/banned).
mw_result = mt5_client.sync_universe_to_market_watch(universe)
if mw_result.get("removed"):
    st.toast(
        f"Market Watch cleaned: removed {len(mw_result['removed'])}, "
        f"keeping {len(mw_result.get('desired') or [])} symbols."
    )

# 3. FETCH SYNTHETIC INDICES SPEC SHEETS
if "asset_data" not in st.session_state:
    with st.status("Scanning synthetic indices...", expanded=True) as status:
        status.write(
            f"Market Watch set to {len(mw_result.get('desired') or [])} allowed "
            f"symbol(s); removed {len(mw_result.get('removed') or [])} other(s)."
        )

        status.write(f"Fetching symbols for {broker_type.replace('_', ' ')}...")
        symbols = discover_symbols(universe)

        if symbols:
            status.write(f"Found {len(symbols)} symbols after filtering. Scanning risk metrics...")
        else:
            status.write("No symbols found for this broker universe.")
            symbols = []

        asset_data = []

        if symbols:
            progress_bar = st.progress(0, text="Starting scan...")
            for i, sym in enumerate(symbols):
                name = sym.name
                progress_bar.progress((i + 1) / len(symbols), text=f"Scanning {name}...")

                info = _ensure_symbol_selected(name)
                tick = mt5.symbol_info_tick(name)

                if info is None or tick is None:
                    continue

                current_price = tick.ask if tick.ask > 0 else tick.bid

                min_lot = info.volume_min
                point_value = info.trade_tick_value / info.trade_tick_size if info.trade_tick_size > 0 else 1.0

                vol_limit = info.volume_limit
                min_margin = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, name, min_lot, current_price)
                if min_margin is None:
                    min_margin = 0.0

                is_suitable = min_margin <= max_risk_cash and min_margin > 0

                # H1 swing is only needed for Safe Size rows; skip history sync
                # for assets that will be filtered out by margin anyway.
                if is_suitable:
                    rates = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_H1, 0, 24)
                    if rates is not None and len(rates) > 0:
                        df_rates = pd.DataFrame(rates)
                        avg_swing = (df_rates["high"] - df_rates["low"]).mean()
                    else:
                        avg_swing = current_price * 0.01
                    min_trade_risk_cost = avg_swing * min_lot * point_value
                else:
                    min_trade_risk_cost = 0.0

                asset_data.append({
                    "Asset": name,
                    "Min Lot": min_lot,
                    "Min-Margin ($)": round(min_margin, 2),
                    "Volume Limit": vol_limit,
                    "Min Risk Exposure ($)": round(min_trade_risk_cost, 2),
                    "Suitable": "🟢 Safe Size" if is_suitable else "🔴 Volatility Too High",
                })

            progress_bar.empty()

            # Apply directional-bias hiding (exporter JSON and/or live MT5 EMA bias).
            if features.get("bias_filter", True):
                status.write("Applying directional bias filter...")
                bias_result = filter_assets_from_exports(asset_data, allow_live_mt5=True)
                next_hidden = set()
                eligible = set(bias_result.get("eligible_assets", []))
                for row in asset_data:
                    name = row.get("Asset")
                    if not name:
                        continue
                    if name not in eligible:
                        next_hidden.add(name)
                st.session_state.hidden_assets = next_hidden
                st.session_state.hidden_assets_profile = profile_name
                save_hidden_assets(next_hidden, profile_name)
                st.session_state.asset_directions = {
                    asset: direction
                    for asset, direction in bias_result.get("directions", {}).items()
                    if asset in eligible
                }
                source = bias_result.get("bias_source", "none")
                status.write(
                    f"Bias filter ({source}) kept {len(eligible)} asset(s), "
                    f"hid {len(next_hidden)}."
                )
            else:
                status.write("Bias filter disabled for this profile.")

            status.update(label="Scan complete!", state="complete", expanded=False)
        else:
            status.update(label="MT5 Initialization Complete, but no symbols found.", state="error", expanded=True)

    st.session_state.asset_data = asset_data
else:
    asset_data = st.session_state.asset_data

# Convert to DataFrame for layout structuring
df_assets = pd.DataFrame(asset_data)

# Filter to show ONLY safe assets, lowest margin first.
if not df_assets.empty:
    df_assets = df_assets[df_assets["Suitable"] == "🟢 Safe Size"]
    df_assets = df_assets.sort_values(by="Min-Margin ($)", ascending=True)

hidden_assets = init_hidden_assets(profile_name)

# 4. RENDER THE INTERFACE DISPLAY LAYOUT
st.subheader("Watchlist")
st.caption("Assets shown here are your active watchlist after bias filtering. Hide any you don't want.")

sync_col, filter_col = st.columns(2, gap="small")
with sync_col:
    if st.button("🔄 Sync Assets", width="stretch"):
        if not asset_data:
            st.warning("No scanned assets are available to sync yet.")
        else:
            with st.spinner("Syncing MT5 snapshots..."):
                result = sync_assets(asset_data)

            if isinstance(result, list):
                snapshots = result
                skipped = []
                error = None
            elif isinstance(result, dict):
                snapshots = result.get("snapshots", [])
                skipped = result.get("skipped", [])
                error = result.get("error")
            else:
                snapshots = []
                skipped = []
                error = "Unexpected sync_assets return type."

            if error:
                st.error(f"Sync failed: {error}")
            else:
                count = len(snapshots)
                st.success(f"Saved {count} snapshot(s). Skipped {len(skipped)} asset(s).")
                if skipped:
                    st.info("Check the MT5 terminal and symbol availability for skipped assets.")
            st.rerun()

with filter_col:
    if st.button("🎯 Filter Assets", width="stretch"):
        if not asset_data:
            st.warning("Run the initial scan first so there is an asset list to filter.")
        else:
            with st.spinner("Re-reading MQL5 Files bias snapshots..."):
                # Always re-read JSON from the connected terminal's Files folder.
                # Margin is already handled by the Safe Size scan.
                result = filter_assets_from_exports(
                    asset_data,
                    allow_live_mt5=True,
                )

            eligible = set(result.get("eligible_assets", []))
            rejected = result.get("rejected_assets", [])
            # Full rebuild (same as initial scan): eligible = watchlist,
            # everything else in the scan = hidden. Avoids stale manual hides
            # blocking assets that are aligned again (e.g. Jump 10).
            next_hidden_assets = set()
            for row in asset_data:
                name = row.get("Asset")
                if name and name not in eligible:
                    next_hidden_assets.add(name)

            st.session_state.hidden_assets = next_hidden_assets
            st.session_state.hidden_assets_profile = profile_name
            save_hidden_assets(next_hidden_assets, profile_name)

            directions = {
                asset: direction
                for asset, direction in result.get("directions", {}).items()
                if asset in eligible
            }
            st.session_state.asset_directions = directions
            buy_count = sum(1 for d in directions.values() if d == "BUY")
            sell_count = sum(1 for d in directions.values() if d == "SELL")
            source = result.get("bias_source", "none")
            folder_label = result.get("export_folder") or "live MT5 only"
            st.success(
                f"One-directional bias ({source}): {len(eligible)} kept "
                f"({buy_count} BUY · {sell_count} SELL) · "
                f"{len(rejected)} hidden · from {folder_label}"
            )
            st.rerun()

if not df_assets.empty:
    df_assets["Index Class"] = df_assets["Asset"].apply(lambda a: get_index_class(a, universe))

    render_sidebar_hidden_assets(hidden_assets)

    df_scanner = df_assets[~df_assets["Asset"].isin(hidden_assets)].copy()

    # Prefer live export directions; fall back to last Filter Assets result.
    live_directions = get_export_directions(df_scanner["Asset"].tolist(), allow_live_mt5=True)
    if live_directions:
        st.session_state.asset_directions = live_directions
    directions = st.session_state.get("asset_directions", {})
    df_scanner["Bias"] = df_scanner["Asset"].map(
        lambda asset: format_bias_arrow(directions.get(asset))
    )

    display_columns = [
        "Asset",
        "Bias",
        r"\volatile",
        "Min Lot",
        "Min-Margin ($)",
    ]
    volatile_options = load_options()
    volatile_option_labels = option_labels(volatile_options)
    volatile_help = (
        " · ".join(f"{o['label']} ({format_option_scale(o)})" for o in volatile_options)
        or "Configure options in Settings → Volatile"
    )
    volatile_ratings = load_volatile()
    df_scanner[r"\volatile"] = df_scanner["Asset"].map(
        lambda asset: volatile_ratings.get(asset)
    )
    total_assets = len(df_scanner)
    index_classes = sorted(df_scanner["Index Class"].unique()) if not df_scanner.empty else []

    class_col, search_col, page_size_col = st.columns([2.4, 2.4, 1.2], gap="small")
    with class_col:
        selected_classes = st.multiselect(
            "Index class",
            options=index_classes,
            default=[],
            placeholder="All classes",
            label_visibility="collapsed",
        )
    with search_col:
        search_query = st.text_input(
            "Search assets",
            placeholder="Search by asset name...",
            label_visibility="collapsed",
        )
    with page_size_col:
        page_size = st.selectbox(
            "Rows",
            options=[10, 25, 50, 100],
            index=1,
            label_visibility="collapsed",
        )

    allowed_volatile = volatile_labels_for_account(account_size, volatile_options)

    df_filtered = df_scanner.copy()
    if selected_classes:
        df_filtered = df_filtered[df_filtered["Index Class"].isin(selected_classes)]
    if search_query.strip():
        df_filtered = df_filtered[
            df_filtered["Asset"].str.contains(search_query.strip(), case=False, na=False)
        ]
    # Addon: only assets whose \\volatile scale band matches account size
    if allowed_volatile:
        df_filtered = df_filtered[
            df_filtered[r"\volatile"].isin(allowed_volatile)
        ]
    else:
        df_filtered = df_filtered.iloc[0:0]

    filtered_count = len(df_filtered)
    total_pages = max(1, math.ceil(filtered_count / page_size))

    filter_key = (
        search_query.strip(),
        tuple(sorted(selected_classes)),
        page_size,
        tuple(sorted(allowed_volatile)),
        round(float(account_size), 4),
    )
    if st.session_state.get("asset_filter_key") != filter_key:
        st.session_state.asset_filter_key = filter_key
        st.session_state.asset_page = 0

    if "asset_page" not in st.session_state:
        st.session_state.asset_page = 0

    st.session_state.asset_page = min(st.session_state.asset_page, total_pages - 1)
    current_page = st.session_state.asset_page
    page_start = current_page * page_size
    page_end = page_start + page_size
    df_page = df_filtered.iloc[page_start:page_end]

    if total_assets == 0:
        st.caption(f"Watchlist: 0 · Hidden: {len(hidden_assets)}")
        st.info("No assets left in the watchlist. Unhide assets from the sidebar or run Filter Assets again.")
    elif filtered_count == 0:
        allowed_txt = ", ".join(sorted(allowed_volatile)) or "none"
        st.caption(f"No matches (Watchlist: {total_assets} · Hidden: {len(hidden_assets)})")
        st.info(
            f"No assets match your search/filter criteria for this account size "
            f"(${account_size:,.2f} → \\volatile: {allowed_txt})."
        )
    else:
        showing_from = page_start + 1
        showing_to = min(page_end, filtered_count)
        allowed_txt = ", ".join(sorted(allowed_volatile)) or "none"
        st.caption(
            f"Showing {showing_from}-{showing_to} of {filtered_count} "
            f"(Watchlist: {total_assets} · Hidden: {len(hidden_assets)} · "
            f"\\volatile for ${account_size:,.2f}: {allowed_txt})"
        )

        row_height = 35
        header_height = 38
        table_height = len(df_page) * row_height + header_height

        # Dynamic key: forces a fresh widget whenever the row set changes
        # (page nav, search, filter, page size) so a stale row-selection
        # index can never be applied to a smaller/different dataframe.
        table_key = f"asset_scanner_table_{current_page}_{filtered_count}_{page_size}"

        table_selection = st.dataframe(
            style_bias_column(df_page[display_columns]),
            hide_index=True,
            width="stretch",
            height=table_height,
            on_select="rerun",
            selection_mode="multi-row",
            key=table_key,
            column_config={
                "Bias": st.column_config.TextColumn(
                    "Bias",
                    help="↑ blue = bullish (BUY) · ↓ red = bearish (SELL)",
                    width="small",
                ),
                r"\volatile": st.column_config.TextColumn(
                    r"\volatile",
                    help=f"{volatile_help} — select row(s) and set below",
                    width="small",
                ),
            },
        )

        selected_rows = (
            table_selection.selection.rows
            if table_selection.selection is not None
            else []
        )

        selected_assets = [
            df_page.iloc[row_idx]["Asset"]
            for row_idx in selected_rows
            if 0 <= row_idx < len(df_page)
        ]
        selection_count = len(selected_assets)

        vol_col, vol_btn_col, hide_col, prev_col, page_col, next_col = st.columns(
            [1.4, 1.2, 1.6, 1, 1.2, 1], gap="small"
        )
        with vol_col:
            volatile_choice = st.selectbox(
                r"\volatile",
                options=list(volatile_option_labels) or [""],
                key=f"volatile_choice_{table_key}",
                label_visibility="collapsed",
                disabled=selection_count == 0 or not volatile_option_labels,
            )
        with vol_btn_col:
            if st.button(
                r"Set \volatile",
                disabled=selection_count == 0,
                width="stretch",
                help=r"Save \volatile for the selected asset(s)",
            ):
                apply_volatile_edits({asset: volatile_choice for asset in selected_assets})
                st.rerun()
        with hide_col:
            hide_label = (
                f"🙈 Hide {selection_count}"
                if selection_count > 1
                else "🙈 Hide selected"
            )
            if st.button(
                hide_label,
                disabled=selection_count == 0,
                width="stretch",
                help="Hides the selected asset(s) until unhidden from the sidebar.",
            ):
                for asset in selected_assets:
                    hide_asset(asset)
                st.rerun()
        with prev_col:
            if st.button("Previous", disabled=current_page == 0, width="stretch"):
                st.session_state.asset_page -= 1
                st.rerun()
        with page_col:
            st.markdown(
                f"<div style='text-align:center;padding-top:0.45rem'>"
                f"<strong>Page {current_page + 1} of {total_pages}</strong></div>",
                unsafe_allow_html=True,
            )
        with next_col:
            if st.button("Next", disabled=current_page >= total_pages - 1, width="stretch"):
                st.session_state.asset_page += 1
                st.rerun()
else:
    render_sidebar_hidden_assets(hidden_assets)
    st.warning("No assets found. Ensure MT5 is connected and logged in to a broker.")
