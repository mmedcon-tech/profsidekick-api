# AGENTS.md — ProfSidekick Backend

> Cross-reference: See [profsidekick-frontend-main/AGENTS.md](../profsidekick-frontend-main/AGENTS.md) for frontend conventions.
> The **authoritative API contract** (§5) and **commit/PR standards** (§6) live in the frontend AGENTS.md and are referenced here.

---

## 1. Project Overview

This repository is the **backend** for ProfSidekick, a FastAPI application that:

- Authenticates teachers and students via JWT, email verification, and a professor approval workflow
- Accepts presentation uploads (PDF/PPTX), converts them to slide images, and uses the OpenAI Vision API to extract content per slide
- Manages courses, sessions, session runs, course materials, and custom AI prompts
- Vends ephemeral OpenAI Realtime API tokens to the frontend so it can initiate voice sessions
- Persists all data in PostgreSQL; uses Redis for session caching
- Stores files in AWS S3 with optional CloudFront CDN, falling back to local filesystem

This is a pure REST API — it has no frontend. All client traffic comes from the Next.js frontend described in [profsidekick-frontend-main/AGENTS.md](../profsidekick-frontend-main/AGENTS.md).

---

## 2. Repository Structure

```
backend-main/
├── app/
│   ├── main.py                        # FastAPI app entry: lifespan, CORS, router registration, health check
│   ├── config.py                      # Pydantic Settings — every env var is declared here; no os.getenv() elsewhere
│   ├── api/                           # Route handlers — thin layer: validate → service call → return schema
│   │   ├── auth/
│   │   │   └── api.py                 # /api/auth/* (register, login, verify-email, forgot/reset-password, verify-token, refresh, logout)
│   │   ├── users/
│   │   │   └── api.py                 # /api/users/* (profile, sessions)
│   │   ├── sessions/
│   │   │   └── api.py                 # /api/sessions/* (~1100 lines — slide mgmt + session CRUD + run lifecycle)
│   │   ├── courses/
│   │   │   └── api.py                 # /api/courses/*
│   │   ├── course_materials/
│   │   │   └── api.py                 # /api/course-materials/*
│   │   └── prompts/
│   │       └── api.py                 # /api/prompts/*
│   ├── database/
│   │   ├── connection.py              # SQLAlchemy engine + session factory + Redis client
│   │   ├── models.py                  # ORM models — source of truth for DB schema
│   │   └── __init__.py
│   ├── schemas/
│   │   └── schemas.py                 # Pydantic request/response models
│   ├── services/                      # All business logic and external API calls live here
│   │   ├── auth_service.py            # Password hashing, JWT, registration, email verification
│   │   ├── session_service.py         # Session CRUD, run lifecycle, pagination
│   │   ├── openai_service.py          # Ephemeral tokens, Vision API, Chat Completions
│   │   ├── file_processor.py          # Validation, PDF→images, thumbnails, S3 upload
│   │   ├── email_service.py           # Multi-provider: SMTP / SendGrid / Resend
│   │   ├── course_service.py          # Course CRUD, student enrollment
│   │   ├── course_material_service.py # Material CRUD + file upload + session linking
│   │   ├── prompt_service.py          # Saved prompt CRUD
│   │   ├── cloud_storage_service.py   # AWS S3 + CloudFront integration
│   │   └── __init__.py
│   └── dependencies/
│       └── auth.py                    # JWT verification dependency + get_current_user / get_optional_current_user
├── alembic/
│   ├── versions/                      # Migration scripts — append-only, never edit applied migrations
│   └── env.py                         # Alembic runtime config
├── alembic.ini                        # Alembic CLI config
├── tests/
│   └── test_main.py                   # Existing tests (sparse — expand, do not replace)
├── requirements.txt
├── env.example                        # Template for .env
├── Dockerfile
├── docker-compose.yml                 # Local dev: postgres + redis + backend (+ optional pgAdmin, Redis Commander)
├── start.py                           # Railway entry point: waits for DB, runs create_all, stamps Alembic, starts uvicorn
├── fly.toml                           # Fly.io deployment config
├── railway.json                       # Railway deployment config
└── nixpacks.toml                      # Nix build config
```

### Directories That Must Not Be Modified Without Justification

| File / Directory | Reason |
|---|---|
| `alembic/versions/` | Migrations are append-only — never edit a migration that has been applied to any environment |
| `app/database/models.py` | Every change here requires a new Alembic migration |
| `app/dependencies/auth.py` | Used by every protected endpoint; a mistake here breaks all auth |
| `start.py` | Controls production boot sequence on Railway; changes affect live deployments |

---

## 3. Development Standards

### 3.1 Naming Conventions

| Artifact | Convention | Example |
|---|---|---|
| Python source files | snake_case | `auth_service.py`, `cloud_storage_service.py` |
| Functions | snake_case | `create_session()`, `get_current_user()` |
| Classes | PascalCase | `SessionService`, `FileProcessor` |
| SQLAlchemy models | PascalCase | `User`, `Course`, `SessionRun` |
| Pydantic schemas | PascalCase with `Request`/`Response` suffix | `SessionCreateRequest`, `SessionResponse` |
| Database columns | snake_case | `user_id`, `created_at`, `is_active` |
| Environment variables | SCREAMING_SNAKE_CASE | `OPENAI_API_KEY`, `DATABASE_URL` |
| Business-facing string IDs | `<prefix>_<random>` pattern | `sess_abc123`, `run_xyz789`, `crs_def456` |
| Database primary keys | `id` UUID, generated at app level | `id: UUID = uuid4()` |

### 3.2 Python Style

- Python 3.11+. Use `from __future__ import annotations` when forward references are needed.
- **Black** for formatting — run `black .` before committing. Do not commit unformatted code.
- **Flake8** for linting — run `flake8 app/` before committing. Max line length: 88 (Black default).
- Type hints are required on all function signatures: parameters and return types.
- Use `Optional[X]` (or `X | None`) explicitly. Do not leave bare `None` defaults without the type annotation.

### 3.3 FastAPI Architecture — Layering Rules

**Route handlers** (`app/api/*/api.py`) must only:
1. Declare inputs via Pydantic schemas, `File`, or `Form` parameters
2. Call one or more service functions
3. Return a Pydantic response schema or raise `HTTPException`

Route handlers must **not** contain: SQL queries, OpenAI calls, file I/O, or password hashing.

**Service functions** (`app/services/*.py`) own all business logic and database access. They accept a `db: Session` injected via `Depends(get_db)`.

**Dependencies** (`app/dependencies/auth.py`) inject the authenticated user. Always use `current_user: User = Depends(get_current_user)` on protected routes. Never decode JWTs inside route handlers.

**Error handling:** raise `HTTPException(status_code=..., detail="message")`. Never return error objects in 2xx responses.

### 3.4 Database / ORM

- Every schema change requires a new Alembic migration: `alembic revision --autogenerate -m "description"`.
- Always review autogenerated migrations before applying — autogenerate is unreliable for JSONB columns and Python enums. Verify the generated SQL manually.
- Never call `Base.metadata.create_all()` in application code outside `start.py`.
- JSONB columns (`presentation_details`, `slides_details`, `assistant_parameters`, `session_run_metadata`) store structured dicts. Document the expected shape in a comment on the model field.
- Default relationship loading is `lazy="select"`. Do not switch to `lazy="joined"` without benchmarking — it can produce cartesian products on wide joins.
- UUIDs are the primary key type on all models. Generate with `uuid.uuid4()` at the application level, not via `server_default`.

### 3.5 Authentication

- JWT tokens are HS256-signed with `SECRET_KEY` from `config.py`. Token expiry: 24 hours.
- Passwords are hashed with bcrypt via `passlib`. Never store plaintext passwords or reversible hashes.
- Email verification tokens and professor approval tokens are UUID strings stored as columns on `User`.
- `get_current_user` is the only approved way to extract the authenticated user in a route. `get_optional_current_user` exists for endpoints that support both guest and authenticated access.
- Do not extend JWT expiry without a security review.

### 3.6 File Handling

- Allowed types: `.pdf`, `.pptx`, `.ppt` (set via `ALLOWED_FILE_TYPES`).
- Max upload size: 52 MB (set via `MAX_FILE_SIZE`).
- All validation occurs in `file_processor.py` before any processing begins.
- PDF conversion uses `pdf2image` at 150 DPI. Thumbnails are generated at 256×192.
- When `USE_CLOUD_STORAGE=true`, all files are stored in S3. Otherwise files go to `UPLOAD_DIR` / `STATIC_DIR` on disk.
- Never leave uploaded files permanently on the application server in production — always forward to S3 after processing.

### 3.7 Anti-Patterns

- **Do not write SQL in route handlers.** Use the service layer.
- **Do not use `os.getenv()` directly.** All env vars are declared in `config.py` and accessed via the `settings` object.
- **Do not hardcode any secret.** `SECRET_KEY`, `OPENAI_API_KEY`, credentials — all from config.
- **Do not edit existing Alembic migration files.** If a migration is wrong, write a new corrective migration.
- **Do not use `Base.metadata.create_all()` in route handlers or services.** Schema management belongs to Alembic.
- **Do not return plain dicts from route handlers.** Always return a Pydantic model or `JSONResponse`.
- **Do not call `db.commit()` in route handlers.** Commit inside the service function that owns the transaction.
- **Do not store raw file bytes in the database.** Use file paths or S3 object keys.

---

## 4. Testing Requirements

**Current state:** `tests/test_main.py` has minimal coverage (health check, basic endpoint validation). Every new feature and every bug fix must ship with tests before the PR can merge.

### Testing Stack

```bash
pip install pytest pytest-asyncio httpx
pytest tests/
```

### Test File Locations

```
tests/
├── conftest.py                        # Shared fixtures: test engine, test client, auth tokens
├── test_auth.py                       # Auth endpoints
├── test_sessions.py                   # Session + run lifecycle endpoints
├── test_courses.py                    # Course CRUD endpoints
├── test_course_materials.py           # Material endpoints
├── test_prompts.py                    # Prompt endpoints
└── test_services/
    ├── test_auth_service.py           # Unit tests for auth_service.py
    ├── test_session_service.py        # Unit tests for session_service.py
    └── test_file_processor.py         # Unit tests for file_processor.py
```

### Required Test Types

| Type | Scope | Examples |
|---|---|---|
| Unit | Service functions with a real test DB | `create_session()` creates correct DB record |
| Unit | Pure utility functions | `file_processor.validate_file()` rejects oversized files, wrong extensions |
| Integration | Full request → response via `TestClient` | `POST /api/auth/login` returns a JWT |
| Integration | Auth boundary | All protected endpoints return 401 without a token |
| Regression | Every reported bug | Add a failing test first, then fix the bug |

### Mandatory Coverage — Critical Path Files

These must have tests before any PR touching them is merged:

- `app/dependencies/auth.py`
- `app/services/auth_service.py` — login, register, token verification, token refresh
- `app/services/session_service.py` — create, start run, stop run
- `app/services/file_processor.py` — validation (type, size, content)
- Any new API endpoint

### Test Database Setup

Create `tests/conftest.py`:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app.main import app
from app.database.models import Base
from app.database.connection import get_db
from app.config import settings

TEST_DATABASE_URL = settings.database_url.replace("/profsidekick", "/profsidekick_test")

@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)

@pytest.fixture
def db_session(engine):
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    yield session
    session.rollback()
    session.close()

@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

Run tests:
```bash
pytest tests/ -v
```

---

## 5. API Contract (Frontend ↔ Backend)

> The **authoritative contract** is in [profsidekick-frontend-main/AGENTS.md §5](../profsidekick-frontend-main/AGENTS.md#5-api-contract-frontend--backend). This section defines the backend's obligations.

### Backend Obligations

- Every protected endpoint verifies `Authorization: Bearer <token>` via `get_current_user`.
- Error responses always use `{"detail": "..."}` — never break this shape.
- Paginated responses include `items`, `total`, `page`, and `limit` at minimum.
- Session IDs use the `sess_` prefix. Run IDs use the `run_` prefix.
- The ephemeral token endpoint is `GET /api/session/ephemeral?session_id=&session_run_id=`.

### Adding a New Endpoint

1. Add the route handler in the appropriate `app/api/<domain>/api.py`.
2. Add Pydantic request/response schemas in `app/schemas/schemas.py`.
3. Add the service function in `app/services/<domain>_service.py`.
4. Update the endpoint inventory table in `profsidekick-frontend-main/AGENTS.md §5`.
5. Write an integration test.

### Changing an Existing Endpoint

- **Breaking change** (removing a field, changing a field type, changing the path or method): coordinate with the frontend — update both repos in one PR or introduce a versioned path.
- **Additive change** (new optional response field): safe to deploy backend first.

---

## 6. Git and PR Standards

> Commit format and branch naming are defined in [profsidekick-frontend-main/AGENTS.md §6](../profsidekick-frontend-main/AGENTS.md#6-git-and-pr-standards). Summary:

### Commit Messages

```
<type>(<scope>): <short description>
```

**Types:** `feat`, `fix`, `chore`, `refactor`, `test`, `docs`, `migration`

**Backend scopes:** `auth`, `sessions`, `courses`, `db`, `openai`, `files`, `email`

```
feat(sessions): add slide reorder endpoint
fix(auth): prevent expired tokens from being refreshed indefinitely
migration(db): add session_run_metadata JSONB column
test(auth): add login and token verification coverage
```

### Branch Naming

```
<type>/<short-description>
```

Examples: `feat/course-materials-api`, `fix/pdf-memory-leak`, `migration/add-prompts-table`

### PR Merge Checklist

- [ ] All existing tests pass (`pytest tests/`)
- [ ] New tests written for all new code (§4)
- [ ] Black formatting applied (`black . --check`)
- [ ] Flake8 clean (`flake8 app/`)
- [ ] No credentials or secrets committed
- [ ] New Alembic migration added if any model changed
- [ ] Migration tested locally (`alembic upgrade head`)
- [ ] API contract in `profsidekick-frontend-main/AGENTS.md §5` updated if endpoints changed

---

## 7. Agent Workflow Checklist

Before marking any task done:

- [ ] **Code written** — feature or fix implemented in service + route layers
- [ ] **Schemas updated** — Pydantic models in `schemas.py` reflect new request/response shapes
- [ ] **Migration added** — if any model changed: `alembic revision --autogenerate -m "..."`
- [ ] **Migration reviewed** — autogenerated SQL is correct; applied locally with `alembic upgrade head`
- [ ] **Black clean** — `black . --check` exits 0
- [ ] **Flake8 clean** — `flake8 app/` exits 0
- [ ] **Tests written** — new endpoints and services have coverage (§4)
- [ ] **Tests passing** — `pytest tests/` exits 0
- [ ] **API contract updated** — frontend AGENTS.md §5 updated if endpoints changed
- [ ] **No secrets** — no hardcoded API keys, passwords, or connection strings
- [ ] **No regressions** — all previously passing tests still pass

---

## 8. Known Constraints and Gotchas

1. **`start.py` runs `create_all` before Alembic.** On first Railway deploy, `start.py` calls `Base.metadata.create_all()` then stamps Alembic with `head`. This creates all tables from models before Alembic runs. On subsequent deploys only `alembic upgrade head` runs. Consequence: adding a column to an existing table requires an Alembic migration — `create_all` only creates missing tables, it never alters existing ones.

2. **JSONB column shapes are not schema-enforced.** `presentation_details`, `slides_details`, `assistant_parameters`, and `session_run_metadata` are JSONB with shapes defined only in service and Pydantic layers. Before changing their structure, search all callers with `grep -r "presentation_details\|slides_details" app/`.

3. **`sessions/api.py` is ~1100 lines.** It mixes slide management, session CRUD, and run lifecycle. Existing code should be maintained in place; when the file grows further, extract slide endpoints to `sessions/slides_api.py` with a separate router.

4. **System dependencies required for file processing.** `pdf2image` requires `poppler` on the host. The Dockerfile installs it (`apt-get install poppler-utils`). On Windows dev machines, download Poppler binaries and add to PATH. `python-magic` requires `libmagic` — on Windows install `python-magic-bin` instead.

5. **Professor approval is email-gated.** Newly registered professors are inactive until someone in `PROFESSOR_APPROVAL_EMAILS` clicks the approval link. If that env var is empty, approval emails are never sent and professor accounts remain pending indefinitely — this is a silent failure mode.

6. **Email service failures are swallowed.** `email_service.py` catches all provider exceptions and logs them without re-raising. A broken email config will not fail the registration request, but users will be unable to verify their email. Monitor logs for email errors.

7. **Redis is used but failure is non-fatal.** The app boots without Redis, but caching-dependent features silently degrade. In local dev, start Redis via `docker-compose up redis` before running the backend.

8. **Three distinct file URL shapes.** Image URLs differ by environment: local dev uses filesystem paths under `STATIC_DIR`; cloud without CDN uses S3 direct URLs; cloud with CDN uses CloudFront URLs. Frontend `getImageUrl()` in `src/lib/config.ts` handles this — do not change URL construction on the backend without coordinating with the frontend.

9. **Alembic `stamp` logic in `start.py`.** The `alembic stamp head` call in `start.py` is intentional — it prevents Alembic from trying to apply migrations on tables already created by `create_all`. Do not remove this without understanding its interaction with `create_all`.

10. **Connection pool recycle interval is 300 seconds.** `connection.py` sets `pool_recycle=300`. Under high load or long-lived idle connections you may see `SSL SYSCALL EOF` or `server closed the connection` errors. Investigate pool size (`pool_size`, `max_overflow`) together with the recycle interval before changing either independently.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **profsidekick-api** (9434 symbols, 26427 relationships, 542 execution flows).

> Index stale? Run `node .gitnexus/run.cjs analyze --index-only` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? Bootstrap with `npx`, `bunx`, or `pnpm dlx` — e.g. `bunx gitnexus@latest analyze` (npm 11 npx crash; #1939).

## Always Do

- **MUST run impact before editing.** Use `impact({target: "symbolName", direction: "upstream"})` or `node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .`; report callers, processes, and risk. Never substitute grep for graph analysis. For unified PDG impact, add `mode: "pdg"` with optional `line: <N>` — it returns statement-level `affectedStatements` over CDG + REACHING_DEF and inter-procedural symbols in `interproceduralByDepth`/`byDepth`; no-layer/degraded PDG results are UNKNOWN-risk notes (`--pdg` layer). CLI equivalent: `node .gitnexus/run.cjs impact "symbolName" --direction upstream --mode pdg --line <N> --repo .`.
- **MUST analyze graph changes before committing.** Use `detect_changes({scope: "all"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .` (CLI fallback). `partial: true` or `truncated: true` is not a clean check — a zero means unseen, not unaffected; re-run it. For regression review: `detect_changes({scope: "compare", base_ref: "main"})` or `node .gitnexus/run.cjs detect-changes --scope compare --base-ref "main" --repo .`.
- MUST warn on HIGH/CRITICAL `risk` pre-edit; never use `riskSharedAxes` to waive a HIGH/CRITICAL `risk` warning. Compare File/symbol: MCP File omits axes; Graph-RAG expands File.
- **MUST treat `risk: UNKNOWN` as unresolved, not as low.** An empty caller set is not evidence the symbol is unused — it can also mean the callers are not resolvable by the index (plain-object property access, dynamic dispatch, cross-language calls). `impact` pairs `UNKNOWN` with a `riskNote` saying so. Confirm with a text search before treating the symbol as safe to change or delete; do not proceed on the strength of a zero.
- **MUST use `query({search_query: "concept"})` for concepts/flows, `context({name: "symbolName"})` for a named symbol, or `impact` for blast radius, on read-only callers, dependencies, imports, or execution flow.** Graph first; text search only for empty/`UNKNOWN`/literals.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).
- For control/data dependence, `pdg_query({mode: "controls", target: "fileOrSymbol"})` answers "under what condition does X run?" (CDG, incl. guard clauses) and `pdg_query({mode: "flows", target, variable})` traces "where does variable Y flow?" (REACHING_DEF). `--pdg` layer.

## Never Do

- NEVER edit a function, class, or method before MCP/CLI impact analysis.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis, and never read `UNKNOWN` as an all-clear — it means the walk could not answer, which is the one verdict that requires confirming by other means.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit before MCP/CLI graph change analysis.

## Resources

| Resource | Use for |
| --- | --- |
| `gitnexus://repo/profsidekick-api/context` | Codebase overview, check index freshness |
| `gitnexus://repo/profsidekick-api/clusters` | All functional areas |
| `gitnexus://repo/profsidekick-api/processes` | All execution flows |
| `gitnexus://repo/profsidekick-api/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
| --- | --- |
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
