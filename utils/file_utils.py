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
    # расширение без точки и маленькими буквами, например "png"
    ext = Path(filename).suffix.replace(".", "").lower()
    if ext in ALLOWED_EXTENSIONS:
        return True
    return False


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

    # открываем картинку через Pillow и проверяем что она не битая
    try:
        img = Image.open(io.BytesIO(contents))
        img.verify()
        fmt = img.format
    except Exception:
        return False, "", "повреждённый файл изображения"

    if fmt is None:
        fmt = ""
    fmt = fmt.upper()

    # расширение берём по настоящему формату файла, а не по имени
    if fmt == "JPEG":
        ext = ".jpg"
    elif fmt == "PNG":
        ext = ".png"
    elif fmt == "GIF":
        ext = ".gif"
    else:
        return False, "", f"неподдерживаемый формат файла ({fmt})"

    # новое случайное имя файла, чтобы файлы не перезаписывали друг друга
    new_filename = uuid.uuid4().hex + ext
    return True, new_filename, ""

