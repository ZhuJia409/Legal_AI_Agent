from functools import lru_cache

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.config import Settings


def build_mysql_async_url(settings: Settings) -> URL:
    return URL.create(
        "mysql+aiomysql",
        username=settings.mysql_user,
        password=settings.mysql_password or None,
        host=settings.mysql_host,
        port=settings.mysql_port,
        database=settings.mysql_database,
    )


def build_mysql_session_factory(settings: Settings) -> async_sessionmaker:
    return _cached_mysql_session_factory(
        settings.mysql_host,
        settings.mysql_port,
        settings.mysql_database,
        settings.mysql_user,
        settings.mysql_password,
    )


@lru_cache(maxsize=4)
def _cached_mysql_session_factory(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
) -> async_sessionmaker:
    engine = create_async_engine(
        URL.create(
            "mysql+aiomysql",
            username=user,
            password=password or None,
            host=host,
            port=port,
            database=database,
        ),
        pool_pre_ping=True,
    )
    return async_sessionmaker(bind=engine, expire_on_commit=False)


def session_factory_engine(session_factory: async_sessionmaker) -> AsyncEngine | None:
    bind = session_factory.kw.get("bind")
    return bind if isinstance(bind, AsyncEngine) else None
