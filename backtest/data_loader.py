"""
歷史價格資料載入。

本開發環境的網路出口政策僅放行 GitHub / npm / PyPI 等白名單網域,
Yahoo Finance、台灣證交所等行情來源目前無法直接連線抓取(已實測為 403)。
因此提供兩種資料來源:

1. generate_synthetic_ohlc(): 用幾何布朗運動(GBM)產生模擬 OHLC 資料,
   僅供在本環境驗證回測引擎邏輯是否跑得通,「不是真實歷史資料」。
2. load_yfinance(): 真實資料載入函式,需要在有網路存取權限的環境
   (自己的電腦、Colab、有出口白名單的伺服器等)先 `pip install yfinance`
   才能執行,可直接處理台股(.TW)、美股、加密貨幣(-USD)等三種標的。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def generate_synthetic_ohlc(
    start: str,
    periods: int,
    start_price: float,
    annual_drift: float,
    annual_vol: float,
    seed: int,
    freq: str = "B",
) -> pd.DataFrame:
    """用 GBM 模擬每日收盤價,再用日內雜訊組出 Open/High/Low,僅供示範用途。"""
    rng = np.random.default_rng(seed)
    dt = 1 / 252
    dates = pd.date_range(start=start, periods=periods, freq=freq)

    shocks = rng.normal(
        (annual_drift - 0.5 * annual_vol**2) * dt,
        annual_vol * np.sqrt(dt),
        size=periods,
    )
    close = start_price * np.exp(np.cumsum(shocks))

    intraday_range = np.abs(rng.normal(0, annual_vol * np.sqrt(dt) * 0.6, size=periods))
    open_ = np.empty(periods)
    open_[0] = start_price
    open_[1:] = close[:-1]

    high = np.maximum(open_, close) * (1 + intraday_range)
    low = np.minimum(open_, close) * (1 - intraday_range)

    df = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close},
        index=dates,
    )
    df.index.name = "Date"
    return df


def load_yfinance(ticker: str, start: str, end: str | None = None) -> pd.DataFrame:
    """
    載入真實歷史價格,需在具備網路存取權限的環境執行:

        pip install yfinance
        from backtest.data_loader import load_yfinance
        df = load_yfinance("2330.TW", "2019-01-01")   # 台股:台積電
        df = load_yfinance("SPY", "2019-01-01")         # 美股:SPY ETF
        df = load_yfinance("BTC-USD", "2019-01-01")     # 加密貨幣:比特幣

    常用代號對照:
        台股: 2330.TW(台積電)、0050.TW(元大台灣50)、2317.TW(鴻海)
        美股: SPY、QQQ、AAPL、TSLA
        加密貨幣: BTC-USD、ETH-USD、SOL-USD
    """
    import yfinance as yf

    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "High", "Low", "Close", "Volume"]]
