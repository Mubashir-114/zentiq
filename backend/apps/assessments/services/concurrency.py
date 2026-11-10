"""
Concurrency and Deadlock Retry Policy for ZENTIQ Assessments.
Provides bounded retry logic for MySQL deadlocks (error 1213) and
fail-fast handling for MySQL lock wait timeouts (error 1205),
as well as candidate-side shared locking (FOR SHARE / LOCK IN SHARE MODE).
"""
import functools
import random
import time
from typing import Any, Callable, TypeVar

from django.db import OperationalError
from django.db.models import QuerySet
from django.db.models.sql.compiler import SQLCompiler

from .exceptions import ConcurrencyConflictError, LockTimeoutError

F = TypeVar('F', bound=Callable[..., Any])

MYSQL_DEADLOCK_CODE = 1213
MYSQL_LOCK_TIMEOUT_CODE = 1205
DEFAULT_MAX_DEADLOCK_RETRIES = 3
DEFAULT_INITIAL_DELAY_SECONDS = 0.05
DEFAULT_BACKOFF_FACTOR = 2.0


# -----------------------------------------------------------------------------
# Candidate-Side Shared Lock Infrastructure
# -----------------------------------------------------------------------------

def _enable_shared_locks() -> None:
    """
    Extends QuerySet.select_for_update to support `share=True` parameter.
    Under MySQL, modifies the generated SQL clause from FOR UPDATE to FOR SHARE.
    Under SQLite and other backends, preserves clean ORM execution.
    """
    if getattr(QuerySet.select_for_update, '_supports_share_param', False):
        return

    _orig_select_for_update = QuerySet.select_for_update

    @functools.wraps(_orig_select_for_update)
    def patched_select_for_update(
        self: QuerySet[Any],
        nowait: bool = False,
        skip_locked: bool = False,
        of: tuple[str, ...] = (),
        no_key: bool = False,
        share: bool = False,
    ) -> QuerySet[Any]:
        qs = _orig_select_for_update(self, nowait=nowait, skip_locked=skip_locked, of=of, no_key=no_key)
        qs.query._select_for_share = bool(share)
        return qs

    patched_select_for_update._supports_share_param = True  # type: ignore[attr-defined]
    QuerySet.select_for_update = patched_select_for_update  # type: ignore[assignment]

    if getattr(SQLCompiler.as_sql, '_supports_share_param', False):
        return

    _orig_as_sql = SQLCompiler.as_sql

    @functools.wraps(_orig_as_sql)
    def custom_as_sql(self: SQLCompiler, *args: Any, **kwargs: Any) -> tuple[str, tuple[Any, ...]]:
        sql, params = _orig_as_sql(self, *args, **kwargs)
        if getattr(self.query, '_select_for_share', False):
            if getattr(self.connection, 'vendor', None) == 'mysql':
                if 'FOR UPDATE' in sql:
                    sql = sql.replace('FOR UPDATE', 'FOR SHARE')
        return sql, params

    custom_as_sql._supports_share_param = True  # type: ignore[attr-defined]
    SQLCompiler.as_sql = custom_as_sql  # type: ignore[assignment]


# Activate shared lock support upon import
_enable_shared_locks()


def select_for_share(
    queryset: QuerySet[Any],
    nowait: bool = False,
    skip_locked: bool = False,
    of: tuple[str, ...] = (),
) -> QuerySet[Any]:
    """
    Applies candidate-side shared lock to a queryset (FOR SHARE under MySQL).
    """
    return queryset.select_for_update(nowait=nowait, skip_locked=skip_locked, of=of, share=True)


# -----------------------------------------------------------------------------
# Deadlock & Lock Timeout Detection and Retry Decorator
# -----------------------------------------------------------------------------

def is_deadlock_exception(exc: Exception) -> bool:
    """
    Detects whether an exception represents a MySQL 1213 deadlock or equivalent database deadlock.
    """
    if isinstance(exc, OperationalError):
        if exc.args and exc.args[0] == MYSQL_DEADLOCK_CODE:
            return True
        msg = str(exc).lower()
        if '1213' in msg or 'deadlock' in msg:
            return True
    return False


def is_lock_timeout_exception(exc: Exception) -> bool:
    """
    Detects whether an exception represents a MySQL 1205 lock wait timeout.
    """
    if isinstance(exc, OperationalError):
        if exc.args and exc.args[0] == MYSQL_LOCK_TIMEOUT_CODE:
            return True
        msg = str(exc).lower()
        if '1205' in msg or 'lock wait timeout' in msg:
            return True
    return False


def with_deadlock_retry(
    max_retries: int = DEFAULT_MAX_DEADLOCK_RETRIES,
    initial_delay: float = DEFAULT_INITIAL_DELAY_SECONDS,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
) -> Callable[[F], F]:
    """
    Decorator that applies bounded retry logic on MySQL deadlock (1213)
    and fails fast on lock wait timeout (1205) with LockTimeoutError.
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = initial_delay
            for attempt_idx in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if is_lock_timeout_exception(exc):
                        raise LockTimeoutError(
                            "Database lock wait timeout exceeded. Service temporarily unavailable.",
                            details={'code': MYSQL_LOCK_TIMEOUT_CODE},
                        ) from exc

                    if is_deadlock_exception(exc):
                        if attempt_idx < max_retries:
                            # Apply exponential backoff with jitter
                            jitter = random.uniform(0.5, 1.5)
                            time.sleep(delay * jitter)
                            delay *= backoff_factor
                            continue
                        raise ConcurrencyConflictError(
                            f"Database deadlock persisted after {max_retries} retries.",
                            details={'code': MYSQL_DEADLOCK_CODE, 'retries': max_retries},
                        ) from exc
                    raise

        return wrapper  # type: ignore

    return decorator
