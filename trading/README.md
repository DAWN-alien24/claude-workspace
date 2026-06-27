# Golden Hour – ICT FVG + Fractal TP Strategy

**版本**: v6  
**語言**: Pine Script v6  
**類型**: Strategy (overlay)  
**建議時間尺度**: 5M  
**Branch**: `claude/automated-trading-mechanism-z73fw0`

---

## 策略邏輯

| 元素 | 說明 |
|------|------|
| Session | London 02:00–05:00 ET、NY 08:00–11:00 ET |
| Catalyst Candle | Body > ATR × 倍數的強勢K線 |
| FVG (Fair Value Gap) | 三根K線結構，中間K線為 Catalyst |
| 趨勢過濾 | EMA 200：收盤在 EMA 上方只做多，下方只做空 |
| 進場 | FVG 偵測當下掛限價單（FVG 中間點） |
| TP | session 內最近的 Bill Williams Fractal 高/低點；找不到時用 1.5R |
| SL | FVG 底部 − ATR buffer |
| 收盤 | Session 結束後強制平倉並取消所有未成交限價單 |

## 視覺元素（全部 plotshape，零 box.new）

| 符號 | 意義 |
|------|------|
| 橘色 ▼ | Bear Fractal（K線上方） |
| 藍色 ▲ | Bull Fractal（K線下方） |
| 綠色 FVG label | Bull FVG 出現（不論趨勢） |
| 紅色 FVG label | Bear FVG 出現（不論趨勢） |
| 綠色/青色 ↑ label | Long 限價單已掛（通過 EMA 過濾） |
| 紅色/深紅 ↓ label | Short 限價單已掛（通過 EMA 過濾） |
| 黃色線 | EMA 趨勢線 |
| 藍色背景 | London session |
| 橘色背景 | NY session |

## 修改歷程

| 版本 | 變更 |
|------|------|
| v1 | 初始版：label.new() + line.new() → Y 軸飄移 |
| v2 | 改用 plot(active_tp/sl) → 仍有舊 fractal 污染 |
| v3 | line.new() moving anchor → 根本原因未解 |
| v4 | 全面改用 plotshape()，但 FVG 仍用 box.new() |
| v4.1 | ses_end 清除改為 if not in_ses |
| v5 | 徹底移除 box.new()；FVG 改用 plotshape() |
| **v6** | **★ EMA 趨勢過濾 + 限價單進場 + Fallback R:R 改為 1.5** |

## v6 三項關鍵改進

### 1. Fallback R:R：0.49 → 1.5
舊版找不到 Fractal TP 時，TP 設在 0.49 倍風險，賠多賺少必虧。
新版改為 1.5R，即使勝率只有 40% 也能正期望值。

### 2. EMA 趨勢過濾
- `close > EMA(200)` → 只接受 Long 訊號
- `close < EMA(200)` → 只接受 Short 訊號
- 可在 Trend Filter 群組關閉（`i_use_ema = false`）

### 3. 限價單進場（取代市價單）
- 舊版：價格進入 FVG 區域時直接市價進場（容易追高殺低）
- 新版：FVG 偵測當下立即掛限價單在 FVG 中間點，等待精確回測
- Zone 失效或 session 結束時自動取消未成交的限價單

---

## 完整 Pine Script 程式碼（v6）

```pine
//@version=6
strategy(
     title             = "Golden Hour – ICT FVG + Fractal TP v6 (Chanelle Style)",
     overlay           = true,
     default_qty_type  = strategy.percent_of_equity,
     default_qty_value = 5,
     commission_type   = strategy.commission.percent,
     commission_value  = 0.02,
     slippage          = 2)

var string G1 = "Sessions (New York Time)"
bool i_lon = input.bool(true, "London Open  02:00–05:00 ET", group=G1)
bool i_ny  = input.bool(true, "NY Open      08:00–11:00 ET", group=G1)

var string G2 = "Catalyst / FVG"
int   i_atr_len  = input.int  (14,  "ATR Length",                      group=G2, minval=1)
float i_cat_mult = input.float(1.5, "Catalyst Size (× ATR)",            group=G2, minval=0.5, step=0.1)
float i_fvg_pct  = input.float(0.5, "FVG Entry %  (0=top · 1=bottom)", group=G2, minval=0.0, maxval=1.0, step=0.05)

var string G3 = "Risk Management"
float i_rr_fb  = input.float(1.5,  "Fallback R:R (no fractal found)", group=G3, minval=0.5, step=0.1)
float i_sl_buf = input.float(0.3,  "SL Buffer (× ATR)",               group=G3, minval=0.0, step=0.05)
float i_min_rr = input.float(0.2,  "Min R:R to accept fractal TP",    group=G3, minval=0.05, step=0.05)

var string G4 = "Fractal"
int i_frac_n = input.int(2, "Fractal Arms  (2 = 5-bar)", group=G4, minval=1, maxval=5)

var string G5 = "Trend Filter"
bool i_use_ema = input.bool(true, "Enable EMA Trend Filter", group=G5)
int  i_ema_len = input.int(200,  "EMA Length",              group=G5, minval=10)

var string G6 = "Display"
bool i_show_fvg  = input.bool(true, "Show FVG Signals",   group=G6)
bool i_show_frac = input.bool(true, "Show Fractals",       group=G6)
bool i_show_sig  = input.bool(true, "Show Entry Signals",  group=G6)
bool i_show_ema  = input.bool(true, "Show EMA",            group=G6)

bool in_lon = i_lon and not na(time(timeframe.period, "0200-0500", "America/New_York"))
bool in_ny  = i_ny  and not na(time(timeframe.period, "0800-1100", "America/New_York"))
bool in_ses = in_lon or in_ny

float ema_val   = ta.ema(close, i_ema_len)
bool bull_trend = not i_use_ema or close > ema_val
bool bear_trend = not i_use_ema or close < ema_val

float atr  = ta.atr(i_atr_len)
float body = math.abs(close - open)
bool bull_cat = close > open and body > i_cat_mult * atr
bool bear_cat = close < open and body > i_cat_mult * atr

int N = i_frac_n
bool bear_frac_ok = high[N] > high[N-1] and high[N] > high[N+1]
bool bull_frac_ok = low[N]  < low[N-1]  and low[N]  < low[N+1]
if N >= 2
    bear_frac_ok := bear_frac_ok and high[N] > high[N-2] and high[N] > high[N+2]
    bull_frac_ok := bull_frac_ok and low[N]  < low[N-2]  and low[N]  < low[N+2]
if N >= 3
    bear_frac_ok := bear_frac_ok and high[N] > high[N-3] and high[N] > high[N+3]
    bull_frac_ok := bull_frac_ok and low[N]  < low[N-3]  and low[N]  < low[N+3]
if N >= 4
    bear_frac_ok := bear_frac_ok and high[N] > high[N-4] and high[N] > high[N+4]
    bull_frac_ok := bull_frac_ok and low[N]  < low[N-4]  and low[N]  < low[N+4]
if N >= 5
    bear_frac_ok := bear_frac_ok and high[N] > high[N-5] and high[N] > high[N+5]
    bull_frac_ok := bull_frac_ok and low[N]  < low[N-5]  and low[N]  < low[N+5]

bool bear_fractal = bear_frac_ok
bool bull_fractal = bull_frac_ok

var array<float> bear_fracs = array.new<float>()
var array<float> bull_fracs = array.new<float>()

if bear_fractal and in_ses[N]
    bear_fracs.push(high[N])
    if bear_fracs.size() > 30
        bear_fracs.shift()
if bull_fractal and in_ses[N]
    bull_fracs.push(low[N])
    if bull_fracs.size() > 30
        bull_fracs.shift()

find_tp_above(float entry, float risk) =>
    float result  = na
    float best_rr = na
    for lvl in bear_fracs
        float rr = (lvl - entry) / risk
        if lvl > entry and rr >= i_min_rr
            if na(best_rr) or rr < best_rr
                result  := lvl
                best_rr := rr
    result

find_tp_below(float entry, float risk) =>
    float result  = na
    float best_rr = na
    for lvl in bull_fracs
        float rr = (entry - lvl) / risk
        if lvl < entry and rr >= i_min_rr
            if na(best_rr) or rr < best_rr
                result  := lvl
                best_rr := rr
    result

bool bull_fvg = low  > high[2] and bull_cat[1] and in_ses[1]
bool bear_fvg = high < low[2]  and bear_cat[1] and in_ses[1]

var float bz_top = na
var float bz_bot = na
var bool  bz_on  = false

var float sz_top = na
var float sz_bot = na
var bool  sz_on  = false

bool flat_pos = strategy.position_size == 0

float bfvg_ep  = bull_fvg ? high[2] + (low - high[2]) * (1.0 - i_fvg_pct) : na
float bfvg_sl  = bull_fvg ? high[2] - i_sl_buf * atr : na
float bfvg_r   = bull_fvg ? math.max(bfvg_ep - bfvg_sl, syminfo.mintick * 5) : na
float bfvg_ftp = bull_fvg ? find_tp_above(bfvg_ep, bfvg_r) : na
bool  bfvg_if  = not na(bfvg_ftp)
float bfvg_tp  = bull_fvg ? (bfvg_if ? bfvg_ftp : bfvg_ep + bfvg_r * i_rr_fb) : na

float sfvg_ep  = bear_fvg ? low[2] - (low[2] - high) * (1.0 - i_fvg_pct) : na
float sfvg_sl  = bear_fvg ? low[2] + i_sl_buf * atr : na
float sfvg_r   = bear_fvg ? math.max(sfvg_sl - sfvg_ep, syminfo.mintick * 5) : na
float sfvg_ftp = bear_fvg ? find_tp_below(sfvg_ep, sfvg_r) : na
bool  sfvg_if  = not na(sfvg_ftp)
float sfvg_tp  = bear_fvg ? (sfvg_if ? sfvg_ftp : sfvg_ep - sfvg_r * i_rr_fb) : na

bool long_detect  = bull_fvg and flat_pos and in_ses and bull_trend
bool short_detect = bear_fvg and flat_pos and in_ses and bear_trend

if bull_fvg
    bz_top := low
    bz_bot := high[2]
    bz_on  := true
    if long_detect
        strategy.cancel("Short")
        strategy.entry("Long", strategy.long, limit=bfvg_ep,
             comment=(bfvg_if ? "FRAC " : "RR ") + str.tostring(bfvg_if ? (bfvg_ftp - bfvg_ep) / bfvg_r : i_rr_fb, "#.##") + "R")
        strategy.exit("L-Exit", from_entry="Long", stop=bfvg_sl, limit=bfvg_tp)

if bear_fvg
    sz_top := low[2]
    sz_bot := high
    sz_on  := true
    if short_detect
        strategy.cancel("Long")
        strategy.entry("Short", strategy.short, limit=sfvg_ep,
             comment=(sfvg_if ? "FRAC " : "RR ") + str.tostring(sfvg_if ? (sfvg_ep - sfvg_ftp) / sfvg_r : i_rr_fb, "#.##") + "R")
        strategy.exit("S-Exit", from_entry="Short", stop=sfvg_sl, limit=sfvg_tp)

if bz_on and close < bz_bot - i_sl_buf * atr
    bz_on := false
    strategy.cancel("Long")
if sz_on and close > sz_top + i_sl_buf * atr
    sz_on := false
    strategy.cancel("Short")

if not in_ses
    bear_fracs.clear()
    bull_fracs.clear()
    bz_on := false
    sz_on := false
    strategy.cancel("Long")
    strategy.cancel("Short")
    if strategy.position_size != 0
        strategy.close_all(comment="EOD")

bgcolor(in_lon ? color.new(color.blue,   92) : na, title="London Window")
bgcolor(in_ny  ? color.new(color.orange, 92) : na, title="NY Window")
barcolor(bull_cat and in_ses ? color.new(color.lime, 0) : na, title="Bull Catalyst")
barcolor(bear_cat and in_ses ? color.new(color.red,  0) : na, title="Bear Catalyst")

plot(i_show_ema ? ema_val : na, title="EMA", color=color.new(color.yellow, 0), linewidth=1)

plotshape(i_show_fvg and bull_fvg,
     title="Bull FVG", style=shape.labelup, location=location.belowbar,
     color=color.new(color.lime, 20), text="FVG", textcolor=color.black, size=size.tiny)
plotshape(i_show_fvg and bear_fvg,
     title="Bear FVG", style=shape.labeldown, location=location.abovebar,
     color=color.new(color.red, 20), text="FVG", textcolor=color.white, size=size.tiny)

plotshape(i_show_sig and long_detect and bfvg_if,
     title="Long FRAC", style=shape.labelup, location=location.belowbar,
     color=color.lime, text="↑ L FRAC", textcolor=color.black, size=size.small)
plotshape(i_show_sig and long_detect and not bfvg_if,
     title="Long RR", style=shape.labelup, location=location.belowbar,
     color=color.teal, text="↑ L RR", textcolor=color.white, size=size.small)
plotshape(i_show_sig and short_detect and sfvg_if,
     title="Short FRAC", style=shape.labeldown, location=location.abovebar,
     color=color.red, text="↓ S FRAC", textcolor=color.white, size=size.small)
plotshape(i_show_sig and short_detect and not sfvg_if,
     title="Short RR", style=shape.labeldown, location=location.abovebar,
     color=color.maroon, text="↓ S RR", textcolor=color.white, size=size.small)

plotshape(i_show_frac and bear_fractal and in_ses[N],
     title="Bear Fractal", style=shape.triangledown, location=location.abovebar,
     color=color.orange, size=size.tiny)
plotshape(i_show_frac and bull_fractal and in_ses[N],
     title="Bull Fractal", style=shape.triangleup, location=location.belowbar,
     color=color.blue, size=size.tiny)

var table tbl = table.new(position.top_right, 2, 7,
     bgcolor=color.new(color.black, 70), border_color=color.new(color.gray, 50),
     border_width=1, frame_color=color.new(color.gray, 50), frame_width=1)

if barstate.islastconfirmedhistory or barstate.islast
    int   total = strategy.closedtrades
    float wr    = total > 0 ? strategy.wintrades / total * 100 : 0.0
    float pf    = strategy.grossloss > 0 ? strategy.grossprofit / strategy.grossloss : 0.0
    table.cell(tbl, 0, 0, "GH FVG + FRACTAL TP  v6",
         text_color=color.white, text_size=size.small, bgcolor=color.new(color.navy, 60))
    table.cell(tbl, 1, 0, "EMA+Limit+RR1.5",
         text_color=color.yellow, text_size=size.small, bgcolor=color.new(color.navy, 60))
    table.cell(tbl, 0, 1, "Win Rate",   text_color=color.silver, text_size=size.tiny)
    table.cell(tbl, 1, 1, str.tostring(wr, "#.1") + "%",
         text_color=wr >= 50 ? color.lime : color.red, text_size=size.tiny)
    table.cell(tbl, 0, 2, "Profit Factor", text_color=color.silver, text_size=size.tiny)
    table.cell(tbl, 1, 2, str.tostring(pf, "#.##"),
         text_color=pf >= 1.0 ? color.lime : color.red, text_size=size.tiny)
    table.cell(tbl, 0, 3, "Total Trades", text_color=color.silver, text_size=size.tiny)
    table.cell(tbl, 1, 3, str.tostring(total), text_color=color.white, text_size=size.tiny)
    table.cell(tbl, 0, 4, "Net P&L",    text_color=color.silver, text_size=size.tiny)
    table.cell(tbl, 1, 4, str.tostring(strategy.netprofit, "#.##"),
         text_color=strategy.netprofit >= 0 ? color.lime : color.red, text_size=size.tiny)
    table.cell(tbl, 0, 5, "Max Drawdown", text_color=color.silver, text_size=size.tiny)
    table.cell(tbl, 1, 5, str.tostring(strategy.max_drawdown, "#.##"),
         text_color=color.orange, text_size=size.tiny)
    table.cell(tbl, 0, 6, "Final Equity", text_color=color.silver, text_size=size.tiny)
    table.cell(tbl, 1, 6, str.tostring(strategy.equity, "#.##"),
         text_color=color.white, text_size=size.tiny)
```
