import math, os, urllib.parse, uvicorn
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from utils import db, file_utils, logger

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# Безопасное определение пути хранилища с откатом на локальную папку
_env_storage = os.environ.get("STORAGE_DIR", "images")
try:
    STORAGE_DIR = Path(_env_storage)
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    _test = STORAGE_DIR / ".check_perm"
    _test.touch()
    _test.unlink()
except (PermissionError, OSError):
    STORAGE_DIR = BASE_DIR / "images"
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 8000))

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация базы данных и рабочих каталогов при запуске приложения."""
    Path("backups").mkdir(parents=True, exist_ok=True)
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    db.init_db()
    yield

app = FastAPI(title="PixelVault Image Hosting", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Главная страница с приветствием и информацией о сервисе."""
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC_DIR / "favicon.ico")

@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request, uploaded: str | None = None, error: str | None = None):
    """Форма для загрузки одного или нескольких файлов."""
    files = []
    if uploaded:
        for name in (s.strip() for s in uploaded.split(",") if s.strip()):
            p = STORAGE_DIR / Path(name).name
            if p.is_file():
                files.append({"name": p.name, "url": f"/images/{p.name}", "size": p.stat().st_size})
    return templates.TemplateResponse(request=request, name="upload.html", context={"uploaded_files": files, "error": error})


@app.post("/upload")
async def upload_file(request: Request, images: list[UploadFile] | None = File(None)):
    """Загрузка одного или нескольких файлов с валидацией Pillow и сохранением в PostgreSQL."""
    is_browser = "text/html" in request.headers.get("accept", "")

    # request.form() возвращает starlette.UploadFile (родитель fastapi.UploadFile),
    # поэтому проверяем именно по базовому классу Starlette.
    try:
        form = await request.form()
        all_files = [v for _, v in form.multi_items() if isinstance(v, StarletteUploadFile) and v.filename]
    except Exception:
        all_files = []

    if not all_files and isinstance(images, list):
        all_files = [f for f in images if isinstance(f, StarletteUploadFile) and f.filename]

    if not all_files:
        logger.log_action("Ошибка", "Файл не выбран.")
        return RedirectResponse("/upload?error=Файл+не+выбран", status_code=303) if is_browser else JSONResponse({"success": False, "error": "Файл не выбран."}, status_code=400)

    saved_items, errors = [], []

    for target in all_files:
        # Читаем не больше лимита + 1 байт, чтобы не держать в памяти огромные файлы
        contents = await target.read(file_utils.MAX_UPLOAD_SIZE + 1)

        # 1. Валидация файла (размер до 5 МБ, расширение и Pillow)
        valid, new_filename, err = file_utils.validate_image(contents, target.filename)
        if not valid:
            logger.log_action("Ошибка", err)
            errors.append(err)
            continue

        # 2. Сохранение файла и запись метаданных в PostgreSQL (с транзакционным откатом)
        save_path = STORAGE_DIR / new_filename
        try:
            save_path.write_bytes(contents)
            orig_name = Path(target.filename).name or "image"
            record_id = db.save_image_metadata(new_filename, orig_name, len(contents), Path(new_filename).suffix.lstrip(".").lower())
            saved_items.append({"id": record_id, "filename": new_filename, "url": f"/images/{new_filename}"})
            logger.log_action("Успех", f"изображение {new_filename} загружено.")
        except Exception as e:
            save_path.unlink(missing_ok=True)
            logger.log_action("Ошибка", f"сбой сохранения метаданных в базе данных ({e})")
            errors.append("сбой сохранения метаданных в базе данных")

    if not saved_items:
        err_msg = "; ".join(errors) or "Не удалось загрузить файлы."
        return RedirectResponse(f"/upload?error={urllib.parse.quote(err_msg)}", status_code=303) if is_browser else JSONResponse({"success": False, "error": err_msg}, status_code=400)

    if is_browser:
        uploaded_param = urllib.parse.quote(",".join(s["filename"] for s in saved_items))
        return RedirectResponse(f"/upload?uploaded={uploaded_param}", status_code=303)

    first = saved_items[0]
    return {
        "success": True,
        "url": first["url"],
        "filename": first["filename"],
        "id": first["id"],
        "files": saved_items,
        "count": len(saved_items),
    }


@app.get("/images", response_class=HTMLResponse)
@app.get("/images/", response_class=HTMLResponse)
def gallery(request: Request, page: int = 1):
    """Галерея картинок с пагинацией по 12 элементов."""
    page = max(1, page)

    try:
        items, total = db.get_images_page(page=page, page_size=12)
    except Exception as e:
        logger.log_action("Ошибка", f"сбой получения изображений из БД ({e})")
        items, total = [], 0

    total_pages = max(1, math.ceil(total / 12)) if total else 1

    return templates.TemplateResponse(
        request=request,
        name="images.html",
        context={
            "images": [{**img, "name": img["filename"]} for img in items],
            "current_page": page,
            "total_pages": total_pages,
            "total_count": total,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "prev_page": page - 1,
            "next_page": page + 1,
        },
    )

@app.get("/images-list", response_class=HTMLResponse)
def images_list(request: Request, page: int = 1, deleted=None, error=None):
    """Реестр всех изображений из базы данных с пагинацией по 10 элементов."""
    page = max(1, page)
    try:
        items, total = db.get_images_page(page=page, page_size=10)
    except Exception as e:
        logger.log_action("Ошибка", f"сбой получения списка изображений из БД ({e})")
        items, total = [], 0

    pages = max(1, math.ceil(total / 10)) if total else 1

    return templates.TemplateResponse(request=request, name="images_list.html", context={
        "images": items, "current_page": page, "total_pages": pages, "total_count": total,
        "has_prev": page > 1, "has_next": page < pages, "prev_page": page - 1, "next_page": page + 1,
        "deleted": bool(deleted), "error": error,
    })

@app.post("/delete/{image_id}")
@app.delete("/delete/{image_id}")
def delete_image(request: Request, image_id: int):
    """Удаление изображения из базы данных и файлового хранилища."""
    is_browser = "text/html" in request.headers.get("accept", "")
    try:
        deleted_filename = db.delete_image_by_id(image_id)
        if deleted_filename:
            file_path = STORAGE_DIR / Path(deleted_filename).name
            file_path.unlink(missing_ok=True)
            logger.log_action("Успех", f"изображение {deleted_filename} (id={image_id}) удалено.")
            if is_browser:
                return RedirectResponse("/images-list?deleted=1", status_code=303)
            return JSONResponse({"success": True, "message": f"Изображение {deleted_filename} удалено", "id": image_id})
        else:
            logger.log_action("Ошибка", f"изображение id={image_id} не найдено для удаления")
            if is_browser:
                return RedirectResponse(f"/images-list?error={urllib.parse.quote('Изображение не найдено')}", status_code=303)
            return JSONResponse({"success": False, "error": "Изображение не найдено"}, status_code=404)
    except Exception as e:
        # Подробности — только в лог, пользователю — общее сообщение (без текста ошибок БД)
        logger.log_action("Ошибка", f"сбой удаления изображения id={image_id} ({e})")
        msg = "Не удалось удалить изображение"
        if is_browser:
            return RedirectResponse(f"/images-list?error={urllib.parse.quote(msg)}", status_code=303)
        return JSONResponse({"success": False, "error": msg}, status_code=500)

@app.get("/images/{filename}")
def serve_image(filename: str):
    """Отдаёт файл изображения."""
    file_path = STORAGE_DIR / Path(filename).name

    if not file_path.is_file():
        logger.log_action("Ошибка", f"изображение {file_path.name} не найдено")
        raise HTTPException(status_code=404, detail="Изображение не найдено")

    return FileResponse(file_path, media_type=file_utils.get_content_type(file_path.name))

@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    """Страница 'Обо мне'."""
    return templates.TemplateResponse(
        request=request,
        name="about.html",
        context={"title": "Обо мне"},
    )

@app.exception_handler(StarletteHTTPException)
@app.exception_handler(Exception)
def app_exception_handler(request: Request, exc: Exception):
    code = getattr(exc, "status_code", 500)
    detail = getattr(exc, "detail", None)
    if code >= 500 or detail is None:
        # Не показываем пользователю внутренний текст исключения
        detail = "Внутренняя ошибка сервера" if code >= 500 else "Ошибка запроса"

    logger.log_action("Ошибка", f"{code} {request.method} {request.url.path}" + (f" ({exc!r})" if code >= 500 else ""))

    accept = request.headers.get("accept", "")
    if "json" in accept or request.url.path.startswith("/api/"):
        return JSONResponse({"error": str(detail)}, status_code=code)

    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={"status_code": code, "detail": str(detail)},
        status_code=code,
    )

if __name__ == "__main__":
    uvicorn.run("app:app", host=HOST, port=PORT)