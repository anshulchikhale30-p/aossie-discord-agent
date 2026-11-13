FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .
COPY frontdesk ./frontdesk
COPY config ./config

RUN mkdir -p /app/data/docs

CMD ["python", "bot.py"]
