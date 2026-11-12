FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install uv
RUN pip install uv

# Copy project specification
COPY pyproject.toml uv.lock README.md ./

# Install only the provider-free core runtime. Document parsing and evaluation
# dependencies remain available as optional project extras for future images.
RUN uv sync --frozen --no-dev

# Copy app code
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Expose FastAPI port
EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
