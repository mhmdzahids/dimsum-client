from contextvars import ContextVar
from threading import get_ident
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import scoped_session, sessionmaker, declarative_base
from app.core.config import Config

Base = declarative_base()
request_scope = ContextVar('database_request_scope', default=None)
db_session = scoped_session(sessionmaker(), scopefunc=lambda: request_scope.get() or get_ident())
engine = None


def init_db():
    """Connect only. Schema changes belong to Alembic, never HTTP startup."""
    global engine
    url = make_url(Config.DATABASE_URL)
    if url.get_backend_name() != 'postgresql':
        raise RuntimeError('Application runtime requires PostgreSQL')
    db_session.remove()
    engine = create_engine(url.set(drivername='postgresql+psycopg'), pool_pre_ping=True,
                           pool_recycle=280, pool_size=5, max_overflow=5)
    db_session.configure(bind=engine)
    load_models()
    with engine.connect() as connection:
        version = connection.execute(text('SELECT version_num FROM alembic_version')).scalar()
        if version != '0002':
            raise RuntimeError('Run alembic upgrade head before starting the API')
    return engine


def load_models():
    import app.modules.auth.models
    import app.modules.products.models
    import app.modules.orders.models
    import app.modules.payments.models
    import app.modules.inventory.models
    import app.modules.chat.models
    import app.modules.banners.models
    import app.modules.settings.models
    import app.modules.vouchers.models
    import app.modules.ingredients.models
    import app.core.security_models
