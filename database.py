import os
import certifi
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

# 1. 优先读取 Vercel 的环境变量，本地开发时使用默认的 TiDB 字符串
# 注意：务必将这里换成你刚刚获取的真实账号密码和云端 host
SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL")


# 2. Serverless 核心架构：NullPool 防连接数爆炸，certifi 动态注入 CA 证书
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    poolclass=NullPool, 
    echo=False,
    connect_args={
        "ssl": {
            "ca": certifi.where()  # 魔法在这里：自动定位跨平台根证书！
        }
    }
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()