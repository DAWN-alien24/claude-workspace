"""
海龜交易策略(Turtle Trading Strategy)回測引擎。

實作範圍:
- 唐奇安通道(Donchian Channel)突破進場,支援系統一(20/10)與系統二(55/20)
- 以 N 值(ATR)為基礎的部位規模計算,每筆風險約為帳戶權益的 1%
- 2N 停損、0.5N 金字塔加碼(最多 4 個單位),加碼後停損同步移動
- 逐日事件驅動模擬,單一標的多空皆可(是否允許放空由呼叫端決定)

這是教學/研究用的簡化實作,不含手續費、稅金、滑價、隔夜利息等交易成本模型,
使用前請先閱讀 backtest/README.md 的限制說明。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


N_PERIOD = 20            # 計算 N 值(ATR)的週期
MAX_UNITS = 4             # 最大加碼單位數
UNIT_ADD_STEP = 0.5        # 每 0.5N 加碼一個單位
STOP_LOSS_N = 2.0          # 停損距離(N 的倍數)
RISK_PER_UNIT = 0.01        # 每個單位承擔的帳戶權益風險比例


SYSTEMS = {
    1: {"entry": 20, "exit": 10},
    2: {"entry": 55, "exit": 20},
}


def compute_indicators(df: pd.DataFrame, system: int = 2) -> pd.DataFrame:
    """為 OHLC 資料加上 N 值(ATR)與唐奇安通道欄位。"""
    entry_period = SYSTEMS[system]["entry"]
    exit_period = SYSTEMS[system]["exit"]

    out = df.copy()
    prev_close = out["Close"].shift(1)
    true_range = pd.concat(
        [
            out["High"] - out["Low"],
            (out["High"] - prev_close).abs(),
            (out["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["N"] = true_range.rolling(N_PERIOD).mean()

    out["entry_high"] = out["High"].rolling(entry_period).max().shift(1)
    out["entry_low"] = out["Low"].rolling(entry_period).min().shift(1)
    out["exit_high"] = out["High"].rolling(exit_period).max().shift(1)
    out["exit_low"] = out["Low"].rolling(exit_period).min().shift(1)
    return out


@dataclass
class Trade:
    direction: str          # "long" 或 "short"
    entry_date: pd.Timestamp
    entry_price: float
    exit_date: pd.Timestamp | None = None
    exit_price: float | None = None
    units: int = 1
    shares: float = 0.0
    pnl: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.exit_date is None


@dataclass
class Position:
    direction: str
    unit_entries: list = field(default_factory=list)   # [(price, shares)]
    stop_price: float = 0.0
    last_n: float = 0.0

    @property
    def units(self) -> int:
        return len(self.unit_entries)

    @property
    def shares(self) -> float:
        return sum(s for _, s in self.unit_entries)

    @property
    def avg_price(self) -> float:
        total_shares = self.shares
        if total_shares == 0:
            return 0.0
        return sum(p * s for p, s in self.unit_entries) / total_shares


class TurtleBacktester:
    """單一標的的海龜策略事件驅動回測器。"""

    def __init__(
        self,
        df: pd.DataFrame,
        initial_capital: float = 1_000_000.0,
        system: int = 2,
        allow_short: bool = True,
        risk_per_unit: float = RISK_PER_UNIT,
    ):
        self.raw = df
        self.system = system
        self.data = compute_indicators(df, system=system)
        self.initial_capital = initial_capital
        self.allow_short = allow_short
        self.risk_per_unit = risk_per_unit

        self.cash = initial_capital
        self.position: Position | None = None
        self.trades: list[Trade] = []
        self.current_trade: Trade | None = None
        self.equity_curve: list[tuple] = []

    def _unit_size(self, price: float, n: float, equity: float) -> float:
        if n <= 0 or np.isnan(n):
            return 0.0
        risk_amount = equity * self.risk_per_unit
        shares = risk_amount / n
        # 避免部位金額超過帳戶權益(槓桿上限,簡化為 1 倍)
        max_shares_by_capital = equity / price if price > 0 else 0
        return max(0.0, min(shares, max_shares_by_capital))

    def _mark_to_market(self, price: float) -> float:
        if self.position is None:
            return self.cash
        direction_sign = 1 if self.position.direction == "long" else -1
        unrealized = direction_sign * (price - self.position.avg_price) * self.position.shares
        return self.cash + unrealized

    def _close_position(self, date, price: float):
        pos = self.position
        direction_sign = 1 if pos.direction == "long" else -1
        pnl = direction_sign * (price - pos.avg_price) * pos.shares
        self.cash += pnl
        self.current_trade.exit_date = date
        self.current_trade.exit_price = price
        self.current_trade.pnl = pnl
        self.current_trade.units = pos.units
        self.current_trade.shares = pos.shares
        self.trades.append(self.current_trade)
        self.current_trade = None
        self.position = None

    def _open_position(self, date, price: float, direction: str, n: float, equity: float):
        shares = self._unit_size(price, n, equity)
        if shares <= 0:
            return
        stop_price = price - STOP_LOSS_N * n if direction == "long" else price + STOP_LOSS_N * n
        self.position = Position(direction=direction, unit_entries=[(price, shares)], stop_price=stop_price, last_n=n)
        self.current_trade = Trade(direction=direction, entry_date=date, entry_price=price)

    def _add_unit(self, date, price: float, n: float, equity: float):
        pos = self.position
        shares = self._unit_size(price, n, equity)
        if shares <= 0:
            return
        pos.unit_entries.append((price, shares))
        pos.last_n = n
        pos.stop_price = (
            price - STOP_LOSS_N * n if pos.direction == "long" else price + STOP_LOSS_N * n
        )

    def run(self) -> pd.DataFrame:
        data = self.data
        for row in data.itertuples():
            date = row.Index
            n = row.N
            equity_before = self._mark_to_market(row.Close)

            if pd.isna(n) or pd.isna(row.entry_high) or pd.isna(row.entry_low):
                self.equity_curve.append((date, equity_before))
                continue

            if self.position is not None:
                pos = self.position
                # 1) 停損檢查(以當日最低/最高判斷是否觸發)
                stopped_out = (
                    (pos.direction == "long" and row.Low <= pos.stop_price)
                    or (pos.direction == "short" and row.High >= pos.stop_price)
                )
                if stopped_out:
                    self._close_position(date, pos.stop_price)
                else:
                    # 2) 唐奇安通道反向出場
                    exit_hit = (
                        (pos.direction == "long" and row.Low <= row.exit_low)
                        or (pos.direction == "short" and row.High >= row.exit_high)
                    )
                    if exit_hit:
                        exit_price = row.exit_low if pos.direction == "long" else row.exit_high
                        self._close_position(date, exit_price)
                    else:
                        # 3) 加碼檢查:價格朝有利方向再走 0.5N,且未達單位上限
                        last_price, _ = pos.unit_entries[-1]
                        add_threshold = (
                            last_price + UNIT_ADD_STEP * pos.last_n
                            if pos.direction == "long"
                            else last_price - UNIT_ADD_STEP * pos.last_n
                        )
                        can_add = (
                            pos.units < MAX_UNITS
                            and (
                                (pos.direction == "long" and row.High >= add_threshold)
                                or (pos.direction == "short" and row.Low <= add_threshold)
                            )
                        )
                        if can_add:
                            equity_now = self._mark_to_market(row.Close)
                            self._add_unit(date, add_threshold, n, equity_now)

            if self.position is None:
                equity_now = self._mark_to_market(row.Close)
                if row.High >= row.entry_high:
                    self._open_position(date, row.entry_high, "long", n, equity_now)
                elif self.allow_short and row.Low <= row.entry_low:
                    self._open_position(date, row.entry_low, "short", n, equity_now)

            equity_after = self._mark_to_market(row.Close)
            self.equity_curve.append((date, equity_after))

        # 若回測結束時仍有未平倉部位,以最後收盤價平倉結算
        if self.position is not None:
            last_close = data["Close"].iloc[-1]
            last_date = data.index[-1]
            self._close_position(last_date, last_close)
            self.equity_curve[-1] = (last_date, self.cash)

        equity_df = pd.DataFrame(self.equity_curve, columns=["date", "equity"]).set_index("date")
        return equity_df

    def trades_frame(self) -> pd.DataFrame:
        rows = [
            {
                "direction": t.direction,
                "entry_date": t.entry_date,
                "entry_price": t.entry_price,
                "exit_date": t.exit_date,
                "exit_price": t.exit_price,
                "units": t.units,
                "shares": t.shares,
                "pnl": t.pnl,
            }
            for t in self.trades
        ]
        return pd.DataFrame(rows)
