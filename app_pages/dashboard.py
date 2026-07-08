import datetime as dt

import streamlit as st

from core import mt5_client
from core.calendar_view import build_calendar_html
from core.config import load_config, get_profile_plan, calculate_plan_progress
from core.watchlist_store import load_watchlist

st.title("📊 Dashboard")

cfg = st.session_state.setdefault("app_config", load_config())

status_col, reconnect_col = st.columns([5, 1])
ok, msg = mt5_client.ensure_connection(cfg)
with status_col:
    if ok:
        st.success(msg)
    else:
        st.error(msg)
        st.page_link("app_pages/settings.py", label="Go to Settings to configure broker login →", icon="⚙️")
with reconnect_col:
    st.write("")
    if st.button("🔄 Reconnect", width="stretch"):
        mt5_client.ensure_connection(cfg, force=True)
        st.rerun()

if not ok:
    st.stop()

account = mt5_client.get_account_info()

if account:
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Balance", f"${account['balance']:,.2f}")
    m2.metric("Equity", f"${account['equity']:,.2f}")
    m3.metric("Margin", f"${account['margin']:,.2f}")
    m4.metric("Free Margin", f"${account['margin_free']:,.2f}")
    floating_pnl = account["equity"] - account["balance"]
    m5.metric("Floating P/L", f"${floating_pnl:,.2f}")
    
    # Trading Plan Status
    st.divider()
    active_profile_name = cfg.get("active_profile")
    if active_profile_name:
        plan_name, plan_data = get_profile_plan(cfg, active_profile_name)
        if plan_name and plan_data:
            # Fetch trade history for current month for automatic tracking
            today = dt.date.today()
            month_start = dt.datetime.combine(today.replace(day=1), dt.time.min)
            month_end = dt.datetime.combine(today.replace(day=28) + dt.timedelta(days=4), dt.time.min).replace(day=1) if today.month == 12 else dt.datetime.combine(today.replace(day=1), dt.time.min).replace(month=today.month + 1)
            
            trade_history = mt5_client.get_history_deals_df(month_start, month_end)
            
            progress = calculate_plan_progress(plan_data, account['balance'], trade_history)
            
            col1, col2, col3 = st.columns([1, 2, 1])
            with col1:
                st.markdown("### 📈 Trading Plan")
            with col2:
                st.markdown(f"**{plan_name}**")
            with col3:
                st.page_link("app_pages/trading_plan.py", label="View Plan →", icon="📊")
            
            # Display "Day X, Y days to final target" format - bold and centered
            if progress['current_day'] > 0:
                st.markdown(f"<div style='text-align: center;'><strong>Day {progress['current_day']}, {progress['remaining_days']} days to get to '${progress['final_balance']:,.2f}'</strong></div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div style='text-align: center;'><strong>Plan starts on {progress['start_date'].strftime('%B %d, %Y')}</strong></div>", unsafe_allow_html=True)
            
            # Progress bar
            progress_percent = (progress['current_day'] / progress['total_days']) * 100 if progress['total_days'] > 0 else 0
            st.progress(progress_percent / 100)
else:
    st.warning("Could not retrieve account info. Make sure you're logged in to a broker account.")

st.divider()

st.subheader("Open Positions")
positions_df = mt5_client.get_open_positions_df()
if positions_df.empty:
    st.info("No open positions.")
else:
    st.dataframe(positions_df, hide_index=True, width="stretch")
    total_open_profit = positions_df["Profit"].sum()
    st.caption(f"Total floating P/L across {len(positions_df)} position(s): ${total_open_profit:,.2f}")

st.divider()

st.subheader("Trading Calendar")

today = dt.date.today()
if "dashboard_cal_year" not in st.session_state:
    st.session_state.dashboard_cal_year = today.year
    st.session_state.dashboard_cal_month = today.month

cal_year = st.session_state.dashboard_cal_year
cal_month = st.session_state.dashboard_cal_month

nav_prev, nav_title, nav_today, nav_next = st.columns([1, 6, 1, 1])
with nav_prev:
    if st.button("◀", key="cal_prev_month", width="stretch"):
        cal_month -= 1
        if cal_month < 1:
            cal_month = 12
            cal_year -= 1
        st.session_state.dashboard_cal_year = cal_year
        st.session_state.dashboard_cal_month = cal_month
        st.rerun()
with nav_title:
    month_label = dt.date(cal_year, cal_month, 1).strftime("%B %Y")
    st.markdown(f"<h3 style='text-align:center;'>{month_label}</h3>", unsafe_allow_html=True)
with nav_today:
    if st.button("⊙", key="cal_reset_month", help="Jump to current month", width="stretch"):
        st.session_state.dashboard_cal_year = today.year
        st.session_state.dashboard_cal_month = today.month
        st.rerun()
with nav_next:
    if st.button("▶", key="cal_next_month", width="stretch"):
        cal_month += 1
        if cal_month > 12:
            cal_month = 1
            cal_year += 1
        st.session_state.dashboard_cal_year = cal_year
        st.session_state.dashboard_cal_month = cal_month
        st.rerun()

month_start = dt.date(cal_year, cal_month, 1)
month_end = dt.date(cal_year + 1, 1, 1) if cal_month == 12 else dt.date(cal_year, cal_month + 1, 1)
deals_df = mt5_client.get_history_deals_df(
    dt.datetime.combine(month_start, dt.time.min),
    dt.datetime.combine(month_end, dt.time.min),
)

daily_stats = {}
if not deals_df.empty:
    closing_deals = deals_df[deals_df["Entry"] == 1]  # DEAL_ENTRY_OUT
    if not closing_deals.empty:
        grouped = (
            closing_deals.assign(Date=closing_deals["Time"].dt.date)
            .groupby("Date")["Profit"]
            .agg(pnl="sum", count="count")
        )
        daily_stats = {
            date_val: {"pnl": float(row["pnl"]), "count": int(row["count"])}
            for date_val, row in grouped.iterrows()
        }

st.markdown(build_calendar_html(daily_stats, cal_year, cal_month), unsafe_allow_html=True)

if daily_stats:
    total_pnl = sum(v["pnl"] for v in daily_stats.values())
    total_trades = sum(v["count"] for v in daily_stats.values())
    win_days = sum(1 for v in daily_stats.values() if v["pnl"] > 0)
    loss_days = sum(1 for v in daily_stats.values() if v["pnl"] < 0)
    traded_days = sum(1 for v in daily_stats.values() if v["count"] > 0)
    day_win_rate = (win_days / traded_days * 100) if traded_days else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Trades This Month", total_trades)
    c2.metric("Winning Days", win_days)
    c3.metric("Losing Days", loss_days)
    c4.metric("Net P/L", f"${total_pnl:,.2f}")
    st.caption(f"Day win rate: {day_win_rate:.1f}% ({win_days}/{traded_days} traded days)")
else:
    st.caption("No closed trades in this month yet.")

st.divider()

st.subheader("Watchlist")
watchlist = load_watchlist()
if not watchlist:
    st.info("No assets in your watchlist yet. Add some from the Indices Advisor page.")
else:
    st.write(", ".join(sorted(watchlist)))
    st.page_link("app_pages/indices_advisor.py", label="Manage watchlist in Indices Advisor →", icon="🎯")