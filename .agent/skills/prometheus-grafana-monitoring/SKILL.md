---
name: prometheus-grafana-monitoring
description: Setting up monitoring and alerting for trading bots using Prometheus and Grafana.
---

# Monitoring with Prometheus & Grafana

## 1. Architecture
- **Exporter:** The bot exposes metrics (e.g., via `prometheus_client` library on port 8000).
- **Prometheus:** Scrapes metrics from the bot every 15s and stores them.
- **Grafana:** Connects to Prometheus to visualize data.
- **Node Exporter:** Runs on VPS to monitor CPU, RAM, Disk usage.

## 2. Key Metrics to Track
- **Business Logic:**
    - `balance_usdt` (Gauge)
    - `open_positions_count` (Gauge)
    - `trades_total_count` (Counter)
    - `profit_loss_realized` (Counter)
- **System Health:**
    - `api_latency_seconds` (Histogram)
    - `api_errors_total` (Counter)
    - `websocket_disconnects_total` (Counter)
    - `loop_execution_time_seconds` (Histogram)

## 3. Implementation Steps (Python)
- **Library:** `pip install prometheus-client`.
- **Code:**
    ```python
    from prometheus_client import start_http_server, Gauge
    BALANCE = Gauge('bot_balance', 'Current USDT balance')
    start_http_server(8000)
    # in loop:
    BALANCE.set(current_balance)
    ```

## 4. Docker Compose Setup
- Add `prometheus` and `grafana` services to `docker-compose.yml`.
- Configure `prometheus.yml` to scrape `bot:8000` and `node-exporter:9100`.

## 5. Grafana Dashboards
- Import standard dashboards for Node Exporter (ID: 1860).
- Create custom dashboard for TitanBot Logic (PnL curve, Position distribution).

## 6. Alerting
- Configure Alertmanager (part of Prometheus stack) to send notifications to Telegram/Discord on critical events (e.g., Balance drop > 10%, Server down).
