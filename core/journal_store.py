"""Trade journal persistence: manual entries plus import from MT5 history."""
import base64
import json
import uuid
from pathlib import Path

import streamlit as st

JOURNAL_FILE = Path(__file__).resolve().parent.parent / "journal.json"

# Keep attachments reasonable so journal.json doesn't balloon in size.
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB per image


def load_journal() -> list[dict]:
    if JOURNAL_FILE.exists():
        try:
            return json.loads(JOURNAL_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_journal(entries: list[dict]) -> None:
    JOURNAL_FILE.write_text(json.dumps(entries, indent=2, default=str), encoding="utf-8")


def init_journal() -> list[dict]:
    if "journal" not in st.session_state:
        st.session_state.journal = load_journal()
    return st.session_state.journal


def get_journal_entry(entry_id: str) -> dict | None:
    for entry in st.session_state.journal:
        if entry.get("id") == entry_id:
            return entry
    return None


def add_journal_entry(entry: dict) -> None:
    entry = dict(entry)
    entry["id"] = entry.get("id") or uuid.uuid4().hex[:8]
    entry.setdefault("images", [])
    st.session_state.journal.append(entry)
    save_journal(st.session_state.journal)


def update_journal_entry(entry_id: str, updates: dict) -> bool:
    for entry in st.session_state.journal:
        if entry.get("id") == entry_id:
            entry.update(updates)
            save_journal(st.session_state.journal)
            return True
    return False


def remove_journal_entry(entry_id: str) -> None:
    st.session_state.journal = [e for e in st.session_state.journal if e.get("id") != entry_id]
    save_journal(st.session_state.journal)


def encode_uploaded_image(uploaded_file) -> dict | None:
    """Converts a Streamlit UploadedFile into a JSON-serializable base64 record."""
    raw_bytes = uploaded_file.getvalue()
    if len(raw_bytes) > MAX_IMAGE_BYTES:
        return None
    return {
        "id": uuid.uuid4().hex[:8],
        "name": uploaded_file.name,
        "mime": uploaded_file.type or "image/png",
        "data": base64.b64encode(raw_bytes).decode("ascii"),
    }


def decode_image_bytes(image_record: dict) -> bytes:
    return base64.b64decode(image_record["data"])


def import_deals_as_entries(deals_df) -> int:
    """Imports closing MT5 deals into the journal, skipping ones already imported (by ticket)."""
    if deals_df is None or deals_df.empty:
        return 0

    existing_tickets = {
        e.get("mt5_ticket") for e in st.session_state.journal if e.get("mt5_ticket")
    }

    imported = 0
    for _, row in deals_df.iterrows():
        ticket = row.get("Ticket")
        if ticket in existing_tickets:
            continue
        entry = {
            "id": uuid.uuid4().hex[:8],
            "date": row["Time"].strftime("%Y-%m-%d %H:%M"),
            "asset": row["Symbol"],
            "direction": row["Type"],
            "lots": float(row["Volume"]),
            "entry_price": float(row["Price"]),
            "exit_price": None,
            "pnl": float(row["Profit"]),
            "notes": "Imported from MT5 history",
            "images": [],
            "mt5_ticket": int(ticket),
        }
        st.session_state.journal.append(entry)
        imported += 1

    if imported:
        save_journal(st.session_state.journal)
    return imported