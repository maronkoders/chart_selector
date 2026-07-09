"""Per-trade annotations (notes + image attachments) keyed by MT5 ticket.

Trade facts (date, asset, direction, lots, entry price, P/L) always come
live from MT5 and are never stored here. This module only persists the
notes and image attachments a user adds to a given trade — functionally a
foreign-key table: entries_description(mt5_ticket FK, notes, images[]).
"""
import base64
import json
import os
import uuid
from pathlib import Path

import streamlit as st

from core.config import get_screenshot_folder

ENTRIES_DESCRIPTION_FILE = Path("entries_description.json")
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB limit for base64 fallback

EMPTY_DESCRIPTION = {"notes": "", "images": []}


# ── ANNOTATIONS (notes + images), keyed by mt5_ticket ───────────────────────

def init_entries_description() -> dict:
    """Loads {ticket_str: {"notes": str, "images": [...]}} from disk once per session."""
    if "entries_description" not in st.session_state:
        if ENTRIES_DESCRIPTION_FILE.exists():
            try:
                data = json.loads(ENTRIES_DESCRIPTION_FILE.read_text(encoding="utf-8"))
                st.session_state.entries_description = data if isinstance(data, dict) else {}
            except (json.JSONDecodeError, OSError):
                st.session_state.entries_description = {}
        else:
            st.session_state.entries_description = {}
    return st.session_state.entries_description


def _save_entries_description() -> None:
    ENTRIES_DESCRIPTION_FILE.write_text(
        json.dumps(st.session_state.entries_description, indent=2), encoding="utf-8"
    )


def get_entry_description(ticket) -> dict:
    """Returns {"notes": str, "images": [...]} for this ticket (empty default if none saved yet)."""
    init_entries_description()
    saved = st.session_state.entries_description.get(str(ticket))
    if saved is None:
        return dict(EMPTY_DESCRIPTION)
    return {"notes": saved.get("notes", ""), "images": saved.get("images", [])}


def save_entry_description(ticket, notes: str, images: list) -> None:
    """Upserts the notes/images for a ticket — this is the only write path
    for journal data now, so a save here always sticks (no separate
    'is this a new row or existing row' branching needed).
    """
    init_entries_description()
    st.session_state.entries_description[str(ticket)] = {"notes": notes, "images": images}
    _save_entries_description()


def clear_entry_description(ticket) -> None:
    """Removes the annotation for a ticket and deletes any associated image files on disk."""
    init_entries_description()
    key = str(ticket)
    existing = st.session_state.entries_description.get(key)
    if existing:
        for img in existing.get("images", []):
            path = img.get("path")
            if path and os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
    st.session_state.entries_description.pop(key, None)
    _save_entries_description()


# ── IMAGE HELPERS (unchanged behavior — annotations own their images) ───────

def _sanitize_filename(text: str) -> str:
    safe = text.strip().replace(" ", "_")
    unsafe = '\\/:*?"<>|'
    for ch in unsafe:
        safe = safe.replace(ch, "")
    return safe


def _build_image_filename(asset: str, direction: str, pnl: float, ext: str = "png") -> str:
    safe_asset = _sanitize_filename(asset)
    safe_dir = _sanitize_filename(direction).lower()
    pnl_str = f"{pnl:+.2f}"
    return f"{safe_asset}_{safe_dir}_{pnl_str}.{ext}"


def _get_screenshot_dir() -> Path | None:
    cfg = st.session_state.get("app_config", {})
    folder = get_screenshot_folder(cfg)
    if folder and os.path.isdir(folder):
        return Path(folder)
    return None


def _ensure_screenshot_dir() -> Path:
    configured = _get_screenshot_dir()
    if configured:
        return configured
    return Path(".")  # fallback: save next to entries_description.json


def encode_uploaded_image(uploaded_file, asset: str = None, direction: str = None, pnl: float = None) -> dict | None:
    """Saves an uploaded image to the screenshot folder and returns metadata.
    Falls back to inline base64 if the folder isn't writable.
    """
    raw = uploaded_file.read()
    if len(raw) > MAX_IMAGE_BYTES:
        return None

    orig_name = uploaded_file.name
    ext = Path(orig_name).suffix.lstrip(".").lower()
    if ext not in ("png", "jpg", "jpeg", "gif", "webp"):
        ext = "png"

    screenshot_dir = _ensure_screenshot_dir()

    if asset and direction is not None and pnl is not None:
        contextual_name = _build_image_filename(asset, direction, pnl, ext)
        dest_path = screenshot_dir / contextual_name
        if dest_path.exists():
            stem = dest_path.stem
            suffix = dest_path.suffix
            short_id = uuid.uuid4().hex[:6]
            dest_path = screenshot_dir / f"{stem}_{short_id}{suffix}"
    else:
        dest_path = screenshot_dir / f"{uuid.uuid4().hex}.{ext}"

    try:
        with open(dest_path, "wb") as f:
            f.write(raw)
    except OSError as e:
        st.warning(f"Could not save image to disk ({e}); falling back to inline storage.")
        return {
            "name": orig_name,
            "data": base64.b64encode(raw).decode("utf-8"),
            "mime": uploaded_file.type,
            "inline": True,
        }

    return {
        "name": dest_path.name,
        "path": str(dest_path),
        "mime": uploaded_file.type,
        "inline": False,
    }


def decode_image_bytes(img_record: dict) -> bytes:
    if img_record.get("inline"):
        return base64.b64decode(img_record["data"])
    path = img_record.get("path")
    if path and os.path.isfile(path):
        return Path(path).read_bytes()
    data = img_record.get("data")
    if data:
        return base64.b64decode(data)
    return b""