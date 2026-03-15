import logging
import json
import uuid
from typing import List, Dict, Optional, Tuple, Any

log = logging.getLogger("BatchOrderManager")

class BatchOrderManager:
    """
    Управляет пакетным размещением ордеров в Bybit V5.
    """
    
    def __init__(self, client):
        self.client = client
        
    def place_grid_batch(self, orders: List[Dict[str, str]], use_postonly: bool = True) -> Tuple[List[str], List[Dict]]:
        """
        Размещает список ордеров пакетом.
        orders: list of {'side': 'Buy/Sell', 'qty': '0.1', 'price': '25000'}
        """
        if not orders:
            return [], []
            
        order_ids = []
        errors = []
        
        # Лимит для Linear UTA - 20 ордеров, для Spot UTA - 10. 
        # Оставляем 10 для безопасности.
        batch_limit = 10
        for i in range(0, len(orders), batch_limit):
            chunk = orders[i:i + batch_limit]
            
            request_list = []
            for o in chunk:
                # Генерируем уникальный orderLinkId для каждого ордера для лучшей диагностики
                link_id = f"grid_{uuid.uuid4().hex[:12]}"
                
                req_item = {
                    "symbol": self.client.symbol,
                    "side": o['side'],
                    "orderType": "Limit",
                    "qty": o['qty'],
                    "price": o['price'],
                    "timeInForce": "PostOnly" if use_postonly else "GTC",
                    "orderLinkId": link_id,
                    "positionIdx": o.get('positionIdx', 0) # 0 для One-Way, 1/2 для Hedge
                }
                request_list.append(req_item)
                
            try:
                # В pybit метод для пакетного размещения
                response = self.client.session.place_batch_order(
                    category=self.client.category,
                    request=request_list
                )
                
                # Обрабатываем результаты каждого ордера в пакете
                result_list = response.get('result', {}).get('list', [])
                ret_code_root = response.get('retCode', 0)
                
                if ret_code_root != 0:
                    log.error(f"❌ Batch request rejected by server: {ret_code_root} - {response.get('retMsg')}")
                    return [], [{"error": response.get('retMsg'), "code": ret_code_root}]

                for i, res in enumerate(result_list):
                    r_code = res.get('retCode') if res.get('retCode') is not None else res.get('code')
                    r_msg = res.get('retMsg') or res.get('msg')
                    
                    if res.get('orderId') and (r_code == 0 or r_code is None):
                        order_ids.append(res['orderId'])
                    else:
                        ret_msg = r_msg or 'Unknown error'
                        ret_code = r_code if r_code is not None else 'No code'
                        
                        # Если ошибка "Unknown", попробуем вывести детали запроса
                        orig_req = request_list[i] if i < len(request_list) else {}
                        log.error(f"❌ Batch Order Failed: {ret_code} - {ret_msg} | Req: {orig_req.get('side')} {orig_req.get('qty')} @ {orig_req.get('price')}")
                        log.debug(f"DEBUG: Full Item Keys: {list(res.keys())}")
                        log.debug(f"DEBUG: Full Response: {json.dumps(response)}")
                        errors.append(res)
                        
            except Exception as e:
                log.error(f"Batch placement Exception: {e}")
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
            request_list = [{"symbol": self.client.symbol, "orderId": oid} for oid in chunk]
            
            try:
                response = self.client.session.cancel_batch_order(
                    category=self.client.category,
                    request=request_list
                )
                
                result_list = response.get('result', {}).get('list', [])
                for res in result_list:
                    r_code = res.get('retCode') if res.get('retCode') is not None else res.get('code')
                    if res.get('orderId') and (r_code == 0 or r_code is None):
                        cancelled_count += 1
                    else:
                        errors.append(res)
            except Exception as e:
                log.error(f"Batch cancel Exception: {e}")
                errors.append({"error": str(e)})
                
        return cancelled_count, errors
