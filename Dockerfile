FROM python:3.11-slim

RUN pip install --no-cache-dir poetry

WORKDIR /app

COPY pyproject.toml poetry.lock ./

RUN poetry config virtualenvs.create false && \
    poetry install

COPY server.py ./

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]