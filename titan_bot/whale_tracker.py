"""
TITAN BOT 2026 - Whale Tracker
Следим за крупными игроками в блокчейне
"""

import pandas as pd
import requests
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime, timedelta
import time
import config

@dataclass
class WhaleTransaction:
    """Крупная транзакция"""
    timestamp: datetime
    from_address: str
    to_address: str
    amount: float
    amount_usd: float
    tx_hash: str
    type: str  # 'EXCHANGE_INFLOW', 'EXCHANGE_OUTFLOW', 'WHALE_TRANSFER'

@dataclass
class WhaleAnalysis:
    """Результат анализа китов"""
    exchange_inflow_24h: float      # Приток на биржи за 24ч
    exchange_outflow_24h: float     # Отток с бирж за 24ч
    net_flow: float                 # Чистый поток (отрицательный = отток)
    large_transactions: List[WhaleTransaction]
    whale_sentiment: str            # 'ACCUMULATING', 'DISTRIBUTING', 'NEUTRAL'
    alert_level: str                # 'HIGH', 'MEDIUM', 'LOW'
    description: str


class WhaleTracker:
    """
    Отслеживание крупных транзакций.
    
    ПОЧЕМУ ЭТО ALPHA:
    
    Киты (крупные держатели) двигают рынок.
    Их действия ОПЕРЕЖАЮТ движение цены.
    
    СИГНАЛЫ:
    
    1. EXCHANGE INFLOW (приток на биржу)
       - Кит перевёл крипту НА биржу
       - Вероятно, собирается ПРОДАВАТЬ
       - МЕДВЕЖИЙ сигнал
    
    2. EXCHANGE OUTFLOW (отток с биржи)
       - Кит вывел крипту С биржи
       - Вероятно, собирается ДЕРЖАТЬ
       - БЫЧИЙ сигнал
    
    3. WHALE ACCUMULATION
       - Крупные покупки вне бирж
       - Готовятся к росту
       - ОЧЕНЬ БЫЧИЙ
    
    API: Используем Whale Alert, Glassnode, или бесплатные альтернативы
    """
    
    def __init__(self):
        # Известные адреса бирж (упрощённый список)
        self.exchange_addresses = {
            'binance': ['0x...', '0x...'],
            'bybit': ['0x...'],
            'coinbase': ['0x...'],
            # В реальности — сотни адресов
        }
        
        # Порог "крупной" транзакции
        self.whale_threshold_usd = 1_000_000  # $1M+
        
        # Кэш транзакций
        self.transactions_cache = []
        self.last_fetch = None
    
    def analyze(self, symbol: str = "ETH") -> WhaleAnalysis:
        """
        Анализирует активность китов за последние 24 часа.
        """
        # Получаем транзакции
        transactions = self._fetch_whale_transactions(symbol)
        
        if not transactions:
            return self._empty_analysis()
        
        # Считаем потоки
        inflow = sum(t.amount_usd for t in transactions if t.type == 'EXCHANGE_INFLOW')
        outflow = sum(t.amount_usd for t in transactions if t.type == 'EXCHANGE_OUTFLOW')
        net_flow = outflow - inflow  # Положительный = отток (бычий)
        
        # Определяем настроение китов
        sentiment = self._determine_sentiment(inflow, outflow, transactions)
        
        # Уровень алерта
        alert = self._calculate_alert_level(inflow, outflow, transactions)
        
        # Описание
        description = self._generate_description(inflow, outflow, net_flow, sentiment)
        
        return WhaleAnalysis(
            exchange_inflow_24h=inflow,
            exchange_outflow_24h=outflow,
            net_flow=net_flow,
            large_transactions=transactions[:10],  # Топ 10
            whale_sentiment=sentiment,
            alert_level=alert,
            description=description
        )
    
    def _fetch_whale_transactions(self, symbol: str) -> List[WhaleTransaction]:
        """
        Получает крупные транзакции.
        
        В реальности здесь подключение к API:
        - Whale Alert API (платный)
        - Glassnode API (платный)
        - Etherscan API (бесплатный, но ограниченный)
        - Blockchair API
        """
        # Проверяем кэш
        if self.last_fetch and datetime.now() - self.last_fetch < timedelta(minutes=5):
            return self.transactions_cache
        
        transactions = []
        
        try:
            # Пример с бесплатным API (в реальности нужен ключ)
            # Это демо-данные для примера структуры
            
            # Вариант 1: Whale Alert API
            # response = requests.get(
            #     f"https://api.whale-alert.io/v1/transactions",
            #     params={
            #         'api_key': 'YOUR_KEY',
            #         'min_value': self.whale_threshold_usd,
            #         'currency': symbol.lower()
            #     }
            # )
            
            # Вариант 2: Парсинг Etherscan для ETH
            # response = requests.get(
            #     f"https://api.etherscan.io/api",
            #     params={
            #         'module': 'account',
            #         'action': 'txlist',
            #         'address': EXCHANGE_ADDRESS,
            #         'apikey': 'YOUR_KEY'
            #     }
            # )
            
            # Демо-данные для тестирования
            demo_transactions = [
                {
                    'timestamp': datetime.now() - timedelta(hours=2),
                    'from': 'whale_wallet_1',
                    'to': 'binance_hot_wallet',
                    'amount': 5000,
                    'amount_usd': 15_000_000,
                    'hash': '0xabc123',
                    'type': 'EXCHANGE_INFLOW'
                },
                {
                    'timestamp': datetime.now() - timedelta(hours=5),
                    'from': 'coinbase_cold_wallet',
                    'to': 'whale_wallet_2',
                    'amount': 8000,
                    'amount_usd': 24_000_000,
                    'hash': '0xdef456',
                    'type': 'EXCHANGE_OUTFLOW'
                },
            ]
            
            for tx in demo_transactions:
                transactions.append(WhaleTransaction(
                    timestamp=tx['timestamp'],
                    from_address=tx['from'],
                    to_address=tx['to'],
                    amount=tx['amount'],
                    amount_usd=tx['amount_usd'],
                    tx_hash=tx['hash'],
                    type=tx['type']
                ))
            
            self.transactions_cache = transactions
            self.last_fetch = datetime.now()
            
        except Exception as e:
            print(f"[WhaleTracker] Error fetching transactions: {e}")
        
        return transactions
    
    def _determine_sentiment(
        self, 
        inflow: float, 
        outflow: float,
        transactions: List[WhaleTransaction]
    ) -> str:
        """Определяет настроение китов."""
        
        # Если отток значительно больше притока — накопление
        if outflow > inflow * 1.5:
            return "ACCUMULATING"
        
        # Если приток значительно больше оттока — распродажа
        if inflow > outflow * 1.5:
            return "DISTRIBUTING"
        
        return "NEUTRAL"
    
    def _calculate_alert_level(
        self,
        inflow: float,
        outflow: float,
        transactions: List[WhaleTransaction]
    ) -> str:
        """Рассчитывает уровень алерта."""
        
        total_volume = inflow + outflow
        
        # Огромный объём
        if total_volume > 100_000_000:  # $100M+
            return "HIGH"
        
        # Большой объём
        if total_volume > 50_000_000:  # $50M+
            return "MEDIUM"
        
        return "LOW"
    
    def _generate_description(
        self,
        inflow: float,
        outflow: float,
        net_flow: float,
        sentiment: str
    ) -> str:
        """Генерирует описание."""
        
        if sentiment == "ACCUMULATING":
            return f"🐋 Киты НАКАПЛИВАЮТ! Отток ${outflow/1e6:.1f}M > Приток ${inflow/1e6:.1f}M. Бычий сигнал."
        
        if sentiment == "DISTRIBUTING":
            return f"⚠️ Киты РАСПРОДАЮТ! Приток ${inflow/1e6:.1f}M > Отток ${outflow/1e6:.1f}M. Медвежий сигнал."
        
        return f"➖ Активность китов нейтральная. Приток: ${inflow/1e6:.1f}M, Отток: ${outflow/1e6:.1f}M"
    
    def _empty_analysis(self) -> WhaleAnalysis:
        """Пустой анализ."""
        return WhaleAnalysis(
            exchange_inflow_24h=0,
            exchange_outflow_24h=0,
            net_flow=0,
            large_transactions=[],
            whale_sentiment="UNKNOWN",
            alert_level="LOW",
            description="Нет данных о китах"
        )
    
    def get_whale_alerts(self, min_usd: float = 10_000_000) -> List[WhaleTransaction]:
        """Возвращает алерты о крупных транзакциях."""
        all_tx = self._fetch_whale_transactions("ETH")
        return [tx for tx in all_tx if tx.amount_usd >= min_usd]
