"""
TITAN BOT 2026 - Telegram Control Center
Интерактивный пульт управления торговой системой
"""

import os
import asyncio
import logging
import threading
import time
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode
from main import TitanBotUltimateFinal
import config

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("TitanTG")

class TitanTelegramBot:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.channel_id = os.getenv("TELEGRAM_CHANNEL")
        
        # Мы создаем ОДИН экземпляр Умного Бота
        self.trading_bot = TitanBotUltimateFinal()
        self.bot_thread = None
        
        # Build app
        self.app = Application.builder().token(self.token).build()
        self._setup_handlers()
        
        print("🤖 TITAN TELEGRAM CONTROL CENTER ЗАПУЩЕН")
        
    def _setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start_cmd))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.text_handler))

    async def start_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Приветствие и главное меню"""
        user = update.effective_user
        
        keyboard = [
            [KeyboardButton("🚀 START SCANNER"), KeyboardButton("🛑 STOP SYSTEM")],
            [KeyboardButton("📊 STATUS"), KeyboardButton("💰 BALANCE")],
            [KeyboardButton("📋 TOP COINS"), KeyboardButton("⚙️ SETTINGS")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
        
        welcome_msg = (
            f"👋 <b>Привет, {user.first_name}!</b>\n\n"
            f"⚡ <b>TITAN CONTROL CENTER</b> ready.\n"
            f"Mode: <b>{config.TRADE_MODE}</b>\n"
            f"Scanning: <b>Top-{config.MAX_SYMBOLS} Volatile Assets</b>\n"
        )
        await update.message.reply_text(welcome_msg, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

    async def text_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        
        if text == "🚀 START SCANNER":
            await self.run_scanner(update, context) # Добавил context
        elif text == "🛑 STOP SYSTEM":
            await self.stop_system(update)
        elif text == "📊 STATUS":
            await self.show_status(update)
        elif text == "💰 BALANCE":
            await self.show_balance(update)
        elif text == "📋 TOP COINS":
            await self.show_top_coins(update)
        elif text == "⚙️ SETTINGS":
            await self.show_settings(update)
        else:
            await update.message.reply_text("🤔 Unknown command")

    async def run_scanner(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запуск сканера в фоновом потоке"""
        if self.trading_bot.is_running:
            await update.message.reply_text("⚠️ Система уже работает! (Игнорирую повторный запуск)")
            return

        msg = await update.message.reply_text("🔄 Запуск TITAN AGGRESSIVE SCANNER...")
        
        # Запускаем в отдельном потоке
        self.bot_thread = threading.Thread(target=self.trading_bot.start)
        self.bot_thread.daemon = True
        self.bot_thread.start()
        
        # Ожидание инициализации
        await asyncio.sleep(7)
        
        if self.trading_bot.is_running:
            # Используем msg.edit_text вместо context.bot
            await msg.edit_text(
                text=(
                    f"🚀 <b>SCANNER STARTED!</b>\n"
                    f"Monitoring Top-{config.MAX_SYMBOLS} coins by Volatility.\n"
                    f"Status: <b>ONLINE</b> 🟢\n"
                    f"Start Time: {datetime.now().strftime('%H:%M:%S')}"
                ),
                parse_mode=ParseMode.HTML
            )
        else:
            await msg.edit_text(text="❌ Ошибка запуска Scanner (см. логи сервера).")

    async def stop_system(self, update: Update):
        """Остановка"""
        if not self.trading_bot.is_running:
            await update.message.reply_text("💤 Система и так спит.")
            return
            
        self.trading_bot.is_running = False 
        if self.trading_bot.stream and self.trading_bot.stream.ws:
            self.trading_bot.stream.ws.exit()
            
        await update.message.reply_text("🛑 Остановка сканера... (завершение текущего цикла)")

    async def show_status(self, update: Update):
        """Статус работы"""
        status = "🟢 ONLINE" if self.trading_bot.is_running else "🔴 OFFLINE"
        current_coin = self.trading_bot.current_symbol
        total_coins = len(self.trading_bot.symbol_list)
        
        msg = (
            f"🖥️ <b>SYSTEM STATUS:</b> {status}\n"
            f"Current Target: <b>{current_coin}</b>\n"
            f"Watchlist Size: <b>{total_coins} coins</b>\n"
            f"Uptime: {(datetime.now()).strftime('%H:%M:%S')}\n"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

    async def show_top_coins(self, update: Update):
        """Показать текущий список монет"""
        coins = self.trading_bot.symbol_list
        if not coins:
            await update.message.reply_text("📭 Список пуст (сканер не запущен).")
            return
            
        display_coins = coins[:15]
        msg = f"📋 <b>TOP VOLATILE COINS (Active):</b>\n\n"
        msg += ", ".join(display_coins)
        if len(coins) > 15:
            msg += f"\n...and {len(coins)-15} more."
            
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

    async def show_balance(self, update: Update):
        try:
            balance = self.trading_bot.data.get_balance()
            msg = f"💰 <b>WALLET:</b> ${balance:.2f}"
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        except:
            await update.message.reply_text("⚠️ Ошибка баланса (проверьте API).")

    def run(self):
        print("🚀 Titan Telegram Control Listening...")
        self.app.run_polling()

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    bot = TitanTelegramBot()
    bot.run()
