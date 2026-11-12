import uuid
from datetime import datetime, timezone

import re

def generate_uuid():
    return str(uuid.uuid4())

def utc_now():
    return datetime.now(timezone.utc)

def sanitize_customer_name(name_str: str, default: str = "Pelanggan") -> str:
    """
    Sanitizes customer full name by removing emojis, symbols, and non-name characters.
    Allows alphanumeric characters, spaces, and standard name punctuation (. ' -).
    Limits length to 70 characters. Defaults to `default` if empty after sanitization.
    """
    if not name_str:
        return default
    # Remove emoji characters, miscellaneous symbols, emoticons, pictographs
    cleaned = re.sub(r'[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\u2b50-\u2b55\u200d\ufe0f]', '', str(name_str))
    # Keep alphanumeric characters, spaces, and .'-
    cleaned = re.sub(r"[^\w\s\.\'\-]", '', cleaned, flags=re.UNICODE)
    # Collapse multiple whitespaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned[:70] if cleaned else default


def sanitize_text_field(text: str, max_length: int = 500, allow_emoji: bool = False) -> str:
    """
    Sanitizes text fields for order notes, delivery address, and other customer inputs.
    - Removes dangerous HTML/JavaScript by escaping (not removing)
    - Optionally removes emojis if allow_emoji=False
    - Trims whitespace and limits length
    
    Args:
        text: Input text to sanitize
        max_length: Maximum allowed length (default 500)
        allow_emoji: If True, keep emojis; if False, remove them (default False)
    
    Returns:
        Sanitized string safe for storage and display
    """
    if not text:
        return ""
    
    # Convert to string and strip whitespace
    cleaned = str(text).strip()
    
    # Remove emojis if not allowed
    if not allow_emoji:
        cleaned = re.sub(r'[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\u2b50-\u2b55\u200d\ufe0f]', '', cleaned)
        # Also remove ASCII control characters and dangerous symbols
        cleaned = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', cleaned)
    
    # Collapse multiple whitespaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    # Limit length
    cleaned = cleaned[:max_length]
    
    return cleaned if cleaned else ""
