FROM python:3.13-slim

WORKDIR /app

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libpq-dev libpq5 postgresql-client curl git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install poetry==1.8.5

COPY pyproject.toml poetry.lock* ./

RUN poetry config virtualenvs.create false && \
    poetry install --only=main --no-root

RUN python -c "import alembic; print('alembic', alembic.__version__)"

COPY . .

ENV PORT=8000 MODULE_NAME=app.main VARIABLE_NAME=app

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn ${MODULE_NAME}:${VARIABLE_NAME} --host 0.0.0.0 --port ${PORT}"]
