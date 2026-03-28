---
name: python-performance-optimization
description: Guidelines and techniques for optimizing Python code performance, focusing on high-frequency trading bot scenarios.
---

# Python Performance Optimization Guide for TitanBot

## 1. Profiling First
Before optimizing, always identify bottlenecks using `cProfile` or `line_profiler`.
- **Action:** Run the bot with profiling enabled to see which functions consume the most CPU time.
- **Tools:** `cProfile`, `snakeviz` (for visualization), `line_profiler` (for line-by-line analysis).

## 2. Reduce Object Creation in Hot Loops
In high-frequency loops (like `_main_loop` or `RealtimeDataStream`), avoid creating new objects unnecessarily.
- **Bad:** Creating a new list or dictionary inside a loop every millisecond.
- **Good:** Reuse existing structures or use generator expressions where possible.

## 3. Optimize NumPy/Pandas Usage
- **Vectorization:** Ensure all DataFrame operations in `DataEngine` and `Indicators` are vectorized. Avoid `apply()` or iterating over rows (`iterrows()`) at all costs.
- **Memory:** Downcast numeric types (e.g., `float64` to `float32`) if high precision isn't required to save memory on the VPS.

## 4. Asynchronous I/O
- Ensure all network calls (Bybit API, Telegram) are non-blocking.
- Use `aiohttp` or `asyncio` for concurrent data fetching if migrating from threaded `requests`.

## 5. Caching
- Cache results of heavy calculations (e.g., complex indicators like SuperTrend or OrderFlow) if the input data hasn't changed.
- Use `functools.lru_cache` for pure functions.

## 6. JIT Compilation (Numba)
- For heavy mathematical loops that cannot be vectorized, use `@numba.jit(nopython=True)`. This compiles Python to machine code.

## Checklist for Optimization
- [ ] Profile the `CompositeScoreEngine.calculate()` method.
- [ ] Check `DataEngine.get_klines()` for redundant API calls.
- [ ] Verify that WebSocket messages are processed without blocking the main loop.
