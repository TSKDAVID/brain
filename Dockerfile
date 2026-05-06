FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY supabase ./supabase

RUN pip install --upgrade pip \
    && pip install -e .

EXPOSE 8010

# Render sets $PORT; default to 8010 for local docker runs.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8010} --workers 2 --proxy-headers --forwarded-allow-ips '*'"]
