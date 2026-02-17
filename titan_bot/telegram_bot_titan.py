"""
TITAN BOT 2026 - Telegram Control Bot
Интерактивное управление через Telegram
"""

import os
import asyncio
import logging
import threading
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode
from main import TitanBotUltimateFinal
import config

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TitanTG")

class TitanTelegramBot:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.symbols = ["ETHUSDT", "SOLUSDT", "BTCUSDT"]
        self.bots = {s: TitanBotUltimateFinal(symbol=s) for s in self.symbols}
        self.bot_threads = {}
        
        # Build app
        self.app = Application.builder().token(self.token).build()
        self._setup_handlers()
        
    def _setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start_cmd))
        self.app.add_handler(CommandHandler("status", self.status_cmd))
        self.app.add_handler(CommandHandler("run", self.run_bot_cmd))
        self.app.add_handler(CommandHandler("stop", self.stop_bot_cmd))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.text_handler))
        self.app.add_handler(CallbackQueryHandler(self.button_handler))

    async def text_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        if text == "🚀 Start Analysis":
            await self.run_bot_cmd(update, context)
        elif text == "🛑 Stop Bot":
            await self.stop_bot_cmd(update, context)
        elif text == "📊 Status":
            await self.status_cmd(update, context)
        elif text == "🚨 Emergency Stop":
            await self.stop_bot_cmd(update, context)
        elif text == "🧠 Composite Score":
            await self.status_cmd(update, context)

    async def start_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            ["🚀 Start Analysis", "🛑 Stop Bot"],
            ["📊 Status", "🧠 Composite Score"],
            ["🚨 Emergency Stop"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            f"💎 <b>TITAN BOT 2026 - MULTI-MODE</b>\n\nМониторинг: {', '.join(self.symbols)}\n\nВыберите действие:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )

    async def status_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = "<b>TITAN MULTI-STATUS:</b>\n\n"
        for s, bot in self.bots.items():
            status = "🟢 ACTIVE" if bot.is_running else "🔴 STANDBY"
            msg += f"• <b>{s}:</b> {status}\n"
            
        msg += f"\n🕓 <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}"
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

    async def run_bot_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        started = []
        for s, bot in self.bots.items():
            if not bot.is_running:
                thread = threading.Thread(target=bot.start)
                thread.daemon = True
                thread.start()
                self.bot_threads[s] = thread
                started.append(s)
                await asyncio.sleep(2)  # Задержка 2 секунды между запуском ботов
        
        if started:
            await update.message.reply_text(f"🚀 Запуск систем TITAN для: {', '.join(started)}")
        else:
            await update.message.reply_text("Все боты уже запущены.")

    async def stop_bot_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        stopped = []
        for s, bot in self.bots.items():
            if bot.is_running:
                bot.is_running = False
                stopped.append(s)
                
        if stopped:
            await update.message.reply_text(f"🛑 Останавливаю TITAN для: {', '.join(stopped)}")
        else:
            await update.message.reply_text("Боты не запущены.")

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        # Handle buttons if needed

    def run(self):
        print("🤖 Titan Telegram Bot Starting...")
        self.app.run_polling()

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    bot = TitanTelegramBot()
    bot.run()
