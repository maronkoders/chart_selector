"""Price Velocity ("Summed Realized Candle Velocity") calculations.

Formula (per timeframe TF, N = closed candles since the start of the
trading day up to the most recently closed candle):

    Velocity(TF) = ( |PrevDayClose - Open_1| + sum_i |Open_i - Close_i| )
                   / (N * TF_minutes)

For D1, the minute multiplier is dropped per the spec — the result is
expressed as pips/day over a multi-day lookback window instead of
pips/minute over a single session.

This module is split into:
  - `_velocity_core`: pure math, no MT5 dependency, easy to unit test.
  - `compute_price_velocity` / `compute_velocity_matrix`: MT5 data-fetch
    wrappers that call into `_velocity_core`.
"""
import datetime as dt

import MetaTrader5 as mt5
import pandas as pd

TIMEFRAME_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "D1": 1440}

MT5_TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "D1": mt5.TIMEFRAME_D1,
}

DEFAULT_MATRIX_TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "D1"]
DEFAULT_D1_LOOKBACK_DAYS = 20


def _velocity_core(prev_reference_close: float, opens: list[float], closes: list[float], divisor: float) -> dict:
    """Pure calculation — no MT5 calls. `opens`/`closes` are the N closed
    candles for the session/window, in chronological order.
    """
    n = len(opens)
    if n == 0 or divisor <= 0:
        return {"n": n, "total_pips": 0.0, "velocity": None}

    gap = abs(prev_reference_close - opens[0])
    body_sum = sum(abs(o - c) for o, c in zip(opens, closes))
    total_pips = gap + body_sum

    return {"n": n, "total_pips": total_pips, "velocity": total_pips / divisor}


def _get_previous_closed_daily_close(symbol: str) -> float | None:
    """Most recently fully-closed D1 candle's close (i.e. "yesterday")."""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 1, 1)
    if rates is None or len(rates) == 0:
        return None
    return float(rates[0]["close"])


def compute_price_velocity(symbol: str, timeframe_label: str, d1_lookback_days: int = DEFAULT_D1_LOOKBACK_DAYS) -> dict | None:
    """Returns a dict with n, total_pips, elapsed_minutes, velocity, unit — or None if
    there isn't enough data yet (e.g. market just opened, no closed candles today).
    """
    if timeframe_label not in TIMEFRAME_MINUTES:
        raise ValueError(f"Unknown timeframe: {timeframe_label}")

    tf_minutes = TIMEFRAME_MINUTES[timeframe_label]
    mt5_tf = MT5_TIMEFRAME_MAP[timeframe_label]

    if timeframe_label == "D1":
        # pos=1 skips today's still-forming daily candle; fetch one extra
        # candle to anchor the initial gap.
        rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 1, d1_lookback_days + 1)
        if rates is None or len(rates) < 2:
            return None

        df = pd.DataFrame(rates).sort_values("time").reset_index(drop=True)
        anchor_close = float(df.iloc[0]["close"])
        window = df.iloc[1:]

        result = _velocity_core(
            anchor_close,
            window["open"].astype(float).tolist(),
            window["close"].astype(float).tolist(),
            divisor=len(window),
        )
        result.update({
            "symbol": symbol,
            "timeframe": timeframe_label,
            "elapsed_minutes": None,
            "unit": "pips/day",
        })
        return result

    prev_day_close = _get_previous_closed_daily_close(symbol)
    if prev_day_close is None:
        return None

    now = dt.datetime.now()
    day_start = dt.datetime.combine(now.date(), dt.time.min)

    rates = mt5.copy_rates_range(symbol, mt5_tf, day_start, now)
    if rates is None or len(rates) == 0:
        return None

    df = pd.DataFrame(rates).sort_values("time").reset_index(drop=True)

    # Drop the currently-forming (not yet closed) candle, if present.
    last_open_time = pd.to_datetime(df.iloc[-1]["time"], unit="s")
    if last_open_time + pd.Timedelta(minutes=tf_minutes) > pd.Timestamp(now):
        df = df.iloc[:-1]

    if df.empty:
        return {
            "symbol": symbol,
            "timeframe": timeframe_label,
            "n": 0,
            "total_pips": 0.0,
            "elapsed_minutes": 0,
            "velocity": None,
            "unit": "pips/min",
        }

    result = _velocity_core(
        prev_day_close,
        df["open"].astype(float).tolist(),
        df["close"].astype(float).tolist(),
        divisor=len(df) * tf_minutes,
    )
    result.update({
        "symbol": symbol,
        "timeframe": timeframe_label,
        "elapsed_minutes": len(df) * tf_minutes,
        "unit": "pips/min",
    })
    return result


def compute_velocity_matrix(symbol: str, timeframes: list[str] | None = None) -> list[dict]:
    timeframes = timeframes or DEFAULT_MATRIX_TIMEFRAMES
    matrix = []
    for tf_label in timeframes:
        result = compute_price_velocity(symbol, tf_label)
        if result is None:
            matrix.append({
                "symbol": symbol,
                "timeframe": tf_label,
                "n": 0,
                "total_pips": None,
                "elapsed_minutes": None,
                "velocity": None,
                "unit": "pips/day" if tf_label == "D1" else "pips/min",
            })
        else:
            matrix.append(result)
    return matrix