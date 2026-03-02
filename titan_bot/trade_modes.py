"""
TITAN BOT 2026 - Trade Modes
Быстрое переключение между режимами торговли для TITAN BOT
"""

# Пресеты настроек для разных режимов
# v8: Все скоры калиброваны для полного 9-компонентного движка (0-100)
TRADE_MODES = {
    
    "CONSERVATIVE": {
        # Мало сделок, но качественные. Для маленьких депо.
        "composite_min_score": 60,    # v10: Снижено (было 70), т.к. починили фундамент со стопами
        "session_filter": True,
        "session_min_quality": 6,
        "news_filter": True,
        "mtf_strict": True,
        "max_positions": 1,
        "risk_per_trade": 0.01,
        "min_rr": 3.0,
        "cooldown_after_losses": 2,
        "expected_trades_per_day": "1-3"
    },
    
    "MODERATE": {
        # Баланс между качеством и количеством
        "composite_min_score": 45,    # v10: Снижено (было 55)
        "session_filter": True,
        "session_min_quality": 4,
        "news_filter": True,
        "mtf_strict": False,
        "max_positions": 3,
        "risk_per_trade": 0.015,
        "min_rr": 2.5,
        "cooldown_after_losses": 2,
        "expected_trades_per_day": "3-6"
    },
    
    "AGGRESSIVE": {
        # Много сделок, умеренный риск. Для опытных.
        "composite_min_score": 40,    # v10: Возврат к стандарту 40
        "session_filter": False,       # Торгуем в любое время (toxic hours уже заблочены)
        "session_min_quality": 1,
        "news_filter": True,
        "mtf_strict": False,
        "max_positions": 5,
        "risk_per_trade": 0.02,
        "min_rr": 2.0,
        "cooldown_after_losses": 3,
        "expected_trades_per_day": "5-15"
    },
    
    "SCALPER": {
        # Максимум сделок, минимум фильтров
        "composite_min_score": 30,    # v10: Было 35 
        "session_filter": False,
        "session_min_quality": 1,
        "news_filter": False,
        "mtf_strict": False,
        "max_positions": 10,
        "risk_per_trade": 0.01,
        "min_rr": 1.5,
        "cooldown_after_losses": 4,
        "expected_trades_per_day": "20-50"
    },

    "ACCEL": {
        # РАЗГОН ДЕПОЗИТА — снайпер. Мало сделок, каждая на вес золота.
        # Данные: SHORT@15:00 UTC = 100% WR. Это ACCEL-стиль.
        "composite_min_score": 48,    # v10: Снижено с 55 до 48 для чуть большей динамики в ACCEL (было 65)
        "session_filter": True,       # Только в ликвидное время
        "session_min_quality": 5,     
        "news_filter": True,
        "mtf_strict": True,           # ОБЯЗАТЕЛЬНОЕ совпадение трендов
        "max_positions": 2,           # Макс 2 позиции
        "risk_per_trade": 0.03,       # 3% на сделку
        "min_rr": 2.5,                
        "cooldown_after_losses": 2,   # 2 убытка = пауза
        "expected_trades_per_day": "2-6"
    }
}


def apply_mode(mode_name: str) -> dict:
    """Применяет выбранный режим."""
    if mode_name not in TRADE_MODES:
        print(f"Unknown mode: {mode_name}. Using MODERATE.")
        mode_name = "MODERATE"
    
    mode = TRADE_MODES[mode_name]
    print(f"\n{'='*50}")
    print(f"🎮 TITAN TRADE MODE: {mode_name}")
    print(f"{'='*50}")
    print(f"  Min Composite Score: {mode['composite_min_score']}")
    print(f"  Session Filter: {mode['session_filter']}")
    print(f"  MTF Strict: {mode['mtf_strict']}")
    print(f"  Max Positions: {mode['max_positions']}")
    print(f"  Risk per Trade: {mode['risk_per_trade']*100}%")
    print(f"  Min R:R: 1:{mode['min_rr']}")
    print(f"  Expected Trades/Day: {mode['expected_trades_per_day']}")
    print(f"{'='*50}\n")
    
    return mode
