import datetime as dt

import pandas as pd
import streamlit as st

from core import mt5_client
from core.config import load_config
from core.journal_store import (
    get_entry_description,
    save_entry_description,
    clear_entry_description,
    encode_uploaded_image,
    decode_image_bytes,
)
from core.page_load_monitor import page_bootstrap

IMAGE_TYPES = ["png", "jpg", "jpeg", "gif", "webp"]

st.title("📓 Trading Journal")

cfg = st.session_state.setdefault("app_config", load_config())

# ── WEEK NAVIGATION ──────────────────────────────────────────────────────────
def get_week_start(date: dt.date) -> dt.date:
    """Return Monday of the given date's week."""
    return date - dt.timedelta(days=date.weekday())

def get_week_end(date: dt.date) -> dt.date:
    """Return Sunday of the given date's week."""
    return date + dt.timedelta(days=6 - date.weekday())

if "journal_week_start" not in st.session_state:
    st.session_state.journal_week_start = get_week_start(dt.date.today())

week_start = st.session_state.journal_week_start
week_end = get_week_end(week_start)

col_nav, col_label, col_empty = st.columns([1, 3, 1])
with col_nav:
    c1, c2 = st.columns(2)
    with c1:
        if st.button("◀", key="prev_week", use_container_width=True):
            st.session_state.journal_week_start = week_start - dt.timedelta(weeks=1)
            st.rerun()
    with c2:
        if st.button("▶", key="next_week", use_container_width=True):
            st.session_state.journal_week_start = week_start + dt.timedelta(weeks=1)
            st.rerun()

with col_label:
    st.markdown(
        f"<h3 style='text-align: center; margin: 0;'>{week_start.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}</h3>",
        unsafe_allow_html=True,
    )

with col_empty:
    if st.button("Today", key="this_week", use_container_width=True):
        st.session_state.journal_week_start = get_week_start(dt.date.today())
        st.rerun()

# ── FETCH LIVE MT5 DATA FOR THE WEEK (trade facts are never stored) ─────────
# Each row is always rebuilt fresh from MT5. Notes/images are looked up
# separately from entries_description.json, keyed by mt5_ticket, and
# attached on top for display — but the trade facts themselves are read-only.
trades = []
mt5_error = None

with page_bootstrap("Journal", "Loading week trades from MT5…") as boot:
    try:
        ok, msg = mt5_client.ensure_connection(cfg)
        boot.ok = ok
        boot.detail = msg
        if ok:
            from_date = dt.datetime.combine(week_start, dt.time.min)
            to_date = dt.datetime.combine(week_end, dt.time.max)
            deals_df = mt5_client.get_history_deals_df(from_date, to_date)
            if not deals_df.empty:
                closing_deals = deals_df[deals_df["Entry"] == 1]
                if not closing_deals.empty:
                    for _, row in closing_deals.iterrows():
                        ticket = int(row["Ticket"])
                        description = get_entry_description(ticket)
                        trades.append({
                            "mt5_ticket": ticket,
                            "date": row["Time"].strftime("%Y-%m-%d %H:%M"),
                            "asset": row["Symbol"],
                            "direction": row["Type"],
                            "lots": float(row["Volume"]),
                            "entry_price": float(row["Price"]),
                            "pnl": float(row["Profit"]),
                            "notes": description["notes"],
                            "images": description["images"],
                        })
                else:
                    mt5_error = "No closing deals found for this week."
            else:
                mt5_error = "No trade history found in MT5 for the selected week."
        else:
            mt5_error = f"MT5 connection failed: {msg}"
    except Exception as e:
        mt5_error = f"Could not fetch live MT5 data: {e}"
        boot.ok = False
        boot.detail = mt5_error

with st.sidebar:
    st.header("Status")
    if trades:
        st.success(f"Showing {len(trades)} live trades")
    elif mt5_error:
        st.error(mt5_error)

if not trades:
    st.info("No trades found for this week. Use the arrows to browse other weeks, or check your MT5 connection.")
    st.stop()

df = pd.DataFrame(trades)
df["date"] = pd.to_datetime(df["date"], errors="coerce")
df["image_count"] = df["images"].apply(len)
df = df.sort_values("date", ascending=False).reset_index(drop=True)

# ── STATS ────────────────────────────────────────────────────────────────────
total_trades = len(df)
win_trades = int((df["pnl"] > 0).sum())
loss_trades = int((df["pnl"] < 0).sum())
win_rate = (win_trades / total_trades * 100) if total_trades else 0.0
total_pnl = df["pnl"].sum()
avg_win = df.loc[df["pnl"] > 0, "pnl"].mean() if win_trades else 0.0
avg_loss = df.loc[df["pnl"] < 0, "pnl"].mean() if loss_trades else 0.0

s1, s2, s3, s4, s5 = st.columns(5)
s1.metric("Total Trades", total_trades)
s2.metric("Win Rate", f"{win_rate:.1f}%")
s3.metric("Net P/L", f"${total_pnl:,.2f}")
s4.metric("Avg Win", f"${avg_win:,.2f}")
s5.metric("Avg Loss", f"${avg_loss:,.2f}")

st.divider()

# ── ENTRIES TABLE (read-only trade facts) ────────────────────────────────────
st.subheader("Entries")

display_columns = ["date", "asset", "direction", "lots", "entry_price", "pnl", "image_count", "notes"]
column_labels = {"image_count": "Images"}

row_height = 35
header_height = 38
table_height = min(len(df), 15) * row_height + header_height

st.dataframe(
    df[display_columns].rename(columns=column_labels),
    hide_index=True,
    use_container_width=True,
    height=table_height,
)

st.divider()

# ── PER-TRADE NOTES/IMAGES (the only editable data) ──────────────────────────
st.subheader("✏️ Notes & Screenshots")
st.caption("Trade details always come straight from MT5 and can't be edited — only your notes and screenshots are saved here, linked to the trade's MT5 ticket.")

for idx, row in df.iterrows():
    ticket = row["mt5_ticket"]

    pnl_color = "🟢" if row["pnl"] > 0 else "🔴" if row["pnl"] < 0 else "⚪"
    date_label = row["date"].strftime("%Y-%m-%d %H:%M") if pd.notna(row["date"]) else "N/A"

    with st.expander(
        f"{pnl_color} {row['asset']} | {row['direction']} | {date_label} | P/L: ${row['pnl']:,.2f}",
        expanded=False,
    ):
        existing_images = row["images"] or []

        with st.form(f"annotate_{ticket}_{idx}"):
            notes_edit = st.text_area("Notes", value=row["notes"], key=f"notes_{ticket}_{idx}")

            if existing_images:
                st.write("Current images (select any to remove):")
                remove_choices = st.multiselect(
                    "Remove image(s)",
                    options=[img["name"] for img in existing_images],
                    key=f"remove_images_{ticket}_{idx}",
                    label_visibility="collapsed",
                )
                thumb_cols = st.columns(min(4, len(existing_images)))
                for i, img in enumerate(existing_images):
                    with thumb_cols[i % len(thumb_cols)]:
                        st.image(decode_image_bytes(img), caption=img["name"], use_container_width=True)
            else:
                remove_choices = []
                st.caption("No images attached yet.")

            new_uploads = st.file_uploader(
                "Add image(s) to notes",
                type=IMAGE_TYPES,
                accept_multiple_files=True,
                key=f"new_images_{ticket}_{idx}",
            )

            save_col, clear_col = st.columns(2)
            save_clicked = save_col.form_submit_button("💾 Save Notes", use_container_width=True)
            clear_clicked = clear_col.form_submit_button("🗑️ Clear Notes/Images", use_container_width=True)

            if save_clicked:
                kept_images = [img for img in existing_images if img["name"] not in remove_choices]
                new_images = []
                for uploaded in new_uploads or []:
                    record = encode_uploaded_image(
                        uploaded,
                        asset=row["asset"],
                        direction=row["direction"],
                        pnl=float(row["pnl"]),
                    )
                    if record is None:
                        st.warning(f"Skipped '{uploaded.name}' — over the 5 MB attachment limit.")
                    else:
                        new_images.append(record)

                save_entry_description(ticket, notes_edit.strip(), kept_images + new_images)
                st.success("Saved.")
                st.rerun()

            if clear_clicked:
                clear_entry_description(ticket)
                st.success("Cleared.")
                st.rerun()