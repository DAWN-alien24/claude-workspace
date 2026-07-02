"""回測績效指標計算。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def performance_summary(equity: pd.Series, trades: pd.DataFrame, periods_per_year: int = 252) -> dict:
    equity = equity.dropna()
    returns = equity.pct_change().dropna()

    total_return = equity.iloc[-1] / equity.iloc[0] - 1
    n_years = len(equity) / periods_per_year
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / n_years) - 1 if n_years > 0 else np.nan

    running_max = equity.cummax()
    drawdown = equity / running_max - 1
    max_drawdown = drawdown.min()

    sharpe = (
        returns.mean() / returns.std() * np.sqrt(periods_per_year)
        if returns.std() > 0
        else np.nan
    )

    if len(trades) > 0:
        wins = trades[trades["pnl"] > 0]
        losses = trades[trades["pnl"] <= 0]
        win_rate = len(wins) / len(trades)
        profit_factor = (
            wins["pnl"].sum() / abs(losses["pnl"].sum())
            if len(losses) > 0 and losses["pnl"].sum() != 0
            else np.nan
        )
        avg_win = wins["pnl"].mean() if len(wins) > 0 else 0.0
        avg_loss = losses["pnl"].mean() if len(losses) > 0 else 0.0
    else:
        win_rate = np.nan
        profit_factor = np.nan
        avg_win = 0.0
        avg_loss = 0.0

    return {
        "起始權益": equity.iloc[0],
        "結束權益": equity.iloc[-1],
        "總報酬率": total_return,
        "年化報酬率(CAGR)": cagr,
        "最大回落(MaxDD)": max_drawdown,
        "年化夏普比率": sharpe,
        "交易筆數": len(trades),
        "勝率": win_rate,
        "獲利因子(Profit Factor)": profit_factor,
        "平均獲利": avg_win,
        "平均虧損": avg_loss,
    }


def format_summary(summary: dict) -> str:
    lines = []
    for key, value in summary.items():
        if isinstance(value, float):
            if "率" in key or "MaxDD" in key or "CAGR" in key:
                lines.append(f"{key}: {value:.2%}")
            else:
                lines.append(f"{key}: {value:,.2f}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)
