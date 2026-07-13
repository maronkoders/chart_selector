"""Per-asset \\volatile ratings and configurable option scales.

volatile.json shape:
{
  "options": [
    {"label": "not", "operator": "<", "scale": 2.5},
    ...
  ],
  "ratings": {"Asset Name": "not", ...}
}

Legacy flat {asset: rating} files are migrated on load.
"""
from __future__ import annotations

import json
from pathlib import Path

VOLATILE_FILE = Path(__file__).resolve().parent.parent / "volatile.json"
DEFAULT_VOLATILE = ""
OPERATORS = ("<", "<=", ">", ">=", "=")

DEFAULT_OPTIONS = [
    {"label": "not", "operator": "<", "scale": 2.5},
    {"label": "tiny", "operator": "<=", "scale": 5.0},
    {"label": "in-between", "operator": "<=", "scale": 7.5},
    {"label": "very", "operator": "=", "scale": 1.0},
]


def _normalize_option(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    label = str(raw.get("label", "")).strip().lower()
    if not label:
        return None
    op = str(raw.get("operator", "<=")).strip()
    if op not in OPERATORS:
        op = "<="
    try:
        scale = float(raw.get("scale", 0))
    except (TypeError, ValueError):
        scale = 0.0
    return {"label": label, "operator": op, "scale": scale}


def _default_store() -> dict:
    return {
        "options": [dict(o) for o in DEFAULT_OPTIONS],
        "ratings": {},
    }


def _migrate_legacy(data: dict) -> dict:
    """Treat a flat asset→rating map as ratings; seed default options."""
    option_labels = {o["label"] for o in DEFAULT_OPTIONS}
    ratings = {
        str(asset): str(value).strip().lower()
        for asset, value in data.items()
        if str(value).strip().lower() in option_labels
    }
    return {
        "options": [dict(o) for o in DEFAULT_OPTIONS],
        "ratings": ratings,
    }


def load_store() -> dict:
    if not VOLATILE_FILE.exists():
        return _default_store()
    try:
        data = json.loads(VOLATILE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default_store()
    if not isinstance(data, dict):
        return _default_store()

    # New format
    if "options" in data or "ratings" in data:
        options = []
        for raw in data.get("options") or []:
            opt = _normalize_option(raw)
            if opt:
                options.append(opt)
        if not options:
            options = [dict(o) for o in DEFAULT_OPTIONS]
        labels = {o["label"] for o in options}
        ratings_raw = data.get("ratings")
        if not isinstance(ratings_raw, dict):
            ratings_raw = {}
        ratings = {
            str(asset): str(value).strip().lower()
            for asset, value in ratings_raw.items()
            if str(value).strip().lower() in labels
        }
        return {"options": options, "ratings": ratings}

    # Legacy flat map
    return _migrate_legacy(data)


def save_store(store: dict) -> None:
    options = []
    for raw in store.get("options") or []:
        opt = _normalize_option(raw)
        if opt:
            options.append(opt)
    labels = {o["label"] for o in options}
    ratings = {
        str(asset): str(value).strip().lower()
        for asset, value in (store.get("ratings") or {}).items()
        if str(value).strip().lower() in labels
    }
    payload = {"options": options, "ratings": ratings}
    VOLATILE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_options() -> list[dict]:
    return load_store()["options"]


def option_labels(options: list[dict] | None = None) -> tuple[str, ...]:
    opts = options if options is not None else load_options()
    return tuple(o["label"] for o in opts)


# Back-compat alias used by older call sites
def get_volatile_options() -> tuple[str, ...]:
    return option_labels()


VOLATILE_OPTIONS = tuple(o["label"] for o in DEFAULT_OPTIONS)


def format_option_scale(opt: dict) -> str:
    return f"{opt['operator']}{opt['scale']:g}"


def load_volatile() -> dict[str, str]:
    return load_store()["ratings"]


def save_volatile(ratings: dict[str, str]) -> None:
    store = load_store()
    store["ratings"] = ratings
    save_store(store)


def get_volatile(asset: str, ratings: dict[str, str] | None = None) -> str:
    store_ratings = ratings if ratings is not None else load_volatile()
    return store_ratings.get(asset, DEFAULT_VOLATILE)


def set_volatile(asset: str, value: str) -> None:
    store = load_store()
    labels = {o["label"] for o in store["options"]}
    value = (value or "").strip().lower()
    if value in labels:
        store["ratings"][asset] = value
    else:
        store["ratings"].pop(asset, None)
    save_store(store)


def apply_volatile_edits(edited_rows: dict[str, str]) -> None:
    """Merge edited asset→value pairs into the JSON store."""
    store = load_store()
    labels = {o["label"] for o in store["options"]}
    changed = False
    for asset, value in edited_rows.items():
        if not asset:
            continue
        value = (value or "").strip().lower()
        if value in labels:
            if store["ratings"].get(asset) != value:
                store["ratings"][asset] = value
                changed = True
        elif asset in store["ratings"]:
            del store["ratings"][asset]
            changed = True
    if changed:
        save_store(store)


def upsert_option(label: str, operator: str, scale: float, replace_label: str | None = None) -> tuple[bool, str]:
    """Add or update an option. Returns (ok, message)."""
    label = (label or "").strip().lower()
    if not label:
        return False, "Label is required."
    if operator not in OPERATORS:
        return False, f"Operator must be one of: {', '.join(OPERATORS)}"
    try:
        scale = float(scale)
    except (TypeError, ValueError):
        return False, "Scale must be a number."

    store = load_store()
    options = store["options"]
    new_opt = {"label": label, "operator": operator, "scale": scale}

    if replace_label:
        replace_label = replace_label.strip().lower()
        idx = next((i for i, o in enumerate(options) if o["label"] == replace_label), None)
        if idx is None:
            return False, f"Option '{replace_label}' not found."
        # Renaming onto an existing different label
        if label != replace_label and any(o["label"] == label for o in options):
            return False, f"Option '{label}' already exists."
        options[idx] = new_opt
        if label != replace_label:
            for asset, rating in list(store["ratings"].items()):
                if rating == replace_label:
                    store["ratings"][asset] = label
    else:
        if any(o["label"] == label for o in options):
            return False, f"Option '{label}' already exists."
        options.append(new_opt)

    store["options"] = options
    save_store(store)
    return True, f"Saved option '{label}' ({format_option_scale(new_opt)})."


def delete_option(label: str) -> tuple[bool, str]:
    label = (label or "").strip().lower()
    store = load_store()
    before = len(store["options"])
    store["options"] = [o for o in store["options"] if o["label"] != label]
    if len(store["options"]) == before:
        return False, f"Option '{label}' not found."
    if not store["options"]:
        return False, "At least one volatile option is required."
    # Drop ratings that used the deleted label
    store["ratings"] = {
        asset: value
        for asset, value in store["ratings"].items()
        if value != label
    }
    save_store(store)
    return True, f"Deleted option '{label}'."


def save_options(options: list[dict]) -> tuple[bool, str]:
    """Replace the full options list (e.g. after bulk reorder/edit)."""
    normalized = []
    seen = set()
    for raw in options:
        opt = _normalize_option(raw)
        if not opt:
            continue
        if opt["label"] in seen:
            return False, f"Duplicate label '{opt['label']}'."
        seen.add(opt["label"])
        normalized.append(opt)
    if not normalized:
        return False, "At least one volatile option is required."
    store = load_store()
    store["options"] = normalized
    save_store(store)
    return True, f"Saved {len(normalized)} option(s)."
