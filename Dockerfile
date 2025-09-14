FROM python:3.11-slim

RUN pip install --no-cache-dir poetry

WORKDIR /app

COPY pyproject.toml poetry.lock ./

RUN poetry config virtualenvs.create false && \
    poetry install

COPY server.py sensor.py client.html start.sh ./

RUN chmod +x start.sh

CMD ["./start.sh"]