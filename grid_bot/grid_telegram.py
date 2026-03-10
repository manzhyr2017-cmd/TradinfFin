"""
GRID BOT 2026 — Telegram Notifications
Уведомления о работе Grid Bot
"""

import requests
from datetime import datetime
import grid_config as cfg
from logger import logger


class GridTelegram:
    """Отправка уведомлений в Telegram"""

    def __init__(self):
        self.token = cfg.TG_TOKEN
        self.channel = cfg.TG_CHANNEL
        self.api_url = f"https://api.telegram.org/bot{self.token}" if self.token else ""
        self.enabled = bool(self.token and self.channel)
        if not self.enabled:
            logger.warning("[GridTG] Telegram disabled (no token/channel)")

    def send(self, text: str) -> bool:
        """Отправляет сообщение"""
        if not self.enabled:
            return False
        try:
            payload = {
                "chat_id": self.channel,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            resp = requests.post(f"{self.api_url}/sendMessage", json=payload, timeout=10)
            if resp.status_code != 200:
                logger.error(f"[GridTG] Error sending msg: {resp.text}")
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"[GridTG] Error: {e}")
            return False

    def notify_start(self, symbol: str, levels: int, upper: float, lower: float,
                     qty: float, balance: float, leverage: int):
        """Уведомление о запуске"""
        step = (upper - lower) / (levels - 1) if levels > 1 else 0
        mode = "DEMO" if cfg.BYBIT_DEMO else ("TESTNET" if cfg.TESTNET else "🔴 LIVE")
        self.send(
            f"🟢 <b>GRID BOT STARTED</b>\n"
            f"{'═' * 28}\n"
            f"📊 Symbol: <b>{symbol}</b>\n"
            f"🔧 Mode: <b>{mode}</b>\n"
            f"📏 Levels: <b>{levels}</b>\n"
            f"📐 Range: <code>{lower:.2f} — {upper:.2f}</code>\n"
            f"📏 Step: <code>{step:.2f}</code>\n"
            f"📦 Qty/level: <code>{qty}</code>\n"
            f"💰 Balance: <code>${balance:.2f}</code>\n"
            f"⚡ Leverage: <b>{leverage}x</b>\n"
            f"\n🤖 <i>Grid Bot 2026</i>"
        )

    def notify_fill(self, side: str, price: float, qty: float, tp_side: str, tp_price: float):
        """Уведомление об исполнении ордера"""
        emoji = "🟢" if side == "Buy" else "🔴"
        tp_emoji = "🎯"
        self.send(
            f"{emoji} <b>{side} FILLED</b> @ <code>{price:.4f}</code>\n"
            f"📦 Qty: <code>{qty}</code>\n"
            f"{tp_emoji} TP {tp_side} → <code>{tp_price:.4f}</code>"
        )

    def notify_profit(self, profit: float, total_profit: float, total_trades: int):
        """Уведомление о профите из grid-пары"""
        self.send(
            f"💰 <b>Grid Profit: ${profit:+.4f}</b>\n"
            f"📊 Total: <b>${total_profit:+.2f}</b> ({total_trades} trades)"
        )

    def notify_rebalance(self, new_upper: float, new_lower: float, reason: str):
        """Уведомление о перестройке сетки"""
        self.send(
            f"🔄 <b>GRID REBALANCED</b>\n"
            f"📐 New range: <code>{new_lower:.2f} — {new_upper:.2f}</code>\n"
            f"📝 Reason: {reason}"
        )

    def notify_stop(self, reason: str, total_profit: float, total_trades: int,
                    final_balance: float):
        """Уведомление об остановке"""
        self.send(
            f"🛑 <b>GRID BOT STOPPED</b>\n"
            f"{'═' * 28}\n"
            f"📝 Reason: {reason}\n"
            f"💰 Total PnL: <b>${total_profit:+.2f}</b>\n"
            f"📊 Trades: {total_trades}\n"
            f"💵 Balance: <code>${final_balance:.2f}</code>\n"
            f"\n🤖 <i>Grid Bot 2026</i>"
        )

    def send_status(self, symbol: str, price: float, upper: float, lower: float,
                    total_profit: float, total_trades: int, balance: float,
                    active_orders: int, positions: int, uptime: str):
        """Периодический heartbeat"""
        # Позиция цены в сетке
        total_range = upper - lower
        if total_range > 0:
            pct = (price - lower) / total_range * 100
            bar_len = 10
            pos = int(pct / 100 * bar_len)
            pos = max(0, min(bar_len - 1, pos))
            bar = "░" * pos + "█" + "░" * (bar_len - 1 - pos)
        else:
            bar = "█" * 10

        self.send(
            f"📊 <b>GRID STATUS</b>\n"
            f"{'─' * 28}\n"
            f"💹 {symbol}: <code>{price:.2f}</code>\n"
            f"📐 [{bar}] {pct:.0f}%\n"
            f"📏 <code>{lower:.2f} ← → {upper:.2f}</code>\n"
            f"{'─' * 28}\n"
            f"💰 PnL: <b>${total_profit:+.2f}</b>\n"
            f"📊 Trades: {total_trades}\n"
            f"💵 Balance: <code>${balance:.2f}</code>\n"
            f"📋 Orders: {active_orders} | Positions: {positions}\n"
            f"⏱️ Uptime: {uptime}"
        )
