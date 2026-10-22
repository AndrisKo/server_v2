from pathlib import Path
import io
import uuid
from PIL import Image

MAX_UPLOAD_SIZE = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
}


def is_allowed_file(filename: str) -> bool:
    """Проверка допустимости расширения файла"""
    return Path(filename).suffix in ALLOWED_EXTENSIONS


def get_content_type(filename: str) -> str:
    """Определение MIME-типа изображения по расширению"""
    return MIME_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")


def validate_image(contents: bytes, filename: str):
    """Проверяет файл изображения на макс. размер, поддерживаемый формат файла..."""
    if not contents:
        return False, "", "файл пустой"

    if len(contents) > MAX_UPLOAD_SIZE:
        return False, "", "превышен максимальный размер файла (более 5 МБ)"

    if not is_allowed_file(filename):
        return False, "", f"неподдерживаемый формат файла ({filename})"

    try:
        img = Image.open(io.BytesIO(contents))
        img.verify()
        fmt = (img.format or "").upper()
    except Exception:
        return False, "", "повреждённый файл изображения"

    if fmt not in ("JPEG", "PNG", "GIF"):
        return False, "", f"неподдерживаемый формат файла ({fmt})"

    ext = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif"}[fmt]
    return True, f"{uuid.uuid4().hex}{ext}", ""

