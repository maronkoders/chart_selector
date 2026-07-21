from core.telegram_notifier import (
    format_watchlist_message,
    notify_watchlist,
    watchlist_fingerprint,
)


def test_format_watchlist_message_includes_asset_fields():
    text = format_watchlist_message(
        "Main",
        [
            {
                "Asset": "Volatility 10 Index",
                "Bias": "BUY",
                "Min Lot": 0.35,
                "Min-Margin ($)": 0.12,
            }
        ],
    )
    assert "Main — Watchlist (1)" in text
    assert "Volatility 10 Index" in text
    assert "Bias: BUY" in text
    assert "Min lot: 0.35" in text
    assert "Min margin: $0.12" in text


def test_watchlist_fingerprint_changes_when_bias_changes():
    rows_a = [{"Asset": "Jump 10 Index", "Bias": "BUY", "Min Lot": 0.5, "Min-Margin ($)": 1.0}]
    rows_b = [{"Asset": "Jump 10 Index", "Bias": "SELL", "Min Lot": 0.5, "Min-Margin ($)": 1.0}]
    assert watchlist_fingerprint(rows_a) != watchlist_fingerprint(rows_b)


def test_notify_watchlist_skips_when_disabled():
    cfg = {"telegram": {"enabled": False, "bot_token": "x", "chat_id": "1"}}
    result = notify_watchlist(cfg, "Main", [{"Asset": "A", "Bias": "BUY", "Min Lot": 1, "Min-Margin ($)": 1}])
    assert result["reason"] == "disabled"
    assert result["sent"] is False
