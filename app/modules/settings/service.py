from app.core.db import db_session
from app.modules.settings.models import Setting

# Default values for all settings
DEFAULTS = {
    'order_item_limit': '50',
    'active_production_days': '0,1,2,3,4,5,6',
}


class SettingsService:
    @staticmethod
    def get(key: str) -> str:
        """Get a setting value by key. Returns default if not found."""
        setting = db_session.query(Setting).filter_by(key=key).first()
        if setting:
            return setting.value
        return DEFAULTS.get(key, '')

    @staticmethod
    def set(key: str, value: str):
        """Set a setting value. Creates or updates the row."""
        setting = db_session.query(Setting).filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            setting = Setting(key=key, value=value)
            db_session.add(setting)
        db_session.commit()
        return setting

    @classmethod
    def get_order_limit(cls) -> int:
        """Get the order item limit as an integer."""
        try:
            return int(cls.get('order_item_limit'))
        except (ValueError, TypeError):
            return int(DEFAULTS['order_item_limit'])

    @classmethod
    def set_order_limit(cls, value: int):
        """Validate and set the order item limit."""
        if not isinstance(value, int) or value < 1 or value > 500:
            raise ValueError('Order limit harus antara 1 dan 500')
        cls.set('order_item_limit', str(value))
        return value

    @classmethod
    def get_active_production_days(cls) -> list:
        """Get active production days (0=Mon, 6=Sun)"""
        try:
            val = cls.get('active_production_days')
            if not val:
                return []
            return [int(x.strip()) for x in val.split(',')]
        except Exception:
            return [0,1,2,3,4,5,6]

    @classmethod
    def set_active_production_days(cls, days: list):
        """Set active production days."""
        if not isinstance(days, list):
            raise ValueError('Days harus berupa list angka')
        valid_days = [str(d) for d in days if isinstance(d, int) and 0 <= d <= 6]
        cls.set('active_production_days', ','.join(valid_days))
        return [int(x) for x in valid_days]
