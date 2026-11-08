"""运行时只接受 MySQL；单元测试通过显式 engine 注入隔离数据库。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_engine(database_url: str):
    if not database_url.startswith('mysql+pymysql://'):
        raise ValueError('DATABASE_URL must use mysql+pymysql://')
    return create_engine(database_url, pool_pre_ping=True, pool_recycle=1800,
                         connect_args={'connect_timeout': 5})


def make_sessions(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
