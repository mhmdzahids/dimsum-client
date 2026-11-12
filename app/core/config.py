import os
from dotenv import load_dotenv
# Explicitly load .env from the backend root directory as well as default CWD
_backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
_env_path = os.path.join(_backend_root, '.env')
if os.path.exists(_env_path):
    load_dotenv(_env_path)
load_dotenv()

class Config:
    ENV = os.environ.get('APP_ENV', 'development')

    # SECRET_KEY: fail-fast in production if not set or too short
    _raw_secret = os.environ.get('SECRET_KEY', '')
    if not _raw_secret or len(_raw_secret) < 32:
        raise RuntimeError(
            'CRITICAL: SECRET_KEY must be set to a secure value (min 32 chars) in production. '
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    SECRET_KEY = _raw_secret

    _raw_db = os.environ.get('DATABASE_URL', 'postgresql+psycopg://localhost/dimsum_dev')
    if _raw_db.startswith(('postgres://', 'postgresql://')):
        _raw_db = 'postgresql+psycopg://' + _raw_db.split('://', 1)[1]
    if not _raw_db.startswith('postgresql+psycopg://'):
        raise RuntimeError('DATABASE_URL must use PostgreSQL')
    DATABASE_URL = _raw_db

    ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173').split(',')
    
    PAYWUZ_API_KEY = os.environ.get('PAYWUZ_API_KEY', '')
    PAYWUZ_API_URL = os.environ.get('PAYWUZ_API_URL', 'https://api.paywuz.id/v1')
    PAYWUZ_WEBHOOK_SECRET = os.environ.get('PAYWUZ_WEBHOOK_SECRET', '')
    
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(_backend_root, 'app', 'static', 'uploads', 'banners'))
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024 # 5 MB limit

    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')

    # OpenWA WhatsApp API Gateway Configuration
    OPENWA_API_URL = os.environ.get('OPENWA_API_URL', 'http://localhost:2785').rstrip('/')
    OPENWA_SESSION_ID = os.environ.get('OPENWA_SESSION_ID', 'default')
    OPENWA_API_KEY = os.environ.get('OPENWA_API_KEY', '')
    OPENWA_ENABLED = os.environ.get('OPENWA_ENABLED', 'true').lower() in ('1', 'true', 'yes')

    PUBLIC_URL = os.environ.get('PUBLIC_URL', 'http://127.0.0.1:5173').rstrip('/')

    # Internal Factory System API Integration (mdi-backend / SuperProduction)
    INTERNAL_API_BASE_URL = os.environ.get('INTERNAL_API_BASE_URL', '').rstrip('/')
    INTERNAL_API_KEY = os.environ.get('INTERNAL_API_KEY', '')
    INTERNAL_API_TIMEOUT = float(os.environ.get('INTERNAL_API_TIMEOUT', 10.0))
    INTERNAL_API_ENABLED = bool(INTERNAL_API_BASE_URL and INTERNAL_API_KEY)

    # Production security validations
    if ENV == 'production':
        import logging
        _logger = logging.getLogger(__name__)
        if not PAYWUZ_WEBHOOK_SECRET:
            _logger.warning("SECURITY WARNING: PAYWUZ_WEBHOOK_SECRET is not set in production. Webhooks will be rejected until set.")
        # S-02: Warn if development-only origins are in production CORS
        for _origin in ALLOWED_ORIGINS:
            if 'ngrok' in _origin or 'localhost' in _origin or '127.0.0.1' in _origin:
                _logger.warning(f"SECURITY WARNING: Development origin '{_origin}' detected in production CORS config!")
