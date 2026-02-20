---
name: postgres-database-design
description: Best practices for designing PostgreSQL schemas for trading data analytics.
---

# PostgreSQL Database Design for Trading

## 1. Schema Design Principles
- **TimescaleDB:** Consider using TimescaleDB extension for time-series data (candles, ticks).
- **Versioning:** Use migration tools like `alembic` (Python) to manage schema changes.

## 2. Key Tables
### `trades`
- `id` (UUID/Serial)
- `symbol` (VARCHAR(20))
- `side` (ENUM: BUY/SELL)
- `entry_price` (DECIMAL)
- `exit_price` (DECIMAL)
- `quantity` (DECIMAL)
- `pnl` (DECIMAL)
- `commissions` (DECIMAL)
- `strategy_id` (VARCHAR)
- `open_time` (TIMESTAMP WITH TIME ZONE)
- `close_time` (TIMESTAMP WITH TIME ZONE)
- `tags` (JSONB - for flexible metadata like "news_pump", "whale_alert")

### `candles`
- `symbol` (VARCHAR)
- `time` (TIMESTAMP)
- `open`, `high`, `low`, `close`, `volume` (DECIMAL)
- **Constraint:** UNIQUE(symbol, time)

### `audit_logs`
- `action` (VARCHAR)
- `details` (JSONB)
- `timestamp` (TIMESTAMP)

## 3. Performance Tuning
- **Indexes:**
    - B-Tree on `id`, `symbol`.
    - BRIN index on `time` column (efficient for time-series).
- **Partitions:** Partition heavy tables (`candles`) by month/year.

## 4. Python Integration (SQLAlchemy)
- Use `SQLAlchemy` ORM for abstraction.
- Use `asyncpg` driver for high-performance async database access.
- Connection Pooling: Use `pgbouncer` or internal poolers to handle many concurrent connections.

## 5. Backup Strategy
- **pg_dump:** Daily backups to S3 or local disk.
- **WAL Archiving:** For point-in-time recovery (PITR).
