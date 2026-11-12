import asyncio
import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure standard web media types are registered across all platforms (notably Windows)
mimetypes.add_type('image/webp', '.webp')
mimetypes.add_type('image/svg+xml', '.svg')
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles
from app.core.config import Config
from app.core.db import init_db
from app.core.errors import register_error_handlers
from app.core.http import prepare_request, RequestScopeMiddleware
from app.core.limiter import rate_limit

logger = logging.getLogger(__name__)


async def periodic_catalog_sync():
    """Background task to periodically sync catalog from the internal factory API."""
    from app.core.internal_client import InternalApiClient
    # Initial delay to allow DB and external server to settle
    await asyncio.sleep(2)
    while True:
        try:
            if InternalApiClient.is_configured():
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, InternalApiClient.sync_catalog)
                logger.info("Auto-sync completed: %s", result.get('synced_counts'))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Auto-sync from internal factory skipped or failed: %s", e)
        try:
            await asyncio.sleep(300)  # Every 5 minutes
        except asyncio.CancelledError:
            break


def create_app():
    @asynccontextmanager
    async def lifespan(app):
        engine = init_db()
        sync_task = asyncio.create_task(periodic_catalog_sync())
        yield
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            pass
        engine.dispose()

    app = FastAPI(
        title='Dimsum API',
        lifespan=lifespan,
        dependencies=[Depends(prepare_request), Depends(rate_limit('300 per hour', global_scope=True))]
    )
    app.add_middleware(RequestScopeMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=Config.ALLOWED_ORIGINS,
        allow_methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
        allow_headers=[
            'Authorization',
            'Content-Type',
            'X-Order-Token',
            'X-Webhook-Signature',
            'X-API-Key',
            'X-Internal-Key'
        ],
        max_age=3600
    )
    register_error_handlers(app)

    @app.middleware('http')
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.update({
            'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; object-src 'none'; frame-ancestors 'none'",
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'X-XSS-Protection': '1; mode=block',
            'Referrer-Policy': 'strict-origin-when-cross-origin',
            'Cache-Control': 'no-store',
        })
        if Config.ENV == 'production':
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    from app.modules.auth.routes import auth_bp
    from app.modules.products.routes import products_bp
    from app.modules.orders.routes import orders_bp
    from app.modules.payments.routes import payments_bp
    from app.modules.banners.routes import banners_bp
    from app.modules.settings.routes import settings_bp
    from app.modules.vouchers.routes import vouchers_bp

    for name, router in [
        ('auth', auth_bp),
        ('products', products_bp),
        ('orders', orders_bp),
        ('payments', payments_bp),
        ('banners', banners_bp),
        ('settings', settings_bp),
        ('vouchers', vouchers_bp)
    ]:
        # Static paths must precede /{id}, as required by Starlette routing.
        router.routes.sort(key=lambda route: ('{' in route.path, -route.path.count('/')))
        app.include_router(router, prefix='/api/' + name)

    static = Path(__file__).parent / 'static'
    static.mkdir(exist_ok=True)
    app.mount('/static', StaticFiles(directory=static), name='static')

    @app.get('/health')
    def health_check():
        from app.core.db import db_session
        from sqlalchemy import text
        db_session.execute(text('SELECT 1'))
        return {'status': 'ok'}

    return app
