# ZENTIQ — Architecture Specification

## 1. System Overview

ZENTIQ is a gamified skill-development platform engineered to accelerate cognitive, technical, and analytical mastery.

The platform employs a **decoupled frontend/backend architecture** centered around a **modular monolith** backend built on Django 6.0 and Django REST Framework, paired with an independent React 19 single-page application (SPA).

```
┌─────────────────────────────────┐        ┌───────────────────────────────────┐
│        Web Client (React)       │        │    Future Mobile Client (Flutter)  │
│  - React 19 + TypeScript        │        │    - Dart / Flutter                │
│  - Tailwind CSS v4              │        │    - Shared REST API consumption   │
│  - Feature-oriented layout      │        │    - Cross-platform iOS/Android    │
└────────────────┬────────────────┘        └─────────────────┬─────────────────┘
                 │                                           │
                 │ JSON / REST                               │ JSON / REST
                 │ Session / CSRF                            │ Session / Auth Token
                 └─────────────────────┬─────────────────────┘
                                       │
                                       ▼
                       ┌───────────────────────────────┐
                       │     ZENTIQ Backend Gateway    │
                       │     Django 6.0 REST API       │
                       │     Prefix: /api/v1/          │
                       └───────────────┬───────────────┘
                                       │
     ┌─────────────────────────────────┴─────────────────────────────────┐
     │                     MODULAR MONOLITH BOUNDARIES                   │
     │                                                                   │
     │  [Implemented - M1-M3B]            [Planned - Provisional Targets]│
     │  ├── apps.accounts                 ├── apps.skills                │
     │  │   └── Custom User Model         ├── apps.gamification (Ledger) │
     │  └── apps.core                     ├── apps.missions (Quest)      │
     │      ├── Live DB Health Check      ├── apps.arena (Assessments)   │
     │      └── Centralized Exceptions    ├── apps.ai_engine (Tutor)     │
     │                                    ├── apps.insights (Analytics)  │
     │                                    ├── apps.duels (1v1 Match)     │
     │                                    └── apps.career (Pathways)     │
     └─────────────────────────────────┬─────────────────────────────────┘
                                       │
                                       ▼
                       ┌───────────────────────────────┐
                       │       Relational Database     │
                       │       MySQL 8.4 Server        │
                       │  - PyMySQL + cryptography     │
                       │  - ACID transaction safety    │
                       │  - Strict SQL mode            │
                       └───────────────────────────────┘
```

---

## 2. Decoupled Architecture Rationale

### Web and Mobile Parity
The backend exposes pure REST endpoints namespaced under `/api/v1/`. The React web application and the upcoming Flutter mobile client consume the identical API contract. No presentation rendering or HTML template logic is coupled to the backend, preventing duplicate business logic.

### Independent Scalability and Development
The frontend and backend repositories are co-located in this mono-repository for unified developer experience, but build, test, and run independently:
- Frontend compiles to static assets via Vite.
- Backend runs as an ASGI/WSGI Python process.

---

## 3. Modular Monolith Architecture Rationale

Rather than introducing microservices prematurely, ZENTIQ adopts a modular monolith structure:
1. **Transaction Integrity:** Gamification workflows (such as quest completion triggering XP ledger increments and badge awards) require atomic ACID transactions across domain tables. Monolithic data stores avoid distributed 2-phase commits or saga orchestrators.
2. **Operational Simplicity:** Zero network latency between internal service calls, zero service-mesh infrastructure overhead, and simplified local development.
3. **Clear Boundary Enforcements:** Modules interact through typed service layers and signals rather than cross-querying private tables directly.
4. **Future Extractability:** Should specific components experience asymmetric high traffic (such as real-time competitive duels), their bounded context is cleanly encapsulated for extraction into standalone services.

---

## 4. Application Boundaries (Implemented vs. Planned)

### Implemented in Milestones 1, 2A & 3B

| Application | Path | Responsibilities | Current Status |
|---|---|---|---|
| **accounts** | `apps/accounts` | Custom user entity (`User`), `UserProfile` 1-to-1 model with unique ZENTIQ handles, curated avatar keys, biography, and JSON preferences. Session authentication endpoints (`/auth/csrf/`, `/auth/register/`, `/auth/login/`, `/auth/logout/`, `/auth/me/`) and profile endpoint (`/profile/`). Authenticated Dashboard view and cognitive skill domains. Brute-force rate throttling. | **Implemented & Tested** (Migrations `0001` & `0002` applied, 31 automated backend tests passing) |
| **core** | `apps/core` | Global exception handling, standardized API error responses (`error.code`, `error.message`, `error.details`), live database connectivity health check (`GET /api/v1/health/`). | **Implemented & Tested** |
| **skills** | `apps/skills` | Skill taxonomy (Domains, Subdomains, Competencies), prerequisite dependency DAGs, user domain and competency mastery matrices, idempotent taxonomy seeder command (`seed_skills_taxonomy`). | **Implemented & Tested (M4 Phase 1)** (Migration `0001` generated, 16 automated backend tests passing) |

### Planned in Future Milestones (Provisional Targets)

> [!NOTE]
> Future milestone designations represent provisional planning targets rather than fixed release commitments. Milestone scoping may be adjusted based on domain dependencies and evolutionary architectural review.

| Application | Provisional Target | Domain Responsibilities |
|---|---|---|
| **gamification** | Provisional (Planned) | Immutable XP transaction ledger, level progression curves, streak calculators, badge definitions. |
| **missions (Quest)** | Provisional (Planned) | Daily quest generators, interactive learning modules, milestone completion trackers. |
| **arena (Assessments)** | Provisional (Milestone 4) | Timed test sessions, question bank with immutable question versioning, anti-cheat time-decay scoring. |
| **ai_engine** | Provisional (Milestone 5) | LLM tutor integrations, adaptive hints, dynamic challenge generation, diagnostic feedback. |
| **insights** | Provisional (Milestone 6) | Skill radar computations, learning velocity analytics, percentile distributions, progress forecasting. |
| **duels** | Provisional (Milestone 7) | Asynchronous and synchronous 1v1 knowledge battles, matchmaking rating (MMR), duel challenge queues. |
| **career** | Provisional (Milestone 8) | Skill-to-role mappings, resume alignment metrics, industry certification readiness scores. |

---

## 5. Authentication & Security Architecture

1. **Authentication Mechanism:** Django Session Authentication utilizing `HttpOnly`, `SameSite=Lax` cookies (`sessionid`). In production, `SESSION_COOKIE_SECURE = True`.
2. **CSRF Protection:** Django CSRF token middleware enabled. Safe endpoints provide the cookie; mutating endpoints require the `X-CSRFToken` header.
3. **CSRF Bootstrap Endpoint:** `GET /api/v1/auth/csrf/` decorated with `@ensure_csrf_cookie` returns `{ "csrfToken": "..." }` and seeds the browser's cookie jar for SPA initial loads.
4. **Rate Throttling:** Scoped rate throttling via DRF's `ScopedRateThrottle` (`auth_login`: 5/min, `auth_register`: 3/min) against brute-force and credential stuffing attacks.
5. **CORS Isolation:** Development origins explicitly whitelist `http://localhost:5173` and `http://127.0.0.1:5173`. Credentials mode (`include`) is enabled for session cookies.
6. **Environment Isolation:** Zero hardcoded credentials. Development and production settings pull all database secrets, debug flags, and secret keys from environment variables.
7. **Identity Separation:** `accounts.User` is strictly for authentication credentials; `accounts.UserProfile` is for presentation and identity (`username` handle, `display_name`, `avatar_key`, `bio`, `preferences`). No gamification logic is bound to the identity system.


---

## 6. Core Architectural Constraints

All future milestones must strictly preserve these engineering principles:

1. **Backend-Validated Gamification:** XP, scores, ranks, and badges must never be calculated or submitted by client applications. The client submits actions or answers; the backend validates criteria and commits rewards.
2. **Auditable XP Ledger:** Every XP modification requires an immutable transaction row recording timestamp, source entity (e.g. `mission_id`), points awarded, and resulting balance.
3. **Assessment Question Versioning:** Modifying an assessment question must never mutate the existing row in place. Questions must be version-incremented so historical user test completions reflect the exact question text and choices evaluated at the time of submission.
4. **Single Source of Truth for Web & Mobile:** Flutter and React must use identical REST contracts. Business rules exist solely in Django services.

