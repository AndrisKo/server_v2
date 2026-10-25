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


def optimize_saved_image(file_path: Path) -> int | None:
    """
    Фоновая оптимизация сохранённого на диске изображения:
    уменьшение разрешения до 1920x1920 и сжатие.
    Возвращает новый размер файла в байтах или None в случае ошибки/отсутствия изменений.
    """
    try:
        if not file_path.is_file():
            return None

        ext = file_path.suffix.lower().lstrip(".")
        temp_path = file_path.with_suffix(file_path.suffix + ".opt")

        with Image.open(file_path) as img:
            # Ограничиваем максимальное разрешение до 1920x1920
            img.thumbnail((1920, 1920), Image.Resampling.LANCZOS)

            if ext in ("jpg", "jpeg"):
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img.save(temp_path, format="JPEG", quality=85, optimize=True)
            elif ext == "png":
                img.save(temp_path, format="PNG", optimize=True)
            elif ext == "gif":
                img.save(temp_path, format="GIF", optimize=True)
            else:
                return None

        # Атомарно заменяем исходный файл оптимизированным
        temp_path.replace(file_path)
        return file_path.stat().st_size
    except Exception:
        if 'temp_path' in locals() and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        return None


