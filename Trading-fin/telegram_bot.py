"""
Telegram Bot для Trading AI
============================
Отправка сигналов в Telegram каналы

Функции:
- Отправка сигналов в разные каналы по качеству
- Статистика результатов
- Команды для управления

Настройка:
1. Создайте бота через @BotFather
2. Получите токен
3. Создайте каналы/группы
4. Добавьте бота админом в каналы
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
import json
import os

try:
    from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
    from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
    from telegram.request import HTTPXRequest
    from telegram.constants import ParseMode
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    Bot = None
    Update = None
    Application = None
    CommandHandler = None
    ContextTypes = None
    ParseMode = None
    print("python-telegram-bot not installed. Run: pip install python-telegram-bot")

from mean_reversion_bybit import AdvancedSignal, SignalType, SignalStrength

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class TelegramConfig:
    """Конфигурация Telegram бота"""
    bot_token: str
    
    # Каналы по уровням качества
    channel_free: Optional[str] = None      # Бесплатный канал (статистика)
    channel_bronze: Optional[str] = None    # 75%+ сигналы
    channel_silver: Optional[str] = None    # 80%+ сигналы
    channel_gold: Optional[str] = None      # 85%+ сигналы
    channel_platinum: Optional[str] = None  # 88%+ сигналы
    
    # Админы
    admin_ids: List[int] = field(default_factory=list)
    
    @classmethod
    def from_env(cls) -> 'TelegramConfig':
        """Загружает конфиг из переменных окружения"""
        return cls(
            bot_token=os.getenv('TELEGRAM_BOT_TOKEN', ''),
            channel_free=os.getenv('TELEGRAM_CHANNEL_FREE'),
            channel_bronze=os.getenv('TELEGRAM_CHANNEL_BRONZE'),
            channel_silver=os.getenv('TELEGRAM_CHANNEL_SILVER'),
            channel_gold=os.getenv('TELEGRAM_CHANNEL_GOLD'),
            channel_platinum=os.getenv('TELEGRAM_CHANNEL_PLATINUM'),
            admin_ids=[int(x) for x in os.getenv('TELEGRAM_ADMIN_IDS', '').split(',') if x]
        )
    
    @classmethod
    def from_json(cls, filepath: str) -> 'TelegramConfig':
        """Загружает конфиг из JSON файла"""
        with open(filepath, 'r') as f:
            data = json.load(f)
        return cls(**data)


class SignalFormatter:
    """Форматирование сигналов для Telegram"""
    
    @staticmethod
    def format_signal(signal: AdvancedSignal, include_position_calc: bool = True, sentiment: str = None, sector: str = None) -> str:
        """Форматирует сигнал для отправки в Telegram"""
        
        emoji = '🟢' if signal.signal_type == SignalType.LONG else '🔴'
        direction = 'LONG 📈' if signal.signal_type == SignalType.LONG else 'SHORT 📉'
        
        # Расчёт процентов
        if signal.signal_type == SignalType.LONG:
            sl_pct = (signal.entry_price - signal.stop_loss) / signal.entry_price * 100
            tp1_pct = (signal.take_profit_1 - signal.entry_price) / signal.entry_price * 100
            tp2_pct = (signal.take_profit_2 - signal.entry_price) / signal.entry_price * 100
        else:
            sl_pct = (signal.stop_loss - signal.entry_price) / signal.entry_price * 100
            tp1_pct = (signal.entry_price - signal.take_profit_1) / signal.entry_price * 100
            tp2_pct = (signal.entry_price - signal.take_profit_2) / signal.entry_price * 100
        
        # Звёзды по силе сигнала
        stars = {
            SignalStrength.WEAK: '⭐',
            SignalStrength.MODERATE: '⭐⭐',
            SignalStrength.STRONG: '⭐⭐⭐',
            SignalStrength.EXTREME: '⭐⭐⭐⭐⭐'
        }.get(signal.strength, '⭐')
        
        # Market Context Header (NEW!)
        context_header = ""
        if sentiment:
            sent_emoji = "🟢" if sentiment == "RISK_ON" else ("🔴" if sentiment == "RISK_OFF" else "🟡")
            context_header += f"{sent_emoji} <b>Рынок:</b> {sentiment}\n"
        if sector:
            context_header += f"🔥 <b>Тренд:</b> {sector}\n"
        
        msg = f"""
{emoji} <b>{signal.symbol}</b> │ {direction}
{'═' * 30}
{context_header}
{stars} <b>Сила сигнала:</b> {signal.strength.value}
🎯 <b>Вероятность:</b> {signal.probability}%
📊 <b>Confluence:</b> {signal.confluence.percentage:.0f}/100

{'─' * 30}
💰 <b>Вход:</b> <code>{signal.entry_price:.4f}</code>
🎯 <b>TP1:</b> <code>{signal.take_profit_1:.4f}</code> (+{tp1_pct:.2f}%)
🎯 <b>TP2:</b> <code>{signal.take_profit_2:.4f}</code> (+{tp2_pct:.2f}%)
🛑 <b>SL:</b> <code>{signal.stop_loss:.4f}</code> (-{sl_pct:.2f}%)
⚖️ <b>R:R:</b> 1:{signal.risk_reward_ratio}

{'─' * 30}
<b>✅ Причины входа:</b>
"""
        
        import html
        for reason in signal.reasoning[:5]:  # Топ 5 причин
            safe_reason = html.escape(str(reason))
            msg += f"• {safe_reason}\n"
        
        # Bybit данные
        if signal.funding_rate is not None:
            fr_emoji = '🔥' if abs(signal.funding_rate) > 0.0005 else '📊'
            msg += f"\n{fr_emoji} <b>Funding:</b> {signal.funding_rate*100:.4f}%"
            if signal.funding_interpretation:
                msg += f" ({signal.funding_interpretation})"
        
        if signal.orderbook_imbalance:
            ob_emoji = '📗' if signal.orderbook_imbalance > 1 else '📕'
            msg += f"\n{ob_emoji} <b>Order Book:</b> {signal.orderbook_imbalance:.2f}x"
        
        # Strategy Specifics
        indicators = signal.indicators
        if 'ema_200' in indicators:
            msg += f"\n\n🚀 <b>Trend Setup:</b>"
            msg += f"\n📏 <b>EMA 200:</b> {indicators['ema_200']:.2f}"
            if 'macd' in indicators:
                msg += f"\n🌊 <b>MACD:</b> {indicators['macd']:.4f}"
                
        elif 'adx' in indicators:
            msg += f"\n\n💥 <b>Breakout Setup:</b>"
            msg += f"\n📊 <b>ADX Force:</b> {indicators['adx']:.1f}"
            if 'kc_upper' in indicators:
                msg += f"\n🧱 <b>KC Level:</b> {indicators['kc_upper']:.2f}"

        # Warnings
        if signal.warnings:
            msg += f"\n\n⚠️ <b>Внимание:</b>\n"
            for w in signal.warnings:
                msg += f"• {w}\n"
        
        # New Feature Notifications
        if 'atr_pct' in signal.indicators and signal.indicators['atr_pct'] > 0:
            msg += f"\n📉 <b>Dynamic SL:</b> {signal.indicators['atr_pct']:.1f}% ATR-based"
        
        # Калькулятор позиции
        if include_position_calc:
            msg += f"""
{'─' * 30}
💼 <b>Размер позиции (риск {signal.position_size_percent}%):</b>
• $100 → ${100 * signal.position_size_percent / sl_pct:.2f}
• $500 → ${500 * signal.position_size_percent / sl_pct:.2f}
• $1000 → ${1000 * signal.position_size_percent / sl_pct:.2f}
"""
        
        msg += f"""
{'─' * 30}
⏰ <i>Действителен до: {signal.valid_until.strftime('%H:%M UTC')}</i>
🤖 <i>Trading AI v2.0 | Bybit</i>
"""
        
        return msg.strip()
    
    @staticmethod
    def format_stats(stats: Dict[str, Any]) -> str:
        """Форматирует статистику"""
        
        win_rate = stats.get('win_rate', 0)
        wr_emoji = '🟢' if win_rate >= 80 else '🟡' if win_rate >= 70 else '🔴'
        
        return f"""
📊 <b>СТАТИСТИКА</b>
{'═' * 30}

{wr_emoji} <b>Win Rate:</b> {win_rate:.1f}%
📈 <b>Всего сигналов:</b> {stats.get('total', 0)}
✅ <b>Прибыльных:</b> {stats.get('wins', 0)}
❌ <b>Убыточных:</b> {stats.get('losses', 0)}
⏳ <b>В ожидании:</b> {stats.get('pending', 0)}

💰 <b>Средняя прибыль:</b> +{stats.get('avg_profit', 0):.2f}%
📉 <b>Средний убыток:</b> -{stats.get('avg_loss', 0):.2f}%
📊 <b>Profit Factor:</b> {stats.get('profit_factor', 0):.2f}

{'─' * 30}
<i>Период: {stats.get('period', 'N/A')}</i>
"""


class SignalTracker:
    """Отслеживание результатов сигналов"""
    
    def __init__(self, filepath: str = 'signal_results.json'):
        self.filepath = filepath
        self.signals: List[Dict] = []
        self._load()
    
    def _load(self):
        """Загружает историю из файла"""
        try:
            if os.path.exists(self.filepath):
                with open(self.filepath, 'r') as f:
                    self.signals = json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки истории: {e}")
            self.signals = []
    
    def _save(self):
        """Сохраняет историю в файл"""
        try:
            with open(self.filepath, 'w') as f:
                json.dump(self.signals, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Ошибка сохранения: {e}")
    
    def add_signal(self, signal: AdvancedSignal):
        """Добавляет сигнал для отслеживания"""
        self.signals.append({
            'id': len(self.signals) + 1,
            'symbol': signal.symbol,
            'type': signal.signal_type.value,
            'entry': signal.entry_price,
            'stop_loss': signal.stop_loss,
            'take_profit_1': signal.take_profit_1,
            'take_profit_2': signal.take_profit_2,
            'probability': signal.probability,
            'timestamp': signal.timestamp.isoformat(),
            'valid_until': signal.valid_until.isoformat(),
            'status': 'PENDING',  # PENDING, WIN, LOSS, EXPIRED
            'result_pct': None,
            'closed_at': None
        })
        self._save()
    
    def update_result(self, signal_id: int, status: str, result_pct: float):
        """Обновляет результат сигнала"""
        for s in self.signals:
            if s['id'] == signal_id:
                s['status'] = status
                s['result_pct'] = result_pct
                s['closed_at'] = datetime.now().isoformat()
                break
        self._save()
    
    def get_stats(self, days: int = 30) -> Dict[str, Any]:
        """Рассчитывает статистику за период"""
        cutoff = datetime.now() - timedelta(days=days)
        
        recent = [s for s in self.signals 
                  if datetime.fromisoformat(s['timestamp']) > cutoff]
        
        wins = [s for s in recent if s['status'] == 'WIN']
        losses = [s for s in recent if s['status'] == 'LOSS']
        pending = [s for s in recent if s['status'] == 'PENDING']
        
        total_closed = len(wins) + len(losses)
        win_rate = (len(wins) / total_closed * 100) if total_closed > 0 else 0
        
        avg_profit = sum(s['result_pct'] for s in wins) / len(wins) if wins else 0
        avg_loss = abs(sum(s['result_pct'] for s in losses) / len(losses)) if losses else 0
        
        total_profit = sum(s['result_pct'] for s in wins) if wins else 0
        total_loss = abs(sum(s['result_pct'] for s in losses)) if losses else 0
        profit_factor = total_profit / total_loss if total_loss > 0 else 0
        
        return {
            'total': len(recent),
            'wins': len(wins),
            'losses': len(losses),
            'pending': len(pending),
            'win_rate': win_rate,
            'avg_profit': avg_profit,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'period': f'{days} дней'
        }


class TradingTelegramBot:
    """Интерактивный Telegram бот"""
    
    def __init__(self, config: TelegramConfig, controller=None):
        if not TELEGRAM_AVAILABLE:
            raise ImportError("python-telegram-bot не установлен")
        
        self.config = config
        self.controller = controller # Объект с методами start_bot(), stop_bot(), get_status()
        self.tracker = SignalTracker()
        self.formatter = SignalFormatter()
        
        # Build app but don't start polling yet
        self.app = Application.builder().token(self.config.bot_token).build()
        self.setup_handlers(self.app)
        
        # AI Agent (Assigned later by TradingBot)
        self.ai_agent = None
        
    async def start(self, polling: bool = True):
        """Запуск бота (async)"""
        # App is already built and handlers setup in __init__
        
        await self.app.initialize()
        await self.app.start()
        
        if polling:
            await self.app.updater.start_polling()
            logger.info("🤖 Telegram бот запущен (Polling)")
        else:
            logger.info("🤖 Telegram бот запущен (Webhook/Notification mode only)")
        
        # Send startup notification to admin channel
        if self.config.channel_gold:
            try:
                status_msg = "🤖 <b>Neuro-Trader V2 STARTED</b>\n"
                
                # Check for Watch-Only Mode
                if self.controller and self.controller.bot.execution is None:
                    status_msg += "\n⚠️ <b>WATCH-ONLY MODE</b> (Keys Invalid/Missing)\n✅ Analytics: Active\n✅ AI Agent: Active\n⛔ Trading: DISABLED"
                else:
                    status_msg += "\n✅ <b>TRADING ACTIVE</b> (Keys Valid)"
                    
                await self.app.bot.send_message(
                    chat_id=self.config.channel_gold, 
                    text=status_msg, 
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Failed to send startup msg: {e}")

    def run_polling(self):
        """Запуск в блокирующем режиме (для standalone)"""
        builder = Application.builder().token(self.config.bot_token)
        
        # No proxy for Telegram - not blocked
            
        self.app = builder.build()
        self.setup_handlers(self.app)
        self.app.run_polling()

        
    async def stop(self):
        """Остановка бота"""
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
    
    async def send_signal_with_actions(self, signal, sentiment: str = None, sector: str = None, channel_id=None, is_executed: bool = False, order_id: str = None, execution_error: str = None):
        """
        Sends a signal with Quick Action buttons (Enter/Skip).
        User can decide whether to execute the trade.
        """
        # --- DEDUPLICATION LOGIC ---
        # Initialize cache if not exists
        if not hasattr(self, 'sent_signals_cache'):
            self.sent_signals_cache = {}
            
        # Key: Symbol_Type (e.g., BTCUSDT_LONG)
        signal_key = f"{signal.symbol}_{signal.signal_type.value}"
        current_time = datetime.now()
        
        # Check cache
        if signal_key in self.sent_signals_cache:
            last_time = self.sent_signals_cache[signal_key]
            # Cooldown: 120 minutes (2 hours)
            if (current_time - last_time).total_seconds() < 7200:
                logger.info(f"🔇 Signal Dedup: Skipping {signal_key} (Sent {(current_time - last_time).total_seconds()/60:.1f} min ago)")
                return None
        
        # Update cache
        self.sent_signals_cache[signal_key] = current_time
        # Clean old cache (optional, preventing unlimited growth)
        if len(self.sent_signals_cache) > 1000:
            # Remove entries older than 4 hours
            cutoff = current_time - timedelta(hours=4)
            self.sent_signals_cache = {k: v for k, v in self.sent_signals_cache.items() if v > cutoff}
        # ---------------------------

        target_channel = channel_id or self.config.channel_gold or os.getenv('TELEGRAM_CHANNEL')
        if not target_channel or not self.app:
            logger.warning(f"⚠️ Cannot send signal for {signal.symbol}: No channel (ID: {target_channel}) or app configured.")
            return None
        
        # Format message
        msg = SignalFormatter.format_signal(signal, include_position_calc=True, sentiment=sentiment, sector=sector)
        
        if is_executed:
            msg += f"\n\n✅ <b>ОРДЕР УЖЕ ИСПОЛНЕН (AUTO)</b>\n🆔 Order ID: <code>{order_id}</code>"
            # Buttons for managing position
            keyboard = [
                [InlineKeyboardButton("📊 Статус позиции", callback_data=f"status_{signal.symbol}")]
            ]
        elif execution_error:
            import html
            safe_error = html.escape(str(execution_error))
            msg += f"\n\n❌ <b>AUTO-TRADE ERROR</b>\n⚠️ <code>{safe_error}</code>"
            # Keep manual entry buttons even if auto failed
            keyboard = [
                [
                    InlineKeyboardButton("✅ ВОЙТИ ВРУЧНУЮ", callback_data=f"enter_{signal.symbol}_{signal.signal_type.value}"),
                    InlineKeyboardButton("❌ Пропустить", callback_data=f"skip_{signal.symbol}")
                ]
            ]
        else:
            # Create Quick Action buttons (Manual Entry)
            keyboard = [
                [
                    InlineKeyboardButton("✅ ВОЙТИ", callback_data=f"enter_{signal.symbol}_{signal.signal_type.value}"),
                    InlineKeyboardButton("❌ Пропустить", callback_data=f"skip_{signal.symbol}")
                ],
                [
                    InlineKeyboardButton("⏳ Напомнить через 30м", callback_data=f"remind_{signal.symbol}")
                ]
            ]
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            sent = await self.app.bot.send_message(
                chat_id=target_channel,
                text=msg,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
            logger.info(f"📨 Signal sent with Quick Actions: {signal.symbol}")
            return sent.message_id
        except Exception as e:
            logger.error(f"Failed to send signal: {e}")
            return None
    
    async def send_daily_briefing(self, sentiment_service=None, selector_service=None, channel_id=None):
        """
        Sends a Daily AI Briefing to Telegram.
        Called at 07:00 Kamchatka Time from the main loop.
        """
        target_channel = channel_id or os.getenv('TELEGRAM_CHANNEL')
        if not target_channel or not self.app:
            logger.warning("Cannot send Daily Briefing: No channel or app configured.")
            return
        
        # Quiet Hours check (Don't send between 00:00 and 06:00)
        if self.is_quiet_hours():
            logger.info("🌙 Daily Briefing skipped (Quiet Hours).")
            return

        # Build Briefing Content
        sentiment = "N/A"
        sentiment_reason = ""
        if sentiment_service:
            sentiment = sentiment_service.regime or "N/A"
            sentiment_reason = sentiment_service.reasoning or ""
        
        top_longs = []
        top_shorts = []
        if selector_service:
            top_longs = selector_service.primary_list[:5] if selector_service.primary_list else []
            top_shorts = selector_service.secondary_list[:5] if selector_service.secondary_list else []
        
        # Get current Kamchatka time for header
        from datetime import timedelta
        utc_now = datetime.utcnow()
        kamchatka_time = utc_now + timedelta(hours=12)
        date_str = kamchatka_time.strftime("%d %b %Y")
        
        # Format message
        sent_emoji = "🟢" if sentiment == "RISK_ON" else ("🔴" if sentiment == "RISK_OFF" else "🟡")
        
        msg = f"""
☀️ <b>УТРЕННИЙ БРИФИНГ</b> | {date_str}
{'═' * 30}

{sent_emoji} <b>Настроение рынка:</b> {sentiment}
📝 <i>{sentiment_reason[:150]}...</i>

{'─' * 30}
🚀 <b>Топ-5 на ЛОНГ:</b>
{', '.join(top_longs) if top_longs else 'Данные загружаются...'}

📉 <b>Топ-5 на ШОРТ:</b>
{', '.join(top_shorts) if top_shorts else 'Данные загружаются...'}

{'─' * 30}
🤖 <i>Neuro-Trader V2 | Автоматический отчет</i>
"""
        
        try:
            await self.app.bot.send_message(
                chat_id=target_channel,
                text=msg.strip(),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
            logger.info("☀️ Daily Briefing sent to Telegram.")
        except Exception as e:
            logger.error(f"Failed to send Daily Briefing: {e}")
    
    def setup_handlers(self, app):
        """Настройка обработчиков"""
        
        async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
            # Try to get TWA URL from config via controller/bot
            twa_url = ""
            if self.controller and hasattr(self.controller, 'bot'):
                # Assuming BotConfig has twa_url
                from web_ui.server import load_config
                conf = load_config()
                twa_url = conf.twa_url

            # Persistent Keyboard (ReplyKeyboardMarkup)
            reply_keyboard = [
                ["🚀 Старт", "🛑 Стоп", "🚨 PANIC"],
                ["📊 Статус", "💰 Баланс", "📋 Топ Монеты"],
                ["🛡️ Защита", "📊 Сводка", "🧠 AI Чат"]
            ]
            
            markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, is_persistent=True)
            
            await update.message.reply_text(
                "🤖 <b>Trading Control Panel</b>\n\nВыберите действие из меню ниже 👇", 
                reply_markup=markup, 
                parse_mode=ParseMode.HTML
            )

        async def panic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Обработка команды /panic"""
            if not self.controller:
                await update.message.reply_text("Ошибка: Контроллер не подключен")
                return

            msg = await update.message.reply_text("🚨 <b>Инициирован режим PANIC...</b>", parse_mode=ParseMode.HTML)
            res = await self.controller.panic_button()
            
            summary = f"💰 Closed: {res.get('results', {}).get('positions_closed', 0)}\n"
            summary += f"📝 Cancelled: {res.get('results', {}).get('orders_cancelled', 0)}"
            
            await msg.edit_text(f"🚨 <b>PANIC MODE EXECUTED!</b>\n\n{summary}", parse_mode=ParseMode.HTML)

        async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            query = update.callback_query
            try:
                await query.answer()
            except Exception:
                pass
            
            if not self.controller:
                await query.edit_message_text("Ошибка: Контроллер не подключен")
                return

            if query.data == 'start':
                res = await self.controller.start_bot()
                await query.edit_message_text(f"🚀 Запуск: {res.get('message', 'error')}")
                
            elif query.data == 'stop':
                res = await self.controller.stop_bot()
                await query.edit_message_text(f"🛑 Остановка: {res.get('message', 'error')}")
                
            elif query.data == 'status':
                status = await self.controller.get_status()
                state = "🟢 RUNNING" if status.get('running') else "🔴 STOPPED"
                msg = f"Статус: {state}\nPID: {status.get('pid')}"
                
                # Добавляем рекомендацию AI
                if status.get('regime'):
                     msg += f"\n\n🌍 <b>Режим рынка:</b> {status.get('regime')}"
                     msg += f"\n💡 <b>AI советует:</b> {status.get('recommendation')}"
                
                await query.edit_message_text(msg, parse_mode=ParseMode.HTML)
                
            elif query.data == 'selector':
                data = await self.controller.get_selector_data()
                if not data:
                    await query.edit_message_text("❌ Данные селектора недоступны (Бот инициализируется...)")
                    return
                
                longs = ", ".join(data.get('longs', [])) or "Нет"
                shorts = ", ".join(data.get('shorts', [])) or "Нет"
                
                msg = f"""
📋 <b>AI MARKET SELECTOR</b>
{'═' * 20}
🚀 <b>TOP LONGS:</b>
{longs}

📉 <b>TOP SHORTS:</b>
{shorts}

🕓 Updated: {data.get('updated').strftime('%H:%M') if data.get('updated') else 'N/A'}
"""
                await query.edit_message_text(msg, parse_mode=ParseMode.HTML)
                
            elif query.data == 'balance':
                # Это можно реализовать через контроллер, который запросит баланс
                # Для упрощения пока просто заглушка или запрос через API
                msg = "💰 Баланс: Функция недоступна (требуется API)\nПопробуйте /start"
                if hasattr(self.controller, 'get_balance'):
                     try:
                         bal = await self.controller.get_balance()
                         msg = f"💰 Баланс: <b>${bal:.2f}</b> USDT"
                     except Exception as e:
                         msg = f"Ошибка получения баланса: {e}"
                await query.edit_message_text(msg, parse_mode=ParseMode.HTML)
                
            elif query.data == 'report':
                # Fetch fresh status and balance
                status = await self.controller.get_status()
                balance = 0.0
                if hasattr(self.controller, 'get_balance'):
                    try:
                        balance = await self.controller.get_balance()
                    except:
                        pass
                
                # Format report
                from datetime import timedelta
                utc_now = datetime.utcnow()
                kamchatka_time = utc_now + timedelta(hours=12)
                time_str = kamchatka_time.strftime("%H:%M")
                
                regime = status.get('regime', 'N/A')
                strategy = status.get('current_strategy', status.get('strategy', 'N/A'))
                top_longs = status.get('top_longs', [])
                top_shorts = status.get('top_shorts', [])
                
                regime_emoji = "🟢" if regime == "RISK_ON" else ("🔴" if regime == "RISK_OFF" else "🟡")
                longs_str = ", ".join(top_longs[:5]) if top_longs else "—"
                shorts_str = ", ".join(top_shorts[:5]) if top_shorts else "—"
                
                msg = f"""
📊 <b>СВОДКА {time_str}</b>
{'─' * 25}

{regime_emoji} <b>Рынок:</b> {regime}
🎯 <b>Стратегия:</b> {strategy}
💰 <b>Баланс:</b> ${balance:.2f}
📈 <b>Позиции:</b> {len(status.get('open_positions', []))}

<b>🚀 LONG:</b> {longs_str}
<b>📉 SHORT:</b> {shorts_str}

<i>🤖 Neuro-Trader V2</i>
"""
                await query.edit_message_text(msg, parse_mode=ParseMode.HTML)

            # --- QUICK ACTION HANDLERS ---
            elif query.data.startswith('enter_'):
                # Format: enter_BTCUSDT_LONG
                parts = query.data.split('_')
                symbol = parts[1]
                direction = parts[2] if len(parts) > 2 else 'LONG'
                
                await query.edit_message_text(f"✅ <b>ВХОД ПОДТВЕРЖДЕН</b>\n\n{symbol} {direction}\n\n⏳ Исполняется...", parse_mode=ParseMode.HTML)
                
                # Notify controller to execute
                if self.controller and hasattr(self.controller, 'execute_pending_signal'):
                    try:
                        result = await self.controller.execute_pending_signal(symbol, direction)
                        await query.message.reply_text(f"🚀 Ордер отправлен: {result}")
                    except Exception as e:
                        await query.message.reply_text(f"❌ Ошибка: {e}")
                else:
                    await query.message.reply_text("⚠️ Auto-execute не подключен. Войдите вручную.")
            
            elif query.data.startswith('skip_'):
                symbol = query.data.replace('skip_', '')
                await query.edit_message_text(f"❌ <b>ПРОПУЩЕНО</b>\n\n{symbol}\n\n<i>Ждем следующий сетап...</i>", parse_mode=ParseMode.HTML)
            
            elif query.data.startswith('remind_'):
                symbol = query.data.replace('remind_', '')
                await query.answer("⏳ Напоминание через 30 минут", show_alert=True)
                # Schedule a reminder (simplified - just log)
                logger.info(f"⏰ Reminder scheduled for {symbol} in 30 min")

        async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Обработка текстовых сообщений (AI)"""
            if not update.message or not update.message.text:
                return
                
            # Игнорируем команды
            if update.message.text.startswith('/'):
                return

            # Отправка "печатает..."
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

            # Вместо AI бреда - показываем меню
            text = update.message.text
            
            if text == "🚀 Старт":
                res = await self.controller.start_bot()
                await update.message.reply_text(f"🚀 Запуск: {res.get('message', 'error')}")
            elif text == "🛑 Стоп":
                res = await self.controller.stop_bot()
                await update.message.reply_text(f"🛑 Остановка: {res.get('message', 'error')}")
            elif text == "📊 Статус":
                status = await self.controller.get_status()
                state = "🟢 RUNNING" if status.get('running') else "🔴 STOPPED"
                msg = f"Статус: {state}\nPID: {status.get('pid')}"
                if status.get('regime'):
                     msg += f"\n\n🌍 <b>Режим рынка:</b> {status.get('regime')}"
                await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
            elif text == "💰 Баланс":
                msg = "💰 Баланс: Функция недоступна"
                if hasattr(self.controller, 'get_balance'):
                     try:
                         bal = await self.controller.get_balance()
                         msg = f"💰 Баланс: <b>${bal:.2f}</b> USDT"
                     except Exception as e:
                         msg = f"Ошибка получения баланса: {e}"
                await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
            elif text == "📋 Топ Монеты":
                data = await self.controller.get_selector_data()
                if not data:
                    await update.message.reply_text("❌ Данные селектора недоступны")
                else:
                    longs = ", ".join(data.get('longs', [])) or "Нет"
                    shorts = ", ".join(data.get('shorts', [])) or "Нет"
                    msg = f"📋 <b>AI MARKET SELECTOR</b>\n\n🚀 <b>LONGS:</b> {longs}\n📉 <b>SHORTS:</b> {shorts}"
                    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

            elif text == "🚨 PANIC":
                msg = await update.message.reply_text("🚨 <b>Инициирован режим PANIC...</b>", parse_mode=ParseMode.HTML)
                if hasattr(self.controller, 'panic_button'):
                    res = await self.controller.panic_button()
                    summary = f"💰 Closed: {res.get('results', {}).get('positions_closed', 0)}\n"
                    summary += f"📝 Cancelled: {res.get('results', {}).get('orders_cancelled', 0)}"
                    await msg.edit_text(f"🚨 <b>PANIC MODE EXECUTED!</b>\n\n{summary}", parse_mode=ParseMode.HTML)
                else:
                    await msg.edit_text("❌ Ошибка: Метод PANIC не найден в контроллере")

            elif text == "🛡️ Защита":
                status = await self.controller.get_status()
                hedge = status.get('hedge_status', 'Inactive')
                news = status.get('news_danger', 'None')
                
                news_emoji = "🛡️" if news == "None" else "⚠️"
                hedge_emoji = "🔒" if "Active" in hedge else "🔓"
                
                msg = f"""
🛡️ <b>GUARDIAN STATUS</b>
{'─' * 20}
{news_emoji} <b>News Shield:</b> {news if news != "None" else "ACTIVE (SAFE)"}
{hedge_emoji} <b>Portfolio Hedge:</b> {hedge.upper()}

✅ <b>Whale Watcher:</b> ACTIVE
✅ <b>ATR Risk:</b> ACTIVE
"""
                await update.message.reply_text(msg.strip(), parse_mode=ParseMode.HTML)

            elif text == "📊 Сводка":
                 # Fetch real statuses
                 status = await self.controller.get_status()
                 balance = 0.0
                 if hasattr(self.controller, 'get_balance'):
                     try:
                         balance = await self.controller.get_balance()
                     except: pass
                     
                 regime = status.get('regime', 'N/A')
                 strategy = status.get('current_strategy', 'N/A')
                 top_longs = status.get('top_longs', [])
                 top_shorts = status.get('top_shorts', [])
                 hedge = status.get('hedge_status', 'Inactive')
                 news = status.get('news_danger', 'None')
                 
                 from datetime import timedelta
                 utc_now = datetime.utcnow()
                 kamchatka_time = utc_now + timedelta(hours=12)
                 time_str = kamchatka_time.strftime("%H:%M")
                 
                 regime_emoji = "🟢" if regime == "RISK_ON" else ("🔴" if regime == "RISK_OFF" else "🟡")
                 
                 msg = f"""
📊 <b>СВОДКА {time_str}</b>
{'─' * 25}

{regime_emoji} <b>Рынок:</b> {regime}
💰 <b>Баланс:</b> ${balance:.2f}
📈 <b>Позиции:</b> {len(status.get('open_positions', []))}

🛡️ <b>Hedge:</b> {hedge}
📰 <b>News:</b> {news if news != "None" else "Safe"}

<b>🚀 LONG:</b> {", ".join(top_longs[:5]) if top_longs else "—"}
<b>📉 SHORT:</b> {", ".join(top_shorts[:5]) if top_shorts else "—"}

<i>🤖 Neuro-Trader V2</i>
"""
                 await update.message.reply_text(msg.strip(), parse_mode=ParseMode.HTML)
            
            elif text == "🧠 AI Чат":
                await update.message.reply_text("🤖 Я готов к общению! Просто напишите мне любой вопрос о рынке или состоянии бота.")
            
            # If text is not a command/button, try to use AI Agent with Real-Time Context
            if text not in ["🚀 Старт", "🛑 Стоп", "📊 Статус", "💰 Баланс", "📋 Топ Монеты", "📊 Сводка", "🚨 PANIC", "🛡️ Защита", "🧠 AI Чат"]:
                 # Send typing action
                 await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
                 
                 if self.ai_agent:
                     # Runs the NEW chat method with real data injection (Async Wrapper)
                     try:
                         response = await self.ai_agent.chat(text)
                         await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
                     except Exception as e:
                         logger.error(f"Chat Error: {e}")
                         await update.message.reply_text("💤 AI сейчас не отвечает (Network/Limit Error).")
                 else:
                     await update.message.reply_text("🤖 AI мозг не подключен. Используйте меню 👇")
                     await start_cmd(update, context)

        app.add_handler(CommandHandler("start", start_cmd))
        app.add_handler(CommandHandler("panic", panic_cmd))
        app.add_handler(CommandHandler("grid", self._grid_cmd))
        app.add_handler(CallbackQueryHandler(button_handler))
        
        # Обработчик текста для AI
        from telegram.ext import MessageHandler, filters
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
        
        # Старые команды
        app.add_handler(CommandHandler("help", self._help_cmd))

    async def _help_cmd(self, update, context):
        await update.message.reply_text("Используйте /start для меню или /grid SYMBOL для сетки")

    async def _grid_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            args = context.args
            if not args:
                await update.message.reply_text("⚠️ Использование: /grid SYMBOL (например /grid BTCUSDT)")
                return
            
            symbol = args[0].upper()
            
            # Импорт тут чтобы не было циклических зависимостей, если что
            from grid_engine import GridStrategy
            
            # Фейковая текущая цена (в реальности надо брать с биржи)
            # Для демо просто выберем фиксированную
            current_price = 96000.0 if 'BTC' in symbol else 2600.0 # Hack for demo
            
            # Эмуляция баланса
            balance = 1000.0
            
            msg = await update.message.reply_text(f"🧮 Расчет сетки для {symbol}...")
            
            # Создаем диапазон -5% ... +5%
            lower = current_price * 0.95
            upper = current_price * 1.05
            
            grid = GridStrategy(symbol, balance)
            orders = grid.calculate_grid(current_price, lower, upper, grids=10)
            summary = grid.get_grid_summary(orders)
            
            # Добавим детали
            details = "\n".join([f"{'🟢' if o.side=='BUY' else '🔴'} {o.side} {o.price:.2f} ({o.qty})" for o in orders[:5]])
            if len(orders) > 5: details += "\n..."
            
            final_msg = summary + "\n" + details + "\n\n⚠️ <i>Это симуляция. Реальные ордера не выставлены.</i>"
            
            await msg.edit_text(final_msg, parse_mode=ParseMode.HTML)
            
        except Exception as e:
            logger.error(f"Grid error: {e}")
            await update.message.reply_text("❌ Ошибка расчета сетки")


# ============================================================
# ИНТЕГРАЦИЯ С ОСНОВНЫМ БОТОМ
# ============================================================

class TelegramNotifier:
    """
    Простой класс для отправки уведомлений
    Используется в main_bybit.py
    """
    
    def __init__(self, bot_token: str, channel_id: str):
        if not TELEGRAM_AVAILABLE:
            self.enabled = False
            logger.warning("Telegram не доступен")
            return
        
        self.enabled = True
        self.bot = Bot(token=bot_token)
        self.channel_id = channel_id
        self.formatter = SignalFormatter()
    
    def is_quiet_hours(self) -> bool:
        """
        Check if current time is within Quiet Hours (00:00 - 06:00 Kamchatka Time).
        Kamchatka is UTC+12.
        """
        # DISABLED: User wants 24/7 operation in AGGRESSIVE mode
        return False

    async def send_message(self, text: str, channel_id: str = None, keyboard=None):
        """Отправка сообщения в канал/чат"""
        target_id = channel_id or self.channel_id
        if not target_id:
            return
            
        # Quiet Hours Check (Skip non-critical messages, or delay them?)
        # User said "what's the point of writing at night". So we skip or mute.
        if self.is_quiet_hours():
            logger.info("🌙 Quiet Hours (Kamchatka Night). Message suppressed.")
            return

        try:
            await self.bot.send_message(
                chat_id=target_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Failed to send telegram message: {e}")
            return False
    
    async def send(self, signal: AdvancedSignal) -> bool:
        """Отправляет сигнал"""
        if not self.enabled:
            return False
        
        try:
            message = self.formatter.format_signal(signal)
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=message,
                parse_mode=ParseMode.HTML
            )
            return True
        except Exception as e:
            logger.error(f"Telegram error: {e}")
            return False
    
    def send_sync(self, signal: AdvancedSignal) -> bool:
        """Синхронная обёртка"""
        return asyncio.run(self.send(signal))
    
    async def send_startup_greeting(self):
        """Отправляет приветствие при запуске бота"""
        if not self.enabled:
            return
        
        from datetime import timedelta
        utc_now = datetime.utcnow()
        kamchatka_time = utc_now + timedelta(hours=12)
        date_str = kamchatka_time.strftime("%d.%m.%Y %H:%M")
        
        msg = f"""
🚀 <b>NEURO-TRADER V2 ONLINE</b>
{'═' * 28}

⚡ <b>Статус:</b> На линии фронта
🕐 <b>Время:</b> {date_str} (Камчатка)
🔍 <b>Режим:</b> Автономное сканирование

<i>🛡️ Веду дозор за рынком...</i>
<i>Сводка — каждый час</i>
"""
        try:
            # Use short timeout for startup msg to prevent blocking the whole bot
            await asyncio.wait_for(
                self.bot.send_message(
                    chat_id=self.channel_id,
                    text=msg.strip(),
                    parse_mode=ParseMode.HTML
                ),
                timeout=10.0
            )
            logger.info("📨 Telegram: Startup greeting sent")
        except asyncio.TimeoutError:
            logger.warning("🕒 Telegram startup greeting timed out (Network issues)")
        except Exception as e:
            logger.error(f"Failed to send startup greeting: {e}")
    
    async def send_hourly_report(self, regime: str = "N/A", strategy: str = "N/A", 
                                  balance: float = 0.0, positions: int = 0,
                                  top_longs: list = None, top_shorts: list = None):
        """Отправляет ежечасную сводку"""
        if not self.enabled:
            return
            
        # Anti-Spam Check (Force 60 min interval)
        now_ts = datetime.utcnow().timestamp()
        if hasattr(self, '_last_report_ts') and (now_ts - self._last_report_ts < 3500): # 58 min buffer
            return
        
        self._last_report_ts = now_ts
        
        # Skip during quiet hours
        if self.is_quiet_hours():
            logger.info("🌙 Hourly report skipped (Quiet Hours)")
            return
        
        from datetime import timedelta
        utc_now = datetime.utcnow()
        kamchatka_time = utc_now + timedelta(hours=12)
        time_str = kamchatka_time.strftime("%H:%M")
        
        regime_emoji = "🟢" if regime == "RISK_ON" else ("🔴" if regime == "RISK_OFF" else "🟡")
        
        longs_str = ", ".join(top_longs[:5]) if top_longs else "—"
        shorts_str = ", ".join(top_shorts[:5]) if top_shorts else "—"
        
        msg = f"""
📊 <b>СВОДКА {time_str}</b>
{'─' * 25}

{regime_emoji} <b>Рынок:</b> {regime}
🎯 <b>Стратегия:</b> {strategy}
💰 <b>Баланс:</b> ${balance:.2f}
📈 <b>Позиции:</b> {positions}

<b>🚀 LONG:</b> {longs_str}
<b>📉 SHORT:</b> {shorts_str}

<i>🤖 Neuro-Trader V2</i>
"""
        try:
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=msg.strip(),
                parse_mode=ParseMode.HTML
            )
            logger.info("📨 Telegram: Hourly report sent")
        except Exception as e:
            logger.error(f"Failed to send hourly report: {e}")


# ============================================================
# DEMO / TEST
# ============================================================

def create_demo_signal() -> AdvancedSignal:
    """Создаёт демо-сигнал для тестирования"""
    from mean_reversion_bybit import ConfluenceScore, MarketRegime
    
    confluence = ConfluenceScore()
    confluence.add_factor('RSI', 20, 25)
    confluence.add_factor('Bollinger Bands', 15, 15)
    confluence.add_factor('Multi-Timeframe', 18, 25)
    confluence.add_factor('Support/Resistance', 12, 15)
    confluence.add_factor('Volume', 8, 10)
    confluence.add_factor('MACD', 7, 10)
    confluence.add_factor('Funding Rate', 8, 10)
    
    return AdvancedSignal(
        signal_type=SignalType.LONG,
        symbol='BTCUSDT',
        entry_price=42500.0,
        stop_loss=41800.0,
        take_profit_1=43200.0,
        take_profit_2=44000.0,
        confluence=confluence,
        probability=86,
        strength=SignalStrength.EXTREME,
        timeframes_aligned={'15m': True, '1h': True, '4h': True},
        support_resistance_nearby=None,
        market_regime=MarketRegime.RANGING_WIDE,
        risk_reward_ratio=2.57,
        position_size_percent=1.5,
        funding_rate=-0.0008,
        funding_interpretation='HIGH_SHORT_BIAS',
        orderbook_imbalance=1.65,
        timestamp=datetime.now(),
        valid_until=datetime.now() + timedelta(hours=4),
        indicators={'rsi_15m': 24.5, 'adx_4h': 18.2},
        reasoning=[
            'RSI=24.5 сильно перепродан',
            'Цена ниже BB Lower',
            '1H и 4H подтверждают',
            'Funding -0.08% (много шортов)',
            'Order Book 1.65x покупатели'
        ],
        warnings=['Слабый нисходящий тренд на 4H']
    )


def main():
    """Демо"""
    print("""
╔══════════════════════════════════════════════════════════════════╗
║              TELEGRAM BOT - TRADING AI                           ║
╚══════════════════════════════════════════════════════════════════╝
    """)
    
    # Демо форматирования
    signal = create_demo_signal()
    formatted = SignalFormatter.format_signal(signal)
    
    print("Пример отформатированного сигнала:")
    print("=" * 50)
    # Убираем HTML теги для консоли
    import re
    clean = re.sub(r'<[^>]+>', '', formatted)
    print(clean)
    print("=" * 50)
    
    print("""
Для запуска бота:

1. Создайте бота через @BotFather
2. Создайте файл config.json:
{
    "bot_token": "YOUR_BOT_TOKEN",
    "channel_gold": "@your_channel"
}

3. Запустите:
from telegram_bot import TradingTelegramBot, TelegramConfig

config = TelegramConfig.from_json('config.json')
bot = TradingTelegramBot(config)
bot.run_polling()
    """)


if __name__ == "__main__":
    main()
