import datetime as dt

import pandas as pd
import streamlit as st

from core import mt5_client
from core.config import load_config
from core.journal_store import (
    init_journal,
    add_journal_entry,
    update_journal_entry,
    remove_journal_entry,
    import_deals_as_entries,
    encode_uploaded_image,
    decode_image_bytes,
    get_journal_entry,
)
from core.watchlist_store import load_watchlist

IMAGE_TYPES = ["png", "jpg", "jpeg", "gif", "webp"]

st.title("📓 Trading Journal")

cfg = st.session_state.setdefault("app_config", load_config())

# ── INITIALIZE JOURNAL STATE ─────────────────────────────────────────────────
# Ensure session state has journal before any store operations
init_journal()

# ── WEEK NAVIGATION ──────────────────────────────────────────────────────────
def get_week_start(date: dt.date) -> dt.date:
    """Return Monday of the given date's week."""
    return date - dt.timedelta(days=date.weekday())

def get_week_end(date: dt.date) -> dt.date:
    """Return Sunday of the given date's week."""
    return date + dt.timedelta(days=6 - date.weekday())

# Initialize current week in session state
if "journal_week_start" not in st.session_state:
    st.session_state.journal_week_start = get_week_start(dt.date.today())

week_start = st.session_state.journal_week_start
week_end = get_week_end(week_start)

# Week navigation with arrows
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

# ── FETCH LIVE MT5 DATA ──────────────────────────────────────────────────────
mt5_data = []
mt5_error = None

try:
    ok, msg = mt5_client.ensure_connection(cfg)
    if ok:
        from_date = dt.datetime.combine(week_start, dt.time.min)
        to_date = dt.datetime.combine(week_end, dt.time.max)
        deals_df = mt5_client.get_history_deals_df(from_date, to_date)
        if not deals_df.empty:
            closing_deals = deals_df[deals_df["Entry"] == 1]
            if not closing_deals.empty:
                for _, row in closing_deals.iterrows():
                    mt5_data.append({
                        "id": str(row["Ticket"]),
                        "date": row["Time"].strftime("%Y-%m-%d %H:%M"),
                        "asset": row["Symbol"],
                        "direction": row["Type"],
                        "lots": float(row["Volume"]),
                        "entry_price": float(row["Price"]),
                        "exit_price": None,
                        "pnl": float(row["Profit"]),
                        "notes": "Live MT5 data",
                        "images": [],
                        "mt5_ticket": int(row["Ticket"]),
                    })
            else:
                mt5_error = "No closing deals found for this week."
        else:
            mt5_error = "No trade history found in MT5 for the selected week."
    else:
        mt5_error = f"MT5 connection failed: {msg}"
except Exception as e:
    mt5_error = f"Could not fetch live MT5 data: {e}"

# ── IMPORT FROM MT5 (sidebar action) ─────────────────────────────────────────
with st.sidebar:
    st.header("Actions")
    days_back = st.number_input("Import days back", min_value=1, max_value=730, value=7)
    if st.button("📥 Import from MT5", use_container_width=True):
        ok, msg = mt5_client.ensure_connection(cfg)
        if not ok:
            st.error(msg)
        else:
            to_date = dt.datetime.now()
            from_date = to_date - dt.timedelta(days=int(days_back))
            deals_df = mt5_client.get_history_deals_df(from_date, to_date)
            closing_deals = deals_df[deals_df["Entry"] == 1] if not deals_df.empty else deals_df
            count = import_deals_as_entries(closing_deals)
            st.success(f"Imported {count} new closed trade(s).")
            st.rerun()

    if mt5_data:
        st.success(f"Showing {len(mt5_data)} live trades")
    elif mt5_error:
        st.error(mt5_error)
        st.info("Showing empty journal")

# Use MT5 data for the week
journal = mt5_data

# ── STATS ────────────────────────────────────────────────────────────────────
if not journal:
    st.info("No trades found for this week. Use the arrows to browse other weeks, or check your MT5 connection.")
    st.stop()

df = pd.DataFrame(journal)
df["date"] = pd.to_datetime(df["date"], errors="coerce")
df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
if "images" not in df.columns:
    df["images"] = [[] for _ in range(len(df))]
df["images"] = df["images"].apply(lambda v: v if isinstance(v, list) else [])
df["image_count"] = df["images"].apply(len)

df = df.sort_values("date", ascending=False).reset_index(drop=True)

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

# ── ENTRIES TABLE ────────────────────────────────────────────────────────────
st.subheader("Entries")

# Display table
display_columns = ["date", "asset", "direction", "lots", "entry_price", "exit_price", "pnl", "image_count", "notes"]
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

# ── INLINE EDIT PER ROW ──────────────────────────────────────────────────────
st.subheader("✏️ Edit Entries")

for idx, row in df.iterrows():
    entry_id = row["id"]
    
    # Build entry dict from row data (live MT5 data won't be in stored journal yet)
    entry = {
        "id": entry_id,
        "date": row["date"].strftime("%Y-%m-%d") if pd.notna(row["date"]) else dt.date.today().strftime("%Y-%m-%d"),
        "asset": row["asset"],
        "direction": row["direction"],
        "lots": row["lots"],
        "entry_price": row["entry_price"],
        "exit_price": row["exit_price"],
        "pnl": row["pnl"],
        "notes": row["notes"],
        "images": row["images"],
        "mt5_ticket": row.get("mt5_ticket"),
    }
    
    # Color-code the expander based on P/L
    pnl_color = "🟢" if row["pnl"] > 0 else "🔴" if row["pnl"] < 0 else "⚪"
    
    with st.expander(f"{pnl_color} {row['asset']} | {row['direction']} | {row['date'].strftime('%Y-%m-%d %H:%M') if pd.notna(row['date']) else 'N/A'} | P/L: ${row['pnl']:,.2f}", expanded=False):
        
        with st.form(f"edit_row_{entry_id}_{idx}"):
            try:
                default_date = dt.datetime.strptime(str(entry.get("date", "")), "%Y-%m-%d").date()
            except ValueError:
                default_date = dt.date.today()

            e1, e2, e3 = st.columns(3)
            date_edit = e1.date_input("Date", value=default_date, key=f"date_{entry_id}_{idx}")
            asset_edit = e2.text_input("Asset", value=entry.get("asset", ""), key=f"asset_{entry_id}_{idx}")
            direction_edit = e3.selectbox(
                "Direction",
                options=["Buy", "Sell"],
                index=0 if entry.get("direction") != "Sell" else 1,
                key=f"direction_{entry_id}_{idx}",
            )

            e4, e5, e6 = st.columns(3)
            lots_edit = e4.number_input(
                "Lots", min_value=0.0, step=0.01,
                value=float(entry.get("lots") or 0.0), key=f"lots_{entry_id}_{idx}",
            )
            entry_price_edit = e5.number_input(
                "Entry Price", min_value=0.0, step=0.00001, format="%.5f",
                value=float(entry.get("entry_price") or 0.0), key=f"entry_price_{entry_id}_{idx}",
            )
            exit_price_val = entry.get("exit_price")
            exit_price_edit = e6.number_input(
                "Exit Price", min_value=0.0, step=0.00001, format="%.5f",
                value=float(exit_price_val) if exit_price_val is not None else 0.0,
                key=f"exit_price_{entry_id}_{idx}",
            )

            pnl_edit = st.number_input(
                "P/L ($)", value=float(entry.get("pnl") or 0.0), step=0.01, key=f"pnl_{entry_id}_{idx}"
            )
            notes_edit = st.text_area(
                "Notes", value=entry.get("notes", ""), key=f"notes_{entry_id}_{idx}"
            )

            existing_images = entry.get("images") or []
            if existing_images:
                st.write("Current images (select any to remove):")
                remove_choices = st.multiselect(
                    "Remove image(s)",
                    options=[img["name"] for img in existing_images],
                    key=f"remove_images_{entry_id}_{idx}",
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
                key=f"new_images_{entry_id}_{idx}",
            )

            save_col, delete_col = st.columns(2)
            save_clicked = save_col.form_submit_button("💾 Save Changes", use_container_width=True)
            delete_clicked = delete_col.form_submit_button("🗑️ Delete Entry", use_container_width=True)

            if save_clicked:
                if not asset_edit.strip():
                    st.warning("Asset is required.")
                else:
                    kept_images = [img for img in existing_images if img["name"] not in remove_choices]
                    new_images = []
                    for uploaded in new_uploads or []:
                        record = encode_uploaded_image(uploaded)
                        if record is None:
                            st.warning(f"Skipped '{uploaded.name}' — over the 5 MB attachment limit.")
                        else:
                            new_images.append(record)

                    update_journal_entry(entry_id, {
                        "date": date_edit.strftime("%Y-%m-%d"),
                        "asset": asset_edit.strip(),
                        "direction": direction_edit,
                        "lots": lots_edit,
                        "entry_price": entry_price_edit,
                        "exit_price": exit_price_edit,
                        "pnl": pnl_edit,
                        "notes": notes_edit.strip(),
                        "images": kept_images + new_images,
                    })
                    st.success("Entry updated.")
                    st.rerun()

            if delete_clicked:
                remove_journal_entry(entry_id)
                st.success("Entry deleted.")
                st.rerun()