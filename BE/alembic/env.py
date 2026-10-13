from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# --- Import settings và models của dự án ---
from app.config import settings
from app.database import Base
from app import models  # noqa: F401 — đảm bảo tất cả models được load vào Base.metadata

# Alembic Config object
config = context.config

# Đọc logging config từ alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Trỏ target_metadata vào Base của project — Alembic dùng để so sánh schema
target_metadata = Base.metadata

# Lấy DATABASE_URL từ .env thay vì alembic.ini
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


def run_migrations_offline() -> None:
    """
    Chạy migration ở chế độ offline (chỉ sinh SQL script, không kết nối DB).
    Dùng khi muốn review SQL trước khi apply.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,       # detect thay đổi kiểu dữ liệu
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Chạy migration ở chế độ online (kết nối thật vào DB và apply).
    Đây là chế độ thường dùng.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,        # detect thay đổi kiểu dữ liệu cột
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
