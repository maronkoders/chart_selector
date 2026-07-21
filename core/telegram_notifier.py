"""Telegram notifications for profile watchlists."""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_FILE = Path(__file__).resolve().parent.parent / "telegram_notify_state.json"


def _read_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def get_telegram_settings(cfg: dict) -> dict[str, Any]:
    raw = cfg.get("telegram") or {}
    return {
        "enabled": bool(raw.get("enabled")),
        "bot_token": str(raw.get("bot_token") or "").strip(),
        "chat_id": str(raw.get("chat_id") or "").strip(),
        "refresh_interval_minutes": max(1, int(raw.get("refresh_interval_minutes") or 10)),
        "notify_on_unchanged": bool(raw.get("notify_on_unchanged", False)),
    }


def watchlist_fingerprint(rows: list[dict[str, Any]]) -> str:
    parts = []
    for row in rows:
        parts.append(
            "|".join(
                [
                    str(row.get("Asset") or ""),
                    str(row.get("Bias") or ""),
                    str(row.get("Min Lot") or ""),
                    str(row.get("Min-Margin ($)") or ""),
                ]
            )
        )
    payload = "\n".join(sorted(parts))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def format_watchlist_message(profile_name: str | None, rows: list[dict[str, Any]]) -> str:
    title = profile_name or "Active profile"
    if not rows:
        return f"<b>{_escape_html(title)}</b>\nNo watchlist assets right now."

    lines = [f"<b>{_escape_html(title)} — Watchlist ({len(rows)})</b>", ""]
    for row in rows:
        asset = _escape_html(str(row.get("Asset") or "?"))
        bias = _escape_html(str(row.get("Bias") or "—"))
        min_lot = row.get("Min Lot")
        min_margin = row.get("Min-Margin ($)")
        lot_txt = _escape_html(_fmt_number(min_lot))
        margin_txt = _escape_html(_fmt_money(min_margin))
        lines.append(f"<b>{asset}</b>")
        lines.append(f"Bias: {bias} · Min lot: {lot_txt} · Min margin: {margin_txt}")
        lines.append("")
    text = "\n".join(lines).strip()
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    return text


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> tuple[bool, str]:
    if not bot_token or not chat_id:
        return False, "Telegram bot token and chat id are required."

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    body = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return False, f"Telegram HTTP {exc.code}: {detail[:300]}"
    except urllib.error.URLError as exc:
        return False, f"Telegram request failed: {exc.reason}"
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"Telegram response error: {exc}"

    if not payload.get("ok"):
        return False, str(payload.get("description") or "Telegram API returned ok=false")
    return True, "sent"


def notify_watchlist(
    cfg: dict,
    profile_name: str | None,
    rows: list[dict[str, Any]],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Send Telegram message when watchlist has assets and content changed."""
    settings = get_telegram_settings(cfg)
    result: dict[str, Any] = {
        "enabled": settings["enabled"],
        "sent": False,
        "skipped": False,
        "reason": None,
        "error": None,
    }

    if not settings["enabled"]:
        result["reason"] = "disabled"
        return result
    if not rows:
        result["reason"] = "empty_watchlist"
        return result
    if not settings["bot_token"] or not settings["chat_id"]:
        result["reason"] = "missing_credentials"
        return result

    profile_key = profile_name or "_default"
    fingerprint = watchlist_fingerprint(rows)
    state = _read_state()
    prev = state.get(profile_key) or {}
    unchanged = prev.get("fingerprint") == fingerprint

    if unchanged and not force and not settings["notify_on_unchanged"]:
        result["skipped"] = True
        result["reason"] = "unchanged"
        return result

    message = format_watchlist_message(profile_name, rows)
    ok, detail = send_telegram_message(settings["bot_token"], settings["chat_id"], message)
    result["sent"] = ok
    if ok:
        state[profile_key] = {
            "fingerprint": fingerprint,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "asset_count": len(rows),
        }
        _write_state(state)
        result["reason"] = "sent"
    else:
        result["error"] = detail
        result["reason"] = "send_failed"
    return result


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _fmt_number(value: Any) -> str:
    if value is None:
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num == int(num):
        return str(int(num))
    return f"{num:g}"


def _fmt_money(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)
