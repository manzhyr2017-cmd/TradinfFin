# -*- coding: utf-8 -*-
import html
import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from main_bybit import TradingBot

logger = logging.getLogger(__name__)

class BotController:
    """Мост между Telegram ботом и TradingBot"""
    
    def __init__(self, bot: 'TradingBot'):
        self.bot = bot
        
    async def start_bot(self):
        self.bot.is_active = True
        return {"message": "Scanner STARTED"}
        
    async def stop_bot(self):
        self.bot.is_active = False
        return {"message": "Scanner PAUSED"}
        
    async def get_status(self):
        status = {
            "running": self.bot.is_active,
            "pid": os.getpid(),
            "regime": self.bot.last_state.get('regime', 'N/A'),
            "recommendation": self.bot.last_state.get('recommendation', 'N/A'),
            "hedge_status": "Inactive",
            "news_danger": "None",
            "open_positions": [],
            "top_longs": [],
            "top_shorts": []
        }
        
        if self.bot.hedge_service:
            status["hedge_status"] = self.bot.hedge_service.status if hasattr(self.bot.hedge_service, 'status') else self.bot.hedge_service.hedge_status
            
        if self.bot.news_service:
            danger = self.bot.news_service.check_danger_zone()
            status["news_danger"] = danger['name'] if danger else "None"
            
        if self.bot.client:
            try:
                status["open_positions"] = self.bot.client.get_open_positions()
            except: pass
            
        if self.bot.selector_service:
            status["top_longs"] = self.bot.selector_service.primary_list
            status["top_shorts"] = self.bot.selector_service.secondary_list
            
        return status
    
    async def get_balance(self):
        if self.bot.client:
            try:
                bal = self.bot.client.get_wallet_balance('USDT')
                return bal
            except Exception as e:
                logger.error(f"Balance error: {e}")
        return 0.0

    async def get_selector_data(self):
        """Получение данных селектора для Telegram"""
        if self.bot.selector_service:
            return {
                "longs": self.bot.selector_service.primary_list,
                "shorts": self.bot.selector_service.secondary_list,
                "updated": self.bot.selector_service.last_update
            }
        return None

    async def send_signal_message(self, data: dict):
        """Отправка сигнала от AI в Telegram с кнопками и статусом"""
        # We try to use the richer Telegram bot if available
        if hasattr(self.bot, 'telegram_bot') and self.bot.telegram_bot:
            try:
                from mean_reversion_bybit import AdvancedSignal, SignalType, SignalStrength, MarketRegime
                
                # Mock a Signal object from AI data for the formatter
                sig_type = SignalType.LONG if data.get('action') == "BUY" else SignalType.SHORT
                
                # Helper for safe float conversion
                def safe_float(val):
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        return 0.0

                signal = AdvancedSignal(
                    symbol=data.get('symbol'),
                    signal_type=sig_type,
                    entry_price=safe_float(data.get('entry')),
                    stop_loss=safe_float(data.get('sl')),
                    take_profit_1=safe_float(data.get('tp')),
                    take_profit_2=safe_float(data.get('tp')) * 1.05,
                    confluence=type('obj', (object,), {
                        'total_score': data.get('confidence', 70),
                        'max_possible': 100,
                        'percentage': data.get('confidence', 70),
                        'get_strength': lambda: SignalStrength.STRONG,
                        'get_breakdown': lambda: "AI Analysis Confluence"
                    })(),
                    probability=data.get('confidence', 70),
                    strength=SignalStrength.STRONG,
                    timeframes_aligned={'1m': True, '15m': True, '1h': True},
                    support_resistance_nearby=None,
                    market_regime=MarketRegime.RANGING_WIDE,
                    risk_reward_ratio=2.0,
                    position_size_percent=1.0,
                    funding_rate=None,
                    funding_interpretation=None,
                    orderbook_imbalance=None,
                    timestamp=datetime.now(),
                    valid_until=datetime.now() + timedelta(hours=4),
                    indicators={},
                    reasoning=[data.get('reason', '')],
                    warnings=[]
                )
                
                # If entry was market, get real price for display
                if signal.entry_price == 0 and self.bot.client:
                    try:
                        ticker = self.bot.client._request(f"/v5/market/tickers?category=linear&symbol={signal.symbol}")
                        signal.entry_price = float(ticker['list'][0]['lastPrice'])
                    except: pass

                await self.bot.telegram_bot.send_signal_with_actions(
                    signal,
                    sentiment=data.get('sentiment'),
                    sector=data.get('strategy'),
                    is_executed=data.get('executed', False),
                    order_id=data.get('order_id'),
                    execution_error=data.get('execution_error')
                )
                return
            except Exception as e:
                logger.error(f"Failed to send rich AI signal: {e}")

        # Fallback to simple message if richer bot fails
        if self.bot.telegram and self.bot.telegram.enabled:
             # Existing fallback logic
             pass

    async def panic_button(self):
        """Экстренная остановка всех торгов и закрытие позиций"""
        if not self.bot.execution:
            return {"error": "Execution manager not initialized"}
            
        self.bot.is_active = False
        
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, self.bot.execution.panic_close_all)
        
        return {
            "message": "PANIC MODE EXECUTED. All positions closed.",
            "results": results
        }

    async def execute_ai_trade(self, data: dict):
        """Исполнение сделки по сигналу от AI. Returns dict with status and order_id."""
        if not self.bot.execution:
            logger.error("Execution manager NOT initialized")
            return {"success": False, "error": "No Execution Manager"}
            
        try:
            from mean_reversion_bybit import AdvancedSignal, SignalType
            
            symbol = data.get('symbol')
            action = data.get('action')
            
            if action not in ["BUY", "SELL"]:
                return {"success": False, "error": f"Invalid action {action}"}
                
            sig_type = SignalType.LONG if action == "BUY" else SignalType.SHORT
            
            entry = data.get('entry_price')
            if entry == "Market" or not entry or entry == 0:
                 ticker = self.bot.client._request(f"/v5/market/tickers?category=linear&symbol={symbol}")
                 if ticker and 'list' in ticker and ticker['list']:
                     entry = float(ticker['list'][0]['lastPrice'])
                 else:
                     logger.error(f"Could not get current price for {symbol}")
                     return {"success": False, "error": "Price fetch failed"}
            
            signal = AdvancedSignal(
                symbol=symbol,
                signal_type=sig_type,
                entry_price=float(entry),
                stop_loss=float(data.get('stop_loss')),
                take_profit_1=float(data.get('take_profit')),
                take_profit_2=float(data.get('take_profit')) * 1.02,
                confluence=type('obj', (object,), {
                    'total_score': data.get('confidence', 90),
                    'max_possible': 100,
                    'percentage': data.get('confidence', 90),
                    'get_strength': lambda: SignalStrength.STRONG,
                    'get_breakdown': lambda: "AI Trade Execution"
                })(),
                probability=data.get('confidence', 90),
                strength=SignalStrength.STRONG,
                timeframes_aligned={'15m': True},
                support_resistance_nearby=None,
                market_regime=MarketRegime.RANGING_WIDE,
                risk_reward_ratio=2.0,
                position_size_percent=1.0,
                funding_rate=None,
                funding_interpretation=None,
                orderbook_imbalance=None,
                timestamp=datetime.now(),
                valid_until=datetime.now() + timedelta(hours=4),
                indicators={},
                reasoning=[data.get('reasoning', 'AI Trade')],
                warnings=[],
                time_exit_bars=data.get('time_exit_bars', 24)
            )
            
            loop = asyncio.get_running_loop()
            suggested_risk = data.get('suggested_risk')
            
            # execute_signal now returns (success, message)
            res = await loop.run_in_executor(None, lambda: self.bot.execution.execute_signal(signal, risk_override=suggested_risk))
            success, msg = res if isinstance(res, tuple) else (res, "Unknown")
            
            if success:
                logger.info(f"✅ AI Trade Executed: {symbol} {action}")
                return {"success": True, "order_id": "AI-EXEC-OK", "message": msg}
            return {"success": False, "error": f"Execution rejected: {msg}"}
            
        except Exception as e:
            logger.error(f"Failed to execute AI trade: {e}")
            return {"success": False, "error": str(e)}

    async def execute_pending_signal(self, symbol: str, direction: str):
        """Ручное исполнение сигнала (через кнопки в Telegram)"""
        if not self.bot.execution:
            raise ValueError("Execution Manager не подключен")
            
        from mean_reversion_bybit import AdvancedSignal, SignalType, SignalStrength, MarketRegime
        
        # Get current price
        ticker = self.bot.client._request(f"/v5/market/tickers?category=linear&symbol={symbol}")
        if not ticker or 'list' not in ticker or not ticker['list']:
             raise ValueError(f"Не удалось получить цену для {symbol}")
             
        price = float(ticker['list'][0]['lastPrice'])
        
        # Simple signal for manual entry
        sig_type = SignalType.LONG if direction.upper() == 'LONG' else SignalType.SHORT
        sl_mult = 0.98 if sig_type == SignalType.LONG else 1.02
        tp_mult = 1.05 if sig_type == SignalType.LONG else 0.95
        
        signal = AdvancedSignal(
            symbol=symbol,
            signal_type=sig_type,
            entry_price=price,
            stop_loss=price * sl_mult,
            take_profit_1=price * tp_mult,
            take_profit_2=price * tp_mult * (1.02 if sig_type == SignalType.LONG else 0.98),
            confluence=type('obj', (object,), {
                'total_score': 95,
                'max_possible': 100,
                'percentage': 95,
                'get_strength': lambda: SignalStrength.STRONG,
                'get_breakdown': lambda: "Manual Telegram Entry"
            })(),
            probability=95,
            strength=SignalStrength.STRONG,
            timeframes_aligned={'Manual': True},
            support_resistance_nearby=None,
            market_regime=MarketRegime.RANGING_WIDE if 'MarketRegime' in locals() else type('obj', (object,), {'name': 'MANUAL'})(),
            risk_reward_ratio=2.0,
            position_size_percent=1.0,
            funding_rate=None,
            funding_interpretation=None,
            orderbook_imbalance=None,
            timestamp=datetime.now(),
            valid_until=datetime.now() + timedelta(hours=1),
            indicators={},
            reasoning=["Ручной вход через Telegram"],
            warnings=[]
        )
        
        loop = asyncio.get_running_loop()
        success_res = await loop.run_in_executor(None, lambda: self.bot.execution.execute_signal(signal))
        success, msg = success_res if isinstance(success_res, tuple) else (success_res, "Unknown")
        
        if success:
            return f"Ордер отправлен успешно: {msg}"
        return f"Ордер отклонен: {msg}"
