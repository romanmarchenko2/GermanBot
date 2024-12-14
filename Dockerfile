# Використовуємо офіційний образ Python
FROM python:3.11-slim

# Встановлюємо робочу директорію
WORKDIR /app

# Копіюємо файли залежностей
COPY requirements.txt .
COPY credentials.json .

# Встановлюємо залежності
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо код бота
COPY german_bot.py .

# Встановлюємо змінні середовища
ENV TELEGRAM_BOT_TOKEN=your_bot_token
ENV SPREADSHEET_ID=your_spreadsheet_id

# Запускаємо бота
CMD ["python", "german_bot.py"]