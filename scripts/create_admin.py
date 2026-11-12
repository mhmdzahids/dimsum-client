"""Explicit admin provisioning. Password is read privately, never from CLI args."""
import argparse
import getpass
from app.core.db import init_db, db_session
from app.modules.auth.models import User
from app.modules.auth.service import AuthService

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--email', required=True)
    parser.add_argument('--reset-existing', action='store_true')
    args = parser.parse_args()
    password = getpass.getpass('New admin password (12+ characters): ')
    if len(password) < 12 or password == 'password123' or password != getpass.getpass('Confirm password: '):
        raise SystemExit('Password too short or confirmation mismatch')
    init_db()
    try:
        user = db_session.query(User).filter_by(email=args.email.strip().lower()).first()
        if user and not args.reset_existing:
            raise SystemExit('Account exists; use --reset-existing to explicitly reset it')
        if not user:
            user = User(email=args.email.strip().lower(), full_name='Administrator', role='admin',
                        password_hash=AuthService.hash_password(password), is_registered=True, auth_version=0)
            db_session.add(user)
        else:
            user.password_hash = AuthService.hash_password(password)
            user.role = 'admin'
            user.is_registered = True
            user.auth_version += 1
        db_session.commit()
        print('Admin account provisioned')
    finally:
        db_session.remove()
