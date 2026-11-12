import os
import pytest
from app.core.config import Config

# PostgreSQL tests use a fresh schema, never shared application tables.
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from uuid import uuid4

_test_url = os.environ.get("TEST_DATABASE_URL") or str(Config.DATABASE_URL)
url = make_url(_test_url)
if url.get_backend_name() != "postgresql":
    raise RuntimeError("Tests require PostgreSQL")
url = url.set(drivername="postgresql+psycopg")
_test_engine = create_engine(url)
_test_schema = "test_" + uuid4().hex
with _test_engine.begin() as conn:
    conn.execute(text(f'CREATE SCHEMA "{_test_schema}"'))
Config.DATABASE_URL = url.update_query_dict({"options": f"-csearch_path={_test_schema}"})
Config.ENV = 'testing'
Config.SECRET_KEY = 'test-secret-key-32-chars-long-must-be-secure!'

from app.main import create_app
from app.core.db import db_session, Base
from app.modules.auth.models import User
from app.modules.auth.service import AuthService
from app.shared.utils import generate_uuid

from fastapi.testclient import TestClient
from alembic.config import Config as AlembicConfig
from alembic import command

class DatabaseAwareTestClient(TestClient):
    def request(self, *args, **kwargs):
        response = super().request(*args, **kwargs)
        # HTTP handlers use an independent request session; refresh assertions.
        db_session.expire_all()
        return response


@pytest.fixture(scope='session')
def app():
    Config.RATELIMIT_ENABLED = False
    engine = create_engine(Config.DATABASE_URL)
    with engine.begin() as connection:
        config = AlembicConfig('alembic.ini')
        config.attributes['connection'] = connection
        command.upgrade(config, 'head')
    engine.dispose()
    app_instance = create_app()
    with DatabaseAwareTestClient(app_instance, raise_server_exceptions=False) as http:
        from seed import seed_products
        seed_products()
        app_instance.state.test_client = http
        yield app_instance
    db_session.remove()
    with _test_engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA "{_test_schema}" CASCADE'))
    _test_engine.dispose()

@pytest.fixture
def client(app):
    return app.state.test_client

@pytest.fixture
def db(app):
    """Provides a clean database session per test."""
    yield db_session
    db_session.rollback()

@pytest.fixture
def admin_headers(app, client, db):
    """Returns authorization headers for an authenticated admin user."""
    admin_user = db_session.query(User).filter_by(email='admin@dimsum.id').first()
    if not admin_user:
        admin_user = User(
            id=generate_uuid(),
            email='admin@dimsum.id',
            password_hash=AuthService.hash_password('password123'),
            full_name='Super Admin',
            role='admin'
        )
        db_session.add(admin_user)
        db_session.commit()
    
    token = AuthService.generate_token(admin_user.id, admin_user.role)
    return {
        'Authorization': f"Bearer {token}",
        'Content-Type': 'application/json'
    }

@pytest.fixture
def customer_headers(app, client, db):
    """Returns authorization headers for an authenticated customer user."""
    customer = db_session.query(User).filter_by(email='customer.test@dimsum.id').first()
    if not customer:
        customer = User(
            id=generate_uuid(),
            email='customer.test@dimsum.id',
            phone='081234567899',
            password_hash=AuthService.hash_password('password123'),
            full_name='Pelanggan Uji Coba',
            role='customer',
            is_registered=True
        )
        db_session.add(customer)
        db_session.commit()

    token = AuthService.generate_token(customer.id, customer.role)
    return {
        'Authorization': f"Bearer {token}",
        'Content-Type': 'application/json'
    }

@pytest.fixture
def staff_headers(app, client, db):
    """Returns authorization headers for an authenticated staff user."""
    staff = db_session.query(User).filter_by(email='staff.test@dimsum.id').first()
    if not staff:
        staff = User(
            id=generate_uuid(),
            email='staff.test@dimsum.id',
            password_hash=AuthService.hash_password('password123'),
            full_name='Staff Kasir',
            role='staff',
            is_registered=True
        )
        db_session.add(staff)
        db_session.commit()

    token = AuthService.generate_token(staff.id, staff.role)
    return {
        'Authorization': f"Bearer {token}",
        'Content-Type': 'application/json'
    }

@pytest.fixture
def inventory_headers(app, client, db):
    """Returns authorization headers for an authenticated inventory user (Ayu/Lala)."""
    user = db_session.query(User).filter_by(email='inventory.test@dimsum.id').first()
    if not user:
        user = User(
            id=generate_uuid(),
            email='inventory.test@dimsum.id',
            password_hash=AuthService.hash_password('password123'),
            full_name='Lala Inventory',
            role='inventory',
            is_registered=True
        )
        db_session.add(user)
        db_session.commit()

    token = AuthService.generate_token(user.id, user.role)
    return {
        'Authorization': f"Bearer {token}",
        'Content-Type': 'application/json'
    }

@pytest.fixture
def checker_headers(app, client, db):
    """Returns authorization headers for an authenticated checker user (Om Yosi)."""
    user = db_session.query(User).filter_by(email='checker.test@dimsum.id').first()
    if not user:
        user = User(
            id=generate_uuid(),
            email='checker.test@dimsum.id',
            password_hash=AuthService.hash_password('password123'),
            full_name='Om Yosi Checker',
            role='checker',
            is_registered=True
        )
        db_session.add(user)
        db_session.commit()

    token = AuthService.generate_token(user.id, user.role)
    return {
        'Authorization': f"Bearer {token}",
        'Content-Type': 'application/json'
    }

