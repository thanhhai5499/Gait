# ================================
# Stage 1: Builder
# ================================
FROM python:3.12-slim AS builder

WORKDIR /app

# Cài build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy và cài requirements trước (tận dụng Docker layer cache)
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt


# ================================
# Stage 2: Runtime
# ================================
FROM python:3.12-slim

WORKDIR /app

# Cài runtime dependencies cho psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy thư viện từ builder
COPY --from=builder /install /usr/local

# Copy source code
COPY . .

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Port expose
EXPOSE 8000

# Chạy qua entrypoint (migrate rồi mới start server)
ENTRYPOINT ["/entrypoint.sh"]
