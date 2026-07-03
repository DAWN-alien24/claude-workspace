"""
永豐 Shioaji API 測試腳本
用於完成官方要求的「登入測試 + 下單測試」，通過後才能申請正式交易權限。
執行方式：python shioaji_test.py
"""

import os
from dotenv import load_dotenv
import shioaji as sj

load_dotenv()

API_KEY    = os.getenv("SHIOAJI_API_KEY")
SECRET_KEY = os.getenv("SHIOAJI_SECRET_KEY")

def run_test():
    print("=" * 50)
    print("永豐 Shioaji API 測試")
    print("=" * 50)

    # ── 1. 登入（模擬環境）──────────────────────────
    print("\n[1] 登入模擬環境...")
    api = sj.Shioaji(simulation=True)
    api.login(api_key=API_KEY, secret_key=SECRET_KEY)
    print("    ✅ 登入成功")

    # ── 2. 取得小台指近月合約 ──────────────────────
    print("\n[2] 取得小台指近月合約...")
    contract = api.Contracts.Futures.MXF["MXFR1"]
    print(f"    ✅ 合約：{contract.symbol} / {contract.name}")

    # ── 3. 模擬下單（市價買進 1 口）────────────────
    print("\n[3] 模擬下單（市價買進 1 口小台）...")
    order = api.Order(
        price=0,
        quantity=1,
        action=sj.constant.Action.Buy,
        price_type=sj.constant.FuturesPriceType.MKT,
        order_type=sj.constant.OrderType.IOC,
    )
    trade = api.place_order(contract, order)
    print(f"    ✅ 委託單號：{trade.order.id}")
    print(f"    狀態：{trade.status.status}")

    # ── 4. 登出 ────────────────────────────────────
    print("\n[4] 登出...")
    api.logout()
    print("    ✅ 登出成功")

    print("\n" + "=" * 50)
    print("測試完成！截圖此畫面回報給永豐即可。")
    print("=" * 50)

if __name__ == "__main__":
    run_test()
