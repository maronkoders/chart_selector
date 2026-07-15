"""Per-profile \\volatile ratings and configurable option scales.

volatile.json shape:
{
  "by_profile": {
    "Weltrade": {
      "options": [{"label": "not", "operator": "<", "scale": 2.5}, ...],
      "ratings": {"Asset Name": "not", ...}
    },
    ...
  }
}

Legacy flat {options, ratings} files migrate under "_default". Profiles that
have not been saved yet inherit from "_default" (or built-in defaults) until
their first edit, which forks a profile-specific copy.
"""
from __future__ import annotations

import json
from pathlib import Path

VOLATILE_FILE = Path(__file__).resolve().parent.parent / "volatile.json"
DEFAULT_VOLATILE = ""
OPERATORS = ("<", "<=", ">", ">=", "=")
DEFAULT_PROFILE_KEY = "_default"

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


def _default_bucket() -> dict:
    return {
        "options": [dict(o) for o in DEFAULT_OPTIONS],
        "ratings": {},
    }


def _normalize_bucket(raw) -> dict:
    if not isinstance(raw, dict):
        return _default_bucket()
    options = []
    for item in raw.get("options") or []:
        opt = _normalize_option(item)
        if opt:
            options.append(opt)
    if not options:
        options = [dict(o) for o in DEFAULT_OPTIONS]
    labels = {o["label"] for o in options}
    ratings_raw = raw.get("ratings")
    if not isinstance(ratings_raw, dict):
        ratings_raw = {}
    ratings = {
        str(asset): str(value).strip().lower()
        for asset, value in ratings_raw.items()
        if str(value).strip().lower() in labels
    }
    return {"options": options, "ratings": ratings}


def _copy_bucket(bucket: dict) -> dict:
    return {
        "options": [dict(o) for o in bucket.get("options") or []],
        "ratings": dict(bucket.get("ratings") or {}),
    }


def _migrate_legacy_flat(data: dict) -> dict:
    """Treat a flat asset→rating map as ratings; seed default options."""
    option_labels = {o["label"] for o in DEFAULT_OPTIONS}
    ratings = {
        str(asset): str(value).strip().lower()
        for asset, value in data.items()
        if str(value).strip().lower() in option_labels
    }
    return {
        "by_profile": {
            DEFAULT_PROFILE_KEY: {
                "options": [dict(o) for o in DEFAULT_OPTIONS],
                "ratings": ratings,
            }
        }
    }


def _migrate_global_options_ratings(data: dict) -> dict:
    return {
        "by_profile": {
            DEFAULT_PROFILE_KEY: _normalize_bucket(data),
        }
    }


def _profile_key(profile_name: str | None) -> str:
    return profile_name or DEFAULT_PROFILE_KEY


def load_store() -> dict:
    if not VOLATILE_FILE.exists():
        return {"by_profile": {DEFAULT_PROFILE_KEY: _default_bucket()}}

    try:
        data = json.loads(VOLATILE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"by_profile": {DEFAULT_PROFILE_KEY: _default_bucket()}}

    if not isinstance(data, dict):
        return {"by_profile": {DEFAULT_PROFILE_KEY: _default_bucket()}}

    # New per-profile format
    if isinstance(data.get("by_profile"), dict):
        by_profile = {}
        for name, raw in data["by_profile"].items():
            by_profile[str(name)] = _normalize_bucket(raw)
        if not by_profile:
            by_profile[DEFAULT_PROFILE_KEY] = _default_bucket()
        return {"by_profile": by_profile}

    # Previous global {options, ratings}
    if "options" in data or "ratings" in data:
        return _migrate_global_options_ratings(data)

    # Oldest flat asset→rating map
    return _migrate_legacy_flat(data)


def save_store(store: dict) -> None:
    by_profile_in = store.get("by_profile")
    if not isinstance(by_profile_in, dict):
        by_profile_in = {}
    by_profile = {
        str(name): _normalize_bucket(raw) for name, raw in by_profile_in.items()
    }
    if not by_profile:
        by_profile[DEFAULT_PROFILE_KEY] = _default_bucket()
    payload = {"by_profile": by_profile}
    VOLATILE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _resolve_bucket(store: dict, profile_name: str | None) -> tuple[dict, str, bool]:
    """Return (bucket, storage_key, inherited).

    Inherited buckets come from ``_default`` (or built-ins) and must be forked
    on write into ``storage_key``.
    """
    by_profile = store.setdefault("by_profile", {})
    key = _profile_key(profile_name)
    if key in by_profile:
        return by_profile[key], key, False
    if DEFAULT_PROFILE_KEY in by_profile:
        return by_profile[DEFAULT_PROFILE_KEY], key, True
    return _default_bucket(), key, True


def _writable_bucket(store: dict, profile_name: str | None) -> dict:
    bucket, key, inherited = _resolve_bucket(store, profile_name)
    by_profile = store.setdefault("by_profile", {})
    if inherited or key not in by_profile:
        by_profile[key] = _copy_bucket(bucket)
    return by_profile[key]


def load_options(profile_name: str | None = None) -> list[dict]:
    store = load_store()
    bucket, _, _ = _resolve_bucket(store, profile_name)
    return [dict(o) for o in bucket["options"]]


def option_labels(
    options: list[dict] | None = None,
    profile_name: str | None = None,
) -> tuple[str, ...]:
    opts = options if options is not None else load_options(profile_name)
    return tuple(o["label"] for o in opts)


# Back-compat alias used by older call sites
def get_volatile_options(profile_name: str | None = None) -> tuple[str, ...]:
    return option_labels(profile_name=profile_name)


VOLATILE_OPTIONS = tuple(o["label"] for o in DEFAULT_OPTIONS)


def format_option_scale(opt: dict) -> str:
    return f"{opt['operator']}{opt['scale']:g}"


def value_matches_scale(value: float, operator: str, scale: float) -> bool:
    if operator == "<":
        return value < scale
    if operator == "<=":
        return value <= scale
    if operator == ">":
        return value > scale
    if operator == ">=":
        return value >= scale
    if operator == "=":
        return value == scale
    return False


def volatile_labels_for_account(
    account_size: float,
    options: list[dict] | None = None,
    profile_name: str | None = None,
) -> set[str]:
    """Pick the volatile label(s) whose scale the account size falls into.

    Upper-bound options (<, <=) are checked tightest-first so e.g. account 1.5
    with not<=2 and tiny<=8 resolves to ``not`` only. Equality options win when
    exact. Open-ended lower bounds (>, >=) are used when no upper band fits.
    """
    opts = options if options is not None else load_options(profile_name)
    if not opts:
        return set()

    for opt in opts:
        if opt["operator"] == "=" and value_matches_scale(
            account_size, opt["operator"], opt["scale"]
        ):
            return {opt["label"]}

    upper = sorted(
        (o for o in opts if o["operator"] in ("<", "<=")),
        key=lambda o: o["scale"],
    )
    for opt in upper:
        if value_matches_scale(account_size, opt["operator"], opt["scale"]):
            return {opt["label"]}

    return {
        opt["label"]
        for opt in opts
        if opt["operator"] in (">", ">=")
        and value_matches_scale(account_size, opt["operator"], opt["scale"])
    }


def load_volatile(profile_name: str | None = None) -> dict[str, str]:
    store = load_store()
    bucket, _, _ = _resolve_bucket(store, profile_name)
    return dict(bucket["ratings"])


def save_volatile(ratings: dict[str, str], profile_name: str | None = None) -> None:
    store = load_store()
    bucket = _writable_bucket(store, profile_name)
    bucket["ratings"] = ratings
    save_store(store)


def get_volatile(
    asset: str,
    ratings: dict[str, str] | None = None,
    profile_name: str | None = None,
) -> str:
    store_ratings = ratings if ratings is not None else load_volatile(profile_name)
    return store_ratings.get(asset, DEFAULT_VOLATILE)


def set_volatile(asset: str, value: str, profile_name: str | None = None) -> None:
    store = load_store()
    bucket = _writable_bucket(store, profile_name)
    labels = {o["label"] for o in bucket["options"]}
    value = (value or "").strip().lower()
    if value in labels:
        bucket["ratings"][asset] = value
    else:
        bucket["ratings"].pop(asset, None)
    save_store(store)


def apply_volatile_edits(
    edited_rows: dict[str, str],
    profile_name: str | None = None,
) -> None:
    """Merge edited asset→value pairs into the profile's JSON store."""
    store = load_store()
    bucket = _writable_bucket(store, profile_name)
    labels = {o["label"] for o in bucket["options"]}
    changed = False
    for asset, value in edited_rows.items():
        if not asset:
            continue
        value = (value or "").strip().lower()
        if value in labels:
            if bucket["ratings"].get(asset) != value:
                bucket["ratings"][asset] = value
                changed = True
        elif asset in bucket["ratings"]:
            del bucket["ratings"][asset]
            changed = True
    if changed:
        save_store(store)


def upsert_option(
    label: str,
    operator: str,
    scale: float,
    replace_label: str | None = None,
    profile_name: str | None = None,
) -> tuple[bool, str]:
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
    bucket = _writable_bucket(store, profile_name)
    options = bucket["options"]
    new_opt = {"label": label, "operator": operator, "scale": scale}

    if replace_label:
        replace_label = replace_label.strip().lower()
        idx = next((i for i, o in enumerate(options) if o["label"] == replace_label), None)
        if idx is None:
            return False, f"Option '{replace_label}' not found."
        if label != replace_label and any(o["label"] == label for o in options):
            return False, f"Option '{label}' already exists."
        options[idx] = new_opt
        if label != replace_label:
            for asset, rating in list(bucket["ratings"].items()):
                if rating == replace_label:
                    bucket["ratings"][asset] = label
    else:
        if any(o["label"] == label for o in options):
            return False, f"Option '{label}' already exists."
        options.append(new_opt)

    bucket["options"] = options
    save_store(store)
    return True, f"Saved option '{label}' ({format_option_scale(new_opt)})."


def delete_option(label: str, profile_name: str | None = None) -> tuple[bool, str]:
    label = (label or "").strip().lower()
    store = load_store()
    bucket = _writable_bucket(store, profile_name)
    before = len(bucket["options"])
    bucket["options"] = [o for o in bucket["options"] if o["label"] != label]
    if len(bucket["options"]) == before:
        return False, f"Option '{label}' not found."
    if not bucket["options"]:
        return False, "At least one volatile option is required."
    bucket["ratings"] = {
        asset: value
        for asset, value in bucket["ratings"].items()
        if value != label
    }
    save_store(store)
    return True, f"Deleted option '{label}'."


def save_options(
    options: list[dict],
    profile_name: str | None = None,
) -> tuple[bool, str]:
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
    bucket = _writable_bucket(store, profile_name)
    bucket["options"] = normalized
    save_store(store)
    return True, f"Saved {len(normalized)} option(s)."
