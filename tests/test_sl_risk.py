"""Unit tests for risk-based SL / plan-based TP sizing (no MT5 required)."""
from core.sl_risk import (
    allocate_risk_cash,
    build_position_sl_rows,
    cash_to_sl_points,
    max_cash_at_risk,
    max_cash_at_target,
    sl_price_from_points,
    tp_price_from_points,
)


def test_max_cash_matches_example():
    # $5.12 account @ 50.5% → $2.5856 ≈ $2.59 displayed
    assert abs(max_cash_at_risk(5.12, 50.5) - 2.5856) < 1e-9
    assert round(max_cash_at_risk(5.12, 50.5), 2) == 2.59


def test_max_cash_at_target_matches_plan_pct():
    assert abs(max_cash_at_target(10.0, 40.0) - 4.0) < 1e-9
    assert round(max_cash_at_target(0.88, 100.0), 2) == 0.88


def test_allocate_sums_to_budget():
    for n in (1, 2, 3, 5):
        shares = allocate_risk_cash(2.59, n)
        assert len(shares) == n
        assert abs(sum(shares) - 2.59) < 1e-9
        assert all(round(s, 2) == s for s in shares)


def test_cash_to_sl_points_single_position():
    # tick_value $0.01 per tick of size 0.01 → $1 per 1.0 price unit per lot
    # point = 0.01 → $0.01 per point per lot; 0.2 lot → $0.002 per point
    # $2.59 risk → 1295 points
    points = cash_to_sl_points(
        cash_risk=2.59,
        volume=0.2,
        tick_value=0.01,
        tick_size=0.01,
        point=0.01,
    )
    assert abs(points - 1295.0) < 1e-6


def test_sl_price_buy_and_sell():
    assert sl_price_from_points(1000.0, "Buy", 100.0, 0.01) == 999.0
    assert sl_price_from_points(1000.0, "Sell", 100.0, 0.01) == 1001.0


def test_tp_price_buy_and_sell():
    assert tp_price_from_points(1000.0, "Buy", 100.0, 0.01) == 1001.0
    assert tp_price_from_points(1000.0, "Sell", 100.0, 0.01) == 999.0


def test_multi_position_sl_cash_sums_to_max_risk():
    max_risk = 2.59
    positions = [
        {
            "Ticket": 1,
            "Symbol": "A",
            "Type": "Buy",
            "Volume": 0.1,
            "Open Price": 100.0,
            "tick_value": 0.01,
            "tick_size": 0.01,
            "point": 0.01,
            "digits": 2,
        },
        {
            "Ticket": 2,
            "Symbol": "B",
            "Type": "Sell",
            "Volume": 0.2,
            "Open Price": 200.0,
            "tick_value": 0.01,
            "tick_size": 0.01,
            "point": 0.01,
            "digits": 2,
        },
    ]
    rows = build_position_sl_rows(positions, max_risk)
    assert sum(r["SL Cash"] for r in rows) == max_risk
    assert all(r["SL Points"] > 0 for r in rows)
    assert all("Suggested TP" not in r for r in rows)


def test_multi_position_tp_from_plan_budget():
    max_risk = 2.59
    max_target = 4.0
    positions = [
        {
            "Ticket": 1,
            "Symbol": "A",
            "Type": "Buy",
            "Volume": 0.1,
            "Open Price": 100.0,
            "tick_value": 0.01,
            "tick_size": 0.01,
            "point": 0.01,
            "digits": 2,
        },
        {
            "Ticket": 2,
            "Symbol": "B",
            "Type": "Sell",
            "Volume": 0.2,
            "Open Price": 200.0,
            "tick_value": 0.01,
            "tick_size": 0.01,
            "point": 0.01,
            "digits": 2,
        },
    ]
    rows = build_position_sl_rows(positions, max_risk, max_target=max_target)
    assert sum(r["SL Cash"] for r in rows) == max_risk
    assert abs(sum(r["TP Cash"] for r in rows) - max_target) < 1e-9
    assert all(r["TP Points"] > 0 for r in rows)
    # Buy TP above open; Sell TP below open
    assert rows[0]["Suggested TP"] > rows[0]["Open Price"]
    assert rows[1]["Suggested TP"] < rows[1]["Open Price"]
    # Favorable side is opposite of SL
    assert rows[0]["Suggested TP"] > rows[0]["Suggested SL"]
    assert rows[1]["Suggested TP"] < rows[1]["Suggested SL"]
