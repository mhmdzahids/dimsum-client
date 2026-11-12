"""Copy a current SQLite database to an empty PostgreSQL database atomically.

Run: python -m scripts.transfer_sqlite --source /path/backup.db
Target is DATABASE_URL; source is opened read-only and never modified.
"""
import argparse
from pathlib import Path
from sqlalchemy import create_engine, inspect, select, func
from sqlalchemy.engine import make_url
from app.core.db import Base, load_models
from app.core.config import Config
from alembic import command
from alembic.config import Config as AlembicConfig


def transfer(source_path, target_url):
    source_path = Path(source_path).resolve(strict=True)
    url = make_url(target_url)
    if url.get_backend_name() != 'postgresql':
        raise ValueError('Target must be PostgreSQL')
    target = create_engine(url.set(drivername='postgresql+psycopg'))
    # URI mode=ro prevents accidental creation or changes to the source.
    source = create_engine(f'sqlite:///file:{source_path.as_posix()}?mode=ro&uri=true')
    load_models()
    counts = {}
    try:
        with source.connect() as src, target.begin() as dst:
            inspector = inspect(src)
            names = set(inspector.get_table_names())
            security_tables = {'revoked_tokens', 'rate_limit_buckets'}
            tables = [t for t in Base.metadata.sorted_tables if t.name not in security_tables]
            expected = {t.name for t in tables}
            if names - security_tables - {'alembic_version'} != expected:
                raise ValueError('Source table set differs from legacy baseline')
            source_columns = {}
            for table in tables:
                columns = {c['name'] for c in inspector.get_columns(table.name)}
                allowed_missing = {'auth_version'} if table.name == 'users' else set()
                if columns - set(table.columns.keys()) or set(table.columns.keys()) - columns - allowed_missing:
                    raise ValueError(f'Source columns differ for {table.name}; upgrade a backup first')
                source_columns[table.name] = [c for c in table.columns if c.name in columns]
            config = AlembicConfig('alembic.ini')
            config.attributes['connection'] = dst
            command.upgrade(config, 'head')
            for table in tables:
                if dst.scalar(select(func.count()).select_from(table)):
                    raise ValueError(f'Target table {table.name} is not empty; refusing to overwrite')
            # FK order and SQLAlchemy typed reads preserve UUIDs, booleans, dates,
            # decimals, password hashes and order access tokens.
            for table in tables:
                columns = source_columns[table.name]
                rows = src.execute(select(*columns)).mappings().all()
                if table.name == 'users':
                    import bcrypt
                    for row in rows:
                        if row['role'] != 'customer' and row.get('is_registered', True):
                            try:
                                demo_password = bcrypt.checkpw(b'password123', row['password_hash'].encode())
                            except (ValueError, TypeError):
                                demo_password = False
                            if demo_password:
                                raise ValueError('Source contains active demo credentials; reset or disable them on a backup first')
                for offset in range(0, len(rows), 500):
                    dst.execute(table.insert(), [dict(row) for row in rows[offset:offset + 500]])
                copied = dst.execute(select(*columns)).mappings().all()
                key = lambda row: tuple(str(row[c.name]) for c in table.primary_key)
                if sorted(rows, key=key) != sorted(copied, key=key):
                    raise ValueError(f'Content verification failed for {table.name}')
                counts[table.name] = len(rows)
        return counts
    finally:
        source.dispose()
        target.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    args = parser.parse_args()
    try:
        result = transfer(args.source, Config.DATABASE_URL)
    except Exception as exc:
        # Do not print DB URLs or row values, which may contain credentials/PII.
        raise SystemExit(f'Transfer failed ({type(exc).__name__}); transaction rolled back. Check schema and constraints.')
    for name, count in result.items():
        print(f'{name}: {count} rows verified')
