# ZENTIQ — API Design Conventions & Standards

## 1. API Versioning & URL Structure

- **Base URL Prefix:** All API endpoints are versioned under `/api/v1/`.
- **Resource Naming:** Nouns in plural kebab-case (e.g. `/api/v1/user-profiles/`, `/api/v1/assessments/`).
- **Trailing Slashes:** Django REST Framework standard enforces trailing slashes on all endpoints (e.g. `/api/v1/health/`).
- **Interactive API Documentation:** Available in development at:
  - Swagger UI: `/api/docs/`
  - OpenAPI 3.0 Schema: `/api/schema/`

---

## 2. HTTP Methods & Status Codes

| Method | Idempotent | Standard Use Case | Success Status |
|---|---|---|---|
| `GET` | Yes | Retrieve resource representations. | `200 OK` |
| `POST` | No | Create new resources or trigger actions. | `201 Created` or `200 OK` |
| `PUT` | Yes | Complete resource replacement. | `200 OK` |
| `PATCH` | No | Partial resource update. | `200 OK` |
| `DELETE` | Yes | Remove or soft-delete a resource. | `204 No Content` |

### Error Status Codes

- `400 Bad Request`: Client validation error or malformed payload.
- `401 Unauthorized`: Authentication credentials missing or invalid.
- `403 Forbidden`: Authenticated user lacks permission to access the resource.
- `404 Not Found`: Requested resource does not exist.
- `408 Request Timeout`: Client or internal proxy timeout.
- `429 Too Many Requests`: Rate limit exceeded.
- `500 Internal Server Error`: Unhandled server exception.
- `503 Service Unavailable`: Dependent service (such as MySQL database) is down.

---

## 3. Standard Response Formats

### Successful Health Response Example (`GET /api/v1/health/`)

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2026-11-09T05:49:27.863330+00:00",
  "services": {
    "api": "operational",
    "database": "operational",
    "database_connection": "operational",
    "database_engine": "mysql"
  }
}
```

### Unhealthy Response Example (HTTP 503)

```json
{
  "status": "unhealthy",
  "version": "1.0.0",
  "timestamp": "2026-11-09T05:49:27.863330+00:00",
  "services": {
    "api": "operational",
    "database": "unavailable",
    "database_connection": "unavailable",
    "database_engine": "mysql"
  }
}
```

### Standardized Error Format (`apps.core.exceptions.custom_exception_handler`)

All DRF errors and unhandled exceptions are intercepted and normalized into a single predictable envelope:

```json
{
  "error": {
    "code": "validation_error",
    "message": "The email address is already in use.",
    "details": {
      "email": [
        "A user with that email already exists."
      ]
    }
  }
}
```

---

## 4. Authentication & Security Expectations

1. **Transport Security:** All traffic in production must be HTTPS encrypted (`SECURE_SSL_REDIRECT = True`).
2. **Session Cookies:**
   - Cookie name: `sessionid`
   - Attributes: `HttpOnly`, `SameSite=Lax`, `Secure` (in production).
3. **CSRF Tokens:**
   - Safe HTTP methods (`GET`, `HEAD`, `OPTIONS`) do not require CSRF tokens.
   - Mutating methods (`POST`, `PUT`, `PATCH`, `DELETE`) require the `X-CSRFToken` header matching the client's `csrftoken` cookie value.
4. **Zero Client Trust:**
   - Client applications never send updated XP values, completion ranks, or score numbers.
   - Client sends only input actions (e.g. answer indices, challenge submission tokens); backend computes all scores and awards.

