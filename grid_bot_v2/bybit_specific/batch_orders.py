import logging
import json
import uuid
import time
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
        Размещает список ордеров пакетом. С автоматическим ретраем при rate limit.
        """
        if not orders:
            return [], []
            
        final_order_ids = []
        final_errors = []
        
        # 1. Первая попытка пакетами по 10
        batch_limit = 10
        to_retry = []

        for i in range(0, len(orders), batch_limit):
            if i > 0:
                time.sleep(0.3) # Небольшая пауза между пакетами по 10
            chunk = orders[i:i + batch_limit]
            request_list = []
            for o in chunk:
                link_id = f"grid_{uuid.uuid4().hex[:12]}"
                req_item = {
                    "symbol": self.client.symbol,
                    "side": o['side'],
                    "orderType": "Limit",
                    "qty": o['qty'],
                    "price": o['price'],
                    "timeInForce": "PostOnly" if use_postonly else "GTC",
                    "orderLinkId": link_id,
                    "positionIdx": o.get('positionIdx', 0)
                }
                request_list.append(req_item)
                
            try:
                response = self.client.session.place_batch_order(category=self.client.category, request=request_list)
                result_list = response.get('result', {}).get('list', [])
                ext_info_list = response.get('retExtInfo', {}).get('list', [])
                
                for idx, res in enumerate(result_list):
                    ext_info = ext_info_list[idx] if idx < len(ext_info_list) else {}
                    r_code = res.get('retCode') or res.get('code') or ext_info.get('code')
                    
                    if res.get('orderId') and (r_code == 0 or r_code is None):
                        final_order_ids.append(res['orderId'])
                    elif r_code == 10006:
                        # Сохраняем оригинальный запрос для ретрая
                        to_retry.append(chunk[idx])
                    else:
                        final_errors.append(res)
            except Exception as e:
                log.error(f"Batch placement Exception: {e}")
                final_errors.append({"error": str(e)})

        # 2. Ретрай для тех, кто попал под лимит (делаем паузу и по одному)
        if to_retry:
            log.warning(f"⏳ Rate limited on {len(to_retry)} orders. Retrying individually after 1s...")
            time.sleep(1.1)
            for o in to_retry:
                try:
                    # Используем обычный place_order для надежности ретрая
                    oid = self.client.place_order(
                        side=o['side'],
                        qty=o['qty'],
                        price=o['price'],
                        position_idx=o.get('positionIdx')
                    )
                    if oid:
                        final_order_ids.append(oid)
                    else:
                        final_errors.append({"msg": "Failed after individual retry", "req": o})
                except Exception as e:
                    final_errors.append({"error": f"Retry error: {e}", "req": o})
                time.sleep(0.5) # Пауза побольше для стабильности

        return final_order_ids, final_errors

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
