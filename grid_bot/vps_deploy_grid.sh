#!/bin/bash
# GRID BOT 2026 — VPS Deployment Script
# Usage: bash vps_deploy_grid.sh

set -e

echo "=== GRID BOT 2026 — VPS SETUP ==="

# 1. System updates
echo "[1/5] System update..."
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git

# 2. Create directory
echo "[2/5] Setting up project..."
BOTDIR="/opt/grid-bot"
sudo mkdir -p $BOTDIR
sudo chown $USER:$USER $BOTDIR

# Copy files (expects grid_bot/ to be in current directory)
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
    cp .env.example .env
    echo "⚠️  Edit .env with your API keys: nano $BOTDIR/.env"
fi

# Create data directory for state
mkdir -p data

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
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable grid-bot

echo ""
echo "=== SETUP COMPLETE ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env: nano $BOTDIR/.env"
echo "  2. Start bot: sudo systemctl start grid-bot"
echo "  3. View logs: journalctl -u grid-bot -f"
echo "  4. Stop bot:  sudo systemctl stop grid-bot"
echo ""
