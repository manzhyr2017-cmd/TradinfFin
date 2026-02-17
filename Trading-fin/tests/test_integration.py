"""
Integration tests for Tradingfin3.0 components
===============================================
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


class TestRiskManagerIntegration:
    """Integration tests for RiskManager"""
    
    def test_full_trading_cycle(self):
        """Test complete trading cycle with risk management"""
        rm = RiskManager(
            total_capital=10000,
            max_risk_per_trade_percent=2.0,
            max_daily_loss_percent=5.0,
            max_position_size_percent=10.0,
            max_correlation=0.7
        )
        
        # Open positions
        rm.register_position("BTCUSDT", "LONG", 50000, 500, 85)
        rm.register_position("ETHUSDT", "LONG", 3000, 300, 80)
        
        # Close positions with mixed results
        rm.close_position("BTCUSDT", 51000, 100)  # Win
        rm.close_position("ETHUSDT", 2900, -50)   # Loss
        
        # Check state
        assert len(rm.open_positions) == 0
        assert len(rm.closed_positions) == 2
        assert rm.total_pnl == 50
    
    def test_circuit_breaker_triggers(self):
        """Test circuit breaker triggers after max losses"""
        rm = RiskManager(
            total_capital=10000,
            max_risk_per_trade_percent=2.0,
            max_daily_loss_percent=5.0,
            max_position_size_percent=10.0,
            max_correlation=0.7
        )
        
        # Simulate 3 consecutive losses
        for i in range(3):
            rm.close_position(
                symbol=f"BTC{i}USDT",
                exit_price=49000,
                pnl=-200
            )
        
        # Circuit breaker should be triggered
        assert rm.circuit_breaker_state == CircuitBreakerState.HALF_OPEN
        
        # Should not allow new trades
        allowed, reason = rm.can_open_trade("BTCUSDT", 500)
        assert allowed is False
        assert "Circuit Breaker" in reason


class TestPerformanceTrackerIntegration:
    """Integration tests for PerformanceTracker"""
    
    def test_sharpe_ratio_calculation(self):
        """Test Sharpe ratio calculation with realistic data"""
        pt = PerformanceTracker(initial_capital=10000)
        
        # Simulate 30 trading days
        for day in range(30):
            pnl = 100 + (day * 5)  # Gradually increasing profits
            pt.add_trade({
                "symbol": "BTCUSDT",
                "side": "LONG",
                "entry_price": 50000 + day * 100,
                "exit_price": 50000 + day * 100 + 100,
                "pnl": pnl,
                "pnl_percent": pnl / 10000 * 100,
                "timestamp": datetime.now() - timedelta(days=30-day),
                "confluence_score": 85,
                "regime": "trending"
            })
        
        stats = pt.get_statistics()
        
        # Sharpe ratio should be positive with consistent profits
        assert stats["sharpe_ratio"] > 0
        assert stats["total_pnl"] > 0
    
    def test_drawdown_calculation(self):
        """Test drawdown calculation"""
        pt = PerformanceTracker(initial_capital=10000)
        
        # Add winning trades
        for i in range(5):
            pt.add_trade({
                "symbol": "BTCUSDT",
                "side": "LONG",
                "entry_price": 50000,
                "exit_price": 51000,
                "pnl": 200,
                "pnl_percent": 2.0,
                "timestamp": datetime.now() - timedelta(days=5-i),
                "confluence_score": 85,
                "regime": "trending"
            })
        
        # Add a big loss
        pt.add_trade({
            "symbol": "ETHUSDT",
            "side": "SHORT",
            "entry_price": 3000,
            "exit_price": 3200,
            "pnl": -1000,
            "pnl_percent": -10.0,
            "timestamp": datetime.now(),
            "confluence_score": 70,
            "regime": "ranging"
        })
        
        stats = pt.get_statistics()
        
        # Should have drawdown from the big loss
        assert stats["max_drawdown"] > 0


class TestNewsEngineIntegration:
    """Integration tests for NewsEngine"""
    
    def test_critical_event_detection(self):
        """Test detection of critical events"""
        engine = NewsEngine(
            api_key="test_key",
            max_daily_loss_percent=5.0
        )
        
        # Test with critical keywords
        critical_headlines = [
            "Major exchange hacked",
            "Regulatory crackdown imminent",
            "Systemic risk detected",
            "Bankruptcy filing expected"
        ]
        
        for headline in critical_headlines:
            sentiment = NewsSentiment(
                score=-0.8,
                headline=headline,
                source="CryptoPanic",
                timestamp=datetime.now()
            )
            assert sentiment.is_critical() is True
    
    def test_sentiment_filtering(self):
        """Test sentiment-based trading filtering"""
        engine = NewsEngine(
            api_key="test_key",
            max_daily_loss_percent=5.0
        )
        
        # Test bullish sentiment
        bullish = NewsSentiment(
            score=0.7,
            headline="Institutional adoption increases",
            source="CryptoPanic",
            timestamp=datetime.now()
        )
        assert bullish.is_bullish() is True
        
        # Test bearish sentiment
        bearish = NewsSentiment(
            score=-0.6,
            headline="Whale sells massive amount",
            source="CryptoPanic",
            timestamp=datetime.now()
        )
        assert bearish.is_bearish() is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
