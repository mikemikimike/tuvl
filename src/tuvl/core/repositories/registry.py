from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from tuvl.core.repositories.base import BaseRepository


def get_repository(model_name: str, session: AsyncSession) -> BaseRepository[Any]:
    return BaseRepository(model_name, session)
