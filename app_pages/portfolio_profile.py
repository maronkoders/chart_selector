"""Portfolio Profile — monthly PnL across all broker login profiles."""
import datetime as dt

import pandas as pd
import streamlit as st

from core import mt5_client
from core.config import load_config, get_active_profile
from core.portfolio_store import (
    has_portfolio_data,
    list_months,
    load_portfolio,
    refresh_active_profile,
    sync_all_profiles,
    table_rows_for_month,
)
from core.page_load_monitor import page_bootstrap

st.title("Portfolio Profile")
st.caption(
    "PnL totals for every broker profile, cached in `portfolio_profile.json`. "
    "The cache updates when you use a profile; use Sync to pull all accounts at once."
)

cfg = st.session_state.setdefault("app_config", load_config())

with page_bootstrap("Portfolio Profile", "Connecting and loading portfolio cache…") as boot:
    ok, msg = mt5_client.ensure_connection(cfg)
    boot.ok = ok
    boot.detail = msg
    active_name, _ = get_active_profile(cfg)
    store = load_portfolio()
    has_data = has_portfolio_data(store)

top_l, top_r = st.columns([3, 2])
with top_l:
    if ok:
        st.success(msg)
    else:
        st.error(msg)
    if store.get("updated_at"):
        st.caption(f"Cache last updated: {store['updated_at']}")
    else:
        st.caption("No portfolio cache yet.")
with top_r:
    sync_clicked = st.button(
        "Sync all profiles PnL",
        type="primary",
        width="stretch",
        help="Log into every saved broker profile, pull history, and rewrite portfolio_profile.json.",
    )
    if ok and active_name and st.button(
        "Refresh active profile",
        width="stretch",
        help=f"Re-pull PnL for the current profile ({active_name}).",
    ):
        with page_bootstrap("Portfolio Profile", f"Refreshing {active_name}…") as boot:
            refresh_active_profile(cfg, force=True)
            boot.detail = f"refreshed {active_name}"
        st.rerun()

if sync_clicked:
    if not (cfg.get("profiles") or {}):
        st.error("No broker profiles configured. Add them in Settings first.")
    else:
        with page_bootstrap(
            "Portfolio Profile",
            "Logging into each profile and collecting PnL…",
        ) as boot:
            result = sync_all_profiles(cfg)
            boot.ok = bool(result.get("ok"))
            boot.detail = f"ok={len(result.get('ok') or [])} failed={len(result.get('failed') or [])}"
        st.session_state["portfolio_sync_result"] = result
        st.rerun()

sync_result = st.session_state.pop("portfolio_sync_result", None)
if sync_result:
    ok_names = sync_result.get("ok") or []
    failed = sync_result.get("failed") or []
    if ok_names:
        st.success(f"Synced {len(ok_names)} profile(s): {', '.join(ok_names)}")
    if failed:
        st.warning(
            "Failed: "
            + "; ".join(f"{f['profile']} ({f['error']})" for f in failed[:6])
            + ("…" if len(failed) > 6 else "")
        )
    store = load_portfolio()
    has_data = has_portfolio_data(store)

if not has_data:
    st.info(
        "No portfolio data in cache yet. Click **Sync all profiles PnL** to log into "
        "each broker profile, collect monthly PnL, and save `portfolio_profile.json`."
    )
    st.stop()

months = list_months(store)
month_options = ["All"] + months
# Default to current month when present, else All
current_month = dt.date.today().strftime("%Y-%m")
default_index = month_options.index(current_month) if current_month in month_options else 0

selected_month = st.selectbox(
    "Filter by month",
    options=month_options,
    index=default_index,
    help="Shows closed-trade PnL for the selected month (or lifetime totals for All).",
)

rows = table_rows_for_month(store, None if selected_month == "All" else selected_month)
df = pd.DataFrame(rows)

if df.empty:
    st.warning("Cache has no profile rows.")
    st.stop()

# Summary metrics for the filtered view
total_pnl = float(df["PnL"].fillna(0).sum())
total_net = float(df["Net PnL"].fillna(0).sum())
total_trades = int(df["Trades"].fillna(0).sum())
m1, m2, m3, m4 = st.columns(4)
m1.metric("Profiles", len(df))
m2.metric("Trades", total_trades)
m3.metric("PnL", f"${total_pnl:,.2f}")
m4.metric("Net PnL", f"${total_net:,.2f}")
st.caption(
    f"Filter: **{selected_month}** · PnL = closed deal profit (same as Dashboard). "
    "Net PnL includes commission + swap."
)

display = df[
    [
        "Profile",
        "Login",
        "Server",
        "Balance",
        "Equity",
        "PnL",
        "Commission",
        "Swap",
        "Net PnL",
        "Trades",
        "Wins",
        "Losses",
        "Updated",
    ]
].copy()

# Format money columns for display while keeping sort via underlying numbers in df
for col in ("Balance", "Equity", "PnL", "Commission", "Swap", "Net PnL"):
    display[col] = display[col].apply(
        lambda v: "" if v is None or (isinstance(v, float) and pd.isna(v)) else f"${float(v):,.2f}"
    )

st.dataframe(display, width="stretch", hide_index=True)

errors = df[df["Error"].astype(str).str.len() > 0]
if not errors.empty:
    with st.expander("Profile sync errors"):
        for _, row in errors.iterrows():
            st.write(f"**{row['Profile']}**: {row['Error']}")
