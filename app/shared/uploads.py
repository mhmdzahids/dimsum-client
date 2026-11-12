"""Decode and re-encode every uploaded image; never serve original bytes."""
import uuid
import warnings
from pathlib import Path
from PIL import Image, UnidentifiedImageError


def save_image(file, folder):
    if not file or not getattr(file, 'filename', ''):
        raise ValueError('No file provided')
    if Path(file.filename).suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
        raise ValueError('File type not allowed')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(file.file) as image:
                if image.width * image.height > 16_000_000 or min(image.size) < 1:
                    raise ValueError('Image dimensions too large')
                image.load()
                clean = image.convert('RGBA' if image.mode == 'RGBA' else 'RGB')
                clean.thumbnail((960, 960), Image.Resampling.LANCZOS)
                destination = Path(folder)
                destination.mkdir(parents=True, exist_ok=True)
                name = uuid.uuid4().hex + '.webp'
                clean.save(destination / name, 'WEBP', quality=82)
                return name
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('Invalid or unsafe image') from exc
