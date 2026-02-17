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
        self.bot_instance = TitanBotUltimateFinal()
        self.bot_thread = None
        
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
            await self.status_cmd(update, context) # Simplified for now

    async def start_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            ["🚀 Start Analysis", "🛑 Stop Bot"],
            ["📊 Status", "🧠 Composite Score"],
            ["🚨 Emergency Stop"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "💎 <b>TITAN BOT 2026 - ULTIMATE FINAL</b>\n\nДобро пожаловать в центр управления. Выберите действие:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )

    async def status_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        status = "🟢 ACTIVE" if self.bot_instance.is_running else "🔴 STANDBY"
        msg = f"<b>TITAN STATUS:</b> {status}\n"
        msg += f"<b>Symbol:</b> {config.SYMBOL}\n"
        msg += f"<b>Time:</b> {datetime.now().strftime('%H:%M:%S')}"
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

    async def run_bot_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.bot_instance.is_running:
            await update.message.reply_text("Бот уже запущен!")
            return
            
        await update.message.reply_text("🚀 Инициализация систем TITAN...")
        # Запускаем бота в отдельном потоке
        self.bot_thread = threading.Thread(target=self.bot_instance.start)
        self.bot_thread.daemon = True
        self.bot_thread.start()
        await update.message.reply_text("✅ TITAN BOT запущен и анализирует рынок.")

    async def stop_bot_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.bot_instance.is_running:
            await update.message.reply_text("Бот не запущен.")
            return
            
        self.bot_instance.is_running = False
        await update.message.reply_text("🛑 Остановка TITAN BOT...")

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
