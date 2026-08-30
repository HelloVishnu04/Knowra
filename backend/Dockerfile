FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install uv
RUN pip install uv

# Copy project specification
COPY pyproject.toml .

# Sync dependencies
RUN uv sync --frozen

# Copy app code
COPY app/ ./app/

# Expose FastAPI port
EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
