# Trading Bot Metrics Exporter
"""
Prometheus metrics exporter for Trading Bot
============================================
"""

import time
import logging
from datetime import datetime
from typing import Dict, Optional
from dataclasses import dataclass

import requests
from prometheus_client import start_http_server, Gauge, Counter, Histogram

logger = logging.getLogger(__name__)


@dataclass
class TradingMetrics:
    """Trading metrics dataclass"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    total_pnl_percent: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    equity: float = 0.0
    balance: float = 0.0
    open_positions: int = 0
    circuit_breaker_state: int = 0  # 0=OPEN, 1=HALF_OPEN, 2=CLOSED
    daily_pnl: float = 0.0
    daily_loss: float = 0.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0


class MetricsExporter:
    """Prometheus metrics exporter for Trading Bot"""
    
    def __init__(self, port: int = 9091):
        self.port = port
        self.metrics = TradingMetrics()
        
        # Define Prometheus metrics
        self.gauge_total_trades = Gauge(
            'trading_bot_total_trades',
            'Total number of trades executed'
        )
        self.gauge_winning_trades = Gauge(
            'trading_bot_winning_trades',
            'Number of winning trades'
        )
        self.gauge_losing_trades = Gauge(
            'trading_bot_losing_trades',
            'Number of losing trades'
        )
        self.gauge_win_rate = Gauge(
            'trading_bot_win_rate',
            'Win rate percentage'
        )
        self.gauge_total_pnl = Gauge(
            'trading_bot_total_pnl',
            'Total profit/loss in USD'
        )
        self.gauge_total_pnl_percent = Gauge(
            'trading_bot_total_pnl_percent',
            'Total profit/loss percentage'
        )
        self.gauge_max_drawdown = Gauge(
            'trading_bot_max_drawdown',
            'Maximum drawdown percentage'
        )
        self.gauge_sharpe_ratio = Gauge(
            'trading_bot_sharpe_ratio',
            'Sharpe ratio'
        )
        self.gauge_equity = Gauge(
            'trading_bot_equity',
            'Current account equity'
        )
        self.gauge_balance = Gauge(
            'trading_bot_balance',
            'Current account balance'
        )
        self.gauge_open_positions = Gauge(
            'trading_bot_open_positions',
            'Number of open positions'
        )
        self.gauge_circuit_breaker_state = Gauge(
            'trading_bot_circuit_breaker_state',
            'Circuit breaker state (0=OPEN, 1=HALF_OPEN, 2=CLOSED)'
        )
        self.gauge_daily_pnl = Gauge(
            'trading_bot_daily_pnl',
            'Daily profit/loss'
        )
        self.gauge_daily_loss = Gauge(
            'trading_bot_daily_loss',
            'Daily loss amount'
        )
        self.gauge_consecutive_wins = Gauge(
            'trading_bot_consecutive_wins',
            'Number of consecutive wins'
        )
        self.gauge_consecutive_losses = Gauge(
            'trading_bot_consecutive_losses',
            'Number of consecutive losses'
        )
        
        # Trade duration histogram
        self.histogram_trade_duration = Histogram(
            'trading_bot_trade_duration_seconds',
            'Duration of trades in seconds',
            buckets=(60, 300, 900, 1800, 3600, 7200, 14400, 28800, 86400)
        )
        
        # PnL histogram
        self.histogram_pnl = Histogram(
            'trading_bot_pnl_usd',
            'Profit/loss per trade in USD',
            buckets=(-1000, -500, -200, -100, -50, -20, -10, -5, 0, 5, 10, 20, 50, 100, 200, 500, 1000)
        )
    
    def start(self):
        """Start the metrics server"""
        start_http_server(self.port)
        logger.info(f"Metrics server started on port {self.port}")
    
    def update(self, metrics: TradingMetrics):
        """Update all metrics"""
        self.gauge_total_trades.set(metrics.total_trades)
        self.gauge_winning_trades.set(metrics.winning_trades)
        self.gauge_losing_trades.set(metrics.losing_trades)
        self.gauge_win_rate.set(metrics.win_rate)
        self.gauge_total_pnl.set(metrics.total_pnl)
        self.gauge_total_pnl_percent.set(metrics.total_pnl_percent)
        self.gauge_max_drawdown.set(metrics.max_drawdown)
        self.gauge_sharpe_ratio.set(metrics.sharpe_ratio)
        self.gauge_equity.set(metrics.equity)
        self.gauge_balance.set(metrics.balance)
        self.gauge_open_positions.set(metrics.open_positions)
        self.gauge_circuit_breaker_state.set(metrics.circuit_breaker_state)
        self.gauge_daily_pnl.set(metrics.daily_pnl)
        self.gauge_daily_loss.set(metrics.daily_loss)
        self.gauge_consecutive_wins.set(metrics.consecutive_wins)
        self.gauge_consecutive_losses.set(metrics.consecutive_losses)
    
    def record_trade(self, pnl: float, duration_seconds: float):
        """Record a trade for histogram metrics"""
        self.histogram_pnl.observe(pnl)
        self.histogram_trade_duration.observe(duration_seconds)
    
    def get_metrics(self) -> Dict:
        """Get current metrics as dictionary"""
        return {
            "total_trades": self.gauge_total_trades._value.get(),
            "winning_trades": self.gauge_winning_trades._value.get(),
            "losing_trades": self.gauge_losing_trades._value.get(),
            "win_rate": self.gauge_win_rate._value.get(),
            "total_pnl": self.gauge_total_pnl._value.get(),
            "total_pnl_percent": self.gauge_total_pnl_percent._value.get(),
            "max_drawdown": self.gauge_max_drawdown._value.get(),
            "sharpe_ratio": self.gauge_sharpe_ratio._value.get(),
            "equity": self.gauge_equity._value.get(),
            "balance": self.gauge_balance._value.get(),
            "open_positions": self.gauge_open_positions._value.get(),
            "circuit_breaker_state": self.gauge_circuit_breaker_state._value.get(),
            "daily_pnl": self.gauge_daily_pnl._value.get(),
            "daily_loss": self.gauge_daily_loss._value.get(),
            "consecutive_wins": self.gauge_consecutive_wins._value.get(),
            "consecutive_losses": self.gauge_consecutive_losses._value.get()
        }


# Global metrics exporter instance
_metrics_exporter: Optional[MetricsExporter] = None


def init_metrics_exporter(port: int = 9091):
    """Initialize the global metrics exporter"""
    global _metrics_exporter
    _metrics_exporter = MetricsExporter(port)
    _metrics_exporter.start()
    return _metrics_exporter


def get_metrics_exporter() -> Optional[MetricsExporter]:
    """Get the global metrics exporter"""
    return _metrics_exporter


def update_metrics(metrics: TradingMetrics):
    """Update metrics with new data"""
    if _metrics_exporter:
        _metrics_exporter.update(metrics)


def record_trade(pnl: float, duration_seconds: float):
    """Record a trade for histogram metrics"""
    if _metrics_exporter:
        _metrics_exporter.record_trade(pnl, duration_seconds)
