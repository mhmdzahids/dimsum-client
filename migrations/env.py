from alembic import context
from sqlalchemy import create_engine
from app.core.config import Config
from app.core.db import Base, load_models
load_models()

def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()

if context.is_offline_mode():
    raise RuntimeError('Use an online PostgreSQL connection for schema migrations')
elif context.config.attributes.get('connection') is not None:
    run(context.config.attributes['connection'])
else:
    engine = create_engine(Config.DATABASE_URL)
    with engine.connect() as connection:
        run(connection)
    engine.dispose()
