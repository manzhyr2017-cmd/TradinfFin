#!/bin/bash

# TITAN BOT 2026 - VPS Deployment Script
# Для Ubuntu 24.04 LTS

echo "🚀 Starting Titan Bot Deployment..."

# 1. Update system
sudo apt update && sudo apt install -y python3-pip python3-venv git

# 2. Check if folder exists
if [ ! -d "titan_bot" ]; then
    echo "📥 Cloning repository..."
    git clone https://github.com/manzhyr2017-cmd/TradinfFin titan_bot
fi

cd titan_bot

# 3. Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# 4. Install dependencies
echo "📦 Installing requirements..."
pip install --upgrade pip
pip install -r requirements.txt

# 5. Setup environment
if [ ! -f ".env" ]; then
    echo "📝 Creating .env from example..."
    cp .env.example .env
    echo "⚠️  IMPORTANT: Edit .env and add your API keys!"
fi

# 6. Create Service for 24/7 run
echo "⚙️  Setting up Systemd Service..."
cat <<EOF | sudo tee /etc/systemd/system/titan.service
[Unit]
Description=Titan Trading Bot
After=network.target

[Service]
User=$USER
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable titan

echo "✅ Deployment complete!"
echo "------------------------------------------------"
echo "To starting bot:"
echo "1. Edit .env (nano .env)"
echo "2. Run: sudo systemctl start titan"
echo "3. Logs: journalctl -u titan -f"
echo "------------------------------------------------"
