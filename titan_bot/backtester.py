"""
TITAN BOT 2026 - Backtesting Engine
Проверь стратегию на истории прежде чем рисковать деньгами!
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Dict, Callable
from datetime import datetime
import config

@dataclass
class BacktestTrade:
    """Сделка в бэктесте"""
    entry_time: datetime
    exit_time: datetime
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_percent: float
    r_multiple: float
    exit_reason: str  # 'TP', 'SL', 'TRAILING', 'SIGNAL'

@dataclass
class BacktestResult:
    """Результат бэктеста"""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    total_pnl: float
    total_pnl_percent: float
    max_drawdown: float
    max_drawdown_percent: float
    avg_win: float
    avg_loss: float
    avg_r_multiple: float
    sharpe_ratio: float
    best_trade: float
    worst_trade: float
    avg_holding_time: float
    trades: List[BacktestTrade]
    equity_curve: pd.Series


class Backtester:
    """
    Движок бэктестинга.
    
    ПОЧЕМУ ЭТО ОБЯЗАТЕЛЬНО:
    
    1. Проверяешь стратегию на 1000+ сделок
    2. Видишь реальный win rate и profit factor
    3. Понимаешь максимальную просадку
    4. НЕ теряешь реальные деньги на тестирование
    
    ПРАВИЛА БЭКТЕСТИНГА:
    - Не подгоняй параметры под историю (overfitting)
    - Используй out-of-sample тестирование
    - Учитывай комиссии и проскальзывание
    - Результат в бэктесте всегда ЛУЧШЕ чем в реале
    """
    
    def __init__(self, initial_balance: float = 300):
        self.initial_balance = initial_balance
        self.commission_rate = 0.001  # 0.1% комиссия
        self.slippage = 0.0005        # 0.05% проскальзывание
    
    def run(
        self,
        data: pd.DataFrame,
        strategy_func: Callable,
        risk_per_trade: float = 0.02,
        default_rr: float = 2.5
    ) -> BacktestResult:
        """
        Запускает бэктест.
        
        Args:
            data: DataFrame с OHLCV данными
            strategy_func: Функция стратегии (принимает df, возвращает сигналы)
            risk_per_trade: Риск на сделку (0.02 = 2%)
            default_rr: Risk/Reward по умолчанию
        
        Returns:
            BacktestResult с полной статистикой
        """
        balance = self.initial_balance
        trades = []
        equity_curve = [balance]
        position = None
        
        # Получаем сигналы от стратегии
        signals = strategy_func(data)
        
        for i in range(len(data)):
            current_bar = data.iloc[i]
            current_price = current_bar['close']
            
            # Если есть открытая позиция — проверяем выход
            if position is not None:
                exit_result = self._check_exit(position, current_bar)
                
                if exit_result:
                    # Закрываем позицию
                    trade = self._close_position(
                        position, 
                        exit_result['price'],
                        exit_result['reason'],
                        current_bar.name if hasattr(current_bar, 'name') else i # Use index or name as timestamp
                    )
                    
                    balance += trade.pnl
                    trades.append(trade)
                    equity_curve.append(balance)
                    position = None
            
            # Если нет позиции — проверяем вход
            if position is None and i < len(signals):
                signal = signals.iloc[i] if hasattr(signals, 'iloc') else signals[i]
                
                if signal and signal.get('action') in ['BUY', 'SELL']:
                    position = self._open_position(
                        side='LONG' if signal['action'] == 'BUY' else 'SHORT',
                        entry_price=current_price,
                        stop_loss=signal.get('stop_loss', current_price * 0.98),
                        take_profit=signal.get('take_profit', current_price * 1.05),
                        balance=balance,
                        risk_per_trade=risk_per_trade,
                        entry_time=current_bar.name if hasattr(current_bar, 'name') else i
                    )
        
        # Закрываем оставшуюся позицию
        if position is not None:
            trade = self._close_position(
                position,
                data.iloc[-1]['close'],
                'END_OF_DATA',
                data.iloc[-1].name if hasattr(data.iloc[-1], 'name') else len(data)
            )
            balance += trade.pnl
            trades.append(trade)
        
        # Рассчитываем статистику
        return self._calculate_statistics(trades, equity_curve)
    
    def _open_position(
        self,
        side: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        balance: float,
        risk_per_trade: float,
        entry_time: datetime
    ) -> dict:
        """Открывает позицию."""
        
        # Добавляем проскальзывание
        if side == 'LONG':
            entry_price *= (1 + self.slippage)
        else:
            entry_price *= (1 - self.slippage)
        
        # Рассчитываем размер позиции
        risk_amount = balance * risk_per_trade
        stop_distance = abs(entry_price - stop_loss)
        
        if stop_distance == 0:
            return None
        
        quantity = risk_amount / stop_distance
        
        # Комиссия за вход
        entry_commission = entry_price * quantity * self.commission_rate
        
        return {
            'side': side,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'quantity': quantity,
            'entry_time': entry_time,
            'initial_risk': risk_amount,
            'entry_commission': entry_commission
        }
    
    def _check_exit(self, position: dict, bar: pd.Series) -> Optional[dict]:
        """Проверяет условия выхода."""
        
        high = bar['high']
        low = bar['low']
        
        if position['side'] == 'LONG':
            # Проверяем стоп-лосс
            if low <= position['stop_loss']:
                return {'price': position['stop_loss'], 'reason': 'SL'}
            
            # Проверяем тейк-профит
            if high >= position['take_profit']:
                return {'price': position['take_profit'], 'reason': 'TP'}
        
        else:  # SHORT
            if high >= position['stop_loss']:
                return {'price': position['stop_loss'], 'reason': 'SL'}
            
            if low <= position['take_profit']:
                return {'price': position['take_profit'], 'reason': 'TP'}
        
        return None
    
    def _close_position(
        self,
        position: dict,
        exit_price: float,
        exit_reason: str,
        exit_time: datetime
    ) -> BacktestTrade:
        """Закрывает позицию и возвращает результат."""
        
        # Добавляем проскальзывание
        if position['side'] == 'LONG':
            exit_price *= (1 - self.slippage)
        else:
            exit_price *= (1 + self.slippage)
        
        # Рассчитываем PnL
        if position['side'] == 'LONG':
            gross_pnl = (exit_price - position['entry_price']) * position['quantity']
        else:
            gross_pnl = (position['entry_price'] - exit_price) * position['quantity']
        
        # Комиссия за выход
        exit_commission = exit_price * position['quantity'] * self.commission_rate
        
        # Чистый PnL
        net_pnl = gross_pnl - position['entry_commission'] - exit_commission
        
        # PnL в процентах
        position_value = position['entry_price'] * position['quantity']
        pnl_percent = (net_pnl / position_value) * 100 if position_value > 0 else 0
        
        # R-Multiple
        r_multiple = net_pnl / position['initial_risk'] if position['initial_risk'] > 0 else 0
        
        return BacktestTrade(
            entry_time=position['entry_time'],
            exit_time=exit_time,
            side=position['side'],
            entry_price=position['entry_price'],
            exit_price=exit_price,
            quantity=position['quantity'],
            pnl=net_pnl,
            pnl_percent=pnl_percent,
            r_multiple=r_multiple,
            exit_reason=exit_reason
        )
    
    def _calculate_statistics(
        self,
        trades: List[BacktestTrade],
        equity_curve: List[float]
    ) -> BacktestResult:
        """Рассчитывает статистику бэктеста."""
        
        if not trades:
            return self._empty_result()
        
        # Базовая статистика
        winners = [t for t in trades if t.pnl > 0]
        losers = [t for t in trades if t.pnl < 0]
        
        total_trades = len(trades)
        winning_trades = len(winners)
        losing_trades = len(losers)
        
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        # PnL
        total_pnl = sum(t.pnl for t in trades)
        total_pnl_percent = (total_pnl / self.initial_balance) * 100
        
        # Profit Factor
        gross_profit = sum(t.pnl for t in winners) if winners else 0
        gross_loss = abs(sum(t.pnl for t in losers)) if losers else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Средние значения
        avg_win = gross_profit / winning_trades if winning_trades > 0 else 0
        avg_loss = gross_loss / losing_trades if losing_trades > 0 else 0
        avg_r = sum(t.r_multiple for t in trades) / total_trades
        
        # Drawdown
        equity_series = pd.Series(equity_curve)
        rolling_max = equity_series.expanding().max()
        drawdown = equity_series - rolling_max
        max_drawdown = drawdown.min()
        max_drawdown_percent = (max_drawdown / rolling_max[drawdown.idxmin()]) * 100 if not rolling_max.empty else 0
        
        # Sharpe Ratio (упрощённый)
        returns = pd.Series([t.pnl_percent for t in trades])
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0
        
        # Время
        try:
            avg_holding = sum((t.exit_time - t.entry_time).total_seconds() / 3600 for t in trades) / total_trades
        except:
            avg_holding = 0
        
        return BacktestResult(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_pnl=total_pnl,
            total_pnl_percent=total_pnl_percent,
            max_drawdown=max_drawdown,
            max_drawdown_percent=max_drawdown_percent,
            avg_win=avg_win,
            avg_loss=avg_loss,
            avg_r_multiple=avg_r,
            sharpe_ratio=sharpe,
            best_trade=max(t.pnl for t in trades),
            worst_trade=min(t.pnl for t in trades),
            avg_holding_time=avg_holding,
            trades=trades,
            equity_curve=pd.Series(equity_curve)
        )
    
    def _empty_result(self) -> BacktestResult:
        """Пустой результат."""
        return BacktestResult(
            total_trades=0, winning_trades=0, losing_trades=0,
            win_rate=0, profit_factor=0, total_pnl=0, total_pnl_percent=0,
            max_drawdown=0, max_drawdown_percent=0, avg_win=0, avg_loss=0,
            avg_r_multiple=0, sharpe_ratio=0, best_trade=0, worst_trade=0,
            avg_holding_time=0, trades=[], equity_curve=pd.Series([])
        )
    
    def print_report(self, result: BacktestResult):
        """Выводит красивый отчёт."""
        print(f"""
╔══════════════════════════════════════════════════════════╗
║                 BACKTEST REPORT                          ║
╠══════════════════════════════════════════════════════════╣
║  Initial Balance:    ${self.initial_balance:>10.2f}                    ║
║  Final Balance:      ${self.initial_balance + result.total_pnl:>10.2f}                    ║
║  Total P&L:          ${result.total_pnl:>10.2f} ({result.total_pnl_percent:+.1f}%)           ║
╠══════════════════════════════════════════════════════════╣
║  Total Trades:       {result.total_trades:>10}                         ║
║  Winning Trades:     {result.winning_trades:>10}                         ║
║  Losing Trades:      {result.losing_trades:>10}                         ║
║  Win Rate:           {result.win_rate*100:>10.1f}%                        ║
╠══════════════════════════════════════════════════════════╣
║  Profit Factor:      {result.profit_factor:>10.2f}                        ║
║  Avg R-Multiple:     {result.avg_r_multiple:>10.2f}                        ║
║  Sharpe Ratio:       {result.sharpe_ratio:>10.2f}                        ║
╠══════════════════════════════════════════════════════════╣
║  Max Drawdown:       ${result.max_drawdown:>10.2f} ({result.max_drawdown_percent:.1f}%)        ║
║  Best Trade:         ${result.best_trade:>10.2f}                        ║
║  Worst Trade:        ${result.worst_trade:>10.2f}                        ║
║  Avg Holding Time:   {result.avg_holding_time:>10.1f}h                       ║
╚══════════════════════════════════════════════════════════╝
        """)
        
        # Оценка стратегии
        print("\n📊 ОЦЕНКА СТРАТЕГИИ:")
        
        if result.win_rate >= 0.45 and result.profit_factor >= 1.5:
            print("  ✅ Стратегия ПРИБЫЛЬНАЯ. Можно тестировать на демо.")
        elif result.win_rate >= 0.40 and result.profit_factor >= 1.2:
            print("  ⚠️ Стратегия ПОСРЕДСТВЕННАЯ. Нужна оптимизация.")
        else:
            print("  ❌ Стратегия УБЫТОЧНАЯ. Не использовать!")
        
        if result.max_drawdown_percent < -20:
            print(f"  ⚠️ Высокая просадка ({result.max_drawdown_percent:.1f}%). Уменьши риск.")
