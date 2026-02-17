"""
Backtesting Module
Test strategies on historical data before going live.
"""

import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Results of a backtest run"""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    trades: List[Dict] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)


class Backtester:
    """
    Simple backtester for trading strategies.
    Uses historical kline data to simulate trades.
    """
    
    def __init__(self, client=None, initial_balance: float = 100.0):
        self.client = client
        self.initial_balance = initial_balance
        
    async def fetch_historical_data(
        self, 
        symbol: str, 
        interval: str = "15", 
        limit: int = 500
    ) -> Optional[pd.DataFrame]:
        """Fetch historical klines from Bybit"""
        if not self.client:
            logger.error("No client configured for backtesting")
            return None
            
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            
            params = {
                'category': self.client.category.value,
                'symbol': symbol,
                'interval': interval,
                'limit': limit
            }
            result = await loop.run_in_executor(None, lambda: self.client._request('/v5/market/kline', params))
            
            if not result or 'list' not in result:
                return None
            
            # Convert to DataFrame
            data = []
            for k in result['list']:
                data.append({
                    'timestamp': pd.to_datetime(int(k[0]), unit='ms'),
                    'open': float(k[1]),
                    'high': float(k[2]),
                    'low': float(k[3]),
                    'close': float(k[4]),
                    'volume': float(k[5])
                })
            
            df = pd.DataFrame(data)
            df = df.sort_values('timestamp').reset_index(drop=True)
            return df
            
        except Exception as e:
            logger.error(f"Failed to fetch historical data: {e}")
            return None
    
    def run_backtest(
        self,
        df: pd.DataFrame,
        strategy_func,
        risk_percent: float = 4.0,
        sl_atr_mult: float = 2.0,
        tp_rr: float = 4.0
    ) -> BacktestResult:
        """
        Run backtest on historical data.
        
        Args:
            df: DataFrame with OHLCV data
            strategy_func: Function(df, index) -> 'LONG' | 'SHORT' | None
            risk_percent: % of balance to risk per trade
            sl_atr_mult: ATR multiplier for stop loss
            tp_rr: Risk-Reward ratio for take profit
        """
        result = BacktestResult()
        balance = self.initial_balance
        equity_curve = [balance]
        trades = []
        
        in_position = False
        entry_price = 0
        stop_loss = 0
        take_profit = 0
        direction = None
        entry_idx = 0
        
        # Calculate ATR
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        
        for i in range(20, len(df) - 1):
            current_price = df.iloc[i]['close']
            
            if not in_position:
                # Check for new signal
                signal = strategy_func(df, i)
                
                if signal in ['LONG', 'SHORT']:
                    # Calculate position
                    atr_val = atr.iloc[i]
                    sl_dist = atr_val * sl_atr_mult
                    
                    if signal == 'LONG':
                        entry_price = current_price
                        stop_loss = entry_price - sl_dist
                        take_profit = entry_price + (sl_dist * tp_rr)
                        direction = 'LONG'
                    else:
                        entry_price = current_price
                        stop_loss = entry_price + sl_dist
                        take_profit = entry_price - (sl_dist * tp_rr)
                        direction = 'SHORT'
                    
                    in_position = True
                    entry_idx = i
                    
            else:
                # Check exit conditions
                high_price = df.iloc[i]['high']
                low_price = df.iloc[i]['low']
                
                hit_sl = False
                hit_tp = False
                exit_price = current_price
                
                if direction == 'LONG':
                    if low_price <= stop_loss:
                        hit_sl = True
                        exit_price = stop_loss
                    elif high_price >= take_profit:
                        hit_tp = True
                        exit_price = take_profit
                else:
                    if high_price >= stop_loss:
                        hit_sl = True
                        exit_price = stop_loss
                    elif low_price <= take_profit:
                        hit_tp = True
                        exit_price = take_profit
                
                if hit_sl or hit_tp:
                    # Calculate PnL
                    if direction == 'LONG':
                        pnl_pct = (exit_price - entry_price) / entry_price
                    else:
                        pnl_pct = (entry_price - exit_price) / entry_price
                    
                    risk_amount = balance * (risk_percent / 100)
                    pnl = risk_amount * tp_rr if hit_tp else -risk_amount
                    
                    balance += pnl
                    equity_curve.append(balance)
                    
                    trade = {
                        'entry_idx': entry_idx,
                        'exit_idx': i,
                        'direction': direction,
                        'entry': entry_price,
                        'exit': exit_price,
                        'pnl': pnl,
                        'pnl_pct': pnl_pct * 100,
                        'is_win': hit_tp
                    }
                    trades.append(trade)
                    
                    if hit_tp:
                        result.wins += 1
                    else:
                        result.losses += 1
                    
                    in_position = False
        
        # Calculate final stats
        result.total_trades = len(trades)
        result.trades = trades
        result.equity_curve = equity_curve
        
        if result.total_trades > 0:
            result.win_rate = result.wins / result.total_trades * 100
            result.total_pnl = balance - self.initial_balance
            
            # Win/Loss averages
            wins = [t['pnl'] for t in trades if t['is_win']]
            losses = [t['pnl'] for t in trades if not t['is_win']]
            
            result.avg_win = np.mean(wins) if wins else 0
            result.avg_loss = np.mean(losses) if losses else 0
            
            # Profit factor
            total_wins = sum(wins) if wins else 0
            total_losses = abs(sum(losses)) if losses else 0.0001
            result.profit_factor = total_wins / total_losses
            
            # Max Drawdown
            peak = equity_curve[0]
            max_dd = 0
            for eq in equity_curve:
                if eq > peak:
                    peak = eq
                dd = (peak - eq) / peak * 100
                if dd > max_dd:
                    max_dd = dd
            result.max_drawdown = max_dd
        
        return result


def simple_rsi_strategy(df: pd.DataFrame, idx: int) -> Optional[str]:
    """
    Simple RSI-based strategy for backtesting.
    LONG when RSI < 30, SHORT when RSI > 70.
    """
    # Calculate RSI
    close = df['close']
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    current_rsi = rsi.iloc[idx]
    
    if current_rsi < 30:
        return 'LONG'
    elif current_rsi > 70:
        return 'SHORT'
    return None


async def run_quick_backtest(client, symbol: str = "BTCUSDT") -> Dict:
    """Quick backtest runner for API endpoint"""
    backtester = Backtester(client, initial_balance=100.0)
    
    df = await backtester.fetch_historical_data(symbol, "15", 500)
    if df is None:
        return {"error": "Failed to fetch data"}
    
    result = backtester.run_backtest(
        df, 
        simple_rsi_strategy,
        risk_percent=4.0,
        sl_atr_mult=2.0,
        tp_rr=4.0
    )
    
    return {
        "symbol": symbol,
        "total_trades": result.total_trades,
        "wins": result.wins,
        "losses": result.losses,
        "win_rate": f"{result.win_rate:.1f}%",
        "total_pnl": f"${result.total_pnl:.2f}",
        "profit_factor": f"{result.profit_factor:.2f}",
        "max_drawdown": f"{result.max_drawdown:.1f}%",
        "final_balance": f"${result.equity_curve[-1]:.2f}" if result.equity_curve else "$100.00"
    }
