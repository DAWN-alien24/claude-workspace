"""
TradingView Webhook → 永豐期貨自動下單伺服器
啟動方式：python webhook_server.py
TradingView 快訊 Webhook URL：http://你的IP:5000/webhook
"""

import os
import logging
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import shioaji as sj

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

API_KEY        = os.getenv("SHIOAJI_API_KEY")
SECRET_KEY     = os.getenv("SHIOAJI_SECRET_KEY")
SIMULATION     = os.getenv("SIMULATION", "True").lower() == "true"
PORT           = int(os.getenv("PORT", 5000))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

app = Flask(__name__)

# ── 初始化 Shioaji ──────────────────────────────────────
api = sj.Shioaji(simulation=SIMULATION)
api.login(api_key=API_KEY, secret_key=SECRET_KEY)
contract = api.Contracts.Futures.MXF["MXFR1"]  # 小台指近月

log.info(f"已連線 {'【模擬】' if SIMULATION else '【正式】'} 環境")
log.info(f"合約：{contract.symbol} {contract.name}")


# ── 下單函式 ────────────────────────────────────────────
def place(action: sj.constant.Action, qty: int = 1):
    order = api.Order(
        price=0,
        quantity=qty,
        action=action,
        price_type=sj.constant.FuturesPriceType.MKT,
        order_type=sj.constant.OrderType.IOC,
    )
    trade = api.place_order(contract, order)
    log.info(f"下單 {action.value} {qty}口 → 單號 {trade.order.id} 狀態 {trade.status.status}")
    return trade


# ── Webhook 接收端點 ─────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True) or {}

    # 驗證安全 token（TradingView 快訊訊息裡要帶 "secret": "你設定的密碼"）
    if WEBHOOK_SECRET and data.get("secret") != WEBHOOK_SECRET:
        log.warning("Webhook 驗證失敗，拒絕請求")
        return jsonify({"error": "unauthorized"}), 403

    action_str = str(data.get("action", "")).lower()
    qty        = int(data.get("qty", 1))

    log.info(f"收到 Webhook：{data}")

    if action_str == "buy":
        place(sj.constant.Action.Buy, qty)
    elif action_str == "sell":
        place(sj.constant.Action.Sell, qty)
    elif action_str == "close":
        # 平倉：反向下單
        pos = api.list_positions(api.futopt_account)
        for p in pos:
            close_action = sj.constant.Action.Sell if p.quantity > 0 else sj.constant.Action.Buy
            place(close_action, abs(p.quantity))
    else:
        log.warning(f"未知 action：{action_str}")
        return jsonify({"error": "unknown action"}), 400

    return jsonify({"status": "ok", "action": action_str, "qty": qty})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "running", "simulation": SIMULATION})


if __name__ == "__main__":
    log.info(f"Webhook 伺服器啟動，監聽 port {PORT}")
    app.run(host="0.0.0.0", port=PORT)
