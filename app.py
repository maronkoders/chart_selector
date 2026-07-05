# app.py
import json
import math
from pathlib import Path

import streamlit as st
import MetaTrader5 as mt5
import pandas as pd

WATCHLIST_FILE = Path(__file__).parent / "watchlist.json"

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


def load_watchlist() -> set[str]:
    if WATCHLIST_FILE.exists():
        try:
            return set(json.loads(WATCHLIST_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_watchlist(watchlist: set[str]) -> None:
    WATCHLIST_FILE.write_text(
        json.dumps(sorted(watchlist), indent=2),
        encoding="utf-8",
    )


def init_watchlist() -> set[str]:
    if "watchlist" not in st.session_state:
        st.session_state.watchlist = load_watchlist()
    return st.session_state.watchlist


def add_to_watchlist(asset: str) -> None:
    st.session_state.watchlist.add(asset)
    save_watchlist(st.session_state.watchlist)


def remove_from_watchlist(asset: str) -> None:
    st.session_state.watchlist.discard(asset)
    save_watchlist(st.session_state.watchlist)


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

# 1. PAGE CONFIGURATION
st.set_page_config(layout="wide", page_title="Simple MT5 Risk Dashboard")
st.title("🎯Deriv Synthetic Indices Advisor")

# 2. SIDEBAR INPUTS
st.sidebar.header("Account Parameters")
account_size = st.sidebar.number_input("Account Balance ($)", min_value=1.0, value=1.0, step=1.0)
risk_percentage = st.sidebar.slider("Risk Tolerance (%)", min_value=1.0, max_value=100.0, value=50.0)

# Calculate absolute cash you are willing to lose on a trade sequence
max_risk_cash = account_size * (risk_percentage / 100.0)
st.sidebar.metric(label="Max Cash at Risk", value=f"${max_risk_cash:,.2f}")

# 3. INITIALIZE METATRADER 5
with st.status("Initializing MT5 Connection...", expanded=True) as status:
    status.write("Connecting to local MT5 terminal...")
    if not mt5.initialize():
        status.update(label=f"Failed to connect to MT5. Error: {mt5.last_error()}", state="error")
        st.error("Ensure your Deriv MT5 app is open.")
        st.stop()
    status.write("Connected successfully.")

    # 4. FETCH SYNTHETIC INDICES SPEC SHEETS
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
            
            mt5.symbol_select(name, True) # Make sure it's active in Market Watch
            
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

# 5. RENDER THE INTERFACE DISPLAY LAYOUT
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
            use_container_width=True,
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

        table_selection = st.dataframe(
            df_page[display_columns],
            hide_index=True,
            use_container_width=True,
            height=table_height,
            on_select="rerun",
            selection_mode="single-row",
            key="asset_scanner_table",
        )

        selected_rows = (
            table_selection.selection.rows
            if table_selection.selection is not None
            else []
        )
        selected_asset = (
            df_page.iloc[selected_rows[0]]["Asset"] if selected_rows else None
        )

        quick_add_col, _ = st.columns([2, 4])
        with quick_add_col:
            if st.button(
                "➕ Add selected row to watchlist",
                disabled=selected_asset is None,
                use_container_width=True,
            ):
                add_to_watchlist(selected_asset)
                st.rerun()

        _, prev_col, page_col, next_col, _ = st.columns([3, 1, 1.5, 1, 3])
        with prev_col:
            if st.button("Previous", disabled=current_page == 0, use_container_width=True):
                st.session_state.asset_page -= 1
                st.rerun()
        with page_col:
            st.markdown(f"**Page {current_page + 1} of {total_pages}**")
        with next_col:
            if st.button("Next", disabled=current_page >= total_pages - 1, use_container_width=True):
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

# Good practice: clean up or leave terminal connection warm for seamless active state refreshes