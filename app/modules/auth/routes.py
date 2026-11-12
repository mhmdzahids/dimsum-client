from fastapi import APIRouter, Request, Depends
from app.shared.response import json_response
import re
from app.shared.response import api_success, api_error
from app.modules.auth.service import AuthService
from app.core.security import login_required, admin_required
from app.core.limiter import rate_limit
auth_bp = APIRouter()
EMAIL_REGEX = re.compile('^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\\.[a-zA-Z0-9-.]+$')
PHONE_REGEX = re.compile('^(?:\\+62|62|0)[0-9]{8,14}$')

def sanitize_identifier(raw: str):
    if not raw:
        return None
    val = raw.strip()
    if EMAIL_REGEX.match(val):
        return val.lower()
    cleaned_phone = re.sub('[\\s\\-]', '', val)
    if PHONE_REGEX.match(cleaned_phone):
        return cleaned_phone
    return None

@auth_bp.api_route('/register', methods=['POST'], dependencies=[Depends(rate_limit('5 per minute'))])
def register(request: Request):
    data = request.state.payload
    if not data:
        return api_error('Invalid request body', 400)
    raw_identifier = data.get('identifier') or data.get('email') or data.get('phone') or ''
    identifier = sanitize_identifier(raw_identifier)
    password = data.get('password') or ''
    full_name = (data.get('full_name') or '').strip()
    if not all([raw_identifier, password, full_name]):
        return api_error('Mohon lengkapi semua kolom: No WhatsApp/Email, Nama, dan Kata Sandi', 400)
    if not identifier:
        return api_error('Format Email atau Nomor WhatsApp tidak valid (contoh: 08123456789 atau user@domain.com)', 400)
    if len(password) < 6:
        return api_error('Kata sandi minimal 6 karakter', 400)
    try:
        user = AuthService.register(identifier, password, full_name)
        token = AuthService.generate_token(user.id, user.role)
        return api_success(data={'user': user.to_dict(), 'token': token}, status=201, message='Registrasi berhasil!')
    except ValueError as e:
        return api_error(str(e), 400)

@auth_bp.api_route('/login', methods=['POST'], dependencies=[Depends(rate_limit('5 per minute'))])
def login(request: Request):
    data = request.state.payload
    if not data:
        return api_error('Invalid request body', 400)
    raw_identifier = data.get('identifier') or data.get('email') or data.get('phone') or ''
    identifier = sanitize_identifier(raw_identifier) or raw_identifier.strip().lower()
    password = data.get('password') or ''
    if not all([raw_identifier, password]):
        return api_error('Mohon isi Nomor WhatsApp/Email dan kata sandi', 400)
    try:
        user, token = AuthService.login(identifier, password)
        return api_success(data={'user': user.to_dict(), 'token': token}, message='Login successful')
    except ValueError as e:
        return api_error(str(e), 401)

@auth_bp.api_route('/logout', methods=['POST'], dependencies=[Depends(login_required)])
def logout(request: Request):
    token = getattr(request.state, 'token', None)
    if token:
        AuthService.revoke_token(token)
    return api_success(message='Logged out successfully')

@auth_bp.api_route('/me', methods=['GET'], dependencies=[Depends(login_required)])
def me(request: Request):
    from app.modules.auth.models import User
    from app.core.db import db_session
    user = db_session.get(User, request.state.user_id)
    if not user:
        return api_error('User not found', 404)
    return api_success(data=user.to_dict())

@auth_bp.api_route('/profile', methods=['PUT'], dependencies=[Depends(login_required)])
def update_profile(request: Request):
    data = request.state.payload
    if not data:
        return api_error('Invalid request body', 400)
    full_name = (data.get('full_name') or '').strip()
    raw_email = (data.get('email') or '').strip()
    raw_phone = (data.get('phone') or '').strip()
    current_password = data.get('current_password') or ''
    new_password = data.get('new_password') or ''
    if not full_name:
        return api_error('Nama lengkap wajib diisi', 400)
    email = None
    if raw_email:
        if not EMAIL_REGEX.match(raw_email):
            return api_error('Format email tidak valid (contoh: user@domain.com)', 400)
        email = raw_email.lower()
    phone = None
    if raw_phone:
        cleaned_phone = re.sub('[\\s\\-]', '', raw_phone)
        if not PHONE_REGEX.match(cleaned_phone):
            return api_error('Format nomor WhatsApp/telepon tidak valid (contoh: 08123456789)', 400)
        phone = cleaned_phone
    if new_password and len(new_password) < 6:
        return api_error('Kata sandi baru minimal 6 karakter', 400)
    try:
        updated_user = AuthService.update_profile(user_id=request.state.user_id, full_name=full_name, email=email, phone=phone, current_password=current_password if current_password else None, new_password=new_password if new_password else None)
        return api_success(data=updated_user.to_dict(), message='Profil berhasil diperbarui!')
    except ValueError as e:
        return api_error(str(e), 400)

@auth_bp.api_route('/google', methods=['POST'], dependencies=[Depends(rate_limit('10 per minute'))])
def google_auth(request: Request):
    data = request.state.payload or {}
    credential = data.get('credential')
    if not credential:
        return api_error('Credential Google wajib disertakan', 400)
    try:
        user, token = AuthService.login_with_google(credential)
        return api_success(data={'user': user.to_dict(), 'token': token}, message='Berhasil masuk dengan Google')
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception as e:
        return api_error('Gagal memproses autentikasi Google. Silakan coba lagi nanti.', 500)

@auth_bp.api_route('/refresh', methods=['POST'], dependencies=[Depends(login_required)])
def refresh_token(request: Request):
    """
    Refresh buyer session token
    """
    try:
        user_id = getattr(request.state, 'user_id', None)
        user_role = getattr(request.state, 'user_role', None)
        if not user_id or not user_role:
            return api_error('Invalid token', 401)
        new_token = AuthService.generate_token(user_id, user_role)
        return api_success(data={'token': new_token}, message='Token refreshed successfully')
    except Exception as e:
        return api_error('Token refresh failed', 401)

