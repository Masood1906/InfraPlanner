FROM python:3.11-slim

# Non-root user — never run as root in production
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Install dependencies first (layer cache — only rebuilds when requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source — owned by appuser
COPY --chown=appuser:appgroup . .

# Drop to non-root
USER appuser

EXPOSE 8000

# Health check — Docker will mark container unhealthy if /health fails
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

# Use exec form so uvicorn receives SIGTERM directly (clean shutdown)
CMD ["python", "main.py", "--serve"]
