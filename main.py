"""PocketSmart AI - FastAPI application entry point.

Run:  python main.py      (or)      uvicorn main:app --reload
"""
import io
import re
import uuid
from contextlib import asynccontextmanager
from typing import List, Optional
from urllib.parse import quote

import uvicorn
from fastapi import (Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageOps
from pydantic import ValidationError

import catalog
import database as db
from config import (ACCESS_TOKEN_EXPIRE_MINUTES, COOKIE_SECURE, CORS_ORIGINS, GEMINI_MODEL,
                    MAX_UPLOAD_MB, STATIC_DIR, TEMPLATES_DIR, UPLOAD_DIR, logger)
from gemini_utils import gemini_configured, generate_plan
from schemas import (HomePlannerRequest, JewelryPlannerRequest, PartyPlannerRequest, TokenResponse)
from security import create_access_token, decode_access_token, hash_password, verify_password
from utils import inr, safe_next

CATEGORY_LABELS = {"home": "Home Interior", "party": "Party", "jewelry": "Jewelry"}


# ---------------------------------------------------------------- startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create DB tables + upload folder. (Implements the documented /startup step.)"""
    db.init_db()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("PocketSmart AI started | Gemini configured: %s | model: %s",
                gemini_configured(), GEMINI_MODEL)
    yield


app = FastAPI(title="PocketSmart AI - Smart Budget & Recommendation Assistant", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["inr"] = inr
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


def render(request: Request, name: str, user=None, status_code: int = 200, **ctx):
    ctx.update(user=user, labels=CATEGORY_LABELS)
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


# ---------------------------------------------------------------- auth helpers
class NotAuthenticated(Exception):
    pass


def _resolve_user(request: Request, bearer: Optional[str] = None):
    token = bearer or request.cookies.get("access_token")
    if not token:
        header = request.headers.get("Authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else None
    username = decode_access_token(token) if token else None
    return db.get_user_by_username(username) if username else None


def optional_user(request: Request, bearer: Optional[str] = Depends(oauth2_scheme)):
    return _resolve_user(request, bearer)


def page_user(request: Request, bearer: Optional[str] = Depends(oauth2_scheme)):
    """For HTML pages: redirect to /login when not signed in."""
    user = _resolve_user(request, bearer)
    if not user:
        raise NotAuthenticated()
    return user


def api_user(request: Request, bearer: Optional[str] = Depends(oauth2_scheme)):
    """For JSON APIs: respond 401 when not signed in."""
    user = _resolve_user(request, bearer)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


@app.exception_handler(NotAuthenticated)
async def not_authenticated_handler(request: Request, exc: NotAuthenticated):
    target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"/login?next={quote(target)}", status_code=303)


def _set_login_cookie(response, username: str):
    response.set_cookie("access_token", create_access_token(username), httponly=True, samesite="lax",
                        secure=COOKIE_SECURE, max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60)


# ---------------------------------------------------------------- public pages
@app.get("/health")
def health():
    return {"status": "ok", "gemini_configured": gemini_configured(), "model": GEMINI_MODEL}


TESTIMONIALS = [
    ("Ananya R.", "Home makeover", "I furnished my flat in Chennai under budget - the room-wise split was a lifesaver."),
    ("Karthik S.", "Birthday party", "It planned food, decor and music for 60 guests in minutes. Zero financial guesswork."),
    ("Meera P.", "Wedding jewelry", "Uploaded my lehenga photo and got matching sets that fit my budget perfectly."),
]


@app.get("/")
def index(request: Request, user=Depends(optional_user)):
    return render(request, "index.html", user, testimonials=TESTIMONIALS)


@app.get("/testimonials")
def testimonials_page(request: Request, user=Depends(optional_user)):
    return render(request, "testimonials.html", user, testimonials=TESTIMONIALS)


# ---------------------------------------------------------------- register / login / logout / token
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.get("/register")
def register_page(request: Request, user=Depends(optional_user)):
    if user:
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "register.html", None, error=None, form={})


@app.post("/register")
def register(request: Request, username: str = Form(...), email: str = Form(...),
             full_name: str = Form(""), password: str = Form(...), confirm_password: str = Form(...)):
    username, email, full_name = username.strip(), email.strip().lower(), full_name.strip()[:80]
    form = {"username": username, "email": email, "full_name": full_name}
    error = None
    if not _USERNAME_RE.match(username):
        error = "Username must be 3-30 characters: letters, numbers, dot, dash or underscore."
    elif not _EMAIL_RE.match(email):
        error = "Please enter a valid email address."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."
    elif password != confirm_password:
        error = "Passwords do not match."
    elif db.user_exists(username, email):
        error = "That username or email is already registered."
    if error:
        return render(request, "register.html", None, status_code=400, error=error, form=form)
    db.create_user(username, email, full_name, hash_password(password))
    return RedirectResponse("/login?registered=1", status_code=303)


@app.get("/login")
def login_page(request: Request, next: str = "/dashboard", registered: int = 0,
               user=Depends(optional_user)):
    if user:
        return RedirectResponse(safe_next(next), status_code=303)
    return render(request, "login.html", None, error=None, next=safe_next(next),
                  registered=bool(registered))


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...),
          next: str = Form("/dashboard")):
    user = db.get_user_by_login(username.strip())
    if not user or not verify_password(password, user["password_hash"]):
        return render(request, "login.html", None, status_code=401, error="Invalid username or password.",
                      next=safe_next(next), registered=False)
    response = RedirectResponse(safe_next(next), status_code=303)
    _set_login_cookie(response, user["username"])
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("access_token")
    return response


@app.post("/token", response_model=TokenResponse)
def token(form: OAuth2PasswordRequestForm = Depends()):
    """OAuth2 password flow - returns a JWT for API clients (curl, Postman, /docs)."""
    user = db.get_user_by_login(form.username.strip())
    if not user or not verify_password(form.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect username or password",
                            headers={"WWW-Authenticate": "Bearer"})
    return TokenResponse(access_token=create_access_token(user["username"]))


# ---------------------------------------------------------------- session endpoints
@app.get("/session-info")
def session_info(user=Depends(optional_user)):
    if not user:
        return {"authenticated": False}
    return {"authenticated": True, "user_id": user["id"], "username": user["username"],
            "full_name": user["full_name"], "member_since": user["created_at"]}


@app.get("/session-data")
def session_data(user=Depends(api_user)):
    counts = db.count_history_by_category(user["id"])
    recent = db.list_history(user["id"], limit=5)
    return {"user_id": user["id"], "total_recommendations": sum(counts.values()), "by_category": counts,
            "recent": [{"id": h["id"], "category": h["category"], "budget": h["budget"],
                        "created_at": h["created_at"]} for h in recent]}


# ---------------------------------------------------------------- planner pages
@app.get("/dashboard")
def dashboard(request: Request, user=Depends(page_user)):
    return render(request, "dashboard.html", user, recent=db.list_history(user["id"], limit=5),
                  counts=db.count_history_by_category(user["id"]))


@app.get("/home-planner")
def home_planner(request: Request, user=Depends(page_user)):
    return render(request, "home_planner.html", user, rooms=catalog.ROOMS,
                  suggestions=catalog.HOME_ITEM_SUGGESTIONS)


@app.get("/party-planner")
def party_planner(request: Request, user=Depends(page_user)):
    return render(request, "party_planner.html", user, party_types=catalog.PARTY_TYPES)


@app.get("/jewelry-planner")
def jewelry_planner(request: Request, user=Depends(page_user)):
    return render(request, "jewelry_planner.html", user, occasions=catalog.OCCASIONS,
                  styles=catalog.JEWELRY_STYLES, max_mb=MAX_UPLOAD_MB)


@app.get("/history")
def history_page(request: Request, category: Optional[str] = None, user=Depends(page_user)):
    category = category if category in CATEGORY_LABELS else None
    return render(request, "history.html", user, items=db.list_history(user["id"], category),
                  selected=category)


@app.get("/recommendations/{history_id}")
def recommendation_page(request: Request, history_id: int, user=Depends(page_user)):
    item = db.get_history_item(user["id"], history_id)
    if not item:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return render(request, f"results.html", user, item=item, plan=item["plan"])


# ---------------------------------------------------------------- generation APIs
def _save(user, category: str, req: dict, plan: dict) -> dict:
    hid = db.add_history(user["id"], category, req["budget"], req, plan)
    return {"id": hid, "category": category, "redirect_url": f"/recommendations/{hid}", "plan": plan}


@app.post("/generate-home")
def generate_home(payload: HomePlannerRequest, user=Depends(api_user)):
    req = payload.model_dump()
    return _save(user, "home", req, generate_plan("home", req))


@app.post("/generate-party")
def generate_party(payload: PartyPlannerRequest, user=Depends(api_user)):
    req = payload.model_dump()
    return _save(user, "party", req, generate_plan("party", req))


def _process_image(upload: UploadFile) -> tuple[bytes, str]:
    """Validate, normalise (max 1600px JPEG) and store an outfit image. Returns (bytes, filename)."""
    limit = MAX_UPLOAD_MB * 1024 * 1024
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"Image is larger than {MAX_UPLOAD_MB} MB.")
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValueError("unsupported format")
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((1600, 1600))
    except Exception:
        raise HTTPException(status_code=400, detail="Please upload a valid JPG, PNG or WEBP image.")
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88)
    name = f"{uuid.uuid4().hex}.jpg"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / name).write_bytes(out.getvalue())
    return out.getvalue(), name


@app.post("/generate-jewelry")
def generate_jewelry(
    budget: float = Form(...),
    occasion: str = Form("Party"),
    styles: List[str] = Form(default=[]),
    metal: str = Form("Any"),
    notes: str = Form(""),
    outfit_image: Optional[UploadFile] = File(None),
    user=Depends(api_user),
):
    image_bytes, filename = None, None
    if outfit_image is not None and outfit_image.filename:
        image_bytes, filename = _process_image(outfit_image)
    try:
        payload = JewelryPlannerRequest(budget=budget, occasion=occasion, styles=styles, metal=metal,
                                        notes=notes, outfit_image=filename)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=[
            {"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()])
    req = payload.model_dump()
    return _save(user, "jewelry", req, generate_plan("jewelry", req, image_bytes, "image/jpeg"))


# ---------------------------------------------------------------- history / details APIs
@app.get("/recommendations-details")
def recommendations_details(category: Optional[str] = Query(None, pattern="^(home|party|jewelry)$"),
                            limit: int = Query(10, ge=1, le=100), id: Optional[int] = None,
                            user=Depends(api_user)):
    """Detailed AI-generated recommendations (full plans) for the signed-in user."""
    if id is not None:
        item = db.get_history_item(user["id"], id)
        if not item:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        return item
    return db.list_history(user["id"], category, limit, include_plan=True)


@app.get("/api/history")
def api_history(category: Optional[str] = Query(None, pattern="^(home|party|jewelry)$"),
                user=Depends(api_user)):
    return db.list_history(user["id"], category)


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith(("/api", "/generate", "/static")) or \
            "application/json" in request.headers.get("accept", ""):
        detail = getattr(exc, "detail", "Not found")
        return JSONResponse({"detail": detail}, status_code=404)
    return render(request, "error.html", _resolve_user(request), status_code=404,
                  code=404, message=getattr(exc, "detail", None) or "Page not found")


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
