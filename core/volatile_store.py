"""Per-asset \\volatile ratings for the Indices Advisor watchlist.

Values: "very" | "in-between" | "not"
Stored flat in volatile.json keyed by asset name.
"""
import json
from pathlib import Path

VOLATILE_FILE = Path(__file__).resolve().parent.parent / "volatile.json"
VOLATILE_OPTIONS = ("very", "in-between", "not")
DEFAULT_VOLATILE = ""


def load_volatile() -> dict[str, str]:
    if not VOLATILE_FILE.exists():
        return {}
    try:
        data = json.loads(VOLATILE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(asset): value
        for asset, value in data.items()
        if value in VOLATILE_OPTIONS
    }


def save_volatile(ratings: dict[str, str]) -> None:
    cleaned = {
        asset: value
        for asset, value in ratings.items()
        if value in VOLATILE_OPTIONS
    }
    VOLATILE_FILE.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")


def get_volatile(asset: str, ratings: dict[str, str] | None = None) -> str:
    store = ratings if ratings is not None else load_volatile()
    return store.get(asset, DEFAULT_VOLATILE)


def set_volatile(asset: str, value: str) -> None:
    ratings = load_volatile()
    if value in VOLATILE_OPTIONS:
        ratings[asset] = value
    else:
        ratings.pop(asset, None)
    save_volatile(ratings)


def apply_volatile_edits(edited_rows: dict[str, str]) -> None:
    """Merge edited asset→value pairs into the JSON store."""
    ratings = load_volatile()
    changed = False
    for asset, value in edited_rows.items():
        if not asset:
            continue
        if value in VOLATILE_OPTIONS:
            if ratings.get(asset) != value:
                ratings[asset] = value
                changed = True
        elif asset in ratings:
            del ratings[asset]
            changed = True
    if changed:
        save_volatile(ratings)
