import os
import math
import urllib.parse
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
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

# Папка для картинок (в Docker Compose это примонтированный том /images)
STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", "images"))
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


def is_browser_request(request):
    """Проверяет, пришёл запрос из браузера или нет (например из curl или скрипта)."""
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return True
    else:
        return False


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
        names = uploaded.split(",")
        for name in names:
            name = name.strip()
            if name == "":
                continue

            # берём только имя файла, чтобы нельзя было передать путь типа ../../
            file_path = STORAGE_DIR / Path(name).name

            if file_path.is_file():
                file_info = {
                    "name": file_path.name,
                    "url": "/images/" + file_path.name,
                    "size": file_path.stat().st_size,
                }
                files.append(file_info)

    return templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={"uploaded_files": files, "error": error},
    )


@app.post("/upload")
async def upload_file(request: Request, images: list[UploadFile] | None = File(None)):
    """Загрузка одного или нескольких файлов с валидацией Pillow и сохранением в PostgreSQL."""
    is_browser = is_browser_request(request)

    # собираем все файлы из формы
    # ВАЖНО: request.form() возвращает UploadFile из starlette, а не из fastapi,
    # поэтому проверяем через StarletteUploadFile, иначе файлы не находятся
    all_files = []
    try:
        form = await request.form()
        for key, value in form.multi_items():
            if isinstance(value, StarletteUploadFile) and value.filename:
                all_files.append(value)
    except Exception:
        all_files = []

    # если в форме ничего не нашли - пробуем взять файлы из параметра images
    if len(all_files) == 0 and images:
        for f in images:
            if isinstance(f, StarletteUploadFile) and f.filename:
                all_files.append(f)

    # файлов нет совсем
    if len(all_files) == 0:
        logger.log_action("Ошибка", "Файл не выбран.")
        if is_browser:
            return RedirectResponse("/upload?error=Файл+не+выбран", status_code=303)
        return JSONResponse({"success": False, "error": "Файл не выбран."}, status_code=400)

    saved_items = []
    errors = []

    for upload in all_files:
        # читаем файл, но не больше 5 МБ + 1 байт (чтобы огромный файл не занял всю память)
        contents = await upload.read(file_utils.MAX_UPLOAD_SIZE + 1)

        # 1. проверяем файл (размер до 5 МБ, расширение и Pillow)
        valid, new_filename, error_text = file_utils.validate_image(contents, upload.filename)
        if not valid:
            logger.log_action("Ошибка", error_text)
            errors.append(error_text)
            continue

        # 2. сохраняем файл на диск и записываем информацию в базу
        save_path = STORAGE_DIR / new_filename
        try:
            save_path.write_bytes(contents)

            original_name = Path(upload.filename).name
            if original_name == "":
                original_name = "image"

            # тип файла = расширение без точки (png, jpg, gif)
            file_type = new_filename.split(".")[-1]

            record_id = db.save_image_metadata(new_filename, original_name, len(contents), file_type)

            saved_items.append({
                "id": record_id,
                "filename": new_filename,
                "url": "/images/" + new_filename,
            })
            logger.log_action("Успех", f"изображение {new_filename} загружено.")

        except Exception as e:
            # если в базу записать не получилось - удаляем файл, чтобы не было мусора
            if save_path.exists():
                save_path.unlink()
            logger.log_action("Ошибка", f"сбой сохранения метаданных в базе данных ({e})")
            errors.append("сбой сохранения метаданных в базе данных")

    # ни один файл не сохранился
    if len(saved_items) == 0:
        if len(errors) > 0:
            error_message = "; ".join(errors)
        else:
            error_message = "Не удалось загрузить файлы."

        if is_browser:
            return RedirectResponse("/upload?error=" + urllib.parse.quote(error_message), status_code=303)
        return JSONResponse({"success": False, "error": error_message}, status_code=400)

    # для браузера - перенаправляем обратно на страницу загрузки и показываем картинки
    if is_browser:
        names = []
        for item in saved_items:
            names.append(item["filename"])
        uploaded_param = urllib.parse.quote(",".join(names))
        return RedirectResponse("/upload?uploaded=" + uploaded_param, status_code=303)

    # для API - возвращаем JSON
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
    per_page = 12

    if page < 1:
        page = 1

    try:
        items, total = db.get_images_page(page=page, page_size=per_page)
    except Exception as e:
        logger.log_action("Ошибка", f"сбой получения изображений из БД ({e})")
        items = []
        total = 0

    # сколько всего страниц (минимум 1)
    total_pages = math.ceil(total / per_page)
    if total_pages < 1:
        total_pages = 1

    # шаблону нужно поле name, поэтому добавляем его к каждой картинке
    images = []
    for img in items:
        image = dict(img)
        image["name"] = img["filename"]
        images.append(image)

    return templates.TemplateResponse(
        request=request,
        name="images.html",
        context={
            "images": images,
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
    per_page = 10

    if page < 1:
        page = 1

    try:
        items, total = db.get_images_page(page=page, page_size=per_page)
    except Exception as e:
        logger.log_action("Ошибка", f"сбой получения списка изображений из БД ({e})")
        items = []
        total = 0

    # сколько всего страниц (минимум 1)
    total_pages = math.ceil(total / per_page)
    if total_pages < 1:
        total_pages = 1

    return templates.TemplateResponse(
        request=request,
        name="images_list.html",
        context={
            "images": items,
            "current_page": page,
            "total_pages": total_pages,
            "total_count": total,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "prev_page": page - 1,
            "next_page": page + 1,
            "deleted": bool(deleted),
            "error": error,
        },
    )


@app.post("/delete/{image_id}")
@app.delete("/delete/{image_id}")
def delete_image(request: Request, image_id: int):
    """Удаление изображения из базы данных и файлового хранилища."""
    is_browser = is_browser_request(request)

    try:
        deleted_filename = db.delete_image_by_id(image_id)

        if deleted_filename:
            # удаляем сам файл с диска
            file_path = STORAGE_DIR / Path(deleted_filename).name
            if file_path.exists():
                file_path.unlink()

            logger.log_action("Успех", f"изображение {deleted_filename} (id={image_id}) удалено.")
            if is_browser:
                return RedirectResponse("/images-list?deleted=1", status_code=303)
            return JSONResponse({"success": True, "message": f"Изображение {deleted_filename} удалено", "id": image_id})

        else:
            logger.log_action("Ошибка", f"изображение id={image_id} не найдено для удаления")
            message = "Изображение не найдено"
            if is_browser:
                return RedirectResponse("/images-list?error=" + urllib.parse.quote(message), status_code=303)
            return JSONResponse({"success": False, "error": message}, status_code=404)

    except Exception as e:
        # текст ошибки пишем только в лог, пользователю показываем простое сообщение
        logger.log_action("Ошибка", f"сбой удаления изображения id={image_id} ({e})")
        message = "Не удалось удалить изображение"
        if is_browser:
            return RedirectResponse("/images-list?error=" + urllib.parse.quote(message), status_code=303)
        return JSONResponse({"success": False, "error": message}, status_code=500)


@app.get("/images/{filename}")
def serve_image(filename: str):
    """Отдаёт файл изображения."""
    file_path = STORAGE_DIR / Path(filename).name

    if not file_path.is_file():
        logger.log_action("Ошибка", f"изображение {file_path.name} не найдено")
        raise HTTPException(status_code=404, detail="Изображение не найдено")

    content_type = file_utils.get_content_type(file_path.name)
    return FileResponse(file_path, media_type=content_type)


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
    # узнаём код ошибки и текст
    if isinstance(exc, StarletteHTTPException):
        code = exc.status_code
        detail = exc.detail
    else:
        code = 500
        detail = None

    if code >= 500:
        # ошибку сервера пишем в лог полностью, а пользователю не показываем подробности
        logger.log_action("Ошибка", f"{code} {request.method} {request.url.path} ({exc})")
        detail = "Внутренняя ошибка сервера"
    else:
        logger.log_action("Ошибка", f"{code} {request.method} {request.url.path}")
        if detail is None:
            detail = "Ошибка запроса"

    # если просили JSON - отвечаем JSON
    accept = request.headers.get("accept", "")
    if "json" in accept or request.url.path.startswith("/api/"):
        return JSONResponse({"error": str(detail)}, status_code=code)

    # иначе показываем красивую страницу ошибки
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={"status_code": code, "detail": str(detail)},
        status_code=code,
    )


if __name__ == "__main__":
    uvicorn.run("app:app", host=HOST, port=PORT)