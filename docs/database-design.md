# ZENTIQ — Database Architecture & Design Strategy

## 1. Database Engine Strategy

- **Production & Development Engine:** MySQL 8.4 Community Server (`InnoDB` storage engine).
- **Driver:** PyMySQL 1.1.2 bridged via `pymysql.install_as_MySQLdb()` with `cryptography 50.0.0` for modern `caching_sha2_password` authentication support.
- **Character Set & Collation:** `utf8mb4` with `utf8mb4_unicode_ci` for complete Unicode, emoji, and multi-language support.
- **SQL Mode:** `STRICT_TRANS_TABLES` enforced in database connection options to reject invalid or truncated data.
- **Isolated Testing Engine:** SQLite in-memory database (`:memory:`) configured strictly for headless test runners (`config.settings.testing`) to enable rapid CI/CD test passes without requiring an active external database instance.

---

## 2. Custom User Model Architecture

### Rationale
Django's default `auth.User` model relies on a required `username` field. In modern platforms, email is the primary credential for identity, communication, and notifications. Substituting the user model mid-project after initial migrations is notoriously difficult and risky in Django. Establishing a custom user model before any initial migration is standard software engineering best practice.

### Implemented Model Specification (`apps.accounts.models.User`)

```python
class User(AbstractBaseUser, PermissionsMixin):
    id = models.BigAutoField(primary_key=True)
    email = models.EmailField(unique=True, max_length=255, db_index=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
```

### Key Design Decisions
1. **Email as Identifier:** `USERNAME_FIELD = 'email'` with RFC-compliant domain normalization via `UserManager.normalize_email()`.
2. **Lean Identity Entity:** Contains only authentication, security, and administrative flags. Speculative profile fields (avatars, bio, preferences, gamer tags) are intentionally decoupled and will reside in a separate profile model in future milestones.
3. **Permissions & Groups:** Inherits `PermissionsMixin` to retain full compatibility with Django's built-in RBAC (`Group`, `Permission`, `has_perm()`).

---

## 3. Initial Database Scope (Milestone 1)

Only the fundamental authentication and session infrastructure tables are defined in Milestone 1:
- `accounts_user` (custom user model)
- `accounts_user_groups` (user-to-group M2M join table)
- `accounts_user_user_permissions` (user-to-permission M2M join table)
- `auth_group`, `auth_group_permissions`, `auth_permission` (Django RBAC)
- `django_content_type`, `django_migrations`, `django_session` (Django internals)

*No speculative business tables have been created prematurely.*

---

## 4. Planned Future Domain Entities

The following entity schemas are planned for upcoming milestones:

### 1. Gamification Ledger (`apps.gamification`)
- `UserExperienceLedger`: Immutable audit record of all XP changes.
  - `id`: BigAutoField
  - `user_id`: ForeignKey(User)
  - `amount`: Integer (+/- points)
  - `source`: Enum (`QUEST`, `ARENA_CHALLENGE`, `DAILY_STREAK`, `DUEL_VICTORY`)
  - `source_id`: BigIntegerField
  - `balance_after`: Integer
  - `created_at`: DateTimeField
- `Badge`: Definition of unlockable achievements.
- `UserBadge`: Join table recording badge unlocks with unlock timestamp.

### 2. Skill Taxonomy (`apps.skills`)
- `Skill`: Represents individual competencies (e.g. "System Architecture", "Python Async").
- `SkillPrerequisite`: Self-referencing DAG representing dependency prerequisites.
- `UserSkillMastery`: Current calculated mastery score and confidence tier per user.

### 3. Assessment Bank (`apps.arena`)
- `Question`: Question metadata and category.
- `QuestionVersion`: Immutable snapshot of question prompt, code snippets, choices, and rubric.
- `AssessmentSession`: Timed user evaluation instance.
- `AssessmentSubmission`: User responses mapped to specific `QuestionVersion` IDs.

---

## 5. Data Integrity & Migration Principles

1. **Foreign Key Integrity:** All relationships enforce database-level foreign key constraints with explicit `on_delete` behaviors (`CASCADE`, `PROTECT`, or `SET_NULL`).
2. **No In-Place Question Mutation:** Content changes to questions generate a new `QuestionVersion` row rather than updating historical text.
3. **Append-Only Auditing:** User XP and reward points cannot be arbitrarily overwritten; they are derived from append-only ledger entries.
4. **Environment-Driven Configuration:** Real database credentials reside exclusively in `.env` and are never hardcoded or checked into version control.

