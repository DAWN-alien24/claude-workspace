"""
海龜策略示範回測:台股 / 美股 / 加密貨幣(三種標的皆使用「模擬資料」)。

由於本開發環境的網路出口政策不放行 Yahoo Finance 等行情資料來源,
這裡用幾何布朗運動模擬三種標的的價格走勢(波動率與趨勢強度取自各市場
的概略特性),藉此驗證海龜策略回測引擎的邏輯是否正確運作。

若要用「真實歷史資料」重跑,請在有網路存取權限的環境執行:

    pip install yfinance
    python backtest/run_demo.py --real

並可透過 --tw / --us / --crypto 參數指定代號,詳見 data_loader.load_yfinance()
的說明文件。
"""

from __future__ import annotations

import argparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

matplotlib.rcParams["font.sans-serif"] = ["WenQuanYi Zen Hei"]
matplotlib.rcParams["axes.unicode_minus"] = False

from data_loader import generate_synthetic_ohlc, load_yfinance
from metrics import format_summary, performance_summary
from turtle_engine import TurtleBacktester

OUTPUT_DIR = "output"

INSTRUMENTS_SYNTHETIC = {
    "台股(模擬,近似台積電走勢)": dict(
        start="2019-01-01", periods=252 * 5, start_price=500.0,
        annual_drift=0.12, annual_vol=0.28, seed=1, freq="B",
        periods_per_year=252, allow_short=True,
    ),
    "美股(模擬,近似大型科技股走勢)": dict(
        start="2019-01-01", periods=252 * 5, start_price=400.0,
        annual_drift=0.10, annual_vol=0.22, seed=2, freq="B",
        periods_per_year=252, allow_short=True,
    ),
    "加密貨幣(模擬,近似比特幣走勢)": dict(
        start="2019-01-01", periods=365 * 5, start_price=30000.0,
        annual_drift=0.20, annual_vol=0.65, seed=3, freq="D",
        periods_per_year=365, allow_short=True,
    ),
}

REAL_TICKERS = {
    "台股": "2330.TW",
    "美股": "SPY",
    "加密貨幣": "BTC-USD",
}


def run_one(name: str, df, periods_per_year: int, allow_short: bool, system: int = 2):
    bt = TurtleBacktester(df, initial_capital=1_000_000.0, system=system, allow_short=allow_short)
    equity = bt.run()
    trades = bt.trades_frame()
    summary = performance_summary(equity["equity"], trades, periods_per_year=periods_per_year)

    print(f"\n===== {name}(系統{system}: {'55/20 突破' if system == 2 else '20/10 突破'}) =====")
    print(format_summary(summary))

    safe_name = name.split("(")[0]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(equity.index, equity["equity"], linewidth=1.2)
    ax.set_title(f"{name} - 海龜策略權益曲線")
    ax.set_ylabel("帳戶權益")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(f"{OUTPUT_DIR}/{safe_name}_equity_curve.png", dpi=150)
    plt.close(fig)

    trades.to_csv(f"{OUTPUT_DIR}/{safe_name}_trades.csv", index=False, encoding="utf-8-sig")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true", help="使用 yfinance 抓取真實歷史資料(需要網路)")
    parser.add_argument("--system", type=int, default=2, choices=[1, 2], help="海龜系統一或系統二")
    args = parser.parse_args()

    import os
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    results = {}
    if args.real:
        for label, ticker in REAL_TICKERS.items():
            df = load_yfinance(ticker, start="2019-01-01")
            periods_per_year = 365 if label == "加密貨幣" else 252
            results[f"{label}({ticker})"] = run_one(
                f"{label}({ticker})", df, periods_per_year, allow_short=True, system=args.system
            )
    else:
        for name, params in INSTRUMENTS_SYNTHETIC.items():
            params = dict(params)
            periods_per_year = params.pop("periods_per_year")
            allow_short = params.pop("allow_short")
            df = generate_synthetic_ohlc(**params)
            results[name] = run_one(name, df, periods_per_year, allow_short, system=args.system)

    print("\n===== 三種標的績效總覽 =====")
    import pandas as pd
    summary_table = pd.DataFrame(results).T
    print(summary_table.to_string())
    summary_table.to_csv(f"{OUTPUT_DIR}/summary_table.csv", encoding="utf-8-sig")


if __name__ == "__main__":
    main()
