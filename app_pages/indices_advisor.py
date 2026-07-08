import math

import streamlit as st
import MetaTrader5 as mt5
import pandas as pd

from core import mt5_client
from core.config import load_config, set_risk_params
from core.watchlist_store import init_watchlist, add_to_watchlist, remove_from_watchlist
from core.velocity import compute_velocity_matrix, TIMEFRAME_MINUTES

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


def render_sidebar_watchlist(watchlist: set[str], df_assets: pd.DataFrame, max_vol_col: str) -> None:
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
                st.caption(
                    f"Margin ${row['Min-Margin ($)']:.2f} · "
                    f"Max Vol {row[max_vol_col]}"
                )

        with remove_col:
            if st.button("✕", key=f"remove_watchlist_{asset}", help="Remove from watchlist"):
                remove_from_watchlist(asset)
                st.rerun()


st.title("🎯 Deriv Synthetic Indices Advisor")

cfg = st.session_state.setdefault("app_config", load_config())

# 1. SIDEBAR RISK INPUTS (persisted to broker_config.json so Dashboard/Settings stay in sync)
st.sidebar.header("Account Parameters")
account_size = st.sidebar.number_input(
    "Account Balance ($)", min_value=1.0, value=float(cfg["risk"]["account_size"]), step=1.0
)
risk_percentage = st.sidebar.slider(
    "Risk Tolerance (%)", min_value=1.0, max_value=100.0, value=float(cfg["risk"]["risk_percentage"])
)

if account_size != cfg["risk"]["account_size"] or risk_percentage != cfg["risk"]["risk_percentage"]:
    set_risk_params(cfg, account_size, risk_percentage)

max_risk_cash = account_size * (risk_percentage / 100.0)
st.sidebar.metric(label="Max Cash at Risk", value=f"${max_risk_cash:,.2f}")

# 2. CONNECT TO MT5 (shared connection, reused across pages)
ok, msg = mt5_client.ensure_connection(cfg)
if not ok:
    st.error(msg)
    st.page_link("app_pages/settings.py", label="Configure broker login in Settings →", icon="⚙️")
    st.stop()

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

            asset_data.append({
                "Asset": name,
                "Min Lot": min_lot,
                "Min-Margin ($)": round(min_margin, 2),
                "Volume Limit": vol_limit,
                "Min Risk Exposure ($)": round(min_trade_risk_cost, 2),
                "Suitable": "🟢 Safe Size" if is_suitable else "🔴 Volatility Too High"
            })

        progress_bar.empty()
        status.update(label="MT5 Data Synchronization Complete!", state="complete", expanded=False)
    else:
        status.update(label="MT5 Initialization Complete, but no symbols found.", state="error", expanded=True)

# Convert to DataFrame for layout structuring
df_assets = pd.DataFrame(asset_data)

# Filter to show ONLY safe assets and sort from least margin to most
if not df_assets.empty:
    df_assets = df_assets[df_assets["Suitable"] == "🟢 Safe Size"]
    df_assets = df_assets.sort_values(by="Min-Margin ($)", ascending=True)

watchlist = init_watchlist()

# 4. RENDER THE INTERFACE DISPLAY LAYOUT
st.subheader("Asset Risk Scanner")
if not df_assets.empty:
    max_vol_col = f"Max Vol Limit Per {account_size:.2f}"
    df_assets[max_vol_col] = df_assets["Min-Margin ($)"].apply(
        lambda margin: int(account_size / margin) if margin > 0 else 0
    )
    df_assets["Index Class"] = df_assets["Asset"].apply(get_index_class)

    render_sidebar_watchlist(watchlist, df_assets, max_vol_col)

    df_scanner = df_assets[~df_assets["Asset"].isin(watchlist)].copy()

    display_columns = [
        "Asset",
        "Min Lot",
        "Min-Margin ($)",
        "Volume Limit",
        max_vol_col,
        "Suitable",
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
        st.caption(f"Scanner: 0 assets · Watchlist: {watchlist_count}")
        st.info("All available assets are in your watchlist. Remove one from the sidebar to see it here again.")
    elif filtered_count == 0:
        st.caption(
            f"No matching assets (Scanner: {total_assets}, Watchlist: {watchlist_count})"
        )
        st.info("No assets match your search or filter criteria.")
    else:
        showing_from = page_start + 1
        showing_to = min(page_end, filtered_count)
        st.caption(
            f"Showing {showing_from}-{showing_to} of {filtered_count} assets "
            f"(Scanner: {total_assets}, Watchlist: {watchlist_count})"
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
            selection_mode="single-row",
            key=table_key,
        )

        selected_rows = (
            table_selection.selection.rows
            if table_selection.selection is not None
            else []
        )

        selected_asset = None
        if selected_rows:
            row_idx = selected_rows[0]
            if 0 <= row_idx < len(df_page):
                selected_asset = df_page.iloc[row_idx]["Asset"]

        quick_add_col, _ = st.columns([2, 4])
        with quick_add_col:
            if st.button(
                "➕ Add selected row to watchlist",
                disabled=selected_asset is None,
                width="stretch",
            ):
                add_to_watchlist(selected_asset)
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
    st.sidebar.divider()
    st.sidebar.subheader("Watchlist")
    st.sidebar.caption(f"{len(watchlist)} saved asset(s)")
    if not watchlist:
        st.sidebar.info("Add assets from the scanner using ➕ Add.")
    else:
        for asset in sorted(watchlist):
            label_col, remove_col = st.sidebar.columns([5, 1])
            with label_col:
                st.markdown(f"**{asset}**")
            with remove_col:
                if st.button("✕", key=f"remove_watchlist_{asset}", help="Remove from watchlist"):
                    remove_from_watchlist(asset)
                    st.rerun()
    st.warning("No assets found. Ensure MT5 is connected and logged in to a broker.")

st.divider()

# 5. PRICE VELOCITY ANALYZER
st.subheader("📈 Price Velocity Analyzer")
st.caption(
    "Summed Realized Candle Velocity — sums the absolute body movement of every closed "
    "candle since the start of the session (plus the overnight gap), divided by elapsed "
    "minutes. Higher = the price is covering more ground per minute right now."
)

velocity_asset_options = sorted({sym.name for sym in symbols}) if symbols else []

if not velocity_asset_options:
    st.info("Run the scanner above first so there are assets available to analyze.")
else:
    va_col, btn_col = st.columns([4, 1])
    with va_col:
        velocity_symbol = st.selectbox(
            "Asset to analyze",
            options=velocity_asset_options,
            key="velocity_symbol_select",
        )
    with btn_col:
        st.markdown("<div style='height: 1.6rem'></div>", unsafe_allow_html=True)
        calc_clicked = st.button("Calculate", key="calc_velocity_btn", width="stretch")

    if calc_clicked:
        with st.spinner(f"Calculating price velocity for {velocity_symbol}..."):
            st.session_state.velocity_matrix = compute_velocity_matrix(velocity_symbol)
            st.session_state.velocity_matrix_symbol = velocity_symbol

    matrix = st.session_state.get("velocity_matrix")
    matrix_symbol = st.session_state.get("velocity_matrix_symbol")

    if matrix and matrix_symbol == velocity_symbol:
        rows = []
        for row in matrix:
            rows.append({
                "Timeframe": row["timeframe"],
                "TF Minutes": TIMEFRAME_MINUTES[row["timeframe"]],
                "Closed Candles (N)": row["n"],
                "Total Movement (pips)": round(row["total_pips"], 2) if row["total_pips"] is not None else "—",
                "Elapsed": f"{row['elapsed_minutes']} min" if row["elapsed_minutes"] else ("—" if row["timeframe"] != "D1" else f"{row['n']} days"),
                "Velocity": round(row["velocity"], 4) if row["velocity"] is not None else "—",
                "Unit": row["unit"],
            })
        df_velocity = pd.DataFrame(rows)
        st.dataframe(df_velocity, hide_index=True, width="stretch")

        valid_rows = [r for r in matrix if r["velocity"] is not None]
        if valid_rows:
            fastest = max(valid_rows, key=lambda r: r["velocity"] if r["unit"] == "pips/min" else 0)
            if fastest["unit"] == "pips/min":
                st.caption(
                    f"Fastest intraday timeframe right now: **{fastest['timeframe']}** at "
                    f"**{fastest['velocity']:.4f} pips/min** ({fastest['n']} closed candles today)."
                )
    elif matrix_symbol and matrix_symbol != velocity_symbol:
        st.caption("Click **Calculate** to analyze the newly selected asset.")
    else:
        st.caption("Select an asset and click **Calculate** to see its velocity across all timeframes.")