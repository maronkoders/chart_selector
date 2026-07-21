"""Shared watchlist / bias-filter refresh for Dashboard and Indices Advisor."""
from __future__ import annotations

from typing import Any

from core.hidden_assets_store import save_hidden_assets
from core.mt5_sync import filter_assets_from_exports


def refresh_bias_filter(
    asset_data: list[dict],
    profile_name: str | None,
    *,
    allow_live_mt5: bool = True,
    persist_hidden: bool = True,
) -> dict[str, Any]:
    """Re-run one-directional bias filter and rebuild hidden set for a profile."""
    result = filter_assets_from_exports(asset_data, allow_live_mt5=allow_live_mt5)
    eligible = set(result.get("eligible_assets") or [])

    next_hidden: set[str] = set()
    for row in asset_data:
        name = row.get("Asset")
        if name and name not in eligible:
            next_hidden.add(str(name))

    directions = {
        asset: direction
        for asset, direction in (result.get("directions") or {}).items()
        if asset in eligible
    }

    if persist_hidden:
        save_hidden_assets(next_hidden, profile_name)

    return {
        "eligible": eligible,
        "hidden": next_hidden,
        "directions": directions,
        "rejected": list(result.get("rejected_assets") or []),
        "bias_source": result.get("bias_source", "none"),
        "export_folder": result.get("export_folder"),
    }


def build_watchlist_rows(
    asset_data: list[dict],
    hidden_assets: set[str],
    directions: dict[str, str],
) -> list[dict[str, Any]]:
    """Return watchlist rows: Asset, Bias, Min Lot, Min-Margin ($)."""
    rows: list[dict[str, Any]] = []
    for row in asset_data:
        if row.get("Suitable") != "🟢 Safe Size":
            continue
        asset = row.get("Asset")
        if not asset or asset in hidden_assets:
            continue
        rows.append(
            {
                "Asset": asset,
                "Bias": directions.get(asset) or "",
                "Min Lot": row.get("Min Lot"),
                "Min-Margin ($)": row.get("Min-Margin ($)"),
            }
        )
    rows.sort(key=lambda r: (float(r.get("Min-Margin ($)") or 0), str(r.get("Asset") or "")))
    return rows
