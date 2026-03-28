---
name: python-testing-patterns
description: Best practices for writing robust tests for Python trading applications.
---

# Python Testing Patterns for TitanBot

## 1. Testing Framework
- **Primary:** `pytest` (Clean, simple, powerful fixtures).
- **Mocking:** `unittest.mock` or `pytest-mock` (Essential for simulating Exchange APIs).

## 2. Unit Tests (Fast & Isolated)
- Test individual functions: `RiskManager.check_risk()`, `CompositeScore.calculate()`.
- **Mock External Calls:** NEVER make real API calls in unit tests. Mock `ccxt` or `pybit`.
    ```python
    def test_risk_limit(mocker):
        mocker.patch('data_engine.get_balance', return_value=1000)
        # ... test logic ...
    ```

## 3. Integration Tests (Component Interaction)
- Test how modules work together: `Signal` -> `Risk` -> `Execution`.
- Use a local DB or mocked Exchange interface.

## 4. Key Trading Scenarios to Test
- **Entry Logic:** Does it trigger only when Score > Threshold?
- **Exit Logic:** Does Stop Loss trigger exactly at the right price?
- **Position Sizing:** Does it respect `MAX_RISK_PER_TRADE`?
- **Edge Cases:**
    - Zero balance?
    - API returns error?
    - WebSocket disconnects?
    - Data gaps in candles?

## 5. Property-Based Testing (Advanced)
- Use `hypothesis` to generate random inputs and find edge cases you didn't think of.

## 6. Continuous Integration
- Run tests automatically before every `git push`.
- Add a script `run_tests.sh` to execute `pytest`.
