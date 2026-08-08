import json
import os
import time

from core import mt5_sync


def test_filter_assets_evaluates_margin_bias_and_trend(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "asset_snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            [
                {
                    "Asset": "BUY_OK",
                    "Min-Margin ($)": 100.0,
                    "Current Price": 10.5,
                    "Daily Close": 10.0,
                    "Daily Change": 0.2,
                    "Bias": {"M1": "BUY", "M5": "BUY", "M15": "BUY", "M30": "BUY"},
                },
                {
                    "Asset": "SELL_OK",
                    "Min-Margin ($)": 100.0,
                    "Current Price": 9.5,
                    "Daily Close": 10.0,
                    "Daily Change": -0.2,
                    "Bias": {"M1": "SELL", "M5": "SELL", "M15": "SELL", "M30": "SELL"},
                },
                {
                    "Asset": "MIXED",
                    "Min-Margin ($)": 100.0,
                    "Current Price": 10.5,
                    "Daily Close": 10.0,
                    "Daily Change": 0.2,
                    "Bias": {"M1": "BUY", "M5": "BUY", "M15": "SELL", "M30": "BUY"},
                },
                {
                    "Asset": "MARGIN_HIGH",
                    "Min-Margin ($)": 5000.0,
                    "Current Price": 10.5,
                    "Daily Close": 10.0,
                    "Daily Change": 0.2,
                    "Bias": {"M1": "BUY", "M5": "BUY", "M15": "BUY", "M30": "BUY"},
                },
                {
                    "Asset": "TREND_MISMATCH",
                    "Min-Margin ($)": 100.0,
                    "Current Price": 9.8,
                    "Daily Close": 10.0,
                    "Daily Change": 0.2,
                    "Bias": {"M1": "BUY", "M5": "BUY", "M15": "BUY", "M30": "BUY"},
                },
            ],
            indent=2,
        )
    )

    monkeypatch.setattr(mt5_sync, "SNAPSHOT_FILE", snapshot_path)

    result = mt5_sync.filter_assets(max_risk_cash=1000.0)

    assert result["eligible_assets"] == ["BUY_OK", "SELL_OK"]
    assert result["rejected_assets"] == ["MIXED", "MARGIN_HIGH", "TREND_MISMATCH"]


def _write_export(folder, symbol, *, price, daily_close, daily_change, bias, **extra):
    safe = mt5_sync._sanitize_symbol_for_filename(symbol)
    path = folder / f"asset_snapshot_{safe}.json"
    payload = {
        "Asset": symbol,
        "Current Price": price,
        "Daily Close": daily_close,
        "Daily Change": daily_change,
        "Bias": bias,
    }
    payload.update(extra)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_filter_rejects_legacy_mold_exports_without_sequential_bias(tmp_path):
    export_folder = tmp_path / "Files"
    export_folder.mkdir()

    _write_export(
        export_folder,
        "Volatility 100 Index",
        price=460.0,
        daily_close=450.0,
        daily_change=2.2,
        bias={"M1": "BUY", "M5": "BUY", "M15": "BUY", "M30": "BUY"},
    )
    _write_export(
        export_folder,
        "Boom 300 Index",
        price=14000.0,
        daily_close=14500.0,
        daily_change=-3.4,
        bias={"M1": "SELL", "M5": "SELL", "M15": "NEUT", "M30": "NEUT"},
        SequentialBias="SELL",
        Source="EMA_Ribbon_Bias_M1_M5",
    )
    _write_export(
        export_folder,
        "Volatility 25 (1s) Index",
        price=100.0,
        daily_close=99.0,
        daily_change=1.0,
        bias={"M1": "NEUT", "M5": "NEUT", "M15": "NEUT", "M30": "NEUT"},
        SequentialBias="NEUT",
        Source="EMA_Ribbon_Bias_M1_M5",
    )

    assets = [
        {"Asset": "Volatility 100 Index", "Min-Margin ($)": 0.5},
        {"Asset": "Boom 300 Index", "Min-Margin ($)": 0.5},
        {"Asset": "Volatility 25 (1s) Index", "Min-Margin ($)": 0.5},
        {"Asset": "Volatility 15 (1s) Index", "Min-Margin ($)": 0.5},
    ]

    result = mt5_sync.filter_assets_from_exports(
        assets, export_folder=export_folder, allow_live_mt5=False
    )

    assert result["eligible_assets"] == ["Boom 300 Index"]
    assert result["directions"]["Boom 300 Index"] == "SELL"
    assert result["reasons"]["Volatility 100 Index"] == "waiting for M1→M5 sequential export"
    assert result["reasons"]["Volatility 25 (1s) Index"] == "sequential bias not confirmed"
    assert result["reasons"]["Volatility 15 (1s) Index"] == "no bias data"


def test_filter_accepts_m1_m5_sequential_bias_export(tmp_path):
    export_folder = tmp_path / "Files"
    export_folder.mkdir()

    _write_export(
        export_folder,
        "Volatility 50 Index",
        price=90.0,
        daily_close=100.0,
        daily_change=-2.5,
        bias={"M1": "SELL", "M5": "SELL", "M15": "NEUT", "M30": "NEUT"},
        SequentialBias="SELL",
        PendingM1="NEUT",
        Source="EMA_Ribbon_Bias_M1_M5",
    )
    _write_export(
        export_folder,
        "Volatility 75 Index",
        price=110.0,
        daily_close=100.0,
        daily_change=1.5,
        bias={"M1": "BUY", "M5": "BUY", "M15": "NEUT", "M30": "NEUT"},
        SequentialBias="NEUT",
        PendingM1="BUY",
        Source="EMA_Ribbon_Bias_M1_M5",
    )

    assets = [
        {"Asset": "Volatility 50 Index", "Min-Margin ($)": 0.5},
        {"Asset": "Volatility 75 Index", "Min-Margin ($)": 0.5},
    ]
    result = mt5_sync.filter_assets_from_exports(
        assets, export_folder=export_folder, allow_live_mt5=False
    )

    assert result["eligible_assets"] == ["Volatility 50 Index"]
    assert result["directions"]["Volatility 50 Index"] == "SELL"
    assert result["reasons"]["Volatility 75 Index"] == "sequential bias not confirmed"

    details = mt5_sync.get_export_tf_biases(
        ["Volatility 50 Index", "Volatility 75 Index"],
        export_folder=export_folder,
        allow_live_mt5=False,
    )
    assert details["Volatility 50 Index"]["M1"] == "SELL"
    assert details["Volatility 50 Index"]["M5"] == "SELL"
    assert details["Volatility 75 Index"]["M1"] == "BUY"


def test_get_export_directions_returns_sequential_only(tmp_path):
    export_folder = tmp_path / "Files"
    export_folder.mkdir()
    _write_export(
        export_folder,
        "Jump 10 Index",
        price=90.0,
        daily_close=100.0,
        daily_change=-2.0,
        bias={"M1": "SELL", "M5": "SELL", "M15": "NEUT", "M30": "NEUT"},
        SequentialBias="SELL",
        Source="EMA_Ribbon_Bias_M1_M5",
    )
    _write_export(
        export_folder,
        "Jump 75 Index",
        price=110.0,
        daily_close=100.0,
        daily_change=1.0,
        bias={"M1": "BUY", "M5": "SELL", "M15": "BUY", "M30": "BUY"},
    )

    result = mt5_sync.get_export_directions(
        ["Jump 10 Index", "Jump 75 Index", "Missing Index"],
        export_folder=export_folder,
        allow_live_mt5=False,
    )

    assert result == {"Jump 10 Index": "SELL"}


def test_filter_assets_from_exports_discovers_folder(tmp_path, monkeypatch):
    export_folder = tmp_path / "Files"
    export_folder.mkdir()
    _write_export(
        export_folder,
        "Crash 500 Index",
        price=110.0,
        daily_close=100.0,
        daily_change=1.5,
        bias={"M1": "BUY", "M5": "BUY", "M15": "NEUT", "M30": "NEUT"},
        SequentialBias="BUY",
        Source="EMA_Ribbon_Bias_M1_M5",
    )

    monkeypatch.setattr(mt5_sync, "_discover_export_folder", lambda: export_folder)

    result = mt5_sync.filter_assets_from_exports(
        [{"Asset": "Crash 500 Index", "Min-Margin ($)": 0.1}],
        allow_live_mt5=False,
    )

    assert result["eligible_assets"] == ["Crash 500 Index"]
    assert result["export_folder"] == str(export_folder)


def test_stale_export_falls_through_to_live_without_sequential(tmp_path, monkeypatch):
    export_folder = tmp_path / "Files"
    export_folder.mkdir()
    _write_export(
        export_folder,
        "Jump 100 Index",
        price=240.0,
        daily_close=262.0,
        daily_change=-8.0,
        bias={"M1": "SELL", "M5": "SELL", "M15": "NEUT", "M30": "NEUT"},
        SequentialBias="SELL",
        Source="EMA_Ribbon_Bias_M1_M5",
    )
    path = export_folder / "asset_snapshot_Jump_100_Index.json"
    stale_mtime = time.time() - (mt5_sync.EXPORT_MAX_AGE_SECONDS + 60)
    os.utime(path, (stale_mtime, stale_mtime))

    live_snapshot = {
        "Asset": "Jump 100 Index",
        "Current Price": 245.0,
        "Daily Close": 262.0,
        "Daily Change": -6.5,
        "Bias": {"M1": "BUY", "M5": "SELL", "M15": "SELL", "M30": "SELL"},
    }
    monkeypatch.setattr(
        mt5_sync,
        "compute_live_bias_snapshot",
        lambda symbol: live_snapshot if symbol == "Jump 100 Index" else None,
    )

    result = mt5_sync.filter_assets_from_exports(
        [{"Asset": "Jump 100 Index", "Min-Margin ($)": 0.1}],
        export_folder=export_folder,
        allow_live_mt5=True,
    )

    assert "Jump 100 Index" in result["rejected_assets"]
    assert result["reasons"]["Jump 100 Index"] == "waiting for M1→M5 sequential export"
    assert result["bias_source"] == "live"
