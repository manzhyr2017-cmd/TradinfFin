# Используем официальный легкий образ Python
FROM python:3.9-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем системные зависимости (если нужны)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем зависимости
# Если requirements.txt неполный, добавляем основные вручную для надежности
RUN pip install --no-cache-dir \
    fastapi uvicorn Jinja2 python-multipart \
    pandas numpy requests python-telegram-bot

# Копируем весь проект
COPY . .

# Создаем директорию для БД и логов
RUN mkdir -p /app/data

# Переменные окружения для Python
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Открываем порт для Web Dashboard
EXPOSE 8080

# Запускаем Dashboard сервер
CMD ["python", "web_ui/server.py"]
