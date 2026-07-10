import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import MetaTrader5 as mt5
else:
    try:
        import MetaTrader5 as mt5
    except ImportError:  # pragma: no cover - exercised in test environments without MT5
        mt5 = None

SNAPSHOT_FILE = Path(__file__).resolve().parent.parent / "asset_snapshot.json"
EXPORT_FILE_PREFIX = "asset_snapshot_"
EXPORT_FILE_SUFFIX = ".json"

# These constants are generic defaults for the MT5 custom indicator query.
# Update INDICATOR_PATH and buffer indexes if you use iCustom instead of file export.
INDICATOR_PATH = "MQL5\\Indicators\\DerivSyntheticExporter.ex5"
INDICATOR_PARAMS: tuple = ()
TIMEFRAME_M1 = 1
TIMEFRAME_M5 = 5
TIMEFRAME_M15 = 15
TIMEFRAME_M30 = 30
TIMEFRAME_D1 = 1440
INDICATOR_BUFFERS = {
    "daily_close": (TIMEFRAME_D1, 0),
    "daily_change": (TIMEFRAME_D1, 1),
    "M1": (TIMEFRAME_M1, 2),
    "M5": (TIMEFRAME_M5, 3),
    "M15": (TIMEFRAME_M15, 4),
    "M30": (TIMEFRAME_M30, 5),
}


def _sanitize_symbol_for_filename(symbol: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_\-]", "_", symbol)
    return safe


def _mt5_files_folder() -> Path | None:
    if mt5 is None:
        return None
    try:
        info = mt5.terminal_info()
        data_path = getattr(info, "data_path", None) or getattr(info, "path", None)
        if not data_path:
            return None
        return Path(data_path) / "MQL5" / "Files"
    except Exception:
        return None


def _discover_export_folder() -> Path | None:
    """Find the MT5 Files folder that contains MOLD_EMPIRE_EXPORTER snapshots."""
    connected = _mt5_files_folder()
    if connected is not None and connected.exists():
        if any(connected.glob(f"{EXPORT_FILE_PREFIX}*{EXPORT_FILE_SUFFIX}")):
            return connected

    terminals_root = Path.home() / "AppData" / "Roaming" / "MetaQuotes" / "Terminal"
    if terminals_root.exists():
        best: Path | None = None
        best_count = 0
        for files_dir in terminals_root.glob("*/MQL5/Files"):
            count = sum(1 for _ in files_dir.glob(f"{EXPORT_FILE_PREFIX}*{EXPORT_FILE_SUFFIX}"))
            if count > best_count:
                best = files_dir
                best_count = count
        if best is not None:
            return best

    return connected if connected is not None and connected.exists() else None


def _export_path_for_symbol(symbol: str, export_folder: Path) -> Path:
    safe_symbol = _sanitize_symbol_for_filename(symbol)
    return export_folder / f"{EXPORT_FILE_PREFIX}{safe_symbol}{EXPORT_FILE_SUFFIX}"


def _indicator_export_path(symbol: str) -> Path | None:
    folder = _discover_export_folder()
    if folder is None:
        return None
    return _export_path_for_symbol(symbol, folder)


def _load_json_dict(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        return None
    return None


def _load_exported_indicator_snapshot(symbol: str) -> dict | None:
    path = _indicator_export_path(symbol)
    if path is None or not path.exists():
        return None
    return _load_json_dict(path)


def _normalize_bias(value) -> str | None:
    if value is None:
        return None

    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in {"BUY", "SELL"}:
            return normalized
        return None

    if isinstance(value, (int, float)):
        if value > 0:
            return "BUY"
        if value < 0:
            return "SELL"

    return None


def _parse_optional_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "null", "none"}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_one_directional_bias(exported: dict) -> tuple[bool, str | None, str]:
    """Return (ok, direction, reason) for a MOLD_EMPIRE_EXPORTER snapshot.

    One-directional bias means M1/M5/M15/M30 are all BUY or all SELL, and
    daily change / price vs daily close confirm that same direction.
    """
    bias_map = exported.get("Bias") or {}
    normalized = {tf: _normalize_bias(bias_map.get(tf)) for tf in ("M1", "M5", "M15", "M30")}

    if any(v is None for v in normalized.values()):
        return False, None, "missing/neutral bias"

    unique = set(normalized.values())
    if len(unique) != 1:
        return False, None, "mixed timeframe biases"

    direction = unique.pop()
    current_price = _parse_optional_float(exported.get("Current Price"))
    daily_close = _parse_optional_float(exported.get("Daily Close"))
    daily_change = _parse_optional_float(exported.get("Daily Change"))

    if direction == "BUY":
        ok = (
            current_price is not None
            and daily_close is not None
            and daily_change is not None
            and current_price > daily_close
            and daily_change > 0
        )
    else:
        ok = (
            current_price is not None
            and daily_close is not None
            and daily_change is not None
            and current_price < daily_close
            and daily_change < 0
        )

    if ok:
        return True, direction, "aligned"
    return False, direction, "daily price/change not confirming bias"


def _ema_last(closes, period: int) -> float | None:
    if closes is None or len(closes) < period:
        return None
    # MT5 MODE_EMA: alpha = 2/(period+1), applied oldest → newest.
    alpha = 2.0 / (period + 1.0)
    value = float(closes[0])
    for price in closes[1:]:
        value = (float(price) - value) * alpha + value
    return value


def _timeframe_ema_bias(symbol: str, timeframe: int, fast: int = 50, slow: int = 110) -> str | None:
    """BUY/SELL/None from EMA fast vs slow on closed bars (same idea as MOLD_EMPIRE_EXPORTER)."""
    if mt5 is None:
        return None
    need = slow + 5
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 1, need)
    if rates is None or len(rates) < slow:
        return None
    closes = [float(r["close"]) for r in rates]
    fast_ema = _ema_last(closes, fast)
    slow_ema = _ema_last(closes, slow)
    if fast_ema is None or slow_ema is None:
        return None
    delta = fast_ema - slow_ema
    if delta > 0:
        return "BUY"
    if delta < 0:
        return "SELL"
    return None


def compute_live_bias_snapshot(symbol: str) -> dict | None:
    """Build an exporter-compatible snapshot from live MT5 rates (any broker)."""
    if mt5 is None:
        return None

    if not mt5.symbol_select(symbol, True):
        return None

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None

    current_price = float(tick.bid if tick.bid > 0 else tick.ask)
    prev_day = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 1, 1)
    if prev_day is None or len(prev_day) < 1:
        daily_close = None
        daily_change = None
    else:
        daily_close = float(prev_day[0]["close"])
        daily_change = (
            ((current_price - daily_close) / daily_close) * 100.0
            if daily_close > 0
            else None
        )

    bias = {
        "M1": _timeframe_ema_bias(symbol, mt5.TIMEFRAME_M1),
        "M5": _timeframe_ema_bias(symbol, mt5.TIMEFRAME_M5),
        "M15": _timeframe_ema_bias(symbol, mt5.TIMEFRAME_M15),
        "M30": _timeframe_ema_bias(symbol, mt5.TIMEFRAME_M30),
    }

    return {
        "Asset": symbol,
        "Current Price": current_price,
        "Daily Close": daily_close,
        "Daily Change": daily_change,
        "Bias": bias,
    }


def _load_bias_snapshot(
    symbol: str,
    export_folder: Path | None,
    allow_live_mt5: bool,
) -> tuple[dict | None, str]:
    """Return (snapshot, source) where source is 'export', 'live', or 'none'."""
    if export_folder is not None and export_folder.exists():
        path = _export_path_for_symbol(symbol, export_folder)
        if path.exists():
            exported = _load_json_dict(path)
            if exported:
                return exported, "export"

    if allow_live_mt5:
        live = compute_live_bias_snapshot(symbol)
        if live:
            return live, "live"

    return None, "none"


def get_export_directions(
    symbols: list[str],
    export_folder: str | Path | None = None,
    allow_live_mt5: bool = True,
) -> dict[str, str]:
    """Return {symbol: "BUY"|"SELL"} for assets with aligned one-directional bias.

    Prefers MOLD_EMPIRE_EXPORTER JSON when present; otherwise computes the same
    EMA/daily-change rules live from MT5 (works for Weltrade and other brokers).
    """
    if export_folder is not None:
        folder: Path | None = Path(export_folder)
    else:
        folder = _discover_export_folder()

    directions: dict[str, str] = {}
    for symbol in symbols:
        snapshot, _source = _load_bias_snapshot(symbol, folder, allow_live_mt5=allow_live_mt5)
        if not snapshot:
            continue
        ok, direction, _reason = _has_one_directional_bias(snapshot)
        if ok and direction:
            directions[symbol] = direction
    return directions


def get_indicator_snapshot(symbol: str) -> dict:
    """Read indicator data exported by the MT5 indicator from the terminal Files folder."""
    exported = _load_exported_indicator_snapshot(symbol)
    if exported:
        return {
            "daily_close": exported.get("Daily Close"),
            "daily_change": exported.get("Daily Change"),
            "bias": {
                "M1": _normalize_bias(exported.get("Bias", {}).get("M1")),
                "M5": _normalize_bias(exported.get("Bias", {}).get("M5")),
                "M15": _normalize_bias(exported.get("Bias", {}).get("M15")),
                "M30": _normalize_bias(exported.get("Bias", {}).get("M30")),
            },
        }

    if mt5 is None:
        return {
            "daily_close": None,
            "daily_change": None,
            "bias": {"M1": None, "M5": None, "M15": None, "M30": None},
        }

    try:
        def _fetch(timeframe: int, buffer: int):
            return mt5.iCustom(
                symbol,
                timeframe,
                INDICATOR_PATH,
                *INDICATOR_PARAMS,
                buffer,
                0,
            )

        raw_daily_close = _fetch(*INDICATOR_BUFFERS["daily_close"])
        raw_daily_change = _fetch(*INDICATOR_BUFFERS["daily_change"])
        bias = {
            timeframe: _normalize_bias(_fetch(*buffer_info))
            for timeframe, buffer_info in INDICATOR_BUFFERS.items()
            if timeframe not in {"daily_close", "daily_change"}
        }
        return {
            "daily_close": raw_daily_close,
            "daily_change": raw_daily_change,
            "bias": bias,
        }
    except Exception:
        return {
            "daily_close": None,
            "daily_change": None,
            "bias": {"M1": None, "M5": None, "M15": None, "M30": None},
        }


def load_asset_snapshot(snapshot_file: Path | None = None) -> list[dict]:
    target = snapshot_file or SNAPSHOT_FILE
    if not target.exists():
        return []

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    return data if isinstance(data, list) else []


def sync_assets(asset_data: list[dict], snapshot_file: Path | None = None) -> dict:
    snapshots = []
    skipped = []
    target = snapshot_file or SNAPSHOT_FILE

    if mt5 is None:
        return {"snapshots": [], "skipped": [], "error": "MetaTrader5 package not installed."}

    for asset in asset_data:
        symbol = asset.get("Asset")
        if not symbol:
            skipped.append({"asset": asset, "reason": "missing asset name"})
            continue

        if not mt5.symbol_select(symbol, True):
            skipped.append({"asset": symbol, "reason": "symbol_select failed"})
            continue

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            skipped.append({"asset": symbol, "reason": "no tick data"})
            continue

        indicator = get_indicator_snapshot(symbol)
        bias_values = indicator.get("bias") or {}

        snapshots.append({
            "Asset": symbol,
            "Min Lot": asset.get("Min Lot"),
            "Min-Margin ($)": asset.get("Min-Margin ($)"),
            "Volume Limit": asset.get("Volume Limit"),
            "Velocity (pips/min)": asset.get("Velocity (pips/min)"),
            "Pip Value ($/min)": asset.get("Pip Value ($/min)"),
            "Current Price": tick.bid,
            "Daily Close": indicator.get("daily_close"),
            "Daily Change": indicator.get("daily_change"),
            "Bias": {
                "M1": bias_values.get("M1"),
                "M5": bias_values.get("M5"),
                "M15": bias_values.get("M15"),
                "M30": bias_values.get("M30"),
            },
        })

        target.write_text(json.dumps(snapshots, indent=4), encoding="utf-8")
    return {"snapshots": snapshots, "skipped": skipped}


def filter_assets_from_exports(
    asset_data: list[dict],
    max_risk_cash: float | None = None,
    export_folder: str | Path | None = None,
    allow_live_mt5: bool = True,
) -> dict:
    """Filter assets by one-directional bias (exporter JSON and/or live MT5).

    Keeps assets with one-directional bias:
    - M1, M5, M15, M30 all BUY or all SELL
    - Daily change and price vs daily close confirm that direction

    Prefers per-symbol JSON exports from MOLD_EMPIRE_EXPORTER when available.
    When exports are missing (typical for Weltrade), computes the same rules
    live from MT5 EMA(50)/EMA(110) + daily change.

    Returns:
      {
        "eligible_assets": [...],
        "rejected_assets": [...],
        "reasons": {symbol: reason},
        "directions": {symbol: "BUY"|"SELL"},
        "export_folder": str | None,
        "bias_source": "export" | "live" | "mixed" | "none",
      }
    """
    eligible: list[str] = []
    rejected: list[str] = []
    reasons: dict[str, str] = {}
    directions: dict[str, str] = {}
    sources_used: set[str] = set()

    if export_folder is not None:
        folder: Path | None = Path(export_folder)
    else:
        folder = _discover_export_folder()

    for asset in asset_data:
        symbol = asset.get("Asset")
        if not symbol:
            continue

        min_margin = asset.get("Min-Margin ($)")
        try:
            margin_val = float(min_margin) if min_margin is not None else 0.0
        except (TypeError, ValueError):
            margin_val = 0.0

        if max_risk_cash is not None and margin_val > max_risk_cash:
            rejected.append(symbol)
            reasons[symbol] = "min margin exceeds max risk"
            continue

        snapshot, source = _load_bias_snapshot(
            symbol, folder, allow_live_mt5=allow_live_mt5
        )
        if not snapshot:
            rejected.append(symbol)
            reasons[symbol] = "no bias data"
            continue

        sources_used.add(source)
        ok, direction, reason = _has_one_directional_bias(snapshot)
        if direction:
            directions[symbol] = direction

        if ok:
            eligible.append(symbol)
        else:
            rejected.append(symbol)
            reasons[symbol] = reason

    if not sources_used:
        bias_source = "none"
    elif sources_used == {"export"}:
        bias_source = "export"
    elif sources_used == {"live"}:
        bias_source = "live"
    else:
        bias_source = "mixed"

    return {
        "eligible_assets": eligible,
        "rejected_assets": rejected,
        "reasons": reasons,
        "directions": directions,
        "export_folder": str(folder) if folder is not None else None,
        "bias_source": bias_source,
    }


def filter_assets(max_risk_cash: float | None = None, snapshot_file: Path | None = None) -> dict:
    snapshots = load_asset_snapshot(snapshot_file)
    eligible_assets = []
    rejected_assets = []

    for snapshot in snapshots:
        symbol = snapshot.get("Asset")
        if not symbol:
            continue

        margin_value = snapshot.get("Min-Margin ($)")
        try:
            margin = float(margin_value)
        except (TypeError, ValueError):
            margin = 0.0

        if max_risk_cash is not None and margin > max_risk_cash:
            rejected_assets.append(symbol)
            continue

        bias_map = snapshot.get("Bias") or {}
        normalized_biases = {
            timeframe: _normalize_bias(value)
            for timeframe, value in bias_map.items()
        }

        if any(value is None for value in normalized_biases.values()):
            rejected_assets.append(symbol)
            continue

        unique_biases = {value for value in normalized_biases.values() if value}
        if len(unique_biases) != 1:
            rejected_assets.append(symbol)
            continue

        bias = next(iter(unique_biases))
        try:
            current_price = float(snapshot.get("Current Price"))
        except (TypeError, ValueError):
            current_price = None

        try:
            daily_close = float(snapshot.get("Daily Close"))
        except (TypeError, ValueError):
            daily_close = None

        try:
            daily_change = float(snapshot.get("Daily Change"))
        except (TypeError, ValueError):
            daily_change = None

        if bias == "BUY":
            trend_confirmed = (
                current_price is not None
                and daily_close is not None
                and daily_change is not None
                and current_price > daily_close
                and daily_change > 0
            )
        else:
            trend_confirmed = (
                current_price is not None
                and daily_close is not None
                and daily_change is not None
                and current_price < daily_close
                and daily_change < 0
            )

        if trend_confirmed:
            eligible_assets.append(symbol)
        else:
            rejected_assets.append(symbol)

    return {
        "eligible_assets": eligible_assets,
        "rejected_assets": rejected_assets,
    }