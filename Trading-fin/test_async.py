import asyncio
import time
import logging
from dotenv import load_dotenv
import os
import sys

# Add project root
sys.path.append(os.getcwd())
load_dotenv()

from bybit_client import BybitClient, BybitScanner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AsyncTest")

async def test_async_scan():
    client = BybitClient(
        category='linear',
        proxy=os.getenv('HTTP_PROXY')
    )
    scanner = BybitScanner(client, min_volume_24h=1_000_000)
    
    # Selecting fewer symbols for test
    scanner.symbols = scanner.symbols[:20] 
    logger.info(f"Testing with {len(scanner.symbols)} symbols")
    
    # 1. Sync Test
    start = time.time()
    logger.info("--- Starting SYNC Scan ---")
    results_sync = scanner.scan_all(delay=0.0) # minimal delay for fair comparison of network
    sync_duration = time.time() - start
    logger.info(f"Sync finished in {sync_duration:.2f}s")
    
    # 2. Async Test
    start = time.time()
    logger.info("--- Starting ASYNC Scan ---")
    results_async = await scanner.scan_all_async(batch_size=10)
    async_duration = time.time() - start
    logger.info(f"Async finished in {async_duration:.2f}s")
    
    # 3. Comparison
    speedup = sync_duration / async_duration if async_duration > 0 else 0
    print(f"\n🚀 Speedup: {speedup:.1f}x")
    print(f"Sync: {sync_duration:.2f}s | Async: {async_duration:.2f}s")
    
    if len(results_sync) != len(results_async):
        print(f"⚠️ Warning: Result count mismatch! Sync: {len(results_sync)}, Async: {len(results_async)}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test_async_scan())
