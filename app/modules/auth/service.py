import bcrypt
import uuid
import jwt
from datetime import datetime, timedelta, timezone
from app.core.db import db_session
from app.modules.auth.models import User
from app.core.config import Config
from app.shared.utils import sanitize_customer_name



class AuthService:
    @staticmethod
    def hash_password(password: str) -> str:
        if not isinstance(password, str) or not 6 <= len(password) or len(password.encode('utf-8')) > 72:
            raise ValueError('Kata sandi minimal 6 karakter dan maksimal 72 byte.')
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    @staticmethod
    def check_password(password_hash: str, password: str) -> bool:
        if not password_hash or not password:
            return False
        try:
            return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
        except Exception:
            return False

    @staticmethod
    def generate_token(user_id: str, role: str) -> str:
        # Smart token expiration based on role and operational needs
        if role in ('staff', 'inventory', 'checker'):
            # Operational roles that need longer sessions for POS and shift work
            expires_delta = timedelta(hours=12)  # 12 hours for operational staff
        elif role == 'admin':
            # Admin role - moderate session for admin panel
            expires_delta = timedelta(hours=8)   # 8 hours for admin workday
        else:
            # Customers and other roles
            expires_delta = timedelta(hours=4)   # 4 hours for customers

        user = db_session.get(User, user_id)
        payload = {
            'jti': uuid.uuid4().hex,
            'auth_version': user.auth_version if user else 0,
            'sub': user_id,
            'user_id': user_id,
            'role': role,
            'exp': datetime.now(timezone.utc) + expires_delta,
            'iat': datetime.now(timezone.utc)
        }
        return jwt.encode(payload, Config.SECRET_KEY, algorithm='HS256')

    @staticmethod
    def decode_token(token: str):
        from app.core.security import verify_token
        return verify_token(token)

    @staticmethod
    def revoke_token(token: str):
        from app.core.security import revoke_token
        revoke_token(token)

    @classmethod
    def register(cls, identifier: str, password: str, full_name: str, role: str = 'customer'):
        from sqlalchemy import func
        clean_name = sanitize_customer_name(full_name, default='')
        if not clean_name or len(clean_name) < 2:
            raise ValueError('Nama lengkap hanya boleh memuat huruf, angka, spasi, dan tanda baca nama (minimal 2 karakter).')
        clean_id = (identifier or '').strip().lower()
        existing_user = db_session.query(User).filter(
            (func.lower(User.email) == clean_id) | (User.phone == clean_id)
        ).first()
        hashed_pw = cls.hash_password(password)
        
        if existing_user:
            # Check if this user was created as a guest and hasn't registered a password
            is_unregistered = (
                not getattr(existing_user, 'is_registered', True) or
                existing_user.password_hash in ('guest', 'not_applicable') or
                str(existing_user.password_hash).startswith('guest_')
            )
            if is_unregistered:
                raise ValueError('Verifikasi kepemilikan akun diperlukan. Hubungi admin.')
            else:
                raise ValueError('Email atau nomor WhatsApp sudah terdaftar. Silakan masuk.')
            
        phone_val = clean_id if '@' not in clean_id else None
        new_user = User(
            email=clean_id,
            phone=phone_val,
            password_hash=hashed_pw,
            full_name=clean_name,
            role=role,
            is_registered=True
        )
        db_session.add(new_user)
        db_session.commit()
        return new_user

    @classmethod
    def login(cls, identifier: str, password: str):
        from sqlalchemy import func
        clean_id = (identifier or '').strip().lower()
        user = db_session.query(User).filter(
            (func.lower(User.email) == clean_id) | (User.phone == clean_id)
        ).first()
        if not user:
            raise ValueError('Email/Nomor WhatsApp atau kata sandi tidak sesuai.')
            
        is_unregistered = (
            not getattr(user, 'is_registered', True) or
            user.password_hash in ('guest', 'not_applicable') or
            str(user.password_hash).startswith('guest_')
        )
        if is_unregistered:
            raise ValueError('Akun ini belum memiliki kata sandi. Silakan buat akun melalui menu Daftar.')
            
        if not cls.check_password(user.password_hash, password):
            raise ValueError('Email/Nomor WhatsApp atau kata sandi tidak sesuai.')
            
        token = cls.generate_token(user.id, user.role)
        return user, token

    @classmethod
    def update_profile(cls, user_id: str, full_name: str, email: str = None, phone: str = None, current_password: str = None, new_password: str = None):
        from sqlalchemy import func
        user = db_session.get(User, user_id)
        if not user:
            raise ValueError('Pengguna tidak ditemukan.')

        clean_name = sanitize_customer_name(full_name, default='')
        if not clean_name or len(clean_name) < 2:
            raise ValueError('Nama lengkap hanya boleh memuat huruf, angka, spasi, dan tanda baca nama (minimal 2 karakter).')
        user.full_name = clean_name

        # Update Email if provided
        if email:
            clean_email = email.strip().lower()
            existing = db_session.query(User).filter(
                func.lower(User.email) == clean_email,
                User.id != user_id
            ).first()
            if existing:
                raise ValueError('Email sudah digunakan oleh akun lain.')
            user.email = clean_email

        # Update Phone if provided
        if phone:
            clean_phone = phone.strip()
            existing_phone = db_session.query(User).filter(
                ((User.phone == clean_phone) | (User.email == clean_phone)),
                User.id != user_id
            ).first()
            if existing_phone:
                raise ValueError('Nomor telepon sudah digunakan oleh akun lain.')
            user.phone = clean_phone

        # Password update logic
        if new_password:
            if len(new_password) < 6:
                raise ValueError('Kata sandi baru minimal 6 karakter.')

            # If user has an existing registered password, require & verify current_password
            has_password = (
                user.password_hash and
                user.password_hash not in ('guest', 'not_applicable') and
                not str(user.password_hash).startswith('guest_')
            )
            if has_password:
                if not current_password:
                    raise ValueError('Mohon masukkan kata sandi saat ini untuk konfirmasi.')
                if not cls.check_password(user.password_hash, current_password):
                    raise ValueError('Kata sandi saat ini tidak sesuai.')

            user.auth_version += 1
            user.password_hash = cls.hash_password(new_password)
            user.is_registered = True

        db_session.commit()
        return user

    @classmethod
    def login_with_google(cls, credential_token: str):
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
        from sqlalchemy import func
        import secrets

        if not Config.GOOGLE_CLIENT_ID:
            raise ValueError('GOOGLE_CLIENT_ID belum dikonfigurasi di file .env backend.')

        try:
            id_info = id_token.verify_oauth2_token(
                credential_token,
                google_requests.Request(),
                Config.GOOGLE_CLIENT_ID,
                clock_skew_in_seconds=30
            )
        except Exception as e:
            raise ValueError('Token Google tidak valid atau kadaluarsa.')

        email = (id_info.get('email') or '').strip().lower()
        if not id_info.get('email_verified'):
            raise ValueError('Email Google belum diverifikasi.')
        if not email:
            raise ValueError('Email tidak ditemukan dari akun Google.')

        full_name = (id_info.get('name') or id_info.get('given_name') or email.split('@')[0]).strip()

        # Check if user already exists with this email
        user = db_session.query(User).filter(func.lower(User.email) == email).first()

        if not user:
            random_pw = secrets.token_urlsafe(32)
            user = User(
                email=email,
                full_name=full_name,
                password_hash=cls.hash_password(random_pw),
                role='customer',
                is_registered=True
            )
            db_session.add(user)
            db_session.commit()
        else:
            if not getattr(user, 'is_registered', True):
                user.is_registered = True
                if not user.full_name or user.full_name == 'Pelanggan Guest':
                    user.full_name = full_name
                db_session.commit()

        token = cls.generate_token(user.id, user.role)
        return user, token

    VALID_ROLES = {'customer', 'staff', 'checker', 'inventory', 'admin'}
    INTERNAL_ROLES = {'staff', 'checker', 'inventory', 'admin'}

    @classmethod
    def list_internal_users(cls):
        """Returns list of internal team users (staff, checker, inventory, admin)"""
        users = db_session.query(User).filter(User.role.in_(list(cls.INTERNAL_ROLES))).order_by(User.created_at.desc()).all()
        return [u.to_dict() for u in users]

    @classmethod
    def create_internal_user(cls, email: str, password: str, full_name: str, role: str, phone: str = None):
        """Creates a new internal team user with an assigned role (admin only)"""
        from sqlalchemy import func
        if role not in cls.INTERNAL_ROLES:
            raise ValueError(f"Role internal tidak valid. Pilihan: {', '.join(sorted(cls.INTERNAL_ROLES))}")
        
        clean_email = (email or '').strip().lower()
        if not clean_email or '@' not in clean_email:
            raise ValueError("Email wajib diisi dan valid")
            
        clean_name = sanitize_customer_name(full_name, default='')
        if not clean_name or len(clean_name) < 2:
            raise ValueError("Nama lengkap minimal 2 karakter")
            
        if not password or len(password) < 6:
            raise ValueError("Kata sandi minimal 6 karakter")
            
        existing = db_session.query(User).filter(func.lower(User.email) == clean_email).first()
        if existing:
            raise ValueError("Email sudah digunakan oleh pengguna lain")
            
        hashed_pw = cls.hash_password(password)
        new_user = User(
            email=clean_email,
            phone=(phone or '').strip() or None,
            password_hash=hashed_pw,
            full_name=clean_name,
            role=role,
            is_registered=True
        )
        db_session.add(new_user)
        db_session.commit()
        return new_user

    @classmethod
    def update_user_role(cls, user_id: str, new_role: str, requesting_admin_id: str = None):
        """Updates an existing user's role (admin only)"""
        if new_role not in cls.VALID_ROLES:
            raise ValueError(f"Role tidak valid. Pilihan: {', '.join(sorted(cls.VALID_ROLES))}")
            
        user = db_session.get(User, user_id)
        if not user:
            raise ValueError("Pengguna tidak ditemukan")
            
        if requesting_admin_id and str(requesting_admin_id) == str(user_id) and new_role != 'admin':
            raise ValueError("Admin tidak dapat mencabut hak admin akun sendiri.")
            
        user.auth_version += 1
        user.role = new_role
        db_session.commit()
        return user
