from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse


def json_response(body, status_code=200):
    return JSONResponse(jsonable_encoder(body), status_code=status_code)


def api_success(data=None, message=None, status=200):
    body = {'success': True}
    if data is not None:
        body['data'] = data
    if message:
        body['message'] = message
    return json_response(body, status)


def api_error(error, status=400, errors=None):
    body = {'success': False, 'error': error}
    if errors:
        body['errors'] = errors
    return json_response(body, status)
