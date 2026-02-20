"""
TITAN BOT 2026 - Telegram Control Center
Интерактивный пульт управления торговой системой
"""

import os
import asyncio
import logging
import threading
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
        
        # Список мониторимых пар
        self.symbols = ["ETHUSDT", "BTCUSDT", "SOLUSDT"]
        
        # Инициализация ботов (пока в режиме ожидания)
        self.bots = {s: TitanBotUltimateFinal(symbol=s) for s in self.symbols}
        self.bot_threads = {}
        
        # Build app
        self.app = Application.builder().token(self.token).build()
        self._setup_handlers()
        
        print("🤖 TITAN TELEGRAM CONTROL CENTER ЗАПУЩЕН")
        
    def _setup_handlers(self):
        # Команды
        self.app.add_handler(CommandHandler("start", self.start_cmd))
        self.app.add_handler(CommandHandler("help", self.help_cmd))
        
        # Текстовые обработчики (для кнопок меню)
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.text_handler))
        
        # Callback query (для инлайн кнопок, если будут)
        self.app.add_handler(CallbackQueryHandler(self.button_handler))

    async def start_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Приветствие и главное меню"""
        user = update.effective_user
        
        # Главное меню клавиатуры
        keyboard = [
            [KeyboardButton("🚀 ЗАПУСК ВСЕХ"), KeyboardButton("🛑 СТОП ВСЕХ")],
            [KeyboardButton("📊 СТАТУС"), KeyboardButton("💰 БАЛАНС")],
            [KeyboardButton("📈 АНАЛИЗ (BTC)"), KeyboardButton("📈 АНАЛИЗ (ETH)")],
            [KeyboardButton("⚙️ НАСТРОЙКИ")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
        
        welcome_msg = (
            f"👋 <b>Привет, {user.first_name}!</b>\n\n"
            f"⚡ <b>TITAN BOT CONTROL CENTER</b> готов к работе.\n"
            f"Режим торговли: <b>{config.TRADE_MODE}</b>\n"
            f"Таймфрейм: <b>{config.TIMEFRAME}m</b>\n\n"
            f"Выберите действие в меню 👇"
        )
        
        await update.message.reply_text(welcome_msg, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

    async def text_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка нажатий на кнопки меню"""
        text = update.message.text
        
        if text == "🚀 ЗАПУСК ВСЕХ":
            await self.run_all_bots(update)
        elif text == "🛑 СТОП ВСЕХ":
            await self.stop_all_bots(update)
        elif text == "📊 СТАТУС":
            await self.show_status(update)
        elif text == "💰 БАЛАНС":
            await self.show_balance(update)
        elif "📈 АНАЛИЗ" in text:
            # Извлекаем монету из текста кнопки "📈 АНАЛИЗ (BTC)"
            symbol_key = "BTCUSDT" if "BTC" in text else ("ETHUSDT" if "ETH" in text else config.SYMBOL)
            await self.show_analysis(update, symbol_key)
        elif text == "⚙️ НАСТРОЙКИ":
            await self.show_settings(update)
        else:
            await update.message.reply_text("🤔 Неизвестная команда. Используйте меню.")

    async def run_all_bots(self, update: Update):
        """Запуск всех инстансов ботов"""
        started_list = []
        
        msg = await update.message.reply_text("🔄 Инициализация систем...")
        
        for s, bot in self.bots.items():
            if not bot.is_running:
                # Запускаем в отдельном потоке
                thread = threading.Thread(target=bot.start) # Предполагаем метод start() в main.py
                thread.daemon = True
                thread.start()
                self.bot_threads[s] = thread
                bot.is_running = True # Флаг должен меняться внутри bot.start(), но для UI меняем тут
                started_list.append(s)
                await asyncio.sleep(1) # Пауза чтобы не спамить API при старте
        
        if started_list:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=msg.message_id,
                text=f"🚀 <b>СИСТЕМЫ ЗАПУЩЕНЫ:</b> {', '.join(started_list)}\nУдачи на рынке! Profit is coming. 💸",
                parse_mode=ParseMode.HTML
            )
        else:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=msg.message_id,
                text="✅ Все системы уже работают в штатном режиме."
            )

    async def stop_all_bots(self, update: Update):
        """Остановка всех ботов"""
        stopped_list = []
        for s, bot in self.bots.items():
            if bot.is_running:
                bot.is_running = False # Это должно остановить цикл в main.py
                stopped_list.append(s)
        
        if stopped_list:
            await update.message.reply_text(f"🛑 <b>ОСТАНОВЛЕНО:</b> {', '.join(stopped_list)}", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("💤 Системы уже спят.")

    async def show_status(self, update: Update):
        """Показ статуса"""
        msg = "🖥️ <b>SYSTEM STATUS</b>\n\n"
        
        active_count = 0
        for s, bot in self.bots.items():
            status_icon = "🟢" if bot.is_running else "🔴"
            status_text = "ONLINE" if bot.is_running else "OFFLINE"
            msg += f"{status_icon} <b>{s}:</b> {status_text}\n"
            if bot.is_running: active_count += 1
            
        msg += f"\n🤖 Active Bots: {active_count}/{len(self.bots)}"
        msg += f"\n⏳ Uptime: {(datetime.now()).strftime('%H:%M:%S')}"
        
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

    async def show_balance(self, update: Update):
        """Показ баланса (берем у первого бота, т.к. счет один)"""
        # Берем любой инстанс для запроса к API
        bot = list(self.bots.values())[0]
        
        try:
            balance = bot.data.get_balance()
            pnl_today = bot.risk.trades_today # Это нужно брать из risk manager
            # Считаем PnL по списку сделок сегодня
            pnl_sum = sum(t['pnl'] for t in pnl_today) if hasattr(bot.risk, 'trades_today') else 0.0
            
            msg = (
                f"💰 <b>WALLET BALANCE</b>\n\n"
                f"💵 Total: <b>${balance:.2f}</b>\n"
                f"📅 Today PnL: <b>${pnl_sum:+.2f}</b>\n"
                f"🔒 Risk per Trade: {config.RISK_PER_TRADE*100}%\n"
            )
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
            
        except Exception as e:
            await update.message.reply_text(f"⚠️ Ошибка получения баланса: {str(e)}")

    async def show_analysis(self, update: Update, symbol: str):
        """Запрашивает анализ у конкретного бота"""
        msg = await update.message.reply_text(f"🔍 Анализирую рынок {symbol}...")
        
        bot = self.bots.get(symbol)
        if not bot:
            await context.bot.edit_message_text("❌ Бот для этого символа не найден.", chat_id=update.effective_chat.id, message_id=msg.message_id)
            return

        try:
            # Запускаем анализ вручную
            # ВАЖНО: Это синхронный вызов, может блокировать на пару секунд. 
            # В идеале нужно делать это в executor'е, но пока так.
            
            # Получаем свежие данные
            df = bot.data.get_klines(symbol, limit=100)
            
            # Считаем Composite Score
            # (Здесь мы эмулируем то, что делает bot.run(), но только для отчета)
            mtf = bot.mtf.analyze(symbol)
            smc = bot.smc.analyze(symbol)
            of = bot.orderflow.analyze(symbol)
            
            # Расчет скора
            composite_signal = bot.composite.calculate(
                symbol=symbol,
                mtf_analysis=mtf,
                smc_signal=smc,
                orderflow_signal=of
                # ... остальные компоненты можно добавить
            )
            
            # Формируем красивый отчет
            report = (
                f"📊 <b>ANALYSIS REPORT: {symbol}</b>\n"
                f"{'═'*20}\n"
                f"🏆 <b>SCORE:</b> {composite_signal.total_score:+.1f}\n"
                f"🎯 <b>Direction:</b> {composite_signal.direction} ({composite_signal.strength})\n"
                f"🧠 <b>Confidence:</b> {composite_signal.confidence*100:.0f}%\n\n"
                f"<b>Components:</b>\n"
                f"• MTF: {composite_signal.components.get('mtf', 0):+.2f}\n"
                f"• SMC: {composite_signal.components.get('smc', 0):+.2f}\n"
                f"• OrderFlow: {composite_signal.components.get('orderflow', 0):+.2f}\n\n"
                f"<i>{composite_signal.recommendation}</i>"
            )
            
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id, 
                message_id=msg.message_id, 
                text=report, 
                parse_mode=ParseMode.HTML
            )
            
        except Exception as e:
            logger.error(f"Analysis error: {e}")
            await context.bot.edit_message_text(f"❌ Ошибка анализа: {e}", chat_id=update.effective_chat.id, message_id=msg.message_id)

    async def show_settings(self, update: Update):
        """Показывает текущие настройки"""
        msg = (
            f"⚙️ <b>BOT SETTINGS</b>\n\n"
            f"Mode: <b>{config.TRADE_MODE}</b>\n"
            f"Timeframe: <b>{config.TIMEFRAME}m</b>\n"
            f"Leverage: <b>Cross (Auto)</b>\n"
            f"Risk/Trade: <b>{config.RISK_PER_TRADE*100}%</b>\n"
            f"Stop Loss: <b>Dynamic (ATR)</b>\n"
            f"Take Profit: <b>RR > {config.MIN_RR_RATIO}</b>\n"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

    async def help_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🆘 <b>HELP</b>\n\n"
            "Используйте кнопки меню для управления.\n"
            "Если бот завис, попробуйте перезапустить скрипт на сервере.",
            parse_mode=ParseMode.HTML
        )

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

    def run(self):
        print("🚀 Titan Telegram Bot Listening...")
        self.app.run_polling()

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    bot = TitanTelegramBot()
    bot.run()
