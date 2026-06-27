# Claude Code — 專案記憶

## Pine Script 指標開發規則

### ⚠️ 核心禁令：禁止在 overlay 指標/策略中使用絕對 Y 座標繪圖

**任何**使用絕對價格座標的 Pine Script 繪圖函數都會拉伸 TradingView Y 軸，
把 K 線壓到圖底部。以下函數**一律禁止**用於訊號/區域標記：

| 禁止使用 | 原因 |
|----------|------|
| `box.new(left, top, right, bottom)` | top/bottom 是絕對價格 |
| `line.new(x1, y1, x2, y2)` | y1/y2 是絕對價格 |
| `label.new(x, y, ...)` 且 `yloc=yloc.price` | y 是絕對價格 |
| `plot(series)` 其中 series 為歷史 fractal/TP/SL 等非當前價格 | 歷史絕對價格殘留在所有歷史 bar |

### ✅ 正確做法：全部用 plotshape()

```pine
// ✅ 訊號標記 — 相對於 K 線，不拉伸 Y 軸
plotshape(condition, style=shape.triangledown, location=location.abovebar, color=color.orange)
plotshape(condition, style=shape.triangleup,   location=location.belowbar, color=color.blue)
plotshape(condition, style=shape.labelup,      location=location.belowbar, color=color.lime, text="Buy")
plotshape(condition, style=shape.labeldown,    location=location.abovebar, color=color.red,  text="Sell")

// ✅ 背景 / K 線顏色 — 無 Y 軸影響
bgcolor(condition ? color.new(color.blue, 92) : na)
barcolor(condition ? color.lime : na)

// ✅ plot() 只用於「永遠跟著當前價格」的序列（如 EMA）
plot(ta.ema(close, 20), color=color.red)
```

### 根本原因（已驗證，2026-06）

Golden Hour ICT FVG 策略反覆出現「所有指標浮在 K 線上方」問題，
最終確認根本原因如下：

1. **`box.new()` 留下歷史絕對座標** — 若 session 結束時 `ses_end` 因資料缺口沒有觸發，
   舊 session 的 FVG box（舊價格）不會被刪除，Y 軸被拉到那個舊價格，K 線壓到圖底。

2. **stale fractal array → `strategy.exit(limit=遠距TP)`** — `bear_fracs`/`bull_fracs`
   若跨 session 沒有清空，`find_tp_above()` 抓到幾個月前的高點，
   `strategy.exit(limit=3500)` 讓 TradingView 在圖上畫一條 3500 的 TP 水平線，Y 軸暴伸。

### Pine Script 狀態清除規則

```pine
// ❌ 錯誤：只靠 ses_end，資料缺口時不觸發
if ses_end
    array.clear(bear_fracs)

// ✅ 正確：每根 session 外的 bar 都清除
if not in_ses
    bear_fracs.clear()
    bull_fracs.clear()
    bz_on := false
    sz_on := false
```

### Pine Script v6 語法注意事項

```pine
// ❌ 不合法：semicolon 多陳述句
bz_on := false; sz_on := false
if not na(box) : box.delete(box); box := na

// ✅ 合法：縮排區塊
bz_on := false
sz_on := false
if not na(bz_box)
    box.delete(bz_box)
    bz_box := na
```

### 已通過驗證的繪圖架構（參考 v5）

- 訊號：`plotshape(location.belowbar / location.abovebar)`
- Fractal 標記：`plotshape(shape.triangledown/up, location.abovebar/belowbar)`
- FVG 事件：`plotshape(shape.labelup/labeldown, location.belowbar/abovebar)`
- Session 背景：`bgcolor()`
- Catalyst K 線：`barcolor()`
- **完全不使用** `box.new()`, `line.new()`, `label.new()` 作為視覺標記
