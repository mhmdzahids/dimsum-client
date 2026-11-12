"""Shared FastAPI request validation and request-scoped database lifecycle."""
import json
import math
import re
from uuid import uuid4
from fastapi import Request, HTTPException
from pydantic import BaseModel, ConfigDict, StrictStr, Field, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool
from app.core.config import Config
from app.core.db import db_session, request_scope


class AuthPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    identifier: StrictStr | None = Field(default=None, max_length=255)
    email: StrictStr | None = Field(default=None, max_length=255)
    phone: StrictStr | None = Field(default=None, max_length=50)
    full_name: StrictStr | None = Field(default=None, max_length=255)
    password: StrictStr | None = Field(default=None, max_length=72)
    current_password: StrictStr | None = Field(default=None, max_length=72)
    new_password: StrictStr | None = Field(default=None, max_length=72)
    role: StrictStr | None = Field(default=None, max_length=20)
    credential: StrictStr | None = Field(default=None, max_length=8192)


EMAIL_PATTERN = re.compile(r"[A-Za-z0-9_+\-]+(?:[.][A-Za-z0-9_+\-]+)*@[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?(?:[.][A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)+")


class CustomerInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: StrictStr = Field(min_length=1, max_length=100)
    email: StrictStr | None = Field(default=None, max_length=255)
    phone: StrictStr | None = Field(default=None, max_length=50)

    @field_validator('email')
    @classmethod
    def validate_email(cls, value):
        if value is None or not value.strip():
            return value
        email = value.strip()
        if len(email.split('@')[0]) > 64 or not EMAIL_PATTERN.fullmatch(email):
            raise ValueError('Format email tidak valid (contoh: nama@domain.com)')
        return email

class OrderItemInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    product_id: StrictStr = Field(min_length=1, max_length=36)
    quantity: int = Field(gt=0, le=10000)

class CheckoutInput(BaseModel):
    model_config = ConfigDict(extra='allow')
    customer: CustomerInput
    items: list[OrderItemInput] = Field(min_length=1, max_length=100)
    notes: StrictStr | None = Field(default=None, max_length=255)
    voucher_code: StrictStr | None = Field(default=None, max_length=50)
    pickup_time: StrictStr | None = Field(default=None, max_length=100)
    order_type: StrictStr = 'pickup'
    delivery_address: StrictStr | None = Field(default=None, max_length=500)


async def prepare_request(request: Request):
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        origin = request.headers.get('origin')
        if origin and origin not in Config.ALLOWED_ORIGINS:
            raise HTTPException(403, 'Untrusted request origin')
    request.state.payload = {}
    request.state.raw_body = b''
    request.state.files = {}
    form = None
    if request.method in ('POST', 'PUT', 'PATCH'):
        media_type = request.headers.get('content-type', '').split(';')[0]
        if media_type == 'application/json':
            raw = await request.body()
            request.state.raw_body = raw
            try:
                payload = json.loads(raw) if raw else {}
                if not isinstance(payload, dict):
                    raise ValueError('Expected JSON object')
                validate_values(payload)
                if request.url.path.startswith('/api/auth/'):
                    AuthPayload.model_validate(payload)
                elif request.url.path == '/api/orders' and request.method == 'POST':
                    CheckoutInput.model_validate(payload)
            except (ValueError, TypeError, ValidationError):
                raise HTTPException(400, 'Invalid request body')
            request.state.payload = payload
        elif media_type == 'multipart/form-data':
            form = await request.form(max_files=1, max_fields=20, max_part_size=Config.MAX_CONTENT_LENGTH)
            request.state.files = form
        elif media_type and media_type != 'application/x-www-form-urlencoded':
            raise HTTPException(415, 'Unsupported content type')
    try:
        yield
    finally:
        if form is not None:
            await form.close()


def validate_values(value, depth=0):
    if depth > 12:
        raise ValueError('JSON nesting too deep')
    if isinstance(value, str) and len(value) > 10000:
        raise ValueError('String too long')
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Invalid number')
    if isinstance(value, dict):
        if len(value) > 100:
            raise ValueError('Too many fields')
        for item in value.values():
            validate_values(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > 1000:
            raise ValueError('Too many items')
        for item in value:
            validate_values(item, depth + 1)


class RequestScopeMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        # Buffer a bounded body before handing it to the application/parser.
        from app.shared.response import api_error
        chunks = []
        size = 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            size += len(message.get('body', b''))
            if size > Config.MAX_CONTENT_LENGTH:
                return await api_error('Request body too large', 413)(scope, receive, send)
            chunks.append(message.get('body', b''))
            if not message.get('more_body', False):
                break
        consumed = False
        async def bounded_receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
            return await receive()
        token = request_scope.set(uuid4().hex)
        try:
            await self.app(scope, bounded_receive, send)
        finally:
            await run_in_threadpool(db_session.remove)
            request_scope.reset(token)
