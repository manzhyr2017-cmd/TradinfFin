#!/bin/bash

# TITAN BOT 2026 - VPS Deployment Script
# Для Ubuntu 24.04 LTS

echo "🚀 Starting Titan Bot Deployment..."

# 1. Update system
sudo apt update && sudo apt install -y python3-pip python3-venv git

# 2. Setup directory structure
TRADING_DIR="/root/TradinfFin"
BOT_DIR="$TRADING_DIR/titan_bot"

echo "📂 Setting up directory: $TRADING_DIR"
mkdir -p "$TRADING_DIR"
cd "$TRADING_DIR"

# 3. Check if folder exists or clone
if [ ! -d "titan_bot" ]; then
    echo "📥 Cloning repository into $BOT_DIR..."
    git clone https://github.com/manzhyr2017-cmd/TradinfFin titan_bot
fi

cd "$BOT_DIR"

# 4. Create virtual environment
echo "🐍 Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# 5. Install dependencies
echo "📦 Installing requirements..."
pip install --upgrade pip
pip install -r requirements.txt

# 6. Setup environment
if [ ! -f ".env" ]; then
    echo "📝 Creating .env from example..."
    cp .env.example .env
    echo "⚠️  IMPORTANT: Edit .env (nano .env) and add your API keys!"
fi

# 7. Create Systemd Service for 24/7 run
echo "⚙️  Setting up Systemd Service..."
cat <<EOF | sudo tee /etc/systemd/system/titan.service
[Unit]
Description=Titan Trading Bot (Aggressive Mode)
After=network.target

[Service]
User=$USER
WorkingDirectory=$BOT_DIR
ExecStart=$BOT_DIR/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable titan

echo "✅ Deployment complete!"
echo "------------------------------------------------"
echo "Path: $BOT_DIR"
echo "To start bot:"
echo "1. cd $BOT_DIR"
echo "2. Edit keys: nano .env"
echo "3. Run: sudo systemctl start titan"
echo "4. Logs: journalctl -u titan -f"
echo "------------------------------------------------"
