"""
TITAN BOT 2026 - Symbol Selector
Выбор топовых монет по волатильности и объему.
"""

import config
from pybit.unified_trading import HTTP

class SymbolSelector:
    def __init__(self, data_engine=None):
        self.session = HTTP(
            testnet=config.TESTNET,
            api_key=config.API_KEY,
            api_secret=config.API_SECRET,
            demo=getattr(config, 'BYBIT_DEMO', False)
        )
        self.data_engine = data_engine

    def get_top_symbols(self, count=10):
        """
        Получает топ монет на основе комбинации объема и волатильности.
        """
        try:
            # 1. Получаем все тикеры для линейных фьючерсов
            response = self.session.get_tickers(category="linear")
            if response['retCode'] != 0:
                print(f"[Selector] Ошибка получения тикеров: {response['retMsg']}")
                return [config.SYMBOL]

            tickers = response['result']['list']
            
            # 2. Фильтруем (только к USDT и с минимальным объемом)
            # Мы ищем монеты, которые "дышат" и ликвидны
            candidates = []
            for t in tickers:
                symbol = t['symbol']
                if not symbol.endswith('USDT'):
                    continue
                
                # Игнорируем стейблкоины и сам BTC/ETH (опционально, но лучше оставить как базу)
                if symbol in ['USDCUSDT', 'BUSDUSDT', 'DAIUSDT']:
                    continue

                volume = float(t['volume24h'])
                volatility = abs(float(t['price24hPcnt'])) * 100 # в процентах
                
                candidates.append({
                    'symbol': symbol,
                    'volume': volume,
                    'volatility': volatility,
                    'last_price': float(t['lastPrice'])
                })

            if not candidates:
                return [config.SYMBOL]

            # 3. Ранжирование
            # Сортируем по объему (Rank Volume)
            candidates.sort(key=lambda x: x['volume'], reverse=True)
            for i, c in enumerate(candidates):
                c['volume_rank'] = i
            
            # Сортируем по волатильности (Rank Volatility)
            candidates.sort(key=lambda x: x['volatility'], reverse=True)
            for i, c in enumerate(candidates):
                c['volatility_rank'] = i

            # Итоговый ранг (чем меньше, тем лучше)
            for c in candidates:
                c['total_rank'] = (c['volume_rank'] + c['volatility_rank']) / 2

            # Сортируем по итоговому рангу
            candidates.sort(key=lambda x: x['total_rank'])

            top_list = [c['symbol'] for c in candidates[:count]]
            
            # Убеждаемся, что Benchmark (BTC) всегда на контроле (опционально)
            if config.BENCHMARK not in top_list:
                top_list.append(config.BENCHMARK)

            print(f"[Selector] Выбран топ-{len(top_list)}: {', '.join(top_list)}")
            return top_list

        except Exception as e:
            print(f"[Selector] Ошибка селектора: {e}")
            return [config.SYMBOL]

if __name__ == "__main__":
    # Тест
    sel = SymbolSelector()
    top = sel.get_top_symbols(10)
    print("Result:", top)
