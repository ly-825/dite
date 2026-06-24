from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


# 创建数据库引擎，开启连接预检查可减少断线问题。
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """提供数据库会话依赖。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

