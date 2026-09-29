# PocketSmart AI – Smart Budget & Recommendation Assistant

FastAPI + Jinja2 + Google Gemini. Three planners (Home Interior, Party, Jewelry), JWT login,
recommendation history, and a rule-based fallback so the app works even without an API key.

## Project structure

```
pocketsmart-ai/
├── main.py            # FastAPI app: routes, auth, pages, CORS, startup
├── gemini_utils.py    # Gemini prompts, multimodal call, JSON validation, budget checks
├── fallbacks.py       # Rule-based plans (no-AI / error / over-budget fallback)
├── catalog.py         # Platform search-link builder + baseline prices
├── schemas.py         # Pydantic input/output models
├── security.py        # Password hashing + JWT
├── database.py        # SQLite (users + history)
├── config.py, utils.py
├── templates/         # index, register, login, dashboard, *_planner, results, history, testimonials, error
├── static/            # styles.css, app.js, uploads/ (outfit images)
├── tests/             # pytest suite
├── .env.example  requirements.txt  pytest.ini  .vscode/
```

## Setup in VS Code (Windows / macOS / Linux)

1. Install **Python 3.10+** and **VS Code** (with the *Python* extension).
2. `File → Open Folder…` and choose `pocketsmart-ai`.
3. Open a terminal: `Terminal → New Terminal`.
4. Create and activate a virtual environment:
   - Windows (PowerShell): `python -m venv .venv` then `.venv\Scripts\Activate.ps1`
     (if blocked: `Set-ExecutionPolicy -Scope Process RemoteSigned`)
   - macOS/Linux: `python3 -m venv .venv && source .venv/bin/activate`
   - When VS Code asks, select the `.venv` interpreter (or `Ctrl+Shift+P → Python: Select Interpreter`).
5. Install dependencies: `pip install -r requirements.txt`
6. Create your config: copy `.env.example` to `.env` and set:
   - `GEMINI_API_KEY` – free key from https://aistudio.google.com/app/apikey
   - `SECRET_KEY` – run `python -c "import secrets; print(secrets.token_urlsafe(48))"` and paste the result.
   
   > No key? Leave it blank – the app runs in **demo mode** with rule-based recommendations.

## Run

```
python main.py
```
or `uvicorn main:app --reload`, or press **F5** in VS Code (uses `.vscode/launch.json`).
Open http://127.0.0.1:8000 · API docs at http://127.0.0.1:8000/docs · health check at `/health`.

## Try it

1. Register → Login.
2. **Home Planner**: budget 150000, add Lights ×4, Ceiling fans ×2, Dining table ×1 → *Get recommendations*.
3. **Party Planner**: budget 100000, 50 guests, Birthday, hall venue.
4. **Jewelry Planner**: budget 25000, Wedding, tick *Traditional*, optionally upload an outfit photo.
5. Check **History** and **Dashboard**. Results say whether they came from Gemini or the fallback.

## Test

```
pytest -v
```
Tests run offline (no API key needed): unit tests for the AI layer/validation/budget logic and
end-to-end tests of auth, all three planners, image upload validation, history and access control.

Manual API check (PowerShell/curl):
```
curl -X POST http://127.0.0.1:8000/token -d "username=YOU&password=YOURPASS"
curl -X POST http://127.0.0.1:8000/generate-party -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
     -d '{"budget":80000,"guests":40,"event_type":"Birthday","venue_type":"hall","city":"Chennai","food_preference":"both"}'
```

## Endpoints

| Route | Purpose |
|---|---|
| `GET /` `/testimonials` | Landing + testimonials |
| `GET/POST /register`, `/login`, `GET /logout`, `POST /token` | Auth (cookie for pages, JWT for API) |
| `GET /dashboard` `/home-planner` `/party-planner` `/jewelry-planner` `/history` | Pages (login required) |
| `POST /generate-home` `/generate-party` `/generate-jewelry` | AI recommendations (jewelry accepts an image) |
| `GET /recommendations/{id}` | Result page |
| `GET /recommendations-details`, `GET /api/history` | JSON details / history |
| `GET /session-info` `/session-data` | Session metadata |
| `GET /health` | Status + whether Gemini is configured |

## Troubleshooting

- **"Demo mode" notice on results** – `GEMINI_API_KEY` missing/invalid, quota hit, or the model name changed.
  Check the terminal log; set `GEMINI_MODEL` in `.env` to a model listed in Google AI Studio.
- **`ModuleNotFoundError`** – the venv isn't active; re-activate and `pip install -r requirements.txt`.
- **Port in use** – change the port in `main.py` or run `uvicorn main:app --port 8001`.
- Logged out after every restart – set a fixed `SECRET_KEY` in `.env`.

## Notes

- The project document names "Gemini 1.5 Flash Pro"; that model is retired, so the model is configurable
  (`GEMINI_MODEL`, default `gemini-2.5-flash`, with `GEMINI_FALLBACK_MODEL` as a second try).
- Product links are **search links** on each platform (no scraping, no invented URLs); prices are AI estimates.
- For production: set `COOKIE_SECURE=true`, serve over HTTPS, restrict `CORS_ORIGINS`, and add CSRF protection.
