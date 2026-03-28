#!/bin/bash
# GRID BOT 2026 — VPS Deployment Script
# Usage: bash vps_deploy_grid.sh

set -e

echo "=== GRID BOT 2026 — VPS SETUP ==="

# 1. System updates & Swap
echo "[1/5] System update..."
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git curl htop

if [ ! -f /swapfile ]; then
    echo "Creating 2GB swap file..."
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

# 2. Create directory
echo "[2/5] Setting up project..."
BOTDIR="/opt/grid-bot"
sudo mkdir -p $BOTDIR
sudo chown $USER:$USER $BOTDIR

cp -r ./* $BOTDIR/
cd $BOTDIR

# 3. Virtual environment
echo "[3/5] Python venv..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. .env
echo "[4/5] Environment..."
if [ ! -f .env ]; then
    [ -f .env.example ] && cp .env.example .env || touch .env
    echo "⚠️  Edit .env with your API keys: nano $BOTDIR/.env"
fi

mkdir -p data logs

# 5. Systemd service
echo "[5/5] Creating systemd service..."
sudo tee /etc/systemd/system/grid-bot.service > /dev/null << EOF
[Unit]
Description=Grid Bot 2026
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$BOTDIR
ExecStart=$BOTDIR/venv/bin/python main_grid.py
Restart=always
RestartSec=10
StandardOutput=append:$BOTDIR/logs/output.log
StandardError=append:$BOTDIR/logs/error.log

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable grid-bot

echo ""
echo "=== ✅ SETUP COMPLETE ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env: nano $BOTDIR/.env"
echo "  2. Start bot: sudo systemctl start grid-bot"
echo "  3. View logs: tail -f $BOTDIR/logs/output.log"
echo ""
