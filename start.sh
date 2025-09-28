#!/bin/bash

set -e

if ! command -v poetry &> /dev/null; then
    echo "Poetry не установлен. Установите: pip install poetry"
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "Создание виртуального окружения..."
    python -m venv .venv
else
    echo "Виртуальное окружение уже существует"
fi

source .venv/bin/activate
echo "Установка зависимостей..."
poetry install

uvicorn server:app --reload --host 0.0.0.0 --port 8000 &
UVICORN_PID=$!

sleep 3

python sensor.py &
SENSOR_PID=$!

echo "Открытие веб-станицы"
xdg-open "http://127.0.0.1:8000/client" || echo "Откройте: http://127.0.0.1:8000/client"

trap 'echo "Остановка сервера и датчика..."; kill $UVICORN_PID $SENSOR_PID 2>/dev/null || true; exit' INT TERM

wait