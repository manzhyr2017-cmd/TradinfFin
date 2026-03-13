#!/bin/bash
# Скрипт для быстрого обновления бота на VPS без потери данных

BOTDIR="/opt/grid-bot"
BACKUP_DIR="$BOTDIR/backup_$(date +%Y%m%d_%H%M%S)"

echo "🚀 Начинаем обновление Grid Bot на VPS..."

# 1. Создаем бэкап старого кода (на всякий случай)
mkdir -p $BACKUP_DIR
cp $BOTDIR/*.py $BACKUP_DIR/
echo "✅ Бэкап старого кода создан в $BACKUP_DIR"

# 2. Обновляем файлы
# Примечание: предполагается, что вы запускаете это из папки с новыми файлами
# или копируете содержимое вручную.
# Мы заменим только логику, не трогая папку data/ (где лежит база данных)

cp main_grid.py $BOTDIR/
cp grid_engine.py $BOTDIR/
cp grid_config.py $BOTDIR/
cp grid_executor.py $BOTDIR/
cp grid_telegram.py $BOTDIR/
cp logger.py $BOTDIR/

echo "✅ Файлы обновлены (база данных не затронута)."

# 3. Перезапускаем сервис
echo "🔄 Перезапуск сервиса..."
sudo systemctl restart grid-bot

echo "📊 Проверка статуса..."
sudo systemctl status grid-bot --no-pager

echo "✨ Готово! Теперь проверьте /status в Telegram."
