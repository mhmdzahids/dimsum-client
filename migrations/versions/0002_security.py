"""Persist session revocation and shared rate limits; add credential version."""
from alembic import op
import sqlalchemy as sa
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('auth_version', sa.Integer(), nullable=False, server_default='0'))
    op.create_table('revoked_tokens',
        sa.Column('digest', sa.String(64), primary_key=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_revoked_tokens_expires_at', 'revoked_tokens', ['expires_at'])
    op.create_table('rate_limit_buckets',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_rate_limit_buckets_expires_at', 'rate_limit_buckets', ['expires_at'])

    # Existing published demo credentials must not survive the security migration.
    # Do not delete users/orders: disable only known demo accounts with that password.
    import bcrypt
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, password_hash FROM users WHERE email IN ('admin@dimsum.id', 'inventory@dimsum.id', 'checker@dimsum.id', 'staff@dimsum.id')")).mappings()
    for row in rows:
        try:
            is_demo = bcrypt.checkpw(b'password123', row['password_hash'].encode())
        except (ValueError, TypeError):
            is_demo = False
        if is_demo:
            connection.execute(sa.text('UPDATE users SET is_registered = false, auth_version = auth_version + 1 WHERE id = :id'), {'id': row['id']})


def downgrade():
    op.drop_table('rate_limit_buckets')
    op.drop_table('revoked_tokens')
    op.drop_column('users', 'auth_version')
