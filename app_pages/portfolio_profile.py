"""Portfolio Profile — monthly PnL across all broker login profiles."""
import datetime as dt

import altair as alt
import pandas as pd
import streamlit as st

from core import mt5_client
from core.config import load_config, get_active_profile
from core.portfolio_store import (
    aggregate_yearly_pnl,
    has_portfolio_data,
    list_months,
    list_years,
    load_portfolio,
    months_for_year,
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

years = list_years(store)
today = dt.date.today()
if not years:
    years = [today.year]
default_year = today.year if today.year in years else years[0]

year_col, month_col = st.columns(2)
with year_col:
    selected_year = st.selectbox(
        "Filter by year",
        options=years,
        index=years.index(default_year),
        help="Year used for the table month list and the Jan→current combined PnL chart.",
    )

year_months = months_for_year(int(selected_year), through_current=True)
cached_in_year = [m for m in list_months(store) if m.startswith(f"{selected_year}-")]
month_options = ["All"] + sorted(set(year_months) | set(cached_in_year))
current_month = today.strftime("%Y-%m")
if current_month in month_options and int(selected_year) == today.year:
    default_month_index = month_options.index(current_month)
else:
    default_month_index = 0

with month_col:
    selected_month = st.selectbox(
        "Filter by month",
        options=month_options,
        index=default_month_index,
        help="Table shows closed-trade PnL for the selected month (or year totals for All).",
    )

if selected_month == "All":
    rows = []
    for name, entry in sorted((store.get("profiles") or {}).items()):
        if not isinstance(entry, dict):
            continue
        months = entry.get("months") or {}
        year_stats = [months[k] for k in year_months if k in months]
        rows.append({
            "Profile": name,
            "Login": entry.get("login") or "",
            "Server": entry.get("server") or "",
            "Balance": entry.get("balance"),
            "Equity": entry.get("equity"),
            "PnL": round(sum(float(m.get("pnl") or 0) for m in year_stats), 4),
            "Commission": round(sum(float(m.get("commission") or 0) for m in year_stats), 4),
            "Swap": round(sum(float(m.get("swap") or 0) for m in year_stats), 4),
            "Net PnL": round(sum(float(m.get("net_pnl") or 0) for m in year_stats), 4),
            "Trades": sum(int(m.get("trades") or 0) for m in year_stats),
            "Wins": sum(int(m.get("wins") or 0) for m in year_stats),
            "Losses": sum(int(m.get("losses") or 0) for m in year_stats),
            "Updated": entry.get("updated_at") or "",
            "Error": entry.get("error") or "",
        })
else:
    rows = table_rows_for_month(store, selected_month)

df = pd.DataFrame(rows)

if df.empty:
    st.warning("Cache has no profile rows.")
    st.stop()

total_pnl = float(df["PnL"].fillna(0).sum())
total_net = float(df["Net PnL"].fillna(0).sum())
total_trades = int(df["Trades"].fillna(0).sum())
m1, m2, m3, m4 = st.columns(4)
m1.metric("Profiles", len(df))
m2.metric("Trades", total_trades)
m3.metric("PnL", f"${total_pnl:,.2f}")
m4.metric("Net PnL", f"${total_net:,.2f}")
st.caption(
    f"Filter: **{selected_year}** / **{selected_month}** · PnL = closed deal profit "
    "(same as Dashboard). Net PnL includes commission + swap."
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

st.divider()
st.subheader(f"Yearly PnL — {selected_year}")
st.caption(
    "Combined closed-trade PnL across all broker profiles, January through "
    + ("the current month." if int(selected_year) == today.year else "December.")
    + " Values include the negative range (not floored at zero)."
)

year_rows = aggregate_yearly_pnl(store, int(selected_year), through_current=True)
chart_df = pd.DataFrame(year_rows)

if chart_df.empty:
    st.info(f"No month range to plot for {selected_year}.")
else:
    y_min = float(min(chart_df["PnL"].min(), chart_df["Cumulative PnL"].min(), 0))
    y_max = float(max(chart_df["PnL"].max(), chart_df["Cumulative PnL"].max(), 0))
    pad = max(abs(y_max - y_min) * 0.08, 1.0)
    y_domain = [y_min - pad, y_max + pad]
    month_order = list(chart_df["Label"])

    monthly = (
        alt.Chart(chart_df)
        .mark_line(point=True, color="#e11d48", strokeWidth=2.5)
        .encode(
            x=alt.X(
                "Label:N",
                sort=month_order,
                title="Month",
                axis=alt.Axis(labelAngle=0),
            ),
            y=alt.Y(
                "PnL:Q",
                title="Combined PnL ($)",
                scale=alt.Scale(domain=y_domain, nice=False, zero=False),
                axis=alt.Axis(format="$,.2f"),
            ),
            tooltip=[
                alt.Tooltip("Month:N", title="Month"),
                alt.Tooltip("PnL:Q", title="Monthly PnL", format="$,.2f"),
                alt.Tooltip("Net PnL:Q", title="Net PnL", format="$,.2f"),
                alt.Tooltip("Trades:Q", title="Trades"),
                alt.Tooltip("Cumulative PnL:Q", title="YTD PnL", format="$,.2f"),
            ],
        )
    )
    cumulative = (
        alt.Chart(chart_df)
        .mark_line(point=True, color="#38bdf8", strokeWidth=2, strokeDash=[6, 4])
        .encode(
            x=alt.X("Label:N", sort=month_order),
            y=alt.Y("Cumulative PnL:Q", scale=alt.Scale(domain=y_domain, nice=False, zero=False)),
            tooltip=[
                alt.Tooltip("Label:N", title="Month"),
                alt.Tooltip("Cumulative PnL:Q", title="YTD PnL", format="$,.2f"),
            ],
        )
    )
    zero_line = (
        alt.Chart(pd.DataFrame({"y": [0.0]}))
        .mark_rule(color="#94a3b8", strokeDash=[4, 4], strokeWidth=1)
        .encode(y="y:Q")
    )

    st.altair_chart(
        (monthly + cumulative + zero_line).properties(height=360).interactive(),
        use_container_width=True,
    )

    c1, c2, c3 = st.columns(3)
    year_pnl = float(chart_df["PnL"].sum())
    year_net = float(chart_df["Net PnL"].sum())
    year_trades = int(chart_df["Trades"].sum())
    c1.metric(f"{selected_year} combined PnL", f"${year_pnl:,.2f}")
    c2.metric(f"{selected_year} combined Net PnL", f"${year_net:,.2f}")
    c3.metric(f"{selected_year} trades", year_trades)
    st.caption("Solid red = monthly combined PnL · Dashed blue = cumulative YTD PnL · Grey = $0.")
