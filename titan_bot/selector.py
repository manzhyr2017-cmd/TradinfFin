"""
TITAN BOT 2026 - Symbol Selector
Выбор топовых монет по волатильности и объему.
"""

import config
from pybit.unified_trading import HTTP
import os

class SymbolSelector:
    def __init__(self, data_engine=None):
        self.session = HTTP(
            testnet=config.TESTNET,
            api_key=config.API_KEY,
            api_secret=config.API_SECRET,
            demo=getattr(config, 'BYBIT_DEMO', False)
        )
        self.data_engine = data_engine

    def get_top_symbols(self, count=30):
        """
        Получает ТОП монет Bybit:
        1. Отбираем топ-100 по ликвидному объему (чтобы не было сквизов).
        2. Сортируем их по волатильности (изменению за 24 часа), чтобы найти самые активные.
        """
        try:
            # Черный список (мем-коины и стейблы)
            blacklist_tokens = [
                'PEPE', 'SHIB', 'DOGE', 'FLOKI', 'BONK', 'MEME', 
                '1000PEPE', '1000LUNC', '1000SHIB', 'PUMPFUN', 
                '1000BONK', '1000FLOKI', 'USDC', 'BUSD', 'DAI', 'USDE'
            ]
            
            # 1. Получаем тикеры
            response = self.session.get_tickers(category="linear")
            if response['retCode'] != 0:
                print(f"[Selector] Ошибка API Bybit: {response['retMsg']}")
                return [config.SYMBOL]

            tickers = response['result']['list']
            
            # 2. Первичный фильтр (USDT + Volume)
            candidates = []
            for t in tickers:
                symbol = t['symbol']
                if not symbol.endswith('USDT'):
                    continue
                
                # Проверка на blacklist (если содержит запрещенные слова)
                is_blacklisted = False
                for bad_token in blacklist_tokens:
                    if symbol.startswith(bad_token):
                        is_blacklisted = True
                        break
                if is_blacklisted:
                    continue

                try:
                    volume = float(t['volume24h']) * float(t['lastPrice']) # Объем в $$$
                    price_change = abs(float(t['price24hPcnt'])) # Волатильность (по модулю)
                    
                    # Фильтр на минимальный объем (например, 50 млн $)
                    if volume > 10_000_000: 
                        candidates.append({
                            'symbol': symbol,
                            'volume': volume,
                            'volatility': price_change
                        })
                except:
                    continue

            if not candidates:
                return [config.SYMBOL]

            # 3. Гибридная сортировка
            # Сначала берем топ-60 по объему (самые ликвидные)
            candidates.sort(key=lambda x: x['volume'], reverse=True)
            top_volume = candidates[:60]
            
            # Из них берем самые волатильные (самые движущиеся)
            # Это именно то, что нужно для Smart Money - движение!
            top_volume.sort(key=lambda x: x['volatility'], reverse=True)
            
            final_list = [c['symbol'] for c in top_volume[:count]]
            
            print(f"[Selector] Отобрано {len(final_list)} монет по волатильности (из топ-60 по объему).")
            print(f"Top 5 Volatile: {', '.join(final_list[:5])}")
            
            return final_list

        except Exception as e:
            print(f"[Selector] Критическая ошибка селектора: {e}")
            return [config.SYMBOL]

if __name__ == "__main__":
    # Тест
    from dotenv import load_dotenv
    load_dotenv()
    sel = SymbolSelector()
    top = sel.get_top_symbols(30)
    print("Final List:", top)
