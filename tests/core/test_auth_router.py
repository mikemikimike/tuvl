import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from tuvl.core.auth.iam_service import get_user_by_login as _get_user_by_login
from tuvl.core.auth.models import IAMUser


@pytest.fixture
async def memory_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all, tables=[IAMUser.__table__])

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


@pytest.mark.asyncio
async def test_get_user_by_login_email(memory_session: AsyncSession):
    # Setup test user
    user = IAMUser(
        email="test@example.com",
        phone_number="+15551234567",
        first_name="Test",
        last_name="User",
        is_active=True,
    )
    memory_session.add(user)
    await memory_session.commit()

    # Test lookup by email
    found = await _get_user_by_login(memory_session, "test@example.com")
    assert found is not None
    assert found.email == "test@example.com"
    assert found.first_name == "Test"


@pytest.mark.asyncio
async def test_get_user_by_login_phone(memory_session: AsyncSession):
    # Setup test user
    user = IAMUser(
        email="phone_user@example.com",
        phone_number="+15559876543",
        first_name="Phone",
        last_name="User",
        is_active=True,
    )
    memory_session.add(user)
    await memory_session.commit()

    # Test lookup by phone number
    found = await _get_user_by_login(memory_session, "+15559876543")
    assert found is not None
    assert found.email == "phone_user@example.com"
    assert found.phone_number == "+15559876543"


@pytest.mark.asyncio
async def test_get_user_by_login_not_found(memory_session: AsyncSession):
    # Test lookup for non-existent user
    found = await _get_user_by_login(memory_session, "nobody@example.com")
    assert found is None
