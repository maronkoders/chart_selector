import datetime as dt
import os
import subprocess
import sys

import pandas as pd
import streamlit as st

from core import mt5_client
from core.calendar_view import build_calendar_html, build_month_grid
from core.config import load_config, get_profile_plan, calculate_plan_progress, get_active_profile, set_risk_params
from core.plan_frequency import build_week_targets_for_grid
from core.hidden_assets_store import load_hidden_assets
from core.page_load_monitor import page_bootstrap, recent_visits, summary_table_rows
from core.sl_risk import max_cash_at_risk
import importlib

# Streamlit can keep a stale mt5_client after new helpers are added; refresh if needed.
if not hasattr(mt5_client, "apply_suggested_sls") or not hasattr(mt5_client, "modify_position_sltp"):
    mt5_client = importlib.reload(mt5_client)

st.title("📊 Dashboard")

cfg = st.session_state.setdefault("app_config", load_config())

with page_bootstrap("Dashboard", "Connecting to MT5 and preparing Dashboard…") as boot:
    ok, msg = mt5_client.ensure_connection(cfg)
    boot.ok = ok
    boot.detail = msg
    loader = mt5_client.chart_loader_status() if ok else {"alive": False}
    account = mt5_client.get_account_info() if ok else None

status_col, reconnect_col = st.columns([5, 1])
with status_col:
    if ok:
        st.success(msg)
    else:
        st.error(msg)
        st.page_link("app_pages/settings.py", label="Go to Settings to configure broker login →", icon="⚙️")
with reconnect_col:
    st.write("")
    if st.button("🔄 Reconnect", width="stretch"):
        with page_bootstrap("Dashboard", "Reconnecting…") as boot:
            ok, msg = mt5_client.ensure_connection(cfg, force=True)
            boot.ok = ok
            boot.detail = msg
        st.rerun()

if not ok:
    st.stop()

# ── ONE-CLICK SYSTEM SYNC ───────────────────────────────────────────────────
st.divider()
st.subheader("MT5 System Sync")
st.caption(
    "One click: reconnect → sync Market Watch → close open charts → open every "
    "watchlist chart on M1 with the new_me indicators."
)

l1, l2 = st.columns([3, 2])
with l1:
    if loader.get("alive"):
        st.success(
            f"ChartSelectorLoader running on `{loader.get('symbol') or '?'}` "
            f"(heartbeat {loader.get('age_seconds', '?')}s ago)"
        )
    else:
        st.warning(loader.get("error") or "ChartSelectorLoader is not running.")
        st.caption(
            "One-time setup: in MT5, open Navigator → Expert Advisors → new_me → "
            "ChartSelectorLoader, drag it onto any chart, and turn on Algo Trading."
        )
with l2:
    experts_dir = loader.get("experts_dir")
    if experts_dir and st.button("📂 Open EA folder", width="stretch"):
        try:
            if sys.platform == "win32":
                os.startfile(experts_dir)
            elif sys.platform == "darwin":
                subprocess.run(["open", experts_dir], check=False)
            else:
                subprocess.run(["xdg-open", experts_dir], check=False)
        except Exception as exc:
            st.error(str(exc))

if st.button("▶ Run MT5 Sync", type="primary", width="stretch"):
    with page_bootstrap("Dashboard", "Running full MT5 sync…") as boot:
        result = mt5_client.run_full_system_sync(cfg, force_reconnect=True)
        boot.ok = bool(result.get("ok"))
        boot.detail = result.get("error") or "sync complete"
    st.session_state["last_system_sync"] = result
    st.rerun()

last = st.session_state.get("last_system_sync")
if last:
    mw = last.get("market_watch") or {}
    charts = last.get("charts") or {}
    if last.get("ok"):
        st.success(
            f"Done — Market Watch {mw.get('desired', 0)} symbol(s); "
            f"charts closed {charts.get('closed', 0)}, opened {charts.get('opened', 0)}."
        )
    elif last.get("error"):
        st.error(last["error"])
        if mw:
            st.info(
                f"Market Watch still updated ({mw.get('desired', mw.get('added', '?'))} "
                f"symbol(s)). Start ChartSelectorLoader to refresh charts."
            )

# ── PAGE LOAD TIMINGS ───────────────────────────────────────────────────────
st.divider()
st.subheader("Page load monitor")
st.caption("How long each page took to finish bootstrap (from `page_load_times.json`).")
summary_rows = summary_table_rows()
if summary_rows:
    st.dataframe(pd.DataFrame(summary_rows), width="stretch", hide_index=True)
    with st.expander("Recent page visits"):
        st.dataframe(pd.DataFrame(recent_visits(25)), width="stretch", hide_index=True)
else:
    st.caption("No page-load timings recorded yet — visit a few pages to populate the log.")

active_plan_data = None  # populated below if the active profile has a linked plan

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
            active_plan_data = plan_data
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

st.subheader("Risk & SL Picker")
st.caption(
    "Stop-loss sizing from your risk tolerance. Max cash at risk is split "
    "equally across open positions; each share converts to SL points via the "
    "symbol's tick value. SL Cash across all positions sums to Max Cash at Risk."
)

live_balance = float(account["balance"]) if account else float(cfg["risk"]["account_size"])
risk_percentage = st.slider(
    "Risk Tolerance (%)",
    min_value=1.0,
    max_value=100.0,
    value=float(cfg["risk"]["risk_percentage"]),
    step=0.5,
    key="dashboard_risk_pct",
)
if live_balance != cfg["risk"]["account_size"] or risk_percentage != cfg["risk"]["risk_percentage"]:
    set_risk_params(cfg, live_balance, risk_percentage)
    st.session_state["app_config"] = cfg

max_risk = round(max_cash_at_risk(live_balance, risk_percentage), 2)
r1, r2, r3 = st.columns(3)
r1.metric("Account Balance", f"${live_balance:,.2f}")
r2.metric("Risk Tolerance", f"{risk_percentage:.1f}%")
r3.metric("Max Cash at Risk", f"${max_risk:,.2f}")

st.subheader("Open Positions")
positions_df = mt5_client.get_open_positions_with_sl_df(max_risk)
if positions_df.empty:
    st.info("No open positions.")
else:
    header_l, header_r = st.columns([3, 2])
    with header_l:
        st.caption("Suggested SL is calculated from your risk budget — apply it to MT5 below.")
    with header_r:
        apply_all = st.button(
            "Apply All Suggested SLs",
            type="primary",
            width="stretch",
            key="apply_all_suggested_sl",
            help="Writes each Suggested SL onto the matching open MT5 position (keeps existing TP).",
        )

    if apply_all:
        with st.spinner("Applying suggested stop-losses on MT5…"):
            st.session_state["last_sl_apply"] = mt5_client.apply_suggested_sls(positions_df)
        st.rerun()

    last_apply = st.session_state.pop("last_sl_apply", None)
    if last_apply:
        if last_apply["failed"] == 0:
            st.success(f"Applied Suggested SL on {last_apply['ok']} position(s).")
        elif last_apply["ok"] == 0:
            st.error("Failed to apply Suggested SL on any position.")
        else:
            st.warning(f"Applied {last_apply['ok']} · failed {last_apply['failed']}.")
        for item in last_apply.get("results") or []:
            st.caption(item["message"])

    st.dataframe(positions_df, hide_index=True, width="stretch")
    total_open_profit = positions_df["Profit"].sum()
    total_sl_cash = float(positions_df["SL Cash"].sum())
    st.caption(
        f"Total floating P/L across {len(positions_df)} position(s): ${total_open_profit:,.2f} · "
        f"SL Cash total: ${total_sl_cash:,.2f} (budget ${max_risk:,.2f})"
    )

    st.markdown("**Apply per position**")
    for _, row in positions_df.iterrows():
        ticket = int(row["Ticket"])
        suggested = float(row["Suggested SL"])
        symbol = str(row["Symbol"])
        col_a, col_b, col_c = st.columns([3, 2, 2])
        with col_a:
            st.write(
                f"`#{ticket}` · {symbol} · {row['Type']} · "
                f"Suggested SL **{suggested}** (cash ${float(row['SL Cash']):,.2f})"
            )
        with col_b:
            current_sl = float(row["SL"] or 0)
            st.caption(f"Current SL: {current_sl if current_sl else '—'}")
        with col_c:
            if st.button(
                "Apply SL",
                key=f"apply_sl_{ticket}",
                width="stretch",
                disabled=suggested <= 0,
            ):
                ok, msg = mt5_client.modify_position_sltp(ticket, suggested, symbol=symbol)
                st.session_state["last_sl_apply"] = {
                    "ok": 1 if ok else 0,
                    "failed": 0 if ok else 1,
                    "results": [{"ticket": ticket, "ok": ok, "message": msg, "sl": suggested}],
                }
                st.rerun()

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

st.markdown(
    build_calendar_html(
        daily_stats,
        cal_year,
        cal_month,
        week_targets=build_week_targets_for_grid(build_month_grid(cal_year, cal_month), active_plan_data),
        freq_label="Planned" if active_plan_data else "Trades",
    ),
    unsafe_allow_html=True,
)

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
asset_data = st.session_state.get("asset_data") or []
active_name, _ = get_active_profile(cfg)
hidden_assets = load_hidden_assets(active_name)
watchlist = sorted(
    {
        row["Asset"]
        for row in asset_data
        if row.get("Suitable") == "🟢 Safe Size" and row.get("Asset") not in hidden_assets
    }
)
if not watchlist:
    st.info("No watchlist assets yet. Run Filter Assets on the Indices Advisor page.")
else:
    st.write(", ".join(watchlist))
    st.page_link("app_pages/indices_advisor.py", label="Manage watchlist in Indices Advisor →", icon="🎯")
