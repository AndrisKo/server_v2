import os
import math
import urllib.parse
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from utils import db, file_utils, logger

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", "images"))
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 8000))


MAX_FILES_PER_REQUEST = 20


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация базы данных и рабочих каталогов при запуске приложения."""
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    db.init_db()
    yield


app = FastAPI(title="PixelVault Image Hosting", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def get_client_ip(request: Request):
    """Узнаёт реальный IP-адрес пользователя."""
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "127.0.0.1")


def upload_error(message):
    """Возвращает пользователя на страницу загрузки с текстом ошибки."""
    return RedirectResponse(f"/upload?error={urllib.parse.quote(message)}", status_code=303)


def get_page_data(page, per_page):
    """Берёт одну страницу картинок из БД и считает данные для пагинации."""
    page = max(page, 1)

    try:
        items, total = db.get_images_page(page=page, page_size=per_page)
    except Exception as e:
        logger.log_action("Ошибка", f"сбой получения изображений из БД ({e})")
        items, total = [], 0

    # сколько всего страниц (минимум 1)
    total_pages = max(math.ceil(total / per_page), 1)

    return {
        "images": items,
        "current_page": page,
        "total_pages": total_pages,
        "total_count": total,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_page": page - 1,
        "next_page": page + 1,
    }


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
def upload_file(request: Request, images: list[UploadFile] | None = File(None)):
    """Загрузка изображений, сохранение на диск и в PostgreSQL."""
    # 1. Отсеиваем пустые поля формы (браузер шлёт пустой файл, если ничего не выбрано)
    uploads = [img for img in images or [] if img.filename]
    if not uploads:
        return upload_error("Файл не выбран.")
    if len(uploads) > MAX_FILES_PER_REQUEST:
        return upload_error(f"Можно загрузить не более {MAX_FILES_PER_REQUEST} файлов за один раз.")

    client_ip = get_client_ip(request)
    saved = []   # имена сохранённых файлов
    errors = []  # сообщения об ошибках

    for upload in uploads:
        name = upload.filename

        # 2. Читаем файл (с ограничением по размеру) и проверяем его
        contents = upload.file.read(file_utils.MAX_UPLOAD_SIZE + 1)
        valid, new_filename, error_text = file_utils.validate_image(contents, name)
        if not valid:
            message = f"{name}: {error_text}"
            logger.log_action("Ошибка", message)
            errors.append(message)
            continue

        # 3. Сохраняем файл на диск и запись о нём в БД
        save_path = STORAGE_DIR / new_filename
        try:
            save_path.write_bytes(contents)
            file_type = Path(new_filename).suffix.lstrip(".")
            with db.get_db_connection() as conn:
                db.save_image_metadata(conn, new_filename, Path(name).name, len(contents), file_type, client_ip)
            saved.append(new_filename)
            logger.log_action("Успех", f"изображение {new_filename} загружено.")
        except Exception as e:
            # если что-то пошло не так — удаляем файл с диска, чтобы не оставлять мусор
            save_path.unlink(missing_ok=True)
            message = f"{name}: не удалось сохранить файл"
            logger.log_action("Ошибка", f"{message} ({e})")
            errors.append(message)

    # 4. Если ничего не сохранилось — показываем ошибки
    if not saved:
        return upload_error("; ".join(errors))

    # 5. Показываем загруженные файлы (и предупреждение, если часть пропущена)
    redirect_url = f"/upload?uploaded={urllib.parse.quote(','.join(saved))}"
    if errors:
        warning = "Некоторые файлы пропущены: " + "; ".join(errors)
        redirect_url += f"&error={urllib.parse.quote(warning)}"
    return RedirectResponse(redirect_url, status_code=303)


@app.get("/images", response_class=HTMLResponse)
@app.get("/images/", response_class=HTMLResponse)
def gallery(request: Request, page: int = 1):
    """Галерея картинок с пагинацией по 12 элементов."""
    context = get_page_data(page, per_page=12)

    # шаблону нужно поле name, поэтому добавляем его к каждой картинке
    for image in context["images"]:
        image["name"] = image["filename"]

    return templates.TemplateResponse(request=request, name="images.html", context=context)


@app.get("/images-list", response_class=HTMLResponse)
def images_list(request: Request, page: int = 1, deleted=None, error=None):
    """Реестр всех изображений из базы данных с пагинацией по 10 элементов."""
    context = get_page_data(page, per_page=10)
    context["current_ip"] = get_client_ip(request)
    context["deleted"] = bool(deleted)
    context["error"] = error

    return templates.TemplateResponse(request=request, name="images_list.html", context=context)


@app.post("/delete/{image_id}")
def delete_image(request: Request, image_id: int):
    """Удаление изображения из базы данных и файлового хранилища."""
    client_ip = get_client_ip(request)

    try:
        deleted_filename = db.delete_image_by_id(image_id, client_ip=client_ip)

        if deleted_filename:
            # удаляем сам файл с диска
            file_path = STORAGE_DIR / Path(deleted_filename).name
            if file_path.exists():
                file_path.unlink()

            logger.log_action("Успех", f"изображение {deleted_filename} (id={image_id}) удалено пользователем {client_ip}.")
            return RedirectResponse("/images-list?deleted=1", status_code=303)

        else:
            logger.log_action("Ошибка", f"попытка удаления id={image_id} (не найдено или чужой IP {client_ip})")
            message = "Изображение не найдено или у вас нет прав на его удаление"
            return RedirectResponse(f"/images-list?error={urllib.parse.quote(message)}", status_code=303)

    except Exception as e:
        # текст ошибки пишем только в лог, пользователю показываем простое сообщение
        logger.log_action("Ошибка", f"сбой удаления изображения id={image_id} ({e})")
        message = "Не удалось удалить изображение"
        return RedirectResponse(f"/images-list?error={urllib.parse.quote(message)}", status_code=303)


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
        # ошибку сервера пишем в лог полностью
        logger.log_action("Ошибка", f"{code} {request.method} {request.url.path} ({exc})")
        detail = "Внутренняя ошибка сервера"
    else:
        logger.log_action("Ошибка", f"{code} {request.method} {request.url.path}")
        if detail is None:
            detail = "Ошибка запроса"

    # всегда показываем красивую страницу ошибки в стиле Solar
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={"status_code": code, "detail": str(detail)},
        status_code=code,
    )


if __name__ == "__main__":
    uvicorn.run("app:app", host=HOST, port=PORT)