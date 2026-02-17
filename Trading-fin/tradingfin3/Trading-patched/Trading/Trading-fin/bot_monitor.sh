#!/bin/bash
# Trading Bot Monitor Script
# ==========================
# Скрипт для проверки логов бота и отправки уведомлений в Telegram

LOG_FILE="bot.log"
STATE_FILE="bot_monitor_state.json"
CHECK_INTERVAL=60

# Telegram настройки
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-8339069750:AAGMYLCZ9bfovVb57fmB3vAZ_M7ePHbl2zo}"
TELEGRAM_CHANNEL="${TELEGRAM_CHANNEL:-1003842003511}"

# Функция отправки уведомления в Telegram
send_telegram() {
    local message="$1"
    if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHANNEL" ]; then
        curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
            -d chat_id="$TELEGRAM_CHANNEL" \
            -d text="$message" \
            -d parse_mode="HTML" > /dev/null 2>&1
    fi
}

# Функция проверки статуса бота
check_bot_status() {
    pgrep -f "main_bybit.py" > /dev/null
    return $?
}

# Функция проверки логов
check_logs() {
    if [ ! -f "$LOG_FILE" ]; then
        return
    fi
    
    # Получить последние 10 строк
    tail -n 10 "$LOG_FILE" | while read line; do
        # Проверить на ключевые слова
        if echo "$line" | grep -q "Исполнение сигнала"; then
            send_telegram "🚀 <b>Открыта сделка</b>:\n<code>$line</code>"
        elif echo "$line" | grep -q "отправлен успешно"; then
            send_telegram "✅ <b>Ордер отправлен</b>:\n<code>$line</code>"
        elif echo "$line" | grep -q "Ошибка"; then
            send_telegram "❌ <b>Ошибка</b>:\n<code>$line</code>"
        elif echo "$line" | grep -q "Предупреждение"; then
            send_telegram "⚠️ <b>Предупреждение</b>:\n<code>$line</code>"
        fi
    done
}

# Основной цикл
main() {
    echo "🚀 Запуск мониторинга бота"
    
    while true; do
        # Проверить статус бота
        if ! check_bot_status; then
            echo "⚠️ Бот не запущен!"
            send_telegram "⚠️ <b>Бот остановлен!</b> Проверьте логи."
            sleep 300
            continue
        fi
        
        # Проверить логи
        check_logs
        
        # Ждать следующую проверку
        sleep $CHECK_INTERVAL
    done
}

# Запуск
main
