#!/bin/bash

# Остановка при ошибке
set -e

echo "🚀 Начинаем установку Trading Bot..."

# 1. Обновление системы
echo "📦 Обновление пакетов Ubuntu..."
sudo apt update && sudo apt upgrade -y

# 2. Установка Python 3.10+ и зависимостей
echo "🐍 Установка Python и venv..."
sudo apt install -y python3 python3-pip python3-venv git htop screen

# 3. Настройка прав
echo "🔧 Настройка прав..."
chmod +x web_ui/server.py ai_agent.py

# 4. Создание виртуального окружения
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# 5. Активация и установка библиотек
echo "📥 Установка библиотек python..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "✅ Установка завершена!"
echo "---------------------------------------------------"
echo "👉 1. Создай файл с ключами:"
echo "      nano .env"
echo "👉 2. Запусти бота:"
echo "      screen -S tradebot"
echo "      source venv/bin/activate"
echo "      python web_ui/server.py"
echo "---------------------------------------------------"
