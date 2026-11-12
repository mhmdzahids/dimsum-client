import logging
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from sqlalchemy.exc import IntegrityError, DataError
from app.shared.response import api_error


def register_error_handlers(app):
    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return api_error(str(exc.detail), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return api_error('Invalid request body or parameters', 400)

    @app.exception_handler(ValueError)
    @app.exception_handler(TypeError)
    @app.exception_handler(KeyError)
    @app.exception_handler(IntegrityError)
    @app.exception_handler(DataError)
    async def invalid_input(request, exc):
        return api_error('Invalid input or conflicting data', 400)

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        logging.getLogger(__name__).error('Unhandled API error: %s', type(exc).__name__)
        return api_error('An internal error occurred', 500)
