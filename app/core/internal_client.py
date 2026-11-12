import logging
import httpx
from datetime import datetime, timezone
from app.core.config import Config
from app.core.db import db_session
from app.modules.products.models import Product
from app.modules.vouchers.models import Voucher
from app.modules.banners.models import Banner
from app.shared.utils import generate_uuid, utc_now

logger = logging.getLogger(__name__)

# In-memory last sync metadata
_sync_state = {
    'last_sync_time': None,
    'last_status': 'idle',
    'last_error': None,
    'synced_counts': {'products': 0, 'vouchers': 0, 'banners': 0}
}


class InternalApiClient:
    @staticmethod
    def get_headers():
        return {
            'X-API-Key': Config.INTERNAL_API_KEY,
            'Accept': 'application/json',
            'User-Agent': 'Dimsum-Buyer-Client/1.0'
        }

    @classmethod
    def is_configured(cls) -> bool:
        return bool(Config.INTERNAL_API_BASE_URL and Config.INTERNAL_API_KEY)

    @classmethod
    def check_connection(cls) -> dict:
        """
        Tests whether the internal factory API is reachable and accepting requests.
        """
        if not cls.is_configured():
            return {
                'connected': False,
                'configured': False,
                'message': 'INTERNAL_API_BASE_URL atau INTERNAL_API_KEY belum dikonfigurasi di .env',
                'base_url': Config.INTERNAL_API_BASE_URL,
                'last_sync': _sync_state['last_sync_time']
            }

        url = f"{Config.INTERNAL_API_BASE_URL}/products"
        try:
            with httpx.Client(timeout=Config.INTERNAL_API_TIMEOUT) as client:
                resp = client.get(url, headers=cls.get_headers())
                if resp.status_code == 200:
                    return {
                        'connected': True,
                        'configured': True,
                        'message': 'Terhubung ke API Sistem Internal Pabrik',
                        'base_url': Config.INTERNAL_API_BASE_URL,
                        'last_sync': _sync_state['last_sync_time'],
                        'synced_counts': _sync_state['synced_counts']
                    }
                elif resp.status_code == 401:
                    return {
                        'connected': False,
                        'configured': True,
                        'message': 'API Key ditolak oleh Sistem Internal (401 Unauthorized)',
                        'base_url': Config.INTERNAL_API_BASE_URL,
                        'last_sync': _sync_state['last_sync_time']
                    }
                else:
                    return {
                        'connected': False,
                        'configured': True,
                        'message': f'Server internal merespons dengan status {resp.status_code}',
                        'base_url': Config.INTERNAL_API_BASE_URL,
                        'last_sync': _sync_state['last_sync_time']
                    }
        except httpx.ConnectError:
            return {
                'connected': False,
                'configured': True,
                'message': f'Tidak dapat menghubungi {Config.INTERNAL_API_BASE_URL} (Server internal offline/belum running)',
                'base_url': Config.INTERNAL_API_BASE_URL,
                'last_sync': _sync_state['last_sync_time']
            }
        except Exception as e:
            return {
                'connected': False,
                'configured': True,
                'message': f'Koneksi error: {str(e)}',
                'base_url': Config.INTERNAL_API_BASE_URL,
                'last_sync': _sync_state['last_sync_time']
            }

    @classmethod
    def fetch_products(cls) -> list | None:
        if not cls.is_configured():
            return None
        url = f"{Config.INTERNAL_API_BASE_URL}/products"
        try:
            with httpx.Client(timeout=Config.INTERNAL_API_TIMEOUT) as client:
                resp = client.get(url, headers=cls.get_headers())
                if resp.status_code == 200:
                    body = resp.json()
                    if isinstance(body, dict) and body.get('success') is False:
                        raise ValueError(body.get('error') or 'Gagal mengambil data produk')
                    return body.get('data', body) if isinstance(body, dict) else body
        except Exception as e:
            logger.warning(f"Failed to fetch products from internal API: {e}")
        return None

    @classmethod
    def fetch_vouchers(cls) -> list | None:
        if not cls.is_configured():
            return None
        url = f"{Config.INTERNAL_API_BASE_URL}/vouchers"
        try:
            with httpx.Client(timeout=Config.INTERNAL_API_TIMEOUT) as client:
                resp = client.get(url, headers=cls.get_headers())
                if resp.status_code == 200:
                    body = resp.json()
                    if isinstance(body, dict) and body.get('success') is False:
                        raise ValueError(body.get('error') or 'Gagal mengambil data voucher')
                    return body.get('data', body) if isinstance(body, dict) else body
        except Exception as e:
            logger.warning(f"Failed to fetch vouchers from internal API: {e}")
        return None

    @classmethod
    def validate_voucher_remote(cls, code: str, subtotal: float) -> dict | None:
        """
        Validates voucher against internal system if available.
        """
        if not cls.is_configured():
            return None
        url = f"{Config.INTERNAL_API_BASE_URL}/vouchers/validate"
        try:
            with httpx.Client(timeout=Config.INTERNAL_API_TIMEOUT) as client:
                resp = client.post(url, headers=cls.get_headers(), json={'code': code, 'subtotal': subtotal})
                if resp.status_code == 200:
                    body = resp.json()
                    if isinstance(body, dict) and body.get('success') is False:
                        raise ValueError(body.get('error') or 'Kode promo tidak valid')
                    return body.get('data', body) if isinstance(body, dict) else body
                elif resp.status_code == 400:
                    err_body = resp.json()
                    err_msg = err_body.get('error') or err_body.get('message') or 'Kode promo tidak valid'
                    raise ValueError(err_msg)
        except ValueError:
            raise
        except Exception as e:
            logger.warning(f"Internal API voucher validation unavailable, falling back to local: {e}")
        return None

    @classmethod
    def fetch_banners(cls) -> list | None:
        if not cls.is_configured():
            return None
        url = f"{Config.INTERNAL_API_BASE_URL}/banners"
        try:
            with httpx.Client(timeout=Config.INTERNAL_API_TIMEOUT) as client:
                resp = client.get(url, headers=cls.get_headers())
                if resp.status_code == 200:
                    body = resp.json()
                    if isinstance(body, dict) and body.get('success') is False:
                        raise ValueError(body.get('error') or 'Gagal mengambil data banner')
                    return body.get('data', body) if isinstance(body, dict) else body
        except Exception as e:
            logger.warning(f"Failed to fetch banners from internal API: {e}")
        return None

    @classmethod
    def sync_catalog(cls) -> dict:
        """
        Pulls products, vouchers, and banners from internal factory API
        and updates the local PostgreSQL cache.
        """
        if not cls.is_configured():
            raise ValueError("Internal API is not configured in .env (INTERNAL_API_BASE_URL / INTERNAL_API_KEY)")

        products_data = cls.fetch_products()
        vouchers_data = cls.fetch_vouchers()
        banners_data = cls.fetch_banners()

        synced_products = 0
        synced_vouchers = 0
        synced_banners = 0

        # 1. Sync Products
        if products_data and isinstance(products_data, list):
            synced_skus = set()
            synced_ids = set()

            for p_raw in products_data:
                sku = p_raw.get('sku')
                if not sku:
                    continue
                synced_skus.add(sku)
                if p_raw.get('id'):
                    synced_ids.add(p_raw['id'])

                product = db_session.query(Product).filter_by(sku=sku).first()
                if not product:
                    product = Product(
                        id=p_raw.get('id') or generate_uuid(),
                        sku=sku,
                        name=p_raw.get('name', 'Dimsum Product'),
                        price=float(p_raw.get('price', 0.0)),
                        is_active=bool(p_raw.get('is_active', True))
                    )
                    db_session.add(product)

                # Update core sync attributes
                product.name = p_raw.get('name', product.name)
                product.price = float(p_raw.get('price', product.price))
                product.sku = sku
                product.is_active = bool(p_raw.get('is_active', product.is_active))
                
                # Discounts
                product.is_discount = bool(p_raw.get('is_discount', False))
                product.discount_percent = int(p_raw.get('discount_percent', 0))
                orig = p_raw.get('original_price')
                product.original_price = float(orig) if orig is not None else None

                # Stock
                stock_on = p_raw.get('stock_online')
                if stock_on is not None:
                    product.stock_online = int(stock_on)
                    product.stock_qty = (product.stock_offline or 0) + product.stock_online

                # Unit & Media
                if p_raw.get('unit'):
                    product.unit = p_raw['unit']
                if p_raw.get('pack_size'):
                    product.pack_size = int(p_raw['pack_size'])
                if p_raw.get('unit_label'):
                    product.unit_label = p_raw['unit_label']
                if p_raw.get('spec'):
                    product.weight = p_raw['spec']
                if p_raw.get('description'):
                    product.description = p_raw['description']

                # Image sync & local static asset caching
                remote_img = p_raw.get('image_url')
                if remote_img:
                    try:
                        from pathlib import Path
                        static_products_dir = Path(__file__).resolve().parent.parent / 'static' / 'uploads' / 'products'
                        static_products_dir.mkdir(parents=True, exist_ok=True)
                        filename = f"{sku}.webp"
                        target_file = static_products_dir / filename
                        with httpx.Client(timeout=10) as http_client:
                            r = http_client.get(remote_img)
                            if r.status_code == 200:
                                with open(target_file, 'wb') as f:
                                    f.write(r.content)
                                product.image_url = f"/static/uploads/products/{filename}"
                            else:
                                product.image_url = remote_img
                    except Exception as img_err:
                        logger.warning(f"Failed to cache product image locally: {img_err}")
                        product.image_url = remote_img
                else:
                    product.image_url = None

                synced_products += 1

            # Prune / Deactivate obsolete or factory-deleted products
            from app.modules.orders.models import OrderItem
            local_products = db_session.query(Product).all()
            for lp in local_products:
                if lp.sku not in synced_skus and lp.id not in synced_ids:
                    has_orders = db_session.query(OrderItem).filter_by(product_id=lp.id).first()
                    if has_orders:
                        lp.is_active = False
                    else:
                        db_session.delete(lp)

        # 2. Sync Vouchers
        if vouchers_data and isinstance(vouchers_data, list):
            synced_codes = set()
            for v_raw in vouchers_data:
                code = (v_raw.get('code') or '').strip().upper()
                if not code:
                    continue
                synced_codes.add(code)
                voucher = db_session.query(Voucher).filter_by(code=code).first()
                if not voucher:
                    voucher = Voucher(
                        id=v_raw.get('id') or generate_uuid(),
                        code=code,
                        discount_type=v_raw.get('discount_type', 'fixed'),
                        discount_value=float(v_raw.get('discount_value', 0.0))
                    )
                    db_session.add(voucher)

                voucher.discount_type = v_raw.get('discount_type', voucher.discount_type)
                voucher.discount_value = float(v_raw.get('discount_value', voucher.discount_value))
                voucher.min_spend = float(v_raw.get('min_spend', voucher.min_spend or 0.0))
                voucher.max_discount = float(v_raw['max_discount']) if v_raw.get('max_discount') is not None else None
                voucher.is_active = bool(v_raw.get('is_active', True))
                voucher.is_public = bool(v_raw.get('is_public', True))

                if v_raw.get('start_date'):
                    try:
                        voucher.start_date = datetime.fromisoformat(v_raw['start_date'].replace('Z', '+00:00'))
                    except Exception:
                        pass
                if v_raw.get('end_date'):
                    try:
                        voucher.end_date = datetime.fromisoformat(v_raw['end_date'].replace('Z', '+00:00'))
                    except Exception:
                        pass
                if v_raw.get('usage_limit') is not None:
                    voucher.usage_limit = int(v_raw['usage_limit'])

                synced_vouchers += 1

            # Prune obsolete or factory-deleted vouchers
            local_vouchers = db_session.query(Voucher).all()
            for lv in local_vouchers:
                if lv.code.upper() not in synced_codes:
                    db_session.delete(lv)

        # 3. Sync Banners
        if banners_data is not None and isinstance(banners_data, list):
            synced_banner_ids = set()
            from pathlib import Path
            static_banners_dir = Path(__file__).resolve().parent.parent / 'static' / 'uploads' / 'banners'
            static_banners_dir.mkdir(parents=True, exist_ok=True)

            for b_raw in banners_data:
                b_id = str(b_raw.get('id') or '')
                remote_img = b_raw.get('image_url')
                if not b_id or not remote_img:
                    continue

                synced_banner_ids.add(b_id)
                banner = db_session.query(Banner).filter_by(id=b_id).first()
                if not banner:
                    banner = Banner(
                        id=b_id,
                        title=b_raw.get('title') or 'Banner Promosi Dimsum',
                        filename=f"banner_{b_id}.webp",
                        image_url='',
                        is_active=bool(b_raw.get('is_active', True))
                    )
                    db_session.add(banner)
                else:
                    banner.title = b_raw.get('title') or banner.title or 'Banner Promosi Dimsum'
                    banner.is_active = bool(b_raw.get('is_active', banner.is_active))

                # Download and cache banner locally
                ext = '.webp'
                if '.' in remote_img:
                    clean_ext = remote_img.split('?')[0].rsplit('.', 1)[-1].lower()
                    if clean_ext in ('webp', 'png', 'jpg', 'jpeg'):
                        ext = f".{clean_ext}"
                filename = f"banner_{b_id}{ext}"
                target_file = static_banners_dir / filename

                try:
                    with httpx.Client(timeout=10) as http_client:
                        r = http_client.get(remote_img)
                        if r.status_code == 200:
                            with open(target_file, 'wb') as f:
                                f.write(r.content)
                            banner.filename = filename
                            banner.image_url = f"/static/uploads/banners/{filename}"
                        else:
                            banner.image_url = remote_img
                except Exception as img_err:
                    logger.warning(f"Failed to cache banner image locally: {img_err}")
                    banner.image_url = remote_img

                synced_banners += 1

            # Prune obsolete or factory-deleted banners
            local_banners = db_session.query(Banner).all()
            for lb in local_banners:
                if lb.id not in synced_banner_ids:
                    try:
                        if lb.filename:
                            del_target = static_banners_dir / lb.filename
                            if del_target.exists():
                                del_target.unlink()
                    except Exception:
                        pass
                    db_session.delete(lb)

        db_session.commit()

        now_iso = utc_now().isoformat()
        _sync_state['last_sync_time'] = now_iso
        _sync_state['last_status'] = 'success'
        _sync_state['last_error'] = None
        _sync_state['synced_counts'] = {
            'products': synced_products,
            'vouchers': synced_vouchers,
            'banners': synced_banners
        }

        return {
            'success': True,
            'synced_at': now_iso,
            'synced_products': synced_products,
            'synced_vouchers': synced_vouchers,
            'synced_banners': synced_banners
        }
