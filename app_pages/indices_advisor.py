import math

import streamlit as st
import MetaTrader5 as mt5
import pandas as pd

from core import mt5_client
from core.config import load_config, set_risk_params
from core.watchlist_store import init_watchlist, add_to_watchlist, remove_from_watchlist
from core.hidden_assets_store import init_hidden_assets, hide_asset, unhide_asset, clear_hidden_assets
from core.velocity import compute_price_velocity

INDEX_CLASS_KEYWORDS = [
    ("Volatility", "volatility"),
    ("Boom", "boom"),
    ("Crash", "crash"),
    ("Step", "step"),
    ("Jump", "jump"),
]


def get_index_class(asset_name: str) -> str:
    name_lower = asset_name.lower()
    for label, keyword in INDEX_CLASS_KEYWORDS:
        if keyword in name_lower:
            return label
    return "Other"


def render_sidebar_watchlist(watchlist: set[str], df_assets: pd.DataFrame) -> None:
    st.sidebar.divider()
    st.sidebar.subheader("Watchlist")
    st.sidebar.caption(f"{len(watchlist)} saved asset(s)")

    if not watchlist:
        st.sidebar.info("Add assets from the scanner using ➕ Add.")
        return

    for asset in sorted(watchlist):
        asset_row = df_assets[df_assets["Asset"] == asset]
        label_col, remove_col = st.sidebar.columns([5, 1])

        with label_col:
            st.markdown(f"**{asset}**")
            if asset_row.empty:
                st.caption("No longer available in scanner")
            else:
                row = asset_row.iloc[0]
                pip_value = row["Pip Value ($/min)"]
                pip_value_label = f"${pip_value:.4f}" if pd.notna(pip_value) else "—"
                st.caption(
                    f"Margin ${row['Min-Margin ($)']:.2f} · "
                    f"Pip Value {pip_value_label}"
                )

        with remove_col:
            if st.button("✕", key=f"remove_watchlist_{asset}", help="Remove from watchlist"):
                remove_from_watchlist(asset)
                st.rerun()


def render_sidebar_hidden_assets(hidden_assets: set[str]) -> None:
    st.sidebar.divider()
    st.sidebar.subheader("Hidden Assets")
    st.sidebar.caption(f"{len(hidden_assets)} hidden asset(s)")

    if not hidden_assets:
        st.sidebar.info("Select a row in the scanner and click 🙈 Hide to remove it from view.")
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


st.title("🎯 Deriv Synthetic Indices Advisor")

cfg = st.session_state.setdefault("app_config", load_config())

# 1. CONNECT TO MT5 first — Account Balance below is read live from this connection.
ok, msg = mt5_client.ensure_connection(cfg)
if not ok:
    st.error(msg)
    st.page_link("app_pages/settings.py", label="Configure broker login in Settings →", icon="⚙️")
    st.stop()

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

# 3. FETCH SYNTHETIC INDICES SPEC SHEETS
with st.status("Scanning synthetic indices...", expanded=True) as status:
    status.write("Fetching Synthetic Indices...")
    symbols = mt5.symbols_get(group="*Volatility*,*Step*,*Jump*,*Crash*,*Boom*,*Dex*,*Range*")

    if not symbols:
        status.write("No symbols in group. Fetching all symbols...")
        symbols = mt5.symbols_get()

    if symbols:
        status.write(f"Found {len(symbols)} symbols. Scanning risk metrics...")
    else:
        status.write("No symbols found from broker.")
        symbols = []

    asset_data = []

    if symbols:
        progress_bar = st.progress(0, text="Starting scan...")
        for i, sym in enumerate(symbols):
            name = sym.name
            progress_bar.progress((i + 1) / len(symbols), text=f"Syncing history for {name}...")

            mt5.symbol_select(name, True)  # Make sure it's active in Market Watch

            info = mt5.symbol_info(name)
            tick = mt5.symbol_info_tick(name)

            if info is None or tick is None:
                continue

            current_price = tick.ask if tick.ask > 0 else tick.bid

            min_lot = info.volume_min
            point_value = info.trade_tick_value / info.trade_tick_size if info.trade_tick_size > 0 else 1.0

            rates = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_H1, 0, 24)

            if rates is not None and len(rates) > 0:
                df_rates = pd.DataFrame(rates)
                avg_swing = (df_rates['high'] - df_rates['low']).mean()
            else:
                avg_swing = current_price * 0.01

            min_trade_risk_cost = avg_swing * min_lot * point_value

            vol_limit = info.volume_limit
            min_margin = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, name, min_lot, current_price)
            if min_margin is None:
                min_margin = 0.0

            is_suitable = min_margin <= max_risk_cash and min_margin > 0

            velocity_result = compute_price_velocity(name, "M1")
            velocity_m1 = (
                round(velocity_result["velocity"], 4)
                if velocity_result and velocity_result["velocity"] is not None
                else None
            )
            pip_value = round(velocity_m1 * min_lot, 4) if velocity_m1 is not None else None

            asset_data.append({
                "Asset": name,
                "Min Lot": min_lot,
                "Min-Margin ($)": round(min_margin, 2),
                "Volume Limit": vol_limit,
                "Min Risk Exposure ($)": round(min_trade_risk_cost, 2),
                "Suitable": "🟢 Safe Size" if is_suitable else "🔴 Volatility Too High",
                "Velocity (pips/min)": velocity_m1,
                "Pip Value ($/min)": pip_value,
            })

        progress_bar.empty()
        status.update(label="MT5 Data Synchronization Complete!", state="complete", expanded=False)
    else:
        status.update(label="MT5 Initialization Complete, but no symbols found.", state="error", expanded=True)

# Convert to DataFrame for layout structuring
df_assets = pd.DataFrame(asset_data)

# Filter to show ONLY safe assets, then sort intelligently: assets with both
# low margin AND low pip value (cheap, calm) rise to the top; assets with both
# high margin AND high pip value (expensive, fast-moving) sink to the bottom.
# Ranks are used instead of raw values so margin (small $ range) and pip value
# (can span 0.001 to 100+) contribute equally regardless of scale.
if not df_assets.empty:
    df_assets = df_assets[df_assets["Suitable"] == "🟢 Safe Size"]

    margin_rank = df_assets["Min-Margin ($)"].rank(method="min", ascending=True)
    pip_value_rank = df_assets["Pip Value ($/min)"].rank(method="min", ascending=True, na_option="bottom")
    df_assets["Risk Score"] = margin_rank + pip_value_rank

    df_assets = df_assets.sort_values(by="Risk Score", ascending=True)

watchlist = init_watchlist()
hidden_assets = init_hidden_assets()

# 4. RENDER THE INTERFACE DISPLAY LAYOUT
st.subheader("Asset Risk Scanner")
if not df_assets.empty:
    df_assets["Index Class"] = df_assets["Asset"].apply(get_index_class)

    render_sidebar_watchlist(watchlist, df_assets)
    render_sidebar_hidden_assets(hidden_assets)

    df_scanner = df_assets[
        ~df_assets["Asset"].isin(watchlist) & ~df_assets["Asset"].isin(hidden_assets)
    ].copy()

    display_columns = [
        "Asset",
        "Min Lot",
        "Min-Margin ($)",
        "Pip Value ($/min)",
        "Velocity (pips/min)",
    ]
    watchlist_count = len(watchlist)
    total_assets = len(df_scanner)
    index_classes = sorted(df_scanner["Index Class"].unique()) if not df_scanner.empty else []

    filter_col, search_col, page_size_col = st.columns([2, 2, 1])
    with filter_col:
        selected_classes = st.multiselect(
            "Filter by index class",
            options=index_classes,
            default=[],
            placeholder="All classes",
        )
    with search_col:
        search_query = st.text_input(
            "Search assets",
            placeholder="Search by asset name...",
        )
    with page_size_col:
        page_size = st.selectbox("Rows per page", options=[10, 25, 50, 100], index=1)

    add_col, add_btn_col = st.columns([4, 1])
    available_assets = sorted(df_scanner["Asset"].unique()) if not df_scanner.empty else []
    with add_col:
        asset_to_add = st.selectbox(
            "Add to watchlist",
            options=available_assets,
            index=None,
            placeholder="Choose an asset to watch...",
        )
    with add_btn_col:
        st.markdown("<div style='height: 1.6rem'></div>", unsafe_allow_html=True)
        if st.button(
            "➕ Add to watchlist",
            disabled=asset_to_add is None,
            width="stretch",
        ):
            add_to_watchlist(asset_to_add)
            st.rerun()

    df_filtered = df_scanner.copy()
    if selected_classes:
        df_filtered = df_filtered[df_filtered["Index Class"].isin(selected_classes)]
    if search_query.strip():
        df_filtered = df_filtered[
            df_filtered["Asset"].str.contains(search_query.strip(), case=False, na=False)
        ]

    filtered_count = len(df_filtered)
    total_pages = max(1, math.ceil(filtered_count / page_size))

    filter_key = (search_query.strip(), tuple(sorted(selected_classes)), page_size)
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
        st.caption(f"Scanner: 0 assets · Watchlist: {watchlist_count} · Hidden: {len(hidden_assets)}")
        st.info("All available assets are in your watchlist or hidden. Remove/unhide one to see it here again.")
    elif filtered_count == 0:
        st.caption(
            f"No matching assets (Scanner: {total_assets}, Watchlist: {watchlist_count}, Hidden: {len(hidden_assets)})"
        )
        st.info("No assets match your search or filter criteria.")
    else:
        showing_from = page_start + 1
        showing_to = min(page_end, filtered_count)
        st.caption(
            f"Showing {showing_from}-{showing_to} of {filtered_count} assets "
            f"(Scanner: {total_assets}, Watchlist: {watchlist_count}, Hidden: {len(hidden_assets)})"
        )

        row_height = 35
        header_height = 38
        table_height = len(df_page) * row_height + header_height

        # Dynamic key: forces a fresh widget whenever the row set changes
        # (page nav, search, filter, page size) so a stale row-selection
        # index can never be applied to a smaller/different dataframe.
        table_key = f"asset_scanner_table_{current_page}_{filtered_count}_{page_size}"

        table_selection = st.dataframe(
            df_page[display_columns],
            hide_index=True,
            width="stretch",
            height=table_height,
            on_select="rerun",
            selection_mode="multi-row",
            key=table_key,
            column_config={
                "Pip Value ($/min)": st.column_config.NumberColumn(
                    "Pip Value ($/min)", format="$%.4f"
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

        quick_add_col, quick_hide_col, _ = st.columns([2, 2, 2])
        with quick_add_col:
            add_label = (
                f"➕ Add {selection_count} selected to watchlist"
                if selection_count > 1
                else "➕ Add selected row to watchlist"
            )
            if st.button(add_label, disabled=selection_count == 0, width="stretch"):
                for asset in selected_assets:
                    add_to_watchlist(asset)
                st.success(f"Added {selection_count} asset(s) to the watchlist.")
                st.rerun()
        with quick_hide_col:
            hide_label = (
                f"🙈 Hide {selection_count} selected"
                if selection_count > 1
                else "🙈 Hide selected row"
            )
            if st.button(
                hide_label,
                disabled=selection_count == 0,
                width="stretch",
                help="Hides the selected asset(s) from the scanner until unhidden from the sidebar.",
            ):
                for asset in selected_assets:
                    hide_asset(asset)
                st.success(f"Hid {selection_count} asset(s).")
                st.rerun()


        _, prev_col, page_col, next_col, _ = st.columns([3, 1, 1.5, 1, 3])
        with prev_col:
            if st.button("Previous", disabled=current_page == 0, width="stretch"):
                st.session_state.asset_page -= 1
                st.rerun()
        with page_col:
            st.markdown(f"**Page {current_page + 1} of {total_pages}**")
        with next_col:
            if st.button("Next", disabled=current_page >= total_pages - 1, width="stretch"):
                st.session_state.asset_page += 1
                st.rerun()
else:
    render_sidebar_watchlist(watchlist, pd.DataFrame(columns=["Asset"]))
    render_sidebar_hidden_assets(hidden_assets)
    st.warning("No assets found. Ensure MT5 is connected and logged in to a broker.")