FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir . && \
    pip install --no-cache-dir duckduckgo-search youtube-transcript-api faiss-cpu

# App code
COPY . .

# Data directory
RUN mkdir -p /app/data/ontologies /app/data/graphs /app/data/simulations /app/data/databases /app/data/graphrag

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
