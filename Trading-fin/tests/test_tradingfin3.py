"""
Unit tests for Tradingfin3.0 components
========================================
"""

import pytest
import sys
import os
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mean_reversion_bybit import (
    RiskManager,
    PerformanceTracker,
    NewsEngine,
    NewsSentiment,
    RiskLevel,
    CircuitBreakerState
)


class TestRiskManager:
    """Tests for RiskManager class"""
    
    def test_init(self):
        """Test RiskManager initialization"""
        rm = RiskManager(
            total_capital=10000,
            max_risk_per_trade_percent=2.0,
            max_daily_loss_percent=5.0,
            max_position_size_percent=10.0,
            max_correlation=0.7
        )
        assert rm.total_capital == 10000
        assert rm.max_risk_per_trade_percent == 2.0
        assert rm.max_daily_loss_percent == 5.0
        assert rm.max_position_size_percent == 10.0
        assert rm.max_correlation == 0.7
    
    def test_can_open_trade(self):
        """Test trade permission check"""
        rm = RiskManager(
            total_capital=10000,
            max_risk_per_trade_percent=2.0,
            max_daily_loss_percent=5.0,
            max_position_size_percent=10.0,
            max_correlation=0.7
        )
        
        # Should allow trade within limits
        allowed, reason = rm.can_open_trade(
            symbol="BTCUSDT",
            position_size_usd=500,
            current_volatility=0.02,
            normal_volatility=0.01
        )
        assert allowed is True
    
    def test_register_position(self):
        """Test position registration"""
        rm = RiskManager(
            total_capital=10000,
            max_risk_per_trade_percent=2.0,
            max_daily_loss_percent=5.0,
            max_position_size_percent=10.0,
            max_correlation=0.7
        )
        
        rm.register_position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000,
            position_size=500,
            confluence_score=85
        )
        
        assert len(rm.open_positions) == 1
        assert rm.open_positions[0].symbol == "BTCUSDT"
    
    def test_close_position(self):
        """Test position closing"""
        rm = RiskManager(
            total_capital=10000,
            max_risk_per_trade_percent=2.0,
            max_daily_loss_percent=5.0,
            max_position_size_percent=10.0,
            max_correlation=0.7
        )
        
        rm.register_position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000,
            position_size=500,
            confluence_score=85
        )
        
        rm.close_position(
            symbol="BTCUSDT",
            exit_price=51000,
            pnl=100
        )
        
        assert len(rm.open_positions) == 0
        assert len(rm.closed_positions) == 1
    
    def test_circuit_breaker(self):
        """Test circuit breaker logic"""
        rm = RiskManager(
            total_capital=10000,
            max_risk_per_trade_percent=2.0,
            max_daily_loss_percent=5.0,
            max_position_size_percent=10.0,
            max_correlation=0.7
        )
        
        # Simulate losses
        for i in range(5):
            rm.close_position(
                symbol=f"BTC{i}USDT",
                exit_price=49000,
                pnl=-200
            )
        
        # Should trigger circuit breaker after 3 losses
        assert rm.circuit_breaker_state == CircuitBreakerState.HALF_OPEN


class TestPerformanceTracker:
    """Tests for PerformanceTracker class"""
    
    def test_init(self):
        """Test PerformanceTracker initialization"""
        pt = PerformanceTracker(initial_capital=10000)
        assert pt.initial_capital == 10000
        assert len(pt.trades) == 0
    
    def test_add_trade(self):
        """Test trade recording"""
        pt = PerformanceTracker(initial_capital=10000)
        
        trade = {
            "symbol": "BTCUSDT",
            "side": "LONG",
            "entry_price": 50000,
            "exit_price": 51000,
            "pnl": 100,
            "pnl_percent": 2.0,
            "timestamp": datetime.now(),
            "confluence_score": 85,
            "regime": "trending"
        }
        
        pt.add_trade(trade)
        
        assert len(pt.trades) == 1
        assert pt.trades[0].symbol == "BTCUSDT"
    
    def test_get_statistics(self):
        """Test statistics calculation"""
        pt = PerformanceTracker(initial_capital=10000)
        
        # Add some winning trades
        for i in range(5):
            pt.add_trade({
                "symbol": "BTCUSDT",
                "side": "LONG",
                "entry_price": 50000,
                "exit_price": 51000,
                "pnl": 100,
                "pnl_percent": 2.0,
                "timestamp": datetime.now(),
                "confluence_score": 85,
                "regime": "trending"
            })
        
        # Add some losing trades
        for i in range(2):
            pt.add_trade({
                "symbol": "ETHUSDT",
                "side": "SHORT",
                "entry_price": 3000,
                "exit_price": 3100,
                "pnl": -50,
                "pnl_percent": -1.0,
                "timestamp": datetime.now(),
                "confluence_score": 70,
                "regime": "ranging"
            })
        
        stats = pt.get_statistics()
        
        assert stats["total_trades"] == 7
        assert stats["win_rate"] == pytest.approx(71.4, rel=0.1)
        assert stats["total_pnl"] == 400
        assert stats["max_drawdown"] == 0  # No drawdown in winning streak
    
    def test_get_per_symbol_stats(self):
        """Test per-symbol statistics"""
        pt = PerformanceTracker(initial_capital=10000)
        
        pt.add_trade({
            "symbol": "BTCUSDT",
            "side": "LONG",
            "entry_price": 50000,
            "exit_price": 51000,
            "pnl": 100,
            "pnl_percent": 2.0,
            "timestamp": datetime.now(),
            "confluence_score": 85,
            "regime": "trending"
        })
        
        pt.add_trade({
            "symbol": "ETHUSDT",
            "side": "SHORT",
            "entry_price": 3000,
            "exit_price": 3100,
            "pnl": -50,
            "pnl_percent": -1.0,
            "timestamp": datetime.now(),
            "confluence_score": 70,
            "regime": "ranging"
        })
        
        symbol_stats = pt.get_per_symbol_stats()
        
        assert "BTCUSDT" in symbol_stats
        assert "ETHUSDT" in symbol_stats
        assert symbol_stats["BTCUSDT"]["total_trades"] == 1
        assert symbol_stats["ETHUSDT"]["total_trades"] == 1


class TestNewsSentiment:
    """Tests for NewsSentiment class"""
    
    def test_init(self):
        """Test NewsSentiment initialization"""
        sentiment = NewsSentiment(
            score=0.5,
            headline="Positive news",
            source="CryptoPanic",
            timestamp=datetime.now()
        )
        
        assert sentiment.score == 0.5
        assert sentiment.headline == "Positive news"
        assert sentiment.source == "CryptoPanic"
    
    def test_is_bullish(self):
        """Test bullish detection"""
        sentiment = NewsSentiment(
            score=0.7,
            headline="Bitcoin surges to new all-time high",
            source="CryptoPanic",
            timestamp=datetime.now()
        )
        
        assert sentiment.is_bullish() is True
        assert sentiment.is_bearish() is False
    
    def test_is_bearish(self):
        """Test bearish detection"""
        sentiment = NewsSentiment(
            score=-0.6,
            headline="Exchange sees massive outflow",
            source="CryptoPanic",
            timestamp=datetime.now()
        )
        
        assert sentiment.is_bearish() is True
        assert sentiment.is_bullish() is False
    
    def test_is_critical(self):
        """Test critical event detection"""
        sentiment = NewsSentiment(
            score=-0.8,
            headline="Major exchange hacked - millions stolen",
            source="CryptoPanic",
            timestamp=datetime.now()
        )
        
        assert sentiment.is_critical() is True
    
    def test_should_block_trading(self):
        """Test trading block logic"""
        # Critical event should block trading
        critical = NewsSentiment(
            score=-0.9,
            headline="Exchange hacked - millions stolen",
            source="CryptoPanic",
            timestamp=datetime.now()
        )
        assert critical.should_block_trading() is True
        
        # Mild negative should not block
        mild = NewsSentiment(
            score=-0.3,
            headline="Market correction expected",
            source="CryptoPanic",
            timestamp=datetime.now()
        )
        assert mild.should_block_trading() is False


class TestNewsEngine:
    """Tests for NewsEngine class"""
    
    @patch('requests.get')
    def test_get_market_sentiment(self, mock_get):
        """Test market sentiment retrieval"""
        # Mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "news": [
                {
                    "title": "Bitcoin surges",
                    "source": "CryptoPanic",
                    "published_at": datetime.now().isoformat(),
                    "category": "market",
                    "important": False
                }
            ]
        }
        mock_get.return_value = mock_response
        
        engine = NewsEngine(
            api_key="test_key",
            max_daily_loss_percent=5.0
        )
        
        sentiment = engine.get_market_sentiment("BTC")
        
        assert sentiment is not None
        assert sentiment.source == "CryptoPanic"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
