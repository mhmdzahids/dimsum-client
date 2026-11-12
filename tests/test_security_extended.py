"""Local adversarial regression tests; isolated PostgreSQL and no provider calls."""
from uuid import uuid4
import pytest
import jwt
from datetime import datetime, timedelta, timezone
from app.modules.orders.models import Order
from app.modules.auth.models import User
from app.modules.auth.service import AuthService
from app.core.config import Config

@pytest.fixture
def private_order(db):
    user = User(id=str(uuid4()), email=f'{uuid4().hex}@example.test', full_name='Private Buyer',
                password_hash='unused', is_registered=True, role='customer')
    order = Order(id=str(uuid4()), customer_id=user.id, status='paid', total_amount=10000,
                  access_token=uuid4().hex, qr_token=uuid4().hex, customer_phone='081200001111')
    db.add(user); db.add(order); db.commit()
    return order

@pytest.mark.parametrize('suffix,method', [('', 'GET'), ('/qr.png', 'GET'), ('/sync-payment','POST'), ('/send-receipt','POST')])
@pytest.mark.parametrize('identity', ['anonymous', 'other_customer', 'wrong_order_token'])
def test_order_resource_ownership(client, customer_headers, private_order, suffix, method, identity):
    headers = customer_headers if identity == 'other_customer' else {'X-Order-Token':'wrong'} if identity == 'wrong_order_token' else {}
    res = client.request(method, f'/api/orders/{private_order.id}{suffix}', headers=headers)
    assert res.status_code == 403
    assert private_order.qr_token not in res.text
    assert private_order.customer_phone not in res.text


def test_order_query_token_is_not_authorization(client, private_order):
    assert client.get(f'/api/orders/{private_order.id}?token={private_order.access_token}').status_code == 403


def test_qr_authorized_positive_control(client, private_order):
    res = client.get(f'/api/orders/{private_order.id}/qr.png', headers={'X-Order-Token':private_order.access_token})
    assert res.status_code == 200
    assert res.content.startswith(b'\x89PNG')
    assert res.headers['cache-control'] == 'no-store'

PROTECTED = [('GET','/api/auth/users'), ('GET','/api/orders'), ('GET','/api/orders/transactions'),
             ('GET','/api/orders/pending-alerts'), ('GET','/api/orders/search-customer?q=Buyer'),
             ('GET','/api/ingredients'), ('POST','/api/products'), ('PUT','/api/products/missing'),
             ('DELETE','/api/products/missing'), ('POST','/api/banners'), ('DELETE','/api/banners/missing'),
             ('PUT','/api/settings/order-limit'), ('PUT','/api/settings/production-days'),
             ('POST','/api/orders/verify'), ('POST','/api/orders/pos'), ('POST','/api/orders/test-whatsapp')]
@pytest.mark.parametrize('method,path', PROTECTED)
@pytest.mark.parametrize('identity', ['anonymous','customer'])
def test_internal_resource_access(client, customer_headers, method, path, identity):
    response = client.request(method,path,headers=customer_headers if identity=='customer' else {})
    assert response.status_code == (403 if identity=='customer' else 401)

@pytest.mark.parametrize('content_type,body', [('application/x-www-form-urlencoded','full_name=CSRF'),('text/plain','{"full_name":"CSRF"}'),('application/json','{"full_name":"CSRF"}')])
def test_csrf_cookie_does_not_authenticate(client, admin_headers, content_type, body):
    response = client.put('/api/auth/profile', content=body, headers={'Origin':'https://attacker.example', 'Content-Type':content_type, 'Cookie':f"token={admin_headers['Authorization'][7:]}"})
    assert response.status_code in (401,403,415)
    assert 'access-control-allow-origin' not in response.headers

@pytest.mark.parametrize('kind', ['expired','forged','none','missing_jti'])
def test_invalid_jwt_rejected(client, customer_headers, kind):
    payload=jwt.decode(customer_headers['Authorization'][7:],options={'verify_signature':False})
    key=Config.SECRET_KEY; algorithm='HS256'
    if kind=='expired': payload['exp']=int((datetime.now(timezone.utc)-timedelta(seconds=5)).timestamp())
    if kind=='forged': key='attacker-key-with-at-least-32-characters'
    if kind=='none': key=None; algorithm='none'
    if kind=='missing_jti': payload.pop('jti')
    token=jwt.encode(payload,key,algorithm=algorithm)
    assert client.get('/api/auth/me',headers={'Authorization':f'Bearer {token}'}).status_code==401

@pytest.mark.parametrize('payload', ["' OR 1=1 --", "'; DROP TABLE users; --", '" UNION SELECT password_hash FROM users --'])
def test_sqli_cannot_login_or_read_order(client,payload):
    assert client.post('/api/auth/login',json={'identifier':payload,'password':'invalid'}).status_code==401
    res=client.get('/api/orders/'+payload)
    assert res.status_code==400
    assert 'SELECT' not in res.text

@pytest.mark.parametrize('path', ['/api/products','/api/auth/me','/api/orders','/.env','/static/../.env'])
def test_no_cache_or_secret_exposure(client,path):
    res=client.get(path)
    assert res.headers['cache-control']=='no-store'
    assert res.headers['x-content-type-options']=='nosniff'
    assert Config.SECRET_KEY not in res.text
    assert 'password_hash' not in res.text
    assert 'Traceback' not in res.text

@pytest.mark.parametrize('base', ['http://127.0.0.1:8000','http://169.254.169.254/latest/meta-data','https://api.paywuz.id.attacker.test','https://api.paywuz.id@attacker.test','file:///etc/passwd','https://api.paywuz.id:444/v1'])
def test_ssrf_gateway_configuration_rejected(monkeypatch, base):
    from app.modules.payments.service import payment_base_url
    monkeypatch.setattr(Config,'PAYWUZ_API_URL',base)
    with pytest.raises(ValueError): payment_base_url()


def test_payment_redirect_cannot_change_destination():
    from app.modules.payments.service import NoRedirect
    assert NoRedirect().redirect_request(None,None,302,'Redirect',{},'http://127.0.0.1/private') is None

@pytest.mark.parametrize('payload', ['[]','null','{"email":{}}','{"email":true}','{"email":"a@b.com","extra":"admin"}'])
def test_malformed_auth_forms_fail_closed(client,payload):
    res=client.post('/api/auth/register',content=payload,headers={'Content-Type':'application/json'})
    assert res.status_code==400
    assert 'Traceback' not in res.text


def test_origin_forgery_rejected_even_with_valid_bearer(client,admin_headers):
    res=client.put('/api/settings/order-limit',json={'order_item_limit':5},headers={**admin_headers,'Origin':'https://attacker.example'})
    assert res.status_code==403


def test_webhook_wrong_signature_cannot_mutate_order(client,private_order):
    res=client.post('/api/payments/webhook',json={'orderId':private_order.id,'status':'success'},headers={'X-Webhook-Signature':'forged'})
    assert res.status_code==403


def test_deactivated_account_token_rejected(client,db,private_order):
    user=db.get(User,private_order.customer_id)
    token=AuthService.generate_token(user.id,user.role)
    user.is_registered=False; db.commit()
    assert client.get('/api/auth/me',headers={'Authorization':f'Bearer {token}'}).status_code==401


def test_auth_version_rotation_invalidates_session(client,db,private_order):
    user=db.get(User,private_order.customer_id)
    token=AuthService.generate_token(user.id,user.role)
    user.auth_version+=1; db.commit()
    assert client.get('/api/auth/me',headers={'Authorization':f'Bearer {token}'}).status_code==401
