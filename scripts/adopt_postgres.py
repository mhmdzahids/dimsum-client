"""Adopt the pre-Alembic PostgreSQL schema after taking a verified backup.
Refuses to stamp databases whose structure differs from the legacy baseline.
"""
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.config import Config as AlembicConfig
from sqlalchemy import MetaData, create_engine, inspect
from app.core.config import Config
from app.core.db import Base, load_models

if __name__ == '__main__':
    load_models()
    baseline = MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name not in {'revoked_tokens', 'rate_limit_buckets'}:
            table.to_metadata(baseline)
    baseline.tables['users']._columns.remove(baseline.tables['users'].c.auth_version)
    engine = create_engine(Config.DATABASE_URL)
    try:
        with engine.begin() as connection:
            if 'alembic_version' in inspect(connection).get_table_names():
                raise SystemExit('Database already managed by Alembic; use alembic upgrade head')
            differences = compare_metadata(MigrationContext.configure(connection), baseline)
            if differences:
                raise SystemExit('Schema differs from baseline; review before adopting')
            config = AlembicConfig('alembic.ini')
            config.attributes['connection'] = connection
            command.stamp(config, '0001')
            command.upgrade(config, 'head')
        print('Legacy schema verified and upgraded to Alembic head')
    finally:
        engine.dispose()
