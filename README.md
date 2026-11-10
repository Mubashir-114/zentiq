# ZENTIQ

> **Level Up Your Mind.**  
> *Learn. Challenge. Evolve.*

ZENTIQ is a gamified skill-development ecosystem designed to help users improve cognitive, analytical, technical, and career-related skills through structured learning, challenges, assessments, rankings, and AI-assisted experiences.

This repository represents **Milestone 1: Architecture & Project Foundation**, establishing a production-grade, independently runnable frontend and backend foundation with MySQL 8.4 database architecture, custom authentication models, versioned REST APIs, and a high-contrast dark gaming design system.

---

## 1. Technology Stack

### Frontend
- **Framework:** React 19 (`^19.3.1`) + TypeScript (`~7.0.2` / `^5.7+`)
- **Build Tool:** Vite (`^8.3.6`)
- **Styling:** Tailwind CSS v4 (`^4.3.5`) via official first-party `@tailwindcss/vite` plugin
- **Routing:** React Router DOM v7 (`^7.18.5`)
- **Icons & UI:** Lucide React (`^1.70.0`), `clsx`, `tailwind-merge`
- **Linting & Verification:** TypeScript strict checks (`tsc -b --noEmit`), Playwright MCP for browser-level smoke verification

### Backend
- **Framework:** Python 3.14 + Django 6.0 (`6.0.8`)
- **API Engine:** Django REST Framework (`3.18.3`)
- **API Documentation:** OpenAPI 3 schema and Swagger UI via `drf-spectacular` (`0.30.0`)
- **Database Driver:** PyMySQL (`1.1.2`) configured with `cryptography` (`50.0.0`) for native MySQL 8.4 authentication
- **Environment Management:** `python-dotenv` (`1.2.4`)
- **Testing:** Pytest (`9.2.0`) + `pytest-django` (`4.14.0`)

### Database
- **Engine:** MySQL 8.4 Community Server (Windows Service `MYSQL84`)
- **Architecture:** Environment-driven database configuration with MySQL 8.4 as default, isolated SQLite support strictly for offline unit testing runners.

---

## 2. Project Directory Structure

```text
D:\zentiq\
│
├── frontend\
│   ├── public\
│   │   └── favicon.svg
│   ├── src\
│   │   ├── app\
│   │   │   ├── App.tsx                    # Root application component
│   │   │   └── router.tsx                 # Centralized React Router configuration
│   │   ├── components\
│   │   │   ├── ui\                        # Reusable design system primitives
│   │   │   │   ├── Button.tsx
│   │   │   │   ├── Card.tsx
│   │   │   │   └── Badge.tsx
│   │   │   └── layout\                    # Responsive application shell
│   │   │       ├── Header.tsx
│   │   │       ├── Sidebar.tsx
│   │   │       └── Shell.tsx
│   │   ├── features\
│   │   │   ├── overview\                  # Overview view & design system showcase
│   │   │   │   └── HomeView.tsx
│   │   │   ├── architecture\              # Architecture specification view
│   │   │   │   └── ArchitectureView.tsx
│   │   │   ├── health\                    # Backend & MySQL health monitoring
│   │   │   │   ├── api\healthApi.ts
│   │   │   │   ├── components\HealthStatusCard.tsx
│   │   │   │   └── HealthView.tsx
│   │   │   └── common\
│   │   │       └── NotFoundView.tsx
│   │   ├── lib\
│   │   │   ├── api-client.ts              # Resilient fetch client with CSRF and error handling
│   │   │   └── utils.ts                   # Class name merger (clsx + tailwind-merge)
│   │   ├── styles\
│   │   │   └── index.css                  # Tailwind v4 @theme and global styles
│   │   ├── types\
│   │   │   └── index.ts                   # Core TypeScript types and API interfaces
│   │   └── main.tsx                       # Frontend entry point
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
│
├── backend\
│   ├── config\
│   │   ├── __init__.py                    # PyMySQL as MySQLdb bridge
│   │   ├── settings\
│   │   │   ├── __init__.py
│   │   │   ├── base.py                    # Shared Django settings
│   │   │   ├── development.py             # Default development settings (MySQL 8.4 default)
│   │   │   ├── testing.py                 # Fast in-memory testing settings
│   │   │   └── production.py              # Production security settings
│   │   ├── urls.py                        # Root URL routing (/api/v1/ and /api/docs/)
│   │   ├── asgi.py
│   │   └── wsgi.py
│   ├── apps\
│   │   ├── accounts\                      # Custom User model and authentication foundation
│   │   │   ├── admin.py
│   │   │   ├── apps.py
│   │   │   ├── managers.py                # UserManager with normalized email handling
│   │   │   ├── models.py                  # User model (AbstractBaseUser, PermissionsMixin)
│   │   │   ├── migrations\
│   │   │   │   └── 0001_initial.py
│   │   │   └── tests\
│   │   │       └── test_user_model.py     # 7 focused unit tests
│   │   └── core\                          # Shared platform services & health checks
│   │       ├── apps.py
│   │       ├── exceptions.py              # Centralized DRF error handler
│   │       ├── views.py                   # GET /api/v1/health/ with live DB ping
│   │       ├── urls.py
│   │       └── tests\
│   │           └── test_health.py         # 3 focused unit tests
│   ├── requirements\
│   │   ├── base.txt
│   │   ├── development.txt
│   │   └── production.txt
│   ├── manage.py
│   └── pytest.ini
│
├── docs\
│   ├── architecture.md                    # System architecture & module boundaries
│   ├── database-design.md                 # Database strategy & custom user model
│   └── api-conventions.md                 # REST API standards & error format
│
├── .gitignore
├── .env.example
└── README.md
```

---

## 3. Getting Started & Installation

### Prerequisites
- **Node.js:** `>= 20.x` (verified on `v26.13.0` with `npm 11.10.1`)
- **Python:** `>= 3.12` (verified on `3.14.10` 64-bit)
- **MySQL Server:** `8.4.x` (verified on `8.4.11` Community Server)

### Environment Setup
1. Copy `.env.example` to `.env` in the project root:
   ```powershell
   Copy-Item .env.example .env
   ```
2. Configure your MySQL credentials in `.env`:
   ```env
   DJANGO_SECRET_KEY=your-secure-random-secret-key
   DJANGO_DEBUG=True
   DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

   DB_ENGINE=django.db.backends.mysql
   DB_NAME=zentiq_dev
   DB_USER=zentiq_user
   DB_PASSWORD=your_secure_password
   DB_HOST=127.0.0.1
   DB_PORT=3306

   # Set to True only when running isolated unit tests without MySQL credentials
   USE_SQLITE_TEST_DB=False
   ```

---

## 4. Backend Setup & Commands

### Virtual Environment & Dependency Installation
Create and use an isolated virtual environment:
```powershell
cd D:\zentiq\backend
python -m venv .venv

# Note: On Windows systems with Application Control (WDAC/AppLocker), dynamically generated
# executable stubs like Scripts\pip.exe are restricted. Always invoke pip via python.exe:
.\.venv\Scripts\python.exe -m pip install -r requirements/development.txt
```

Alternatively, you can install into your user Python environment:
```powershell
python -m pip install --user -r requirements/development.txt
```

### Run Django System Checks
```powershell
python manage.py check
```

### Run Backend Unit Tests
Execute the focused Pytest test suite (11 unit tests covering User model, UserManager, and Health endpoint):
```powershell
python -m pytest
```

### Start Backend Development Server
With MySQL credentials in `.env`:
```powershell
python manage.py runserver 127.0.0.1:8000
```
Or for offline development using the explicit SQLite test toggle:
```powershell
$env:USE_SQLITE_TEST_DB="True"; python manage.py runserver 127.0.0.1:8000
```

- API Base: `http://127.0.0.1:8000/api/v1/`
- Health Endpoint: `http://127.0.0.1:8000/api/v1/health/`
- Interactive Swagger UI: `http://127.0.0.1:8000/api/docs/`
- OpenAPI JSON Schema: `http://127.0.0.1:8000/api/schema/`

---

## 5. Frontend Setup & Commands

### Install Frontend Dependencies
```powershell
cd D:\zentiq\frontend
npm install
```

### Type Checking & Linting
```powershell
npm run lint
```

### Production Build
```powershell
npm run build
```

### Start Frontend Development Server
```powershell
npm run dev -- --host 127.0.0.1 --port 5173
```
Open `http://127.0.0.1:5173` in your browser.

---

## 6. Architecture & Foundation Highlights

- **Custom User Model Configured Upfront:** Implemented in `apps/accounts/models.py` before any database migration. Uses normalized email as the unique identifier (`USERNAME_FIELD = 'email'`), avoiding speculative profile fields.
- **Environment-Driven MySQL 8.4 Default:** Default development and production configurations target MySQL 8.4 via PyMySQL. SQLite is supported only when explicitly requested via `USE_SQLITE_TEST_DB=True` or `config.settings.testing`.
- **Live Database Health Verification:** `GET /api/v1/health/` actively verifies database connectivity (`SELECT 1;`), returning HTTP 200 when healthy and HTTP 503 when the database drops, without exposing internal credentials or tracebacks.
- **ZENTIQ Design Tokens:** Tailwind CSS v4 CSS `@theme` variables: Electric Violet (`#8B5CF6`), Neon Cyan (`#22D3EE`), Deep Space (`#10121E`), Surface (`#1B1E2D`), Success (`#34D399`), Warning (`#FBBF24`), Error (`#FB7185`), Reward Gold (`#F5C451`).
- **Browser Smoke Tested:** Verified using Playwright MCP with zero browser console errors and full layout responsiveness.

