"""Stop-loss / take-profit sizing from risk tolerance, plan TP%, and open positions.

Max cash at risk = balance × (risk% / 100).
Max cash at target = balance × (plan daily TP% / 100).

Each budget is split across open positions; each share converts to points via
the symbol's tick value, then to an SL or TP price on the adverse / favorable side.
"""
from __future__ import annotations


def max_cash_at_risk(account_balance: float, risk_percentage: float) -> float:
    return float(account_balance) * (float(risk_percentage) / 100.0)


def max_cash_at_target(account_balance: float, tp_percentage: float) -> float:
    """Daily profit budget from the active profile's trading-plan TP%."""
    return float(account_balance) * (float(tp_percentage) / 100.0)


def allocate_risk_cash(max_risk: float, n_positions: int) -> list[float]:
    """Equal cash split in cents so displayed amounts sum exactly to *max_risk*."""
    if n_positions <= 0 or max_risk <= 0:
        return [0.0] * max(0, n_positions)

    # Work in integer cents to avoid 1.295+1.295 → 2.58 after rounding.
    total_cents = int(round(max_risk * 100))
    base, rem = divmod(total_cents, n_positions)
    return [(base + (1 if i < rem else 0)) / 100.0 for i in range(n_positions)]


def value_per_point(tick_value: float, tick_size: float, point: float) -> float:
    """Account-currency profit for a 1-point move on 1.0 lot."""
    if tick_value <= 0 or tick_size <= 0 or point <= 0:
        return 0.0
    return tick_value * (point / tick_size)


def cash_to_sl_points(
    cash_risk: float,
    volume: float,
    tick_value: float,
    tick_size: float,
    point: float,
) -> float:
    """Points of adverse move that loses *cash_risk* for the given volume."""
    vpp = value_per_point(tick_value, tick_size, point)
    dollars_per_point = volume * vpp
    if cash_risk <= 0 or dollars_per_point <= 0:
        return 0.0
    return cash_risk / dollars_per_point


def sl_price_from_points(
    open_price: float,
    side: str,
    sl_points: float,
    point: float,
) -> float:
    """Suggested SL price from open price and SL distance in points."""
    distance = sl_points * point
    if str(side).lower().startswith("buy"):
        return open_price - distance
    return open_price + distance


def tp_price_from_points(
    open_price: float,
    side: str,
    tp_points: float,
    point: float,
) -> float:
    """Suggested TP price from open price and TP distance in points (favorable side)."""
    distance = tp_points * point
    if str(side).lower().startswith("buy"):
        return open_price + distance
    return open_price - distance


def build_position_sl_rows(
    positions: list[dict],
    max_risk: float,
    max_target: float | None = None,
) -> list[dict]:
    """Attach SL (and optional TP) cash / points / price to each position dict.

    Each input dict needs: Volume, Type, Open Price, tick_value, tick_size, point.
    Optional: digits (for rounding suggested prices).
    When *max_target* is set, also attaches TP Cash / TP Points / Suggested TP
    from the plan daily-profit budget (same equal-split rules as SL).
    """
    sl_shares = allocate_risk_cash(max_risk, len(positions))
    tp_shares = (
        allocate_risk_cash(max_target, len(positions))
        if max_target is not None
        else [None] * len(positions)
    )
    rows: list[dict] = []
    for pos, sl_cash, tp_cash in zip(positions, sl_shares, tp_shares):
        volume = float(pos.get("Volume") or 0)
        tick_value = float(pos.get("tick_value") or 0)
        tick_size = float(pos.get("tick_size") or 0)
        point = float(pos.get("point") or 0)
        open_price = float(pos.get("Open Price") or 0)
        side = str(pos.get("Type") or "Buy")
        digits = int(pos.get("digits") or 5)

        sl_points = cash_to_sl_points(sl_cash, volume, tick_value, tick_size, point)
        sl_price = (
            sl_price_from_points(open_price, side, sl_points, point) if sl_points > 0 else 0.0
        )

        row = dict(pos)
        row["SL Cash"] = round(sl_cash, 2)
        row["SL Points"] = round(sl_points, 1)
        row["Suggested SL"] = round(sl_price, digits) if sl_points > 0 else 0.0

        if tp_cash is not None:
            tp_points = cash_to_sl_points(tp_cash, volume, tick_value, tick_size, point)
            tp_price = (
                tp_price_from_points(open_price, side, tp_points, point) if tp_points > 0 else 0.0
            )
            row["TP Cash"] = round(tp_cash, 2)
            row["TP Points"] = round(tp_points, 1)
            row["Suggested TP"] = round(tp_price, digits) if tp_points > 0 else 0.0

        rows.append(row)
    return rows
