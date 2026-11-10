# AI Website Audit Assistant

Audit one public HTML page at a time. The React/Vite interface displays SEO and answer engine optimization (AEO) checks, evidence, and actions. Export the report as TXT or JSON, or select **Print / save PDF** and choose your browser's PDF destination.

## Run in VS Code on Windows

Extract the ZIP and open the extracted project folder in VS Code. Use Python 3.11 and Node.js 22.12+.

In the first PowerShell terminal, run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

To enable AI recommendations, edit the root `.env` with your xAI API key and restart the backend. The default model is `grok-4.7`. The app still runs its rule-based checks with an empty key. The key stays on the backend. With a key configured, a bounded set of extracted audit evidence is sent to xAI for recommendations. The app sends no raw HTML and requests that the provider disable response storage.

In a second terminal, run:

```powershell
cd frontend
npm ci
npm run dev
```

Open the URL printed by Vite (usually http://localhost:5173) and enter an absolute URL such as `https://www.iana.org/`. The Vite development server forwards API calls to port 8000.

## Verify

From the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix frontend ci
npm --prefix frontend run build
```

Tests use mocked DNS and xAI responses. Use `GET /api/health` to check service health and `POST /api/audit` with a JSON object containing `url` to obtain the report. FastAPI exposes interactive API docs at `/docs`.

## Deploy

The production Vite build is served by FastAPI from `frontend/dist` on the same origin. Build the frontend before starting the API. The included Dockerfile builds both layers:

```sh
docker build -t website-audit .
docker run --rm -p 127.0.0.1:8000:8000 --env-file .env website-audit
```

Open http://127.0.0.1:8000. For a hosted deployment, use the Dockerfile on a container host and configure container port 8000, the environment secrets, and `/api/health` as the health check. Place the service behind an authenticated HTTPS gateway with request rate limits and outbound network rules denying private, link-local, metadata, and infrastructure ranges. Allow outbound DNS, public HTTP(S), and xAI HTTPS. The app has no built-in accounts, quotas, or billing.

## Scope and architecture

- `frontend/` contains the UI and report exports.
- `app/main.py` handles input validation and serves the app.
- `app/fetch.py` fetches a single public IPv4 page, plus that site's `/robots.txt` and `/llms.txt`. It validates each redirect, rejects credentials and nondefault ports, connects to approved numeric addresses while retaining hostname-based TLS validation, disables environment proxies and cookies, and caps time, redirects, and HTML size.
- `app/audit.py` defines the LangGraph workflow. One node fetches HTML and produces deterministic checks: 16 SEO checks (plus hreflang when present) and 12 AEO checks (plus schema-versus-visible-content when FAQ/QA schema is present), including search and AI answer-engine crawler access in robots.txt. The second optionally asks the xAI Responses API to prioritize improvements.
- `tests/` covers input validation, DNS filtering, reports, and the mocked AI integration.

Scores are the percentage of equally weighted checks passed. The audit uses server-delivered HTML and heuristic checks. It does not run JavaScript, crawl the site, verify JSON-LD against schema definitions, or predict ranking, indexing, or inclusion in answer engines. Sites without public IPv4, or that block simple HTTP clients, may fail to fetch.

[Grok API documentation](https://docs.x.ai/developers/rest-api-reference/inference)
