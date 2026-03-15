import logging
import json
from typing import List, Dict, Optional, Tuple, Any

log = logging.getLogger("BatchOrderManager")

class BatchOrderManager:
    """
    Управляет пакетным размещением ордеров в Bybit.
    Позволяет разместить до 10 ордеров (Spot) или 20 (UTA Linear) за один запрос.
    """
    
    def __init__(self, client):
        self.client = client
        self.category = client.category
        self.symbol = client.symbol
        
    def place_grid_batch(self, orders: List[Dict[str, str]], use_postonly: bool = True) -> Tuple[List[str], List[Dict]]:
        """
        Размещает список ордеров пакетом.
        orders: list of {'side': 'Buy/Sell', 'qty': '0.1', 'price': '25000'}
        """
        if not orders:
            return [], []
            
        order_ids = []
        errors = []
        
        # Bybit позволяет макс 10 ордеров в batch для UTA Spot
        batch_limit = 10
        for i in range(0, len(orders), batch_limit):
            chunk = orders[i:i + batch_limit]
            
            request_list = []
            for o in chunk:
                request_list.append({
                    "symbol": self.symbol,
                    "side": o['side'],
                    "orderType": "Limit",
                    "qty": o['qty'],
                    "price": o['price'],
                    "timeInForce": "PostOnly" if use_postonly else "GTC"
                })
                
            try:
                # В pybit метод для пакетного размещения
                response = self.client.session.place_batch_order(
                    category=self.category,
                    request=request_list
                )
                
                # Обрабатываем результаты каждого ордера в пакете
                result_list = response.get('result', {}).get('list', [])
                for res in result_list:
                    if res.get('orderId'):
                        order_ids.append(res['orderId'])
                    else:
                        errors.append(res)
                        
            except Exception as e:
                log.error(f"Batch placement failed: {e}")
                errors.append({"error": str(e)})
                
        return order_ids, errors

    def cancel_batch(self, order_ids: List[str]) -> Tuple[int, List[Dict]]:
        """Отмена ордеров пакетом."""
        if not order_ids:
            return 0, []
            
        cancelled_count = 0
        errors = []
        batch_limit = 10
        
        for i in range(0, len(order_ids), batch_limit):
            chunk = order_ids[i:i + batch_limit]
            request_list = [{"symbol": self.symbol, "orderId": oid} for oid in chunk]
            
            try:
                response = self.client.session.cancel_batch_order(
                    category=self.category,
                    request=request_list
                )
                
                result_list = response.get('result', {}).get('list', [])
                for res in result_list:
                    if res.get('orderId'):
                        cancelled_count += 1
                    else:
                        errors.append(res)
            except Exception as e:
                log.error(f"Batch cancel failed: {e}")
                errors.append({"error": str(e)})
                
        return cancelled_count, errors
