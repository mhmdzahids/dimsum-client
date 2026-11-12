import pytest
from datetime import datetime, timedelta
from app.core.db import db_session
from app.modules.products.models import Product
from app.modules.inventory.models import ProductionBatch, DailyProductionPlan
from app.shared.utils import generate_uuid, utc_now

def ensure_test_products():
    """Ensure at least 1 Mika (50 pcs) and 1 Vakum (25 pcs) product exist in DB."""
    mika = db_session.query(Product).filter(Product.sku == 'DIMSUM-JUMBO-MIKA-50').first()
    if not mika:
        mika = Product(
            id=generate_uuid(),
            name='Dimsum Jumbo (1 Mika Isi 50 Pcs)',
            sku='DIMSUM-JUMBO-MIKA-50',
            price=80000.0,
            stock_qty=100,
            is_active=True
        )
        db_session.add(mika)

    vakum = db_session.query(Product).filter(Product.sku == 'DIMSUM-MINI-PAX-25').first()
    if not vakum:
        vakum = Product(
            id=generate_uuid(),
            name='Dimsum Vakum (1 Pax Isi 25 Pcs)',
            sku='DIMSUM-MINI-PAX-25',
            price=25000.0,
            stock_qty=100,
            is_active=True
        )
        db_session.add(vakum)

    db_session.commit()
    return mika, vakum

def test_get_weekly_production_plans_initializes_7_days(client, admin_headers):
    ensure_test_products()
    res = client.get('/api/inventory/production/plans/weekly', headers=admin_headers)
    assert res.status_code == 200
    data = res.json()['data']

    assert 'plans' in data
    assert len(data['plans']) == 7
    assert 'weekly_totals' in data
    assert 'has_past_data' in data
    assert data['weekly_totals']['target_mika'] > 0

    today_str = utc_now().strftime('%Y-%m-%d')
    today_plan = next((p for p in data['plans'] if p['plan_date'] == today_str), None)
    assert today_plan is not None
    assert today_plan['target_mika'] == 350
    assert today_plan['target_vakum'] == 100
    assert today_plan['total_gilingan'] == 36.0
    assert today_plan['is_today'] is True
    assert 'readiness' in today_plan

def test_upsert_daily_production_plan(client, inventory_headers):
    ensure_test_products()
    today_str = utc_now().strftime('%Y-%m-%d')
    payload = {
        'plan_date': today_str,
        'target_mika': 400,
        'target_vakum': 120,
        'target_online': 300,
        'target_offline': 220,
        'notes': 'Lonjakan pesanan campaign online'
    }

    res = client.post('/api/inventory/production/plans/daily', json=payload, headers=inventory_headers)
    assert res.status_code == 200
    plan = res.json()['data']

    assert plan['target_mika'] == 400
    assert plan['target_vakum'] == 120
    assert plan['target_online'] == 300
    assert plan['target_offline'] == 220
    assert plan['notes'] == 'Lonjakan pesanan campaign online'
    # Gilingan: 400/350*30 = 34.3; 120/100*6 = 7.2; total = 41.5
    assert plan['total_gilingan'] > 36.0
    assert plan['total_channel_demand'] == 300 + 220

def test_generate_batches_from_daily_plan(client, inventory_headers):
    ensure_test_products()
    today_str = utc_now().strftime('%Y-%m-%d')
    # 1. Fetch weekly plans to get today's plan ID
    res = client.get('/api/inventory/production/plans/weekly', headers=inventory_headers)
    plans = res.json()['data']['plans']
    today_plan = next((p for p in plans if p['plan_date'] == today_str), plans[0])

    # 2. Call generate batches
    gen_res = client.post(
        f"/api/inventory/production/plans/{today_plan['id']}/generate-batches",
        headers=inventory_headers
    )
    assert gen_res.status_code == 201
    batches_data = gen_res.json()['data']
    assert len(batches_data['batches_created']) == 2

    # Mika batch lot_size should be 50, Vakum should be 25
    b_mika = next(b for b in batches_data['batches_created'] if b['lot_size'] == 50)
    b_vakum = next(b for b in batches_data['batches_created'] if b['lot_size'] == 25)
    assert b_mika['planned_lots'] == today_plan['target_mika']
    assert b_vakum['planned_lots'] == today_plan['target_vakum']

def test_cannot_generate_batches_for_past_plan(client, inventory_headers):
    ensure_test_products()
    yesterday_str = (utc_now() - timedelta(days=1)).strftime('%Y-%m-%d')
    # Upsert a past plan
    client.post('/api/inventory/production/plans/daily', json={'plan_date': yesterday_str, 'target_mika': 100}, headers=inventory_headers)
    
    # Get weekly plans
    res = client.get(f'/api/inventory/production/plans/weekly?start_date={yesterday_str}', headers=inventory_headers)
    plans = res.json()['data']['plans']
    past_plan = next((p for p in plans if p['plan_date'] == yesterday_str), None)
    assert past_plan is not None
    assert past_plan['is_past'] is True

    # Try generate batches for past plan -> should fail
    gen_res = client.post(
        f"/api/inventory/production/plans/{past_plan['id']}/generate-batches",
        headers=inventory_headers
    )
    assert gen_res.status_code == 400
    assert 'lewat' in gen_res.json()['error'].lower()

def test_unauthorized_daily_plan_upsert(client):
    res = client.post('/api/inventory/production/plans/daily', json={'plan_date': '2026-09-30'})
    assert res.status_code in (401, 403)
