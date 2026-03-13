"""
GRID BOT 2026 — Telegram Interactive
Уведомления и команды (асинхронно через мостик)
"""

import asyncio
import threading
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
import grid_config as cfg
from logger import logger

class GridTelegram:
    """Уведомления и обработка команд"""

    def __init__(self, main_bot=None):
        self.token = cfg.TG_TOKEN
        self.channel = cfg.TG_CHANNEL
        self.enabled = bool(self.token and self.channel)
        self.main_bot = main_bot # Ссылка на главный объект GridBot для доступа к данным
        
        if self.enabled:
            # Создаем асинхронное приложение для команд
            self.app = Application.builder().token(self.token).build()
            self._setup_handlers()
            
            # Запускаем поллинг в отдельном потоке
            self.loop = asyncio.new_event_loop()
            self.thread = threading.Thread(target=self._run_event_loop, daemon=True)
            self.thread.start()
            logger.info("[GridTG] Telegram polling started")
        else:
            logger.warning("[GridTG] Telegram disabled (no token/channel)")

    def _run_event_loop(self):
        # В PTB 20+ run_polling по умолчанию ставит обработчики сигналов, 
        # что запрещено в доп. потоках. Отключаем через stop_signals=False.
        asyncio.set_event_loop(self.loop)
        self.app.run_polling(close_loop=False, stop_signals=False)

    def _setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self._cmd_status))
        self.app.add_handler(CommandHandler("status", self._cmd_status))
        self.app.add_handler(CommandHandler("pairs", self._cmd_pairs))
        self.app.add_handler(CommandHandler("help", self._cmd_help))

    async def _is_admin(self, update: Update) -> bool:
        user_id = str(update.effective_user.id)
        logger.info(f"[GridTG] Command from User ID: {user_id}")
        
        if cfg.TG_ADMIN_ID and user_id != str(cfg.TG_ADMIN_ID):
            await update.message.reply_text(f"⛔ Доступ запрещен. Ваш ID: {user_id}")
            return False
        return True

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._is_admin(update): return
        text = (
            "🤖 <b>Grid Bot 2026 Commands:</b>\n\n"
            "/status - Общий статус всех сеток\n"
            "/pairs - Список активных пар\n"
            "/help - Эта справка"
        )
        await update.message.reply_html(text)

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._is_admin(update): return
        if not self.main_bot:
            await update.message.reply_text("Бот еще инициализируется...")
            return

        eq = self.main_bot.executor.get_equity()
        count = len(self.main_bot.engines)
        
        text = f"📊 <b>GRID BOT STATUS</b>\n{'═'*20}\n"
        text += f"💰 Equity: <b>${eq:.2f}</b>\n"
        text += f"🔌 Active Grids: <b>{count} / {cfg.MAX_CONCURRENT_GRIDS}</b>\n\n"
        
        for sym, engine in self.main_bot.engines.items():
            price = self.main_bot.executor.get_price(sym)
            pos = self.main_bot.executor.get_positions(sym)
            unrealized = sum(p['unrealized_pnl'] for p in pos)
            
            text += f"💹 <b>{sym}</b>: <code>{price:.4f}</code>\n"
            text += f"💵 Realized: <code>${engine.total_profit:+.2f}</code>\n"
            text += f"⏳ Floating: <code>${unrealized:+.2f}</code>\n"
            text += f"🔄 Trades: {engine.total_trades}\n"
            text += f"{'─'*20}\n"
            
        await update.message.reply_html(text)

    async def _cmd_pairs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._is_admin(update): return
        if not self.main_bot: return
        pairs = list(self.main_bot.engines.keys())
        text = "🎯 <b>Active Pairs:</b>\n" + ("\n".join([f"• <code>{p}</code>" for p in pairs]) if pairs else "No active pairs")
        await update.message.reply_html(text)

    # --- Синхронные методы отправки (для вызова из главного потока) ---

    def send(self, text: str):
        if not self.enabled: return
        # Посылаем задачу в асинхронный цикл
        asyncio.run_coroutine_threadsafe(
            self.app.bot.send_message(chat_id=self.channel, text=text, parse_mode="HTML", disable_web_page_preview=True),
            self.loop
        )

    def notify_start(self, symbol: str, levels: int, upper: float, lower: float,
                      qty: float, balance: float, leverage: int):
        step = (upper - lower) / (levels - 1) if levels > 1 else 0
        mode = "DEMO" if cfg.BYBIT_DEMO else ("TESTNET" if cfg.TESTNET else "🔴 LIVE")
        self.send(
            f"🟢 <b>GRID BOT STARTED</b>\n"
            f"{'═' * 28}\n"
            f"📊 Symbol: <b>{symbol}</b>\n"
            f"🔧 Mode: <b>{mode}</b>\n"
            f"📏 Levels: <b>{levels}</b>\n"
            f"📐 Range: <code>{lower:.4f} — {upper:.4f}</code>\n"
            f"📦 Qty/level: <code>{qty}</code>\n"
            f"⚡ Leverage: <b>{leverage}x</b>\n"
            f"\n🤖 <i>Grid Bot 2026</i>"
        )

    def notify_fill(self, side: str, price: float, qty: float, tp_side: str, tp_price: float):
        emoji = "🟢" if side == "Buy" else "🔴"
        self.send(
            f"{emoji} <b>{side} FILLED</b> @ <code>{price:.4f}</code>\n"
            f"📦 Qty: <code>{qty}</code>\n"
            f"🎯 TP {tp_side} → <code>{tp_price:.4f}</code>"
        )

    def notify_profit(self, profit: float, total_profit: float, total_trades: int):
        self.send(
            f"💰 <b>Grid Profit: ${profit:+.4f}</b>\n"
            f"📊 Total: <b>${total_profit:+.2f}</b> ({total_trades} trades)"
        )

    def send_status(self, symbol: str, price: float, upper: float, lower: float,
                    total_profit: float, total_trades: int, balance: float, 
                    active_orders: int, positions: int, uptime: str):
        """Регулярный Heartbeat-статус в канал"""
        # Считаем суммарный Unrealized
        total_unrealized = 0
        if self.main_bot:
            for s in self.main_bot.engines:
                pos = self.main_bot.executor.get_positions(s)
                total_unrealized += sum(p['unrealized_pnl'] for p in pos)

        self.send(
            f"💓 <b>GRID HEARTBEAT</b>\n"
            f"{'═' * 28}\n"
            f"💰 Equity: <b>${balance:.2f}</b>\n"
            f"📈 Realized: <b>${total_profit:+.2f}</b>\n"
            f"⏳ Floating: <b>${total_unrealized:+.2f}</b>\n"
            f"🔌 Active Grids: <b>{positions}</b>\n"
            f"📦 Orders: <b>{active_orders}</b>\n"
            f"⏱ Uptime: <code>{uptime}</code>"
        )

    def notify_rebalance(self, new_upper: float, new_lower: float, reason: str):
        self.send(
            f"⚠️ <b>GRID REBALANCED</b>\n"
            f"📝 Reason: {reason}\n"
            f"📐 New Range: <code>{new_lower:.4f} — {new_upper:.4f}</code>"
        )

    def notify_stop(self, reason: str, total_profit: float, total_trades: int,
                    final_balance: float):
        self.send(
            f"🛑 <b>GRID BOT STOPPED</b>\n"
            f"{'═' * 28}\n"
            f"📝 Reason: {reason}\n"
            f"💰 Total Realized: <b>${total_profit:+.2f}</b>\n"
            f"📊 Trades: {total_trades}\n"
            f"💵 Final Equ: <code>${final_balance:.2f}</code>\n"
        )
