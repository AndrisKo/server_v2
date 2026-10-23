import math, os, urllib.parse, uvicorn
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from utils import db, file_utils, logger

load_dotenv()

STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", "images"))
TEMPLATES_DIR = Path("templates")
STATIC_DIR = Path("static")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 8000))

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация базы данных и рабочих каталогов при запуске приложения."""
    Path("backups").mkdir(parents=True, exist_ok=True)
    db.init_db()
    yield

app = FastAPI(title="PixelVault Image Hosting")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Главная страница с приветствием и информацией о сервисе."""
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC_DIR / "favicon.ico")

@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request, uploaded: str = None, error: str = None):
    """Форма для загрузки одного или нескольких файлов."""
    files = []
    if uploaded:
        for name in (s.strip() for s in uploaded.split(",") if s.strip()):
            p = STORAGE_DIR / Path(name).name
            if p.is_file():
                files.append({"name": p.name, "url": f"/images/{p.name}", "size": p.stat().st_size})
    return templates.TemplateResponse(request=request, name="upload.html", context={"uploaded_files": files, "error": error})


@app.post("/upload")
async def upload_file(request: Request):
    """Загрузка одного или нескольких файлов."""
    is_browser = "text/html" in request.headers.get("accept", "")

    # 1. Получаем файлы из формы
    try:
        form = await request.form()
        files = [
            v for _, v in form.multi_items()
            if isinstance(v, UploadFile) and v.filename
        ]
    except Exception:
        files = []

    # Если файлов нет — возвращаем ошибку
    if not files:
        logger.log_action("Ошибка", "Файл не выбран.")
        if is_browser:
            return RedirectResponse("/upload?error=Файл+не+выбран", status_code=303)
        return JSONResponse({"success": False, "error": "Файл не выбран."}, status_code=400)

    saved = []
    errors = []

    # 2. Обрабатываем каждый файл
    for f in files:
        data = await f.read()

        # Проверяем файл
        valid, new_name, err = file_utils.validate_image(data, f.filename)
        if not valid:
            logger.log_action("Ошибка", err)
            errors.append(err)
            continue

        # Пытаемся сохранить
        path = STORAGE_DIR / new_name
        try:
            path.write_bytes(data)

            ext = Path(new_name).suffix.lstrip(".").lower()
            rec_id = db.save_image_metadata(new_name, f.filename, len(data), ext)

            saved.append({
                "id": rec_id,
                "filename": new_name,
                "url": f"/images/{new_name}",
            })
            logger.log_action("Успех", f"изображение {new_name} загружено.")

        except Exception as e:
            # Если ошибка — удаляем файл
            path.unlink(missing_ok=True)
            logger.log_action("Ошибка", f"сбой сохранения метаданных ({e})")
            errors.append("сбой сохранения метаданных в базе данных")

    # 3. Если ничего не сохранилось — ошибка
    if not saved:
        err_msg = "; ".join(errors) or "Не удалось загрузить файлы."
        logger.log_action("Ошибка", err_msg)
        if is_browser:
            return RedirectResponse(
                f"/upload?error={urllib.parse.quote(err_msg)}",
                status_code=303,
            )
        return JSONResponse({"success": False, "error": err_msg}, status_code=400)

    # 4. Успех
    if is_browser:
        uploaded = ",".join(s["filename"] for s in saved)
        return RedirectResponse(f"/upload?uploaded={uploaded}", status_code=303)

    first = saved[0]
    return {
        "success": True,
        "url": first["url"],
        "filename": first["filename"],
        "id": first["id"],
        "files": saved,
        "count": len(saved),
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
    detail = getattr(exc, "detail", str(exc))

    logger.log_action("Ошибка", f"{code} {request.method} {request.url.path}")

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