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
        Получает ТОП-10 монет Bybit по объему торгов.
        Исключаем мем-коины и неликвид.
        """
        try:
            # Черный список (мем-коины и волатильный мусор)
            blacklist = ['PEPEUSDT', 'SHIBUSDT', 'DOGEUSDT', 'FLOKIUSDT', 'BONKUSDT', 'MEMEUSDT', '1000PEPEUSDT', '1000LUNCUSDT', '1000SHIBUSDT']
            
            # 1. Получаем все тикеры
            response = self.session.get_tickers(category="linear")
            if response['retCode'] != 0:
                return [config.SYMBOL]

            tickers = response['result']['list']
            
            # 2. Фильтруем и собираем данные по объемам
            candidates = []
            for t in tickers:
                symbol = t['symbol']
                if not symbol.endswith('USDT') or symbol in blacklist:
                    continue
                
                # Игнорируем стейблкоины
                if symbol in ['USDCUSDT', 'BUSDUSDT', 'DAIUSDT']:
                    continue

                candidates.append({
                    'symbol': symbol,
                    'volume': float(t['volume24h'])
                })

            if not candidates:
                return [config.SYMBOL]

            # 3. Сортируем ТОЛЬКО по объему (самые надежные и ликвидные)
            candidates.sort(key=lambda x: x['volume'], reverse=True)

            top_list = [c['symbol'] for c in candidates[:count]]
            
            print(f"[Selector] Актуальный ТОП-10 по объему: {', '.join(top_list)}")
            return top_list

        except Exception as e:
            print(f"[Selector] Ошибка селектора: {e}")
            return [config.SYMBOL]

        except Exception as e:
            print(f"[Selector] Ошибка селектора: {e}")
            return [config.SYMBOL]

if __name__ == "__main__":
    # Тест
    sel = SymbolSelector()
    top = sel.get_top_symbols(10)
    print("Result:", top)
