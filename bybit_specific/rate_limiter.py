import time
import logging
from collections import deque

log = logging.getLogger("RateLimitManager")

class RateLimitManager:
    """
    Интеллектуальный ограничитель частоты запросов.
    Отслеживает лимиты Bybit и вводит задержки, чтобы избежать 429 ошибок.
    """
    
    def __init__(self, max_requests: int = 20, period: float = 1.0):
        self.max_requests = max_requests
        self.period = period
        self.requests = deque()
        
    def wait_if_needed(self):
        """Останавливает выполнение, если порог запросов превышен."""
        now = time.time()
        
        # Удаляем старые запросы из очереди
        while self.requests and now - self.requests[0] > self.period:
            self.requests.popleft()
            
        if len(self.requests) >= self.max_requests:
            wait_time = self.period - (now - self.requests[0])
            if wait_time > 0:
                log.info(f"RateLimitManager: Yielding for {wait_time:.4f}s")
                time.sleep(wait_time)
                
        self.requests.append(time.time())

    def update_limits_from_response(self, headers: dict):
        """
        Может обновлять внутренние лимиты на основе заголовков ответа Bybit:
        X-Bapi-Limit, X-Bapi-Limit-Status, X-Bapi-Limit-Reset-Timestamp
        """
        # В UTA Bybit лимиты на чтение и запись разделены.
        # Обычно это 20 req/s для Order размещения и 50 для GetTicker.
        pass
