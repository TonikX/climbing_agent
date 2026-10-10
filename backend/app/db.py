from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

engine = create_async_engine(get_settings().database_url, pool_pre_ping=True, hide_parameters=True)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
control_engine = create_async_engine(get_settings().control_database_url, pool_pre_ping=True, hide_parameters=True)
ControlSessionFactory = async_sessionmaker(control_engine, expire_on_commit=False)


async def set_user_context(session: AsyncSession, user_id: str) -> None:
    from sqlalchemy import text
    await session.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": user_id})
    session.info["user_id"] = user_id


async def get_control_session() -> AsyncIterator[AsyncSession]:
    async with ControlSessionFactory() as session:
        async with session.begin():
            yield session


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        async with session.begin():
            yield session
