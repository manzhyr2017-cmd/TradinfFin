# 🤖 Trading AI v2.0 - Bybit Edition

**Advanced Mean Reversion System | Target: 85%+ Win Rate**

## 📁 Структура проекта

```
trading_ai/
├── main_bybit.py           # Точка входа (CLI)
├── mean_reversion_bybit.py # Движок стратегии
├── bybit_client.py         # Клиент Bybit API
├── telegram_bot.py         # Telegram уведомления
├── backtesting.py          # Система бэктестинга
├── requirements.txt        # Зависимости
└── README.md
```

## 🚀 Быстрый старт

### Установка

```bash
pip install pandas numpy requests python-telegram-bot
```

### Команды

```bash
# Сканирование рынка
python main_bybit.py scan                    # Топ пары по объёму
python main_bybit.py scan --all              # ВСЕ пары
python main_bybit.py scan --symbols BTCUSDT ETHUSDT
python main_bybit.py scan --continuous       # Непрерывный мониторинг
python main_bybit.py scan --demo             # Демо без API

# Бэктестинг
python main_bybit.py backtest                # Синтетические данные
python main_bybit.py backtest -f data.csv    # Свои данные
python main_bybit.py backtest --periods 20000 --max-trades 200

# Telegram бот
python main_bybit.py telegram --token YOUR_TOKEN

# Демо
python main_bybit.py demo
```

## 📊 Confluence Scoring System (100 баллов)

| Фактор | Макс | Описание |
|--------|------|----------|
| RSI | 25 | <20 или >80 = экстремум |
| Bollinger Bands | 15 | За пределами полос |
| Multi-Timeframe | 25 | 15m + 1h + 4h aligned |
| Support/Resistance | 15 | Близость к уровням |
| Volume | 10 | Spike |
| MACD | 10 | Разворот |
| Funding Rate | 10 | Bybit perpetual |
| Order Book | 5 | Imbalance |
| Oscillators | 10 | Stoch RSI, Williams |

**Вход только при score ≥ 70**

## 🔧 Параметры

### Сканирование

| Параметр | Описание | По умолчанию |
|----------|----------|--------------|
| `--symbols` | Конкретные пары | Авто |
| `--all` | Все пары | Нет |
| `--min-volume` | Мин. объём 24h | $5M |
| `--continuous` | Мониторинг | Нет |
| `--interval` | Интервал (мин) | 15 |
| `--min-probability` | Мин. вероятность | 85% |
| `--category` | spot/linear | linear |

### Бэктестинг

| Параметр | Описание | По умолчанию |
|----------|----------|--------------|
| `--data-file` | CSV с данными | Генерация |
| `--periods` | Свечей | 10000 |
| `--capital` | Начальный капитал | $10000 |
| `--risk` | % риска на сделку | 1% |
| `--min-confluence` | Мин. score | 70 |
| `--max-trades` | Лимит сделок | 100 |

## 📱 Telegram Bot

### Настройка

1. Создайте бота через @BotFather
2. Создайте каналы для разных уровней
3. Установите переменные окружения:

```bash
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHANNEL_GOLD="@your_channel"
```

4. Запустите:

```bash
python main_bybit.py telegram
```

### Уровни каналов

- 🥉 Bronze: 75%+ сигналы
- 🥈 Silver: 80%+ сигналы  
- 🥇 Gold: 85%+ сигналы
- 💎 Platinum: 88%+ сигналы

## 💰 Risk Management

- **Stop Loss:** 2 ATR от входа
- **TP1:** BB Middle (закрыть 50%)
- **TP2:** BB Opposite (закрыть 50%)
- **Min R:R:** 1:2.5

## 📈 Пример результата бэктеста

```
╔══════════════════════════════════════════════════════════════╗
║                    ОТЧЁТ БЭКТЕСТА                            ║
╠══════════════════════════════════════════════════════════════╣
║  Win Rate:             78.5%                                 ║
║  Profit Factor:        2.34                                  ║
║  Total PnL:           +45.2%                                 ║
║  Max Drawdown:         8.3%                                  ║
║  Sharpe Ratio:         1.85                                  ║
╚══════════════════════════════════════════════════════════════╝
```

## ⚠️ Disclaimer

Торговля криптовалютами несёт высокие риски. Это НЕ финансовый совет. Прошлые результаты не гарантируют будущие. Торгуйте только свободными средствами.

## 📝 Лицензия

MIT
