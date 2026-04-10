# Stage 1: Builder
FROM python:3.13-slim as builder

WORKDIR /app

# Set environment variables
ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Install system build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libpq-dev \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install poetry==1.7.0

# Copy poetry files
COPY pyproject.toml poetry.lock* ./

# Configure Poetry and install dependencies
RUN poetry config virtualenvs.create false && \
    poetry install --only=main --no-root

# Stage 2: Runtime
FROM python:3.13-slim

WORKDIR /app

# Install runtime dependencies first
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libpq5 \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder stage
COPY --from=builder /usr/local/lib/python3.13/site-packages/ /usr/local/lib/python3.13/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# Verify alembic is available
RUN which alembic && alembic --version

# Copy application code (will be overridden by volume in development)
COPY . .

# Configure environment
ENV PYTHONPATH=/app \
    PORT=8000 \
    MODULE_NAME=app.main \
    VARIABLE_NAME=app

# Create non-root user
# RUN adduser --disabled-password --gecos '' logbukuser && \
#     chown -R logbukuser /app
# USER logbukuser

# Expose port
EXPOSE 8000

# Default command (overridden in docker-compose for development)
CMD ["sh", "-c", "alembic upgrade head && uvicorn ${MODULE_NAME}:${VARIABLE_NAME} --host 0.0.0.0 --port ${PORT}"]


# # Stage 1: Builder
# FROM python:3.13-slim as builder

# WORKDIR /app

# # Set environment variables
# ENV PYTHONFAULTHANDLER=1 \
#     PYTHONUNBUFFERED=1 \
#     PYTHONPATH=/app

# # Install system build dependencies
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential \
#     gcc \
#     libpq-dev \
#     curl \
#     git \
#     && rm -rf /var/lib/apt/lists/*

# # Install Poetry
# RUN pip install poetry==1.7.0

# # Copy poetry files
# COPY pyproject.toml poetry.lock* ./

# # Configure Poetry and install dependencies
# RUN poetry config virtualenvs.create false && \
#     poetry install --only=main --no-root

# # Stage 2: Runtime
# FROM python:3.13-slim

# WORKDIR /app

# # Copy installed packages from builder stage
# COPY --from=builder /usr/local/lib/python3.13/site-packages/ /usr/local/lib/python3.13/site-packages/
# COPY --from=builder /usr/local/bin/ /usr/local/bin/

# # Install runtime dependencies
# RUN apt-get update && \
#     apt-get install -y --no-install-recommends \
#     libpq5 \
#     postgresql-client \
#     && rm -rf /var/lib/apt/lists/*

# # Copy application code (will be overridden by volume in development)
# COPY . .

# # Configure environment
# ENV PYTHONPATH=/app \
#     PORT=8000 \
#     MODULE_NAME=app.main \
#     VARIABLE_NAME=app

# # Create non-root user
# RUN adduser --disabled-password --gecos '' logbukuser && \
#     chown -R logbukuser /app
# USER logbukuser

# # Expose port
# EXPOSE 8000

# # Default command (overridden in docker-compose for development)
# CMD ["sh", "-c", "alembic upgrade head && uvicorn ${MODULE_NAME}:${VARIABLE_NAME} --host 0.0.0.0 --port ${PORT}"]
