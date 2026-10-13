#!/bin/bash
set -e

echo "======================================="
echo " Gait Analysis API - Starting up..."
echo "======================================="

# Chờ PostgreSQL sẵn sàng
echo "Waiting for PostgreSQL to be ready..."
until python -c "
import psycopg2, os, sys
try:
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    conn.close()
    print('PostgreSQL is ready!')
except Exception as e:
    print(f'Not ready yet: {e}')
    sys.exit(1)
"; do
  echo "  PostgreSQL unavailable - retrying in 2s..."
  sleep 2
done

# Kiểm tra DB đã có tables chưa (fresh install hay đã có data)
TABLES_EXIST=$(python -c "
import psycopg2, os
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute(\"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='users'\")
print(cur.fetchone()[0])
conn.close()
")

if [ "$TABLES_EXIST" = "1" ]; then
    echo "DB already has tables — skipping migration, stamping head..."
    # Tạo file migration giả nếu versions/ rỗng (alembic cần ít nhất 1 revision)
    if [ -z "$(ls -A /app/alembic/versions/ 2>/dev/null)" ]; then
        alembic revision --autogenerate -m "initial_schema" > /dev/null 2>&1 || true
    fi
    alembic stamp head
    echo "Stamp completed."
else
    echo "Fresh database — generating and applying migrations..."
    if [ -z "$(ls -A /app/alembic/versions/ 2>/dev/null)" ]; then
        alembic revision --autogenerate -m "initial_schema"
    fi
    alembic upgrade head
    echo "Migrations completed."
fi

# Xóa bytecode cache cũ để tránh dùng .pyc từ image cũ
find /app/app -name '*.pyc' -delete 2>/dev/null || true
find /app/app -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
echo "Cleared Python bytecode cache."

# Khởi động FastAPI server
echo "Starting FastAPI server on port 8000..."
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1
