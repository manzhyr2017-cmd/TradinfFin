# Trading Bot Dockerfile with Tradingfin3.0
FROM python:3.9-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir \
    pandas \
    numpy \
    requests \
    openai \
    python-dotenv \
    pandas-ta \
    ta \
    joblib \
    xgboost \
    lightgbm \
    transformers \
    torch \
    passlib \
    cryptography \
    fastapi \
    uvicorn \
    scikit-learn \
    python-telegram-bot \
    aiohttp \
    pytest \
    pytest-asyncio \
    httpx

# Копируем весь проект
COPY . .

# Создаем директории для данных, логов и мониторинга
RUN mkdir -p /app/data /app/logs /app/monitoring

# Переменные окружения для Python
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV TZ=Asia/Kamchatka

# Открываем порты
EXPOSE 8080 9090 3000 9093

# Создаем скрипт запуска
RUN echo '#!/bin/bash\n\
    # Запуск Trading Bot\n\
    python main_bybit.py scan --continuous --auto-trade\n\
    ' > /app/start_bot.sh && chmod +x /app/start_bot.sh

# Создаем скрипт запуска мониторинга
RUN echo '#!/bin/bash\n\
    # Запуск Dashboard сервера\n\
    python web_ui/server.py\n\
    ' > /app/start_dashboard.sh && chmod +x /app/start_dashboard.sh

# Запуск по умолчанию - Dashboard сервер
CMD ["python", "web_ui/server.py"]
