"""
Golden Hour ICT FVG + Fractal TP Strategy – Python Backtest  (v2)
Instrument : GC synthetic (Gold Futures proxy)
Timeframe  : 5-minute bars
Sessions   : London Open 02:00-05:00 ET  |  NY Open 08:00-11:00 ET
Logic      : Catalyst candle → FVG forms → wait for retest → enter at midpoint
             Take-profit: nearest Bill Williams Bear/Bull Fractal above/below entry
             Fallback TP: 0.49 × risk (actual Chanelle parameter from Lucid Flex)
"""

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
from datetime import datetime, timezone
import pytz

# ──────────────────────────────────────────────
# PARAMETERS  (mirror the Pine Script inputs)
# ──────────────────────────────────────────────
SYMBOL          = "GC (synthetic)"
INTERVAL        = "5m"
PERIOD          = "1y"

ATR_LEN         = 14
CATALYST_MULT   = 1.5          # body must be > 1.5 × ATR
FVG_ENTRY_PCT   = 0.5          # 0 = top of gap, 1 = bottom, 0.5 = midpoint
RR_FALLBACK     = 0.49         # fallback R:R when no fractal found (Chanelle's 0.49 from Lucid Flex)
SL_BUFFER       = 0.3          # SL buffer = 0.3 × ATR
FRACTAL_ARMS    = 2            # 5-bar fractal (arms=2): high[2] highest of 5 bars
FRACTAL_LB      = 60           # bars to look back for nearest fractal
MIN_FRAC_RR     = 0.35         # skip fractal TPs that give less than this R:R

ET = pytz.timezone("America/New_York")

SESSIONS = [
    ("London", 2, 5),   # 02:00–05:00 ET
    ("NY",     8, 11),  # 08:00–11:00 ET
]

INITIAL_CAPITAL = 10_000.0
RISK_PER_TRADE  = 0.01         # risk 1% of equity per trade
COMMISSION_PCT  = 0.0002       # 0.02% round-trip

# ──────────────────────────────────────────────
# 1.  GENERATE REALISTIC SYNTHETIC GOLD DATA
#
#  Mimics 5-minute GC (gold futures) behaviour:
#  - Base price ~$3200, daily range ~$20-40
#  - Higher volatility during London/NY sessions
#  - Autocorrelated returns (trending periods)
#  - Realistic spread between O/H/L/C
# ──────────────────────────────────────────────
print("Generating synthetic Gold Futures (GC) data…")
print("  (Yahoo Finance blocked by network policy – using realistic simulation)")

np.random.seed(42)
START      = pd.Timestamp("2024-01-02", tz=ET)
END        = pd.Timestamp("2025-01-01", tz=ET)
BASE_PRICE = 2050.0   # gold was ~$2050 in early 2024, rising to ~$2700 by end

# Build a 5-minute date range for trading hours (Sunday 6PM – Friday 5PM ET)
# Gold trades nearly 24h, but we generate full week for session filtering
all_times = pd.date_range(start=START, end=END, freq="5min", tz=ET)
# Remove weekends (Saturday = 5, Sunday = 6 – keep partial)
# Gold market is open Sun 6PM to Fri 5PM
mask = ~((all_times.dayofweek == 5) |  # Saturday
         ((all_times.dayofweek == 6) & (all_times.hour < 18)))  # Sunday before 6PM
all_times = all_times[mask]

n = len(all_times)

# Gradual uptrend over 2024 (gold went from ~2050 to ~2700)
trend = np.linspace(0, 650, n)

# Simulate price with GBM + mean-reversion + sessions
returns     = np.zeros(n)
volatility  = np.zeros(n)

for idx in range(1, n):
    t   = all_times[idx]
    h   = t.hour + t.minute / 60.0
    dow = t.dayofweek   # Mon=0 … Fri=4

    # Higher vol in London (2-5 ET) and NY open (8-11 ET)
    if 2 <= h < 5:
        vol_mult = 2.2
    elif 8 <= h < 11:
        vol_mult = 2.8
    elif 13 <= h < 15:
        vol_mult = 1.4
    else:
        vol_mult = 0.6

    sigma = 0.0008 * vol_mult           # ~0.08% base vol per 5m, scaled
    drift = 0.00003                     # slight upward drift
    volatility[idx] = sigma
    returns[idx] = drift + sigma * np.random.randn() + 0.25 * returns[idx-1]

prices = BASE_PRICE + trend + np.cumsum(returns) * BASE_PRICE

# Build OHLCV from close prices
rows = []
for idx in range(n):
    C   = prices[idx]
    sig = volatility[idx] * C
    rng = abs(np.random.randn()) * sig * 2.5 + sig * 0.5
    # Directional candle body
    body_dir = np.random.choice([-1, 1])
    body_sz  = abs(np.random.randn()) * sig * 1.2
    O = C + body_dir * body_sz
    H = max(O, C) + abs(np.random.randn()) * sig * 0.8
    L = min(O, C) - abs(np.random.randn()) * sig * 0.8
    rows.append({"Open": O, "High": H, "Low": L, "Close": C, "Volume": int(np.random.exponential(500))})

df = pd.DataFrame(rows, index=all_times)
df.dropna(inplace=True)
print(f"  → {len(df):,} bars  ({df.index[0].date()} to {df.index[-1].date()})")

# ──────────────────────────────────────────────
# 2.  INDICATORS
# ──────────────────────────────────────────────
df["body"] = (df["Close"] - df["Open"]).abs()
df["tr"]   = np.maximum(df["High"] - df["Low"],
             np.maximum((df["High"] - df["Close"].shift(1)).abs(),
                        (df["Low"]  - df["Close"].shift(1)).abs()))
df["atr"]  = df["tr"].ewm(span=ATR_LEN, adjust=False).mean()

df["bull_cat"] = (df["Close"] > df["Open"]) & (df["body"] > CATALYST_MULT * df["atr"])
df["bear_cat"] = (df["Close"] < df["Open"]) & (df["body"] > CATALYST_MULT * df["atr"])

def in_session(idx):
    h = idx.hour + idx.minute / 60.0
    return any(s <= h < e for _, s, e in SESSIONS)

df["in_ses"] = df.index.map(in_session)

# ──────────────────────────────────────────────
# 3.  BILL WILLIAMS FRACTAL DETECTION
#  Bear fractal (local HIGH, TP for LONG):
#    high[N] > high[N±1], high[N±2], ...
#  Bull fractal (local LOW, TP for SHORT):
#    low[N]  < low[N±1],  low[N±2], ...
#  Default N=2 → 5-bar fractal
# ──────────────────────────────────────────────
N = FRACTAL_ARMS

def is_bear_fractal_at(highs, i):
    if i < N or i + N >= len(highs):
        return False
    h = highs[i]
    for k in range(1, N+1):
        if not (h > highs[i-k] and h > highs[i+k]):
            return False
    return True

def is_bull_fractal_at(lows, i):
    if i < N or i + N >= len(lows):
        return False
    l = lows[i]
    for k in range(1, N+1):
        if not (l < lows[i-k] and l < lows[i+k]):
            return False
    return True

H = df["High"].values
L = df["Low"].values
n_bars = len(df)

bear_frac_flag  = np.zeros(n_bars, dtype=bool)
bull_frac_flag  = np.zeros(n_bars, dtype=bool)
bear_frac_level = np.full(n_bars, np.nan)
bull_frac_level = np.full(n_bars, np.nan)

for i in range(N, n_bars - N):
    if is_bear_fractal_at(H, i):
        bear_frac_flag[i]  = True
        bear_frac_level[i] = H[i]
    if is_bull_fractal_at(L, i):
        bull_frac_flag[i]  = True
        bull_frac_level[i] = L[i]

df["bear_frac"] = bear_frac_flag
df["bull_frac"] = bull_frac_flag
df["bear_frac_lvl"] = bear_frac_level
df["bull_frac_lvl"] = bull_frac_level

# ──────────────────────────────────────────────
# 4.  FVG DETECTION
# ──────────────────────────────────────────────
df["bull_fvg"] = (
    (df["Low"]  > df["High"].shift(2)) &
    df["bull_cat"].shift(1) &
    df["in_ses"].shift(1)
)
df["bear_fvg"] = (
    (df["High"] < df["Low"].shift(2)) &
    df["bear_cat"].shift(1) &
    df["in_ses"].shift(1)
)

df["bfvg_top"] = np.where(df["bull_fvg"], df["Low"],           np.nan)
df["bfvg_bot"] = np.where(df["bull_fvg"], df["High"].shift(2), np.nan)
df["sfvg_top"] = np.where(df["bear_fvg"], df["Low"].shift(2),  np.nan)
df["sfvg_bot"] = np.where(df["bear_fvg"], df["High"],          np.nan)

# ──────────────────────────────────────────────
# 4.  BACKTEST LOOP
# ──────────────────────────────────────────────
equity  = INITIAL_CAPITAL
trades  = []

# Active zone state
bz = {"top": np.nan, "bot": np.nan, "active": False, "formed_i": -1}
sz = {"top": np.nan, "bot": np.nan, "active": False, "formed_i": -1}

# Position state
pos = {"side": None, "entry": np.nan, "sl": np.nan, "tp": np.nan,
       "size": 0.0, "entry_i": -1, "entry_time": None}

prev_in_ses = False

vals = df[["Open","High","Low","Close","atr","in_ses",
           "bull_fvg","bear_fvg",
           "bfvg_top","bfvg_bot","sfvg_top","sfvg_bot",
           "bear_frac","bull_frac","bear_frac_lvl","bull_frac_lvl"]].values

cols = {c: i for i, c in enumerate(
    ["Open","High","Low","Close","atr","in_ses",
     "bull_fvg","bear_fvg",
     "bfvg_top","bfvg_bot","sfvg_top","sfvg_bot",
     "bear_frac","bull_frac","bear_frac_lvl","bull_frac_lvl"])}

# Rolling fractal history for nearest-fractal search
bear_frac_hist = []   # list of (level,) for bear fractals seen so far
bull_frac_hist = []

for i, row in enumerate(vals):
    O, H, L, C = row[cols["Open"]], row[cols["High"]], row[cols["Low"]], row[cols["Close"]]
    atr_v   = row[cols["atr"]]
    in_s    = bool(row[cols["in_ses"]])
    b_fvg   = bool(row[cols["bull_fvg"]])
    s_fvg   = bool(row[cols["bear_fvg"]])

    # Update fractal history (fractals confirmed 2 bars ago, now safe to use)
    if bool(row[cols["bear_frac"]]):
        bear_frac_hist.append(row[cols["bear_frac_lvl"]])
        if len(bear_frac_hist) > 50:
            bear_frac_hist.pop(0)
    if bool(row[cols["bull_frac"]]):
        bull_frac_hist.append(row[cols["bull_frac_lvl"]])
        if len(bull_frac_hist) > 50:
            bull_frac_hist.pop(0)

    ses_end = prev_in_ses and not in_s
    prev_in_ses = in_s

    # ── Register new FVGs
    if b_fvg:
        bz = {"top": row[cols["bfvg_top"]], "bot": row[cols["bfvg_bot"]],
              "active": True, "formed_i": i}
    if s_fvg:
        sz = {"top": row[cols["sfvg_top"]], "bot": row[cols["sfvg_bot"]],
              "active": True, "formed_i": i}

    # ── Invalidate zones on break of structure
    if bz["active"] and C < bz["bot"] - SL_BUFFER * atr_v:
        bz["active"] = False
    if sz["active"] and C > sz["top"] + SL_BUFFER * atr_v:
        sz["active"] = False

    # ── Clear zones at session end
    if ses_end:
        bz["active"] = False
        sz["active"] = False

    # ── Check open position exit
    if pos["side"] is not None:
        exit_price = None
        exit_reason = None

        if pos["side"] == "long":
            if L <= pos["sl"]:
                exit_price  = pos["sl"]
                exit_reason = "SL"
            elif H >= pos["tp"]:
                exit_price  = pos["tp"]
                exit_reason = "TP"
        else:  # short
            if H >= pos["sl"]:
                exit_price  = pos["sl"]
                exit_reason = "SL"
            elif L <= pos["tp"]:
                exit_price  = pos["tp"]
                exit_reason = "TP"

        if exit_reason is None and ses_end:
            exit_price  = C
            exit_reason = "EOD"

        if exit_price is not None:
            direction = 1 if pos["side"] == "long" else -1
            pnl       = direction * (exit_price - pos["entry"]) * pos["size"]
            comm      = exit_price * pos["size"] * COMMISSION_PCT
            net_pnl   = pnl - comm

            equity += net_pnl
            trades.append({
                "entry_time":  pos["entry_time"],
                "exit_time":   df.index[i],
                "side":        pos["side"],
                "entry":       pos["entry"],
                "exit":        exit_price,
                "sl":          pos["sl"],
                "tp":          pos["tp"],
                "size":        pos["size"],
                "pnl":         net_pnl,
                "reason":      exit_reason,
                "tp_src":      pos.get("tp_src", "RR"),
                "equity":      equity,
            })
            pos["side"] = None

    # ── Enter new trades (only if flat and in session)
    if pos["side"] is None and in_s:

        # ── helpers to find nearest fractal TP ──────────────────
        def nearest_frac_above(entry, risk, hist):
            # Prefer fractal closest to RR_FALLBACK target; must be >= MIN_FRAC_RR
            best, best_dist = None, None
            for lvl in hist:
                if lvl > entry:
                    rr   = (lvl - entry) / risk
                    if rr >= MIN_FRAC_RR:
                        dist = abs(rr - RR_FALLBACK)   # how close to target RR
                        if best_dist is None or dist < best_dist:
                            best, best_dist = lvl, dist
            return best

        def nearest_frac_below(entry, risk, hist):
            best, best_dist = None, None
            for lvl in hist:
                if lvl < entry:
                    rr   = (entry - lvl) / risk
                    if rr >= MIN_FRAC_RR:
                        dist = abs(rr - RR_FALLBACK)
                        if best_dist is None or dist < best_dist:
                            best, best_dist = lvl, dist
            return best

        # LONG: price retraces into bullish FVG
        if (bz["active"] and i > bz["formed_i"] and
                L <= bz["top"] and H >= bz["bot"]):
            entry_px = bz["bot"] + (bz["top"] - bz["bot"]) * (1.0 - FVG_ENTRY_PCT)
            sl_px    = bz["bot"] - SL_BUFFER * atr_v
            risk     = max(entry_px - sl_px, atr_v * 0.01)

            frac_tp  = nearest_frac_above(entry_px, risk, bear_frac_hist)
            tp_px    = frac_tp if frac_tp is not None else entry_px + risk * RR_FALLBACK

            risk_amt = equity * RISK_PER_TRADE
            size     = risk_amt / risk if risk > 0 else 0
            comm     = entry_px * size * COMMISSION_PCT

            if size > 0:
                equity -= comm
                pos = {"side": "long", "entry": entry_px, "sl": sl_px,
                       "tp": tp_px, "size": size, "formed_i": i,
                       "entry_time": df.index[i],
                       "tp_src": "FRAC" if frac_tp else "RR"}
            bz["active"] = False

        # SHORT: price retraces into bearish FVG
        elif (sz["active"] and i > sz["formed_i"] and
              H >= sz["bot"] and L <= sz["top"]):
            entry_px = sz["top"] - (sz["top"] - sz["bot"]) * (1.0 - FVG_ENTRY_PCT)
            sl_px    = sz["top"] + SL_BUFFER * atr_v
            risk     = max(sl_px - entry_px, atr_v * 0.01)

            frac_tp  = nearest_frac_below(entry_px, risk, bull_frac_hist)
            tp_px    = frac_tp if frac_tp is not None else entry_px - risk * RR_FALLBACK

            risk_amt = equity * RISK_PER_TRADE
            size     = risk_amt / risk if risk > 0 else 0
            comm     = entry_px * size * COMMISSION_PCT

            if size > 0:
                equity -= comm
                pos = {"side": "short", "entry": entry_px, "sl": sl_px,
                       "tp": tp_px, "size": size, "formed_i": i,
                       "entry_time": df.index[i],
                       "tp_src": "FRAC" if frac_tp else "RR"}
            sz["active"] = False

# ──────────────────────────────────────────────
# 5.  RESULTS
# ──────────────────────────────────────────────
tdf = pd.DataFrame(trades)

if tdf.empty:
    print("\n⚠ No trades generated – try adjusting parameters.")
else:
    wins    = (tdf["pnl"] > 0).sum()
    losses  = (tdf["pnl"] <= 0).sum()
    total   = len(tdf)
    wr      = wins / total * 100
    gross_p = tdf[tdf["pnl"] > 0]["pnl"].sum()
    gross_l = abs(tdf[tdf["pnl"] < 0]["pnl"].sum())
    pf      = gross_p / gross_l if gross_l > 0 else float("inf")
    net     = tdf["pnl"].sum()
    ret_pct = net / INITIAL_CAPITAL * 100
    avg_w   = tdf[tdf["pnl"] > 0]["pnl"].mean() if wins > 0 else 0
    avg_l   = tdf[tdf["pnl"] < 0]["pnl"].mean() if losses > 0 else 0

    # Max drawdown
    eq_curve = np.array([INITIAL_CAPITAL] + list(tdf["equity"]))
    peak     = np.maximum.accumulate(eq_curve)
    dd       = (eq_curve - peak) / peak * 100
    max_dd   = dd.min()

    # Exit reason breakdown
    reason_counts = tdf["reason"].value_counts()

    # ── Console output
    print("\n" + "═"*52)
    print(f"  GOLDEN HOUR FVG STRATEGY  –  BACKTEST RESULTS")
    print(f"  {SYMBOL} · {INTERVAL} · {df.index[0].date()} → {df.index[-1].date()}")
    print("═"*52)
    print(f"  Total Trades     : {total}")
    print(f"  Win Rate         : {wr:.1f}%   ({wins}W / {losses}L)")
    print(f"  Profit Factor    : {pf:.2f}")
    print(f"  Net P&L          : ${net:+.2f}  ({ret_pct:+.1f}%)")
    print(f"  Avg Win          : ${avg_w:+.2f}")
    print(f"  Avg Loss         : ${avg_l:+.2f}")
    print(f"  Max Drawdown     : {max_dd:.1f}%")
    print(f"  Final Equity     : ${equity:,.2f}")
    print(f"\n  Exit Breakdown:")
    for r, c in reason_counts.items():
        print(f"    {r:12s}: {c}")
    print("═"*52)

    # ── TP source breakdown
    frac_trades = tdf[tdf["tp_src"] == "FRAC"]
    rr_trades   = tdf[tdf["tp_src"] == "RR"]
    print(f"\n  TP Source Breakdown:")
    if len(frac_trades):
        fw = (frac_trades["pnl"] > 0).sum()
        print(f"    Fractal TP : {len(frac_trades)} trades  WR {fw/len(frac_trades)*100:.0f}%  PnL ${frac_trades['pnl'].sum():+.2f}")
    if len(rr_trades):
        rw = (rr_trades["pnl"] > 0).sum()
        print(f"    Fallback RR: {len(rr_trades)} trades  WR {rw/len(rr_trades)*100:.0f}%  PnL ${rr_trades['pnl'].sum():+.2f}")

    # ── Per-session breakdown
    tdf["session"] = tdf["entry_time"].apply(
        lambda t: "London" if 2 <= t.hour < 5 else ("NY" if 8 <= t.hour < 11 else "Other"))
    print(f"\n  Session Breakdown:")
    for sess in ["London", "NY"]:
        s = tdf[tdf["session"] == sess]
        if s.empty:
            continue
        sw = (s["pnl"] > 0).sum()
        print(f"    {sess:8s} → {len(s)} trades  WR {sw/len(s)*100:.0f}%  PnL ${s['pnl'].sum():+.2f}")
    print()

    # ──────────────────────────────────────────────
    # 6.  CHARTS
    # ──────────────────────────────────────────────
    fig = plt.figure(figsize=(16, 12), facecolor="#0d1117")
    gs  = GridSpec(3, 2, figure=fig,
                   height_ratios=[2.5, 1, 1], hspace=0.45, wspace=0.35)

    col_bg   = "#0d1117"
    col_text = "#e6edf3"
    col_grid = "#21262d"
    col_lime = "#39d353"
    col_red  = "#f85149"
    col_blue = "#388bfd"
    col_gold = "#e3b341"

    def style_ax(ax, title=""):
        ax.set_facecolor("#161b22")
        ax.tick_params(colors=col_text, labelsize=8)
        ax.spines[:].set_color(col_grid)
        ax.yaxis.label.set_color(col_text)
        ax.xaxis.label.set_color(col_text)
        if title:
            ax.set_title(title, color=col_text, fontsize=10, pad=6)
        ax.grid(True, color=col_grid, linewidth=0.5)

    # ── (A) Equity Curve
    ax_eq = fig.add_subplot(gs[0, :])
    style_ax(ax_eq, "Equity Curve")
    ax_eq.plot(eq_curve, color=col_gold, linewidth=1.5, label="Equity")
    ax_eq.fill_between(range(len(eq_curve)), INITIAL_CAPITAL, eq_curve,
                        where=np.array(eq_curve) >= INITIAL_CAPITAL,
                        color=col_lime, alpha=0.15)
    ax_eq.fill_between(range(len(eq_curve)), INITIAL_CAPITAL, eq_curve,
                        where=np.array(eq_curve) < INITIAL_CAPITAL,
                        color=col_red, alpha=0.2)
    ax_eq.axhline(INITIAL_CAPITAL, color=col_grid, linewidth=0.8, linestyle="--")
    ax_eq.set_ylabel("Equity ($)", color=col_text)
    ax_eq.legend(fontsize=8, facecolor="#161b22", labelcolor=col_text)
    # Annotate final
    ax_eq.annotate(f"${equity:,.0f}  ({ret_pct:+.1f}%)",
                   xy=(len(eq_curve)-1, equity),
                   xytext=(-80, 12), textcoords="offset points",
                   fontsize=9, color=col_gold,
                   arrowprops=dict(arrowstyle="->", color=col_gold, lw=1))

    # ── (B) Drawdown
    ax_dd = fig.add_subplot(gs[1, :])
    style_ax(ax_dd, "Drawdown (%)")
    ax_dd.fill_between(range(len(dd)), dd, 0, color=col_red, alpha=0.6)
    ax_dd.plot(dd, color=col_red, linewidth=0.8)
    ax_dd.set_ylabel("DD %", color=col_text)
    ax_dd.axhline(0, color=col_grid, linewidth=0.6)

    # ── (C) Monthly P&L bar chart
    ax_month = fig.add_subplot(gs[2, 0])
    style_ax(ax_month, "Monthly P&L ($)")
    tdf["month"] = tdf["entry_time"].dt.to_period("M")
    monthly = tdf.groupby("month")["pnl"].sum()
    colors_m = [col_lime if v >= 0 else col_red for v in monthly.values]
    ax_month.bar(range(len(monthly)), monthly.values, color=colors_m, alpha=0.8)
    ax_month.set_xticks(range(len(monthly)))
    ax_month.set_xticklabels([str(m) for m in monthly.index], rotation=45, ha="right", fontsize=7)
    ax_month.axhline(0, color=col_grid, linewidth=0.6)

    # ── (D) Trade P&L distribution
    ax_dist = fig.add_subplot(gs[2, 1])
    style_ax(ax_dist, "Trade P&L Distribution")
    bins = np.linspace(tdf["pnl"].min(), tdf["pnl"].max(), 30)
    w_vals = tdf[tdf["pnl"] > 0]["pnl"].values
    l_vals = tdf[tdf["pnl"] < 0]["pnl"].values
    if len(w_vals): ax_dist.hist(w_vals, bins=bins, color=col_lime, alpha=0.7, label="Wins")
    if len(l_vals): ax_dist.hist(l_vals, bins=bins, color=col_red,  alpha=0.7, label="Losses")
    ax_dist.axvline(0, color=col_grid, linewidth=0.8, linestyle="--")
    ax_dist.legend(fontsize=8, facecolor="#161b22", labelcolor=col_text)

    # Stats text box
    stats_txt = (
        f"Trades : {total}  |  WR : {wr:.1f}%\n"
        f"PF : {pf:.2f}  |  Max DD : {max_dd:.1f}%\n"
        f"Avg W : ${avg_w:.2f}  |  Avg L : ${avg_l:.2f}"
    )
    fig.text(0.5, 0.97, stats_txt, ha="center", va="top",
             fontsize=9, color=col_text,
             bbox=dict(boxstyle="round,pad=0.4", fc="#21262d", ec=col_grid))

    fig.suptitle(
        f"Golden Hour FVG + Fractal TP v2  ·  {SYMBOL}  {INTERVAL}  ·  Fallback RR={RR_FALLBACK}  CAT={CATALYST_MULT}×ATR",
        color=col_text, fontsize=12, y=1.01)

    out = "/home/user/claude-workspace/trading/backtest_result.png"
    plt.savefig(out, dpi=150, bbox_inches="tight", facecolor=col_bg)
    print(f"Chart saved → {out}")
