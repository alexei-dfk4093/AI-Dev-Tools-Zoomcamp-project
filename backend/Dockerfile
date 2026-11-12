# EcoMind backend: FastAPI API + SQLite storage.
#
# Build (from the repository root):
#   docker build -f backend/Dockerfile -t ecomind-backend .
#
# The SQLite database is created at /app/data/economind.db; mount a volume
# on /app/data to persist it across container replacements.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app /app/app

RUN mkdir -p /app/data

# /health is served for container orchestration checks.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

EXPOSE 8000

# One worker keeps the in-process background tasks and the AI request
# budget shared by every request.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
