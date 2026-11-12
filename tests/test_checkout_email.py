import pytest
from unittest.mock import patch
from app.core.http import CustomerInput

@pytest.mark.parametrize('email', ['nama', 'nama@domain', 'nama.domain.com', 'nama@@domain.com', 'nama@.com', 'nama@domain.', 'nama@-domain.com', 'nama..lain@domain.com', 'nama @domain.com'])
def test_invalid_checkout_email_rejected_before_service(client, email):
    with patch('app.modules.orders.service.OrderService.create_order') as create:
        response = client.post('/api/orders', json={
            'customer': {'name': 'Buyer', 'phone': '081234567890', 'email': email},
            'items': [{'product_id': 'test-product', 'quantity': 1}]})
    assert response.status_code == 400
    create.assert_not_called()

@pytest.mark.parametrize('email', [None, '', '  ', 'nama@domain.com', 'nama.lain+tag@sub.domain.co.id', ' nama@domain.com '])
def test_valid_optional_checkout_email(email):
    CustomerInput(name='Buyer', email=email)
