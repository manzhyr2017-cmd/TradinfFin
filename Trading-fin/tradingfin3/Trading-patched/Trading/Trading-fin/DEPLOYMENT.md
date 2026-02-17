# Trading Bot Deployment Guide
# ==============================
# This guide covers deployment on VPS and local environments

## Prerequisites
- Python 3.9+
- Docker & Docker Compose
- Bybit API keys
- CryptoPanic API key (optional)
- Telegram Bot token (optional)

## Quick Start (Docker)

```bash
# Clone the repository
git clone https://github.com/yourusername/trading-bot.git
cd trading-bot/Trading-fin

# Create .env file
cp .env.example .env
# Edit .env with your API keys

# Start with Docker Compose
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the bot
docker-compose down
```

## Manual Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
python main_bybit.py scan --continuous --auto-trade

# Run with specific strategy
python main_bybit.py scan --continuous --auto-trade --strategy mean_reversion

# Run in demo mode
python main_bybit.py scan --continuous --demo
```

## Configuration

Create a `.env` file with the following variables:

```env
# Bybit API
BYBIT_API_KEY=your_api_key
BYBIT_API_SECRET=your_api_secret

# CryptoPanic (optional)
CRYPTO_PANIC_API_KEY=your_cryptopanic_key

# Telegram (optional)
TELEGRAM_BOT_TOKEN=your_telegram_token
TELEGRAM_CHANNEL=@your_channel

# Trading Settings
RISK_PER_TRADE=1.0
MAX_DAILY_LOSS=50.0
MAX_POSITION_SIZE=10.0

# Proxy (optional)
HTTP_PROXY=http://proxy:port
HTTPS_PROXY=http://proxy:port
```

## Monitoring

### Prometheus Metrics
- Port: 9091
- Metrics endpoint: `/metrics`

### Grafana Dashboard
- URL: http://localhost:3000
- Default credentials: admin/admin
- Datasource: Prometheus (http://prometheus:9090)

### Alertmanager
- Port: 9093
- Web UI: http://localhost:9093

## Deployment on VPS

### Ubuntu/Debian

```bash
# Update system
apt update && apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Install Docker Compose
curl -L "https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Clone and deploy
git clone https://github.com/yourusername/trading-bot.git
cd trading-bot/Trading-fin
docker-compose up -d
```

### Windows

```powershell
# Install Docker Desktop
# Clone repository
git clone https://github.com/yourusername/trading-bot.git

# Deploy
cd Trading-fin
docker-compose up -d
```

## Troubleshooting

### Bot not starting
```bash
# Check logs
docker-compose logs trading-bot

# Check configuration
docker-compose exec trading-bot cat .env
```

### Connection issues
```bash
# Test API connectivity
docker-compose exec trading-bot python check_auth.py

# Test proxy
docker-compose exec trading-bot python check_proxy.py
```

### High memory usage
```bash
# Check container resources
docker stats

# Restart container
docker-compose restart trading-bot
```

## Maintenance

### Backup
```bash
# Backup database
docker-compose exec trading-bot cp /app/data/trades.db /app/data/trades.db.backup

# Backup logs
docker-compose exec trading-bot cp /app/logs/bot.log /app/logs/bot.log.backup
```

### Update
```bash
# Pull latest changes
git pull origin main

# Rebuild and restart
docker-compose down
docker-compose build
docker-compose up -d
```

## Support

For issues and questions:
- GitHub Issues: https://github.com/yourusername/trading-bot/issues
- Telegram: @your_channel
