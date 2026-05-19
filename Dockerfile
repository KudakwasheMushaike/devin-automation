FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies first (cached layer — only rebuilds when requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Create data directory for SQLite database
RUN mkdir -p /app/data

# Expose the port FastAPI runs on
EXPOSE 8000

# Health check — Docker will restart the container if this fails
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Start the server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
