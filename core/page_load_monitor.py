"""Full-page load gate + JSON timing log for Streamlit page switches.

Shows a blocking overlay (dimmed page, spinner) while bootstrap work runs,
then records elapsed time in page_load_times.json.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import streamlit as st
import streamlit.components.v1 as components

PAGE_LOAD_LOG_FILE = Path(__file__).resolve().parent.parent / "page_load_times.json"
MAX_VISITS_KEPT = 200

_OVERLAY_SHOW_HTML = """
<script>
(function () {
  const doc = window.parent.document;
  let el = doc.getElementById("cs-page-load-blocker");
  if (!el) {
    el = doc.createElement("div");
    el.id = "cs-page-load-blocker";
    el.innerHTML = `
      <div class="cs-plb-card">
        <div class="cs-plb-spinner"></div>
        <div class="cs-plb-title">Loading page…</div>
        <div class="cs-plb-sub" id="cs-plb-sub">Please wait — UI is locked until ready</div>
      </div>`;
    const style = doc.createElement("style");
    style.id = "cs-page-load-blocker-style";
    style.textContent = `
      #cs-page-load-blocker {
        position: fixed; inset: 0; z-index: 2147483646;
        background: rgba(15, 23, 42, 0.62);
        backdrop-filter: blur(2px);
        display: flex; align-items: center; justify-content: center;
        pointer-events: all; cursor: wait;
        font-family: system-ui, -apple-system, Segoe UI, sans-serif;
      }
      #cs-page-load-blocker .cs-plb-card {
        background: #0f172a; color: #e2e8f0;
        border: 1px solid rgba(148,163,184,0.35);
        border-radius: 12px; padding: 28px 32px; min-width: 280px;
        text-align: center; box-shadow: 0 16px 48px rgba(0,0,0,0.35);
      }
      #cs-page-load-blocker .cs-plb-title { font-size: 1.05rem; font-weight: 600; margin-top: 14px; }
      #cs-page-load-blocker .cs-plb-sub { font-size: 0.85rem; color: #94a3b8; margin-top: 6px; }
      #cs-page-load-blocker .cs-plb-spinner {
        width: 36px; height: 36px; margin: 0 auto;
        border: 3px solid rgba(148,163,184,0.25);
        border-top-color: #38bdf8; border-radius: 50%;
        animation: cs-plb-spin 0.8s linear infinite;
      }
      @keyframes cs-plb-spin { to { transform: rotate(360deg); } }
    `;
    doc.head.appendChild(style);
    doc.body.appendChild(el);
  }
  const sub = doc.getElementById("cs-plb-sub");
  if (sub) sub.textContent = %SUB%;
  el.style.display = "flex";
})();
</script>
"""

_OVERLAY_HIDE_HTML = """
<script>
(function () {
  const doc = window.parent.document;
  const el = doc.getElementById("cs-page-load-blocker");
  if (el) el.style.display = "none";
})();
</script>
"""


def load_page_timings() -> dict:
    if not PAGE_LOAD_LOG_FILE.exists():
        return {"visits": [], "summary": {}}
    try:
        data = json.loads(PAGE_LOAD_LOG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"visits": [], "summary": {}}
    if not isinstance(data, dict):
        return {"visits": [], "summary": {}}
    data.setdefault("visits", [])
    data.setdefault("summary", {})
    return data


def save_page_timings(data: dict) -> None:
    PAGE_LOAD_LOG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def record_page_load(
    page: str,
    *,
    started_at: dt.datetime,
    elapsed_ms: float,
    ok: bool = True,
    detail: str | None = None,
) -> dict:
    data = load_page_timings()
    visit = {
        "page": page,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": dt.datetime.now().isoformat(timespec="seconds"),
        "elapsed_ms": round(elapsed_ms, 1),
        "elapsed_sec": round(elapsed_ms / 1000.0, 3),
        "ok": bool(ok),
        "detail": detail or "",
    }
    visits = list(data.get("visits") or [])
    visits.append(visit)
    data["visits"] = visits[-MAX_VISITS_KEPT:]

    summary = data.setdefault("summary", {})
    page_sum = summary.setdefault(
        page,
        {"count": 0, "total_ms": 0.0, "avg_ms": 0.0, "last_ms": 0.0, "min_ms": None, "max_ms": None},
    )
    page_sum["count"] = int(page_sum.get("count") or 0) + 1
    page_sum["total_ms"] = float(page_sum.get("total_ms") or 0) + elapsed_ms
    page_sum["avg_ms"] = round(page_sum["total_ms"] / page_sum["count"], 1)
    page_sum["last_ms"] = round(elapsed_ms, 1)
    prev_min = page_sum.get("min_ms")
    prev_max = page_sum.get("max_ms")
    page_sum["min_ms"] = round(elapsed_ms if prev_min is None else min(float(prev_min), elapsed_ms), 1)
    page_sum["max_ms"] = round(elapsed_ms if prev_max is None else max(float(prev_max), elapsed_ms), 1)
    page_sum["last_at"] = visit["finished_at"]
    data["updated_at"] = visit["finished_at"]
    save_page_timings(data)
    return visit


def _show_overlay(message: str) -> None:
    safe = json.dumps(message)
    components.html(_OVERLAY_SHOW_HTML.replace("%SUB%", safe), height=0)


def _hide_overlay() -> None:
    components.html(_OVERLAY_HIDE_HTML, height=0)


class PageLoadState:
    """Mutable result bag filled inside page_bootstrap()."""

    def __init__(self, page: str):
        self.page = page
        self.ok = True
        self.detail = ""


@contextmanager
def page_bootstrap(page: str, message: str | None = None) -> Iterator[PageLoadState]:
    """Block the UI with a full-page overlay while the page bootstraps.

    Usage::

        with page_bootstrap("Dashboard") as boot:
            ok, msg = mt5_client.ensure_connection(cfg)
            boot.ok = ok
            boot.detail = msg
        # interactive UI below
    """
    state = PageLoadState(page)
    started_at = dt.datetime.now()
    t0 = time.perf_counter()
    _show_overlay(message or f"Loading {page}…")
    try:
        with st.spinner(message or f"Loading {page}…"):
            yield state
    except Exception as exc:
        state.ok = False
        state.detail = str(exc)
        raise
    finally:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        try:
            record_page_load(
                page,
                started_at=started_at,
                elapsed_ms=elapsed_ms,
                ok=state.ok,
                detail=state.detail,
            )
        except Exception:
            pass
        try:
            _hide_overlay()
        except Exception:
            pass


def recent_visits(limit: int = 20) -> list[dict[str, Any]]:
    data = load_page_timings()
    visits = list(data.get("visits") or [])
    return list(reversed(visits[-limit:]))


def summary_table_rows() -> list[dict[str, Any]]:
    data = load_page_timings()
    rows = []
    for page, stats in sorted((data.get("summary") or {}).items()):
        if not isinstance(stats, dict):
            continue
        rows.append({
            "Page": page,
            "Visits": int(stats.get("count") or 0),
            "Avg (s)": round(float(stats.get("avg_ms") or 0) / 1000.0, 3),
            "Last (s)": round(float(stats.get("last_ms") or 0) / 1000.0, 3),
            "Min (s)": round(float(stats["min_ms"]) / 1000.0, 3) if stats.get("min_ms") is not None else None,
            "Max (s)": round(float(stats["max_ms"]) / 1000.0, 3) if stats.get("max_ms") is not None else None,
            "Last at": stats.get("last_at") or "",
        })
    return rows
