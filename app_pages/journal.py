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
journal = init_journal()

# 1. IMPORT FROM MT5
with st.expander("Import closed trades from MT5", expanded=False):
    col1, col2 = st.columns([3, 1])
    with col1:
        days_back = st.number_input("Days back", min_value=1, max_value=730, value=30)
    with col2:
        st.write("")
        st.write("")
        if st.button("Connect & Import", width="stretch"):
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

# 2. ADD MANUAL ENTRY
with st.expander("Add manual journal entry", expanded=False):
    watchlist_assets = sorted(load_watchlist())
    with st.form("add_journal_entry_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        date_val = c1.date_input("Date", value=dt.date.today())
        asset_val = c2.text_input(
            "Asset", placeholder=", ".join(watchlist_assets[:3]) if watchlist_assets else "e.g. Volatility 75 Index"
        )
        direction_val = c3.selectbox("Direction", options=["Buy", "Sell"])

        c4, c5, c6 = st.columns(3)
        lots_val = c4.number_input("Lots", min_value=0.0, step=0.01, value=0.01)
        entry_price_val = c5.number_input("Entry Price", min_value=0.0, step=0.00001, format="%.5f")
        exit_price_val = c6.number_input("Exit Price", min_value=0.0, step=0.00001, format="%.5f")

        pnl_val = st.number_input("P/L ($)", value=0.0, step=0.01)
        notes_val = st.text_area("Notes", placeholder="Setup, reasoning, lessons learned...")
        image_uploads = st.file_uploader(
            "Attach image(s) to notes",
            type=IMAGE_TYPES,
            accept_multiple_files=True,
            key="add_entry_images",
        )

        submitted = st.form_submit_button("Add Entry", width="stretch")
        if submitted:
            if not asset_val.strip():
                st.warning("Asset is required.")
            else:
                images = []
                for uploaded in image_uploads or []:
                    record = encode_uploaded_image(uploaded)
                    if record is None:
                        st.warning(f"Skipped '{uploaded.name}' — over the 5 MB attachment limit.")
                    else:
                        images.append(record)

                add_journal_entry({
                    "date": date_val.strftime("%Y-%m-%d"),
                    "asset": asset_val.strip(),
                    "direction": direction_val,
                    "lots": lots_val,
                    "entry_price": entry_price_val,
                    "exit_price": exit_price_val,
                    "pnl": pnl_val,
                    "notes": notes_val.strip(),
                    "images": images,
                })
                st.success("Entry added.")
                st.rerun()

st.divider()

# 3. FILTERS + TABLE + STATS
if not journal:
    st.info("No journal entries yet. Add one manually or import from MT5 above.")
    st.stop()

df = pd.DataFrame(journal)
df["date"] = pd.to_datetime(df["date"], errors="coerce")
df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
if "images" not in df.columns:
    df["images"] = [[] for _ in range(len(df))]
df["images"] = df["images"].apply(lambda v: v if isinstance(v, list) else [])
df["image_count"] = df["images"].apply(len)

assets_available = sorted(df["asset"].dropna().unique())
directions_available = sorted(df["direction"].dropna().unique())

f1, f2, f3 = st.columns(3)
with f1:
    asset_filter = st.multiselect("Filter by asset", options=assets_available, default=[])
with f2:
    direction_filter = st.multiselect("Filter by direction", options=directions_available, default=[])
with f3:
    date_range = st.date_input(
        "Date range",
        value=(df["date"].min().date(), df["date"].max().date()),
    )

df_filtered = df.copy()
if asset_filter:
    df_filtered = df_filtered[df_filtered["asset"].isin(asset_filter)]
if direction_filter:
    df_filtered = df_filtered[df_filtered["direction"].isin(direction_filter)]
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
    df_filtered = df_filtered[
        (df_filtered["date"].dt.date >= start_date) & (df_filtered["date"].dt.date <= end_date)
    ]

df_filtered = df_filtered.sort_values("date", ascending=False).reset_index(drop=True)

if df_filtered.empty:
    st.info("No journal entries match your filters.")
    st.stop()

total_trades = len(df_filtered)
win_trades = int((df_filtered["pnl"] > 0).sum())
loss_trades = int((df_filtered["pnl"] < 0).sum())
win_rate = (win_trades / total_trades * 100) if total_trades else 0.0
total_pnl = df_filtered["pnl"].sum()
avg_win = df_filtered.loc[df_filtered["pnl"] > 0, "pnl"].mean() if win_trades else 0.0
avg_loss = df_filtered.loc[df_filtered["pnl"] < 0, "pnl"].mean() if loss_trades else 0.0

s1, s2, s3, s4, s5 = st.columns(5)
s1.metric("Total Trades", total_trades)
s2.metric("Win Rate", f"{win_rate:.1f}%")
s3.metric("Net P/L", f"${total_pnl:,.2f}")
s4.metric("Avg Win", f"${avg_win:,.2f}")
s5.metric("Avg Loss", f"${avg_loss:,.2f}")

st.subheader("Entries")
display_columns = ["date", "asset", "direction", "lots", "entry_price", "exit_price", "pnl", "image_count", "notes"]
column_labels = {"image_count": "Images"}
row_height = 35
header_height = 38
table_height = min(len(df_filtered), 15) * row_height + header_height

table_key = f"journal_table_{len(df_filtered)}_{hash(tuple(asset_filter))}_{hash(tuple(direction_filter))}"

table_selection = st.dataframe(
    df_filtered[display_columns].rename(columns=column_labels),
    hide_index=True,
    width="stretch",
    height=table_height,
    on_select="rerun",
    selection_mode="single-row",
    key=table_key,
)

selected_rows = table_selection.selection.rows if table_selection.selection is not None else []
selected_id = None
if selected_rows:
    row_idx = selected_rows[0]
    if 0 <= row_idx < len(df_filtered):
        selected_id = df_filtered.iloc[row_idx]["id"]

action_col, _ = st.columns([2, 4])
with action_col:
    if st.button("🗑️ Delete selected entry", disabled=selected_id is None, width="stretch"):
        remove_journal_entry(selected_id)
        st.success("Entry deleted.")
        st.rerun()

# 4. EDIT SELECTED ENTRY (text + images)
if selected_id is not None:
    entry = get_journal_entry(selected_id)
    if entry is not None:
        st.divider()
        st.subheader(f"✏️ Edit Entry — {entry.get('asset', '')} ({entry.get('date', '')})")

        existing_images = entry.get("images") or []

        with st.form(f"edit_journal_form_{selected_id}"):
            try:
                default_date = dt.datetime.strptime(str(entry.get("date", "")), "%Y-%m-%d").date()
            except ValueError:
                default_date = dt.date.today()

            e1, e2, e3 = st.columns(3)
            date_edit = e1.date_input("Date", value=default_date, key=f"edit_date_{selected_id}")
            asset_edit = e2.text_input("Asset", value=entry.get("asset", ""), key=f"edit_asset_{selected_id}")
            direction_edit = e3.selectbox(
                "Direction",
                options=["Buy", "Sell"],
                index=0 if entry.get("direction") != "Sell" else 1,
                key=f"edit_direction_{selected_id}",
            )

            e4, e5, e6 = st.columns(3)
            lots_edit = e4.number_input(
                "Lots", min_value=0.0, step=0.01,
                value=float(entry.get("lots") or 0.0), key=f"edit_lots_{selected_id}",
            )
            entry_price_edit = e5.number_input(
                "Entry Price", min_value=0.0, step=0.00001, format="%.5f",
                value=float(entry.get("entry_price") or 0.0), key=f"edit_entry_price_{selected_id}",
            )
            exit_price_val = entry.get("exit_price")
            exit_price_edit = e6.number_input(
                "Exit Price", min_value=0.0, step=0.00001, format="%.5f",
                value=float(exit_price_val) if exit_price_val is not None else 0.0,
                key=f"edit_exit_price_{selected_id}",
            )

            pnl_edit = st.number_input(
                "P/L ($)", value=float(entry.get("pnl") or 0.0), step=0.01, key=f"edit_pnl_{selected_id}"
            )
            notes_edit = st.text_area(
                "Notes", value=entry.get("notes", ""), key=f"edit_notes_{selected_id}"
            )

            if existing_images:
                st.write("Current images (select any to remove):")
                remove_choices = st.multiselect(
                    "Remove image(s)",
                    options=[img["name"] for img in existing_images],
                    key=f"edit_remove_images_{selected_id}",
                    label_visibility="collapsed",
                )
                thumb_cols = st.columns(min(4, len(existing_images)))
                for i, img in enumerate(existing_images):
                    with thumb_cols[i % len(thumb_cols)]:
                        st.image(decode_image_bytes(img), caption=img["name"], width="stretch")
            else:
                remove_choices = []
                st.caption("No images attached yet.")

            new_uploads = st.file_uploader(
                "Add image(s) to notes",
                type=IMAGE_TYPES,
                accept_multiple_files=True,
                key=f"edit_new_images_{selected_id}",
            )

            save_col, cancel_col = st.columns(2)
            save_clicked = save_col.form_submit_button("💾 Save Changes", width="stretch")
            cancel_clicked = cancel_col.form_submit_button("Cancel", width="stretch")

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

                    update_journal_entry(selected_id, {
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

            if cancel_clicked:
                st.rerun()