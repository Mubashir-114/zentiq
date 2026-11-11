"""
Deterministic canonical JSON serialization and answer hashing (Phase 2E.2).

Version: ``answer_canon_v1``.

Rules (frozen):
- ``null`` -> ``null``; ``bool`` -> ``true``/``false`` (tested before ``int``);
- ``int`` -> shortest integer literal; ``Decimal`` -> exact non-exponent form
  with trailing fractional zeros stripped (``1.50`` == ``1.5``, ``5.00`` == ``5``);
  binary ``float`` is rejected;
- ``str`` -> JSON string, UTF-8, ``ensure_ascii=False``, no Unicode normalization,
  no case folding, no whitespace trimming; unpaired surrogates rejected;
- ``list``/``tuple`` -> order preserved (order is semantic);
- ``dict`` -> members sorted by Unicode code point of the key; keys must be strings;
- separators are ``,`` and ``:`` with no whitespace.

The hash is computed server-side only. Changing any rule requires a new version
tag so historical hashes remain interpretable.
"""
import hashlib
import json
from decimal import Decimal
from typing import Any

CANONICALIZATION_VERSION = 'answer_canon_v1'

REDACTION_MARKER_KEY = '__redacted__'


class CanonicalizationError(ValueError):
    """Raised when a value cannot be canonically serialized."""


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise CanonicalizationError('Non-finite Decimal values are not serializable.')
    if value == 0:
        return '0'
    _sign, _digits, exponent = value.as_tuple()
    if exponent >= 0:
        return str(int(value))
    text = format(value, 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text or '0'


def _canonical_string(value: str) -> str:
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as exc:  # lone surrogates
        raise CanonicalizationError('String contains invalid Unicode surrogate data.') from exc
    return json.dumps(value, ensure_ascii=False)


def canonical_dumps(value: Any) -> str:
    """Returns the single canonical JSON text for ``value``."""
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(int(value))
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if isinstance(value, float):
        raise CanonicalizationError('Binary floats are not part of the canonical contract.')
    if isinstance(value, str):
        return _canonical_string(value)
    if isinstance(value, (list, tuple)):
        return '[' + ','.join(canonical_dumps(item) for item in value) + ']'
    if isinstance(value, dict):
        parts = []
        for key in sorted(value.keys()):
            if not isinstance(key, str):
                raise CanonicalizationError('Object keys must be strings.')
            parts.append(f'{_canonical_string(key)}:{canonical_dumps(value[key])}')
        return '{' + ','.join(parts) + '}'
    raise CanonicalizationError(f'Unsupported canonical type: {type(value).__name__}')


def canonical_bytes(value: Any) -> bytes:
    return canonical_dumps(value).encode('utf-8')


def answer_payload_hash(payload: Any) -> str:
    """SHA-256 (lowercase hex) of the canonical UTF-8 encoding of an answer payload."""
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def evaluation_config_hash(
    grading_strategy: str,
    correct_payload: Any,
    scoring_rubric: Any,
    evaluator_version: str,
) -> str:
    """Hash of the grading configuration actually used, for reproducibility audits."""
    return hashlib.sha256(canonical_bytes({
        'grading_strategy': grading_strategy,
        'correct_payload': correct_payload,
        'scoring_rubric': scoring_rubric,
        'evaluator_version': evaluator_version,
    })).hexdigest()


def contains_redaction_marker(value: Any) -> bool:
    """Recursive check for the internal redaction sentinel in client-supplied payloads."""
    if isinstance(value, dict):
        if REDACTION_MARKER_KEY in value:
            return True
        return any(contains_redaction_marker(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_redaction_marker(v) for v in value)
    return False
