# ZENTIQ — Phase 2E.1: Scoring & Evaluation Architecture Proposal

**Status:** Design only. Nothing in this document is implemented.
**Scope:** Phase 2E.1 (architecture). Phase 2E.2 is not started.
**Date:** 2026-11-11

**Status labels used throughout**

| Label | Meaning |
|---|---|
| `[IMPLEMENTED]` | Exists in the repository today and was verified by reading the code. |
| `[PROPOSED]` | Technical design recommended by this document. No product decision implied. |
| `[APPROVAL]` | Requires explicit product/business approval before any implementation. Nothing may be hardcoded in the meantime. |

---

## 1. Executive summary

The execution engine is complete and internally consistent, but there is **no evaluation layer at all**. An attempt can be `SUBMITTED` without any score, per-question outcome, competency evidence, or XP. The word "score" does not appear in any assessment model.

Key verified facts:

1. `[IMPLEMENTED]` `AssessmentAttempt.submit_attempt()` only changes status to `SUBMITTED`, sets `completed_at`, deletes the active reservation, and appends an `ATTEMPT_SUBMITTED` event. It performs no grading (`backend/apps/assessments/services/attempt_service.py`).
2. `[IMPLEMENTED]` `AssessmentAttempt` has no score, result, pass/fail, or evaluation-status field (`backend/apps/assessments/models.py`).
3. `[IMPLEMENTED]` Every published `QuestionVersion` is **required** to have confidential `QuestionEvaluationData` (grading strategy + correct payload + free-form rubric) before publication (`apps/arena/services/versioning_service.py::validate_version_completeness`). Evaluation *metadata* therefore exists for every published question; evaluation *logic* does not.
4. `[IMPLEMENTED]` Weights exist at two levels (`AssessmentVersionQuestion.weight`, frozen into `AttemptQuestion.weight`, `Decimal(5,2)`, `>= 0.01`) but are never used for scoring.
5. `[IMPLEMENTED]` `AttemptQuestion` freezes the exact `QuestionVersion` FK, prompt, sanitized/shuffled presentation payload, question type, and weight. It does **not** freeze `QuestionEvaluationData`, the primary competency, or `QuestionCompetencyMapping`.
6. `[IMPLEMENTED]` `AttemptAnswer` is one row per attempt question and can be **overwritten** while the attempt is `IN_PROGRESS`. There is no answer revision history and the `ANSWER_SUBMITTED` audit event does not contain the answer payload.
7. `[IMPLEMENTED]` "Skipped" is only an `AttemptEvent`. `skip_question()` does not create, delete, or flag an `AttemptAnswer`, so a question answered earlier and later "skipped" still counts as answered. Unanswered and skipped are currently indistinguishable at the data level.
8. `[IMPLEMENTED]` `UserCompetencyMastery` and `UserDomainMastery` exist with range-validated `Decimal(5,2)` scores, evaluation counters, and a `confidence_tier` choice field — but **no service anywhere writes them**. No mastery formula, tier threshold, or domain aggregation rule exists.
9. `[IMPLEMENTED]` There is no `apps.gamification` app, no XP model, no ledger. XP is a planned target in `docs/architecture.md` only.
10. `[IMPLEMENTED]` Candidate-facing serializers/DTOs deliberately strip evaluation keys (`sanitize_candidate_content_payload`), and question publication rejects confidential keys in public `content_payload`.

Two existing behaviours materially constrain the design and should be decided before implementation:

- Submitting after the deadline transitions the attempt to `EXPIRED` and raises HTTP 410. Expired and cancelled attempts therefore reach a terminal state without any evaluation hook.
- `AttemptAnswer.clean()`/`save()` enforce **no** attempt-state guard. Immutability of answers after submission is service-enforced only, and admin/existing callers can still write.

The proposal introduces two new bounded contexts — `apps.evaluation` (objective evaluation, immutable results, competency evidence) and `apps.gamification` (auditable XP ledger) — plus a versioned scoring-policy registry. It deliberately leaves every grading threshold, tolerance, formula, and reward rule to an explicit product decision (Section 13).

---

## 2. Existing implementation dependency map

### 2.1 Component inventory

| Component | File | Responsibility | Phase 2E dependency |
|---|---|---|---|
| `Assessment` | `apps/assessments/models.py` | Canonical series anchor, `active_version`, deprecation. | Result snapshot parent. |
| `AssessmentVersion` | same | Immutable once `PUBLISHED`; holds time limit, backtracking, status transitions `DRAFT → PUBLISHED → ARCHIVED`. | Result snapshot pins this row. |
| `AssessmentVersionQuestion` | same | Pins exact `QuestionVersion`, `order_index` 1..N, `weight >= 0.01`; immutable after publication. | Source of question set and weights. |
| `AssessmentAttempt` | same | `IN_PROGRESS / SUBMITTED / EXPIRED / CANCELLED`; `attempt_number`, `idempotency_key`, `deadline`, `question_count`, `answer_count`. | Evaluation trigger and idempotency root. |
| `ActiveAssessmentReservation` | same | Unconditional unique `(user, assessment)` guard, deleted on terminal transition. | Pattern to reuse for "one current result per attempt". |
| `AttemptQuestion` | same | Frozen `question_version`, `order_index`, `weight`, prompt, sanitized/shuffled payload, type, per-question time limit. | Per-question evaluation unit. |
| `AttemptAnswer` | same | `OneToOne(AttemptQuestion)`, JSON `answer_payload`, `is_answered`, `answered_at`. Mutable pre-submission. | Candidate answer source snapshot. |
| `AttemptEvent` | same | Append-only audit with `update()`/`delete()` rejected at QuerySet and instance level. | Pattern to reuse for `EvaluationEvent` and XP ledger. |
| `AssessmentAttemptService` | `services/attempt_service.py` | Start/resume, submit, expire, cancel, deadline enforcement, deadlock retry, shared locks. | Evaluation must hook submit/expire atomically. |
| `AssessmentAnswerService` | `services/answer_service.py` | Payload validation per type, overwrite semantics, counter recompute, skip event. | Defines canonical answer shapes. |
| `AssessmentNavigationService` | `services/navigation_service.py` | Question retrieval, backtracking rules, candidate DTO. | Post-submission review access rules. |
| `AssessmentCompositionService` | `services/composition_service.py` | Draft/version/question composition, publication completeness. | Must gain evaluation-readiness validation (later phase). |
| `sanitize_candidate_content_payload` | `services/dto.py` | Strips forbidden keys from candidate payloads. | Result API must not undo this. |
| `Question` / `QuestionVersion` | `apps/arena/models.py` | Immutable published question version, `question_type`, `primary_competency`, `content_payload`, `explanation`. | Eligibility for evaluation; competency source. |
| `QuestionEvaluationData` | same | `OneToOne(QuestionVersion)`: `grading_strategy` (`EXACT_MATCH`, `SET_MATCH`, `NUMERIC_TOLERANCE`, `NORMALIZED_STRING`, `REGEX_MATCH`, `STDOUT_MATCH`), `correct_payload`, `scoring_rubric`; immutable after publication. | Criteria source; must be snapshotted into results. |
| `QuestionCompetencyMapping` | same | Primary + secondary competencies, weight `0.05..1.00`; immutable after publication. | Secondary evidence mapping. |
| `Domain / Subdomain / Competency` | `apps/skills/models.py` | 3-tier taxonomy; immutable codes. | Evidence targets. |
| `UserCompetencyMastery` | same | Unique `(user, competency)`, `mastery_score 0..100`, `evaluations_count`, `last_assessed_at`. | Projection target. |
| `UserDomainMastery` | same | Unique `(user, domain)`, `mastery_score 0..100`, `confidence_tier`, `total_assessments_completed`, `last_assessed_at`. | Projection target. |
| `PrerequisiteService` | `apps/skills/services.py` | DAG validation for prerequisites. | Unlock logic reads mastery only; no write path today. |
| Assessment API | `apps/assessments/views.py`, `urls.py` | Catalog, start, detail, submit, navigate, current question, answer, skip. | No result endpoint exists. |
| Error envelope | `apps/assessments/exceptions.py`, `apps/core/exceptions.py` | Domain exception → `{error: {code, message, details}}`. | New evaluation exceptions reuse the mapper. |

### 2.2 Current attempt lifecycle (verified)

```
start_or_resume_attempt
  ├─ lock Assessment (FOR SHARE)
  ├─ idempotency replay by (user, assessment, idempotency_key)
  ├─ lock AssessmentVersion (FOR SHARE), require PUBLISHED
  ├─ reject if ActiveAssessmentReservation exists and not expired
  ├─ read pinned AssessmentVersionQuestion rows
  ├─ FOR SHARE locks on canonical Question and QuestionVersion rows
  ├─ compute attempt_number = max + 1
  ├─ create Attempt + ActiveAssessmentReservation (savepoint)
  ├─ create AttemptQuestion rows (sanitize payload, random.shuffle(options))
  └─ append ATTEMPT_STARTED

answer / skip / navigate
  ├─ select_for_update(Attempt)
  ├─ deadline check → EXPIRED + 410
  ├─ answer: type validation → get_or_create AttemptAnswer (overwrite allowed)
  │           → recompute answer_count → optional auto-advance → ANSWER_SUBMITTED
  └─ skip:   log QUESTION_SKIPPED only (answer row untouched)

submit_attempt
  ├─ select_for_update(Attempt)
  ├─ if deadline passed → EXPIRED, delete reservation, ATTEMPT_EXPIRED, raise 410
  └─ else → SUBMITTED, completed_at, delete reservation, ATTEMPT_SUBMITTED
             *** no evaluation, no result ***
```

### 2.3 Invariants Phase 2E must not break

1. `[IMPLEMENTED]` Published `AssessmentVersion` and `QuestionVersion` rows are immutable; only lifecycle status may change.
2. `[IMPLEMENTED]` An attempt always references exactly one `AssessmentVersion` and one `QuestionVersion` per question; `on_delete=PROTECT` prevents deletion.
3. `[IMPLEMENTED]` Exactly one active attempt per `(user, assessment)` via an unconditional unique reservation row (no partial indexes — deliberate MySQL 8.4 portability).
4. `[IMPLEMENTED]` Attempt creation is idempotent per `(user, assessment, idempotency_key)` and returns the existing attempt rather than creating a duplicate.
5. `[IMPLEMENTED]` Terminal attempts reject further answer/navigation mutation at the service layer.
6. `[IMPLEMENTED]` Candidate payloads never include answer keys, rubrics, explanations, points, or competency mappings.
7. `[IMPLEMENTED]` All lifecycle mutations use row locks and the `with_deadlock_retry` decorator; deadlock → retry, lock timeout → 503.

### 2.4 Gaps that block scoring

| # | Gap | Impact | Design response |
|---|---|---|---|
| G1 | No result or evaluation model | Submission produces no outcome | `[PROPOSED]` `AttemptEvaluation`, `QuestionEvaluation` |
| G2 | No scoring policy versioning | Future policy changes would silently alter history | `[PROPOSED]` `ScoringPolicy` + activation pointer + snapshot |
| G3 | `QuestionEvaluationData` not snapshotted into the attempt | Result depends on live rows | `[PROPOSED]` criteria/rubric/mapping snapshots inside result |
| G4 | Unanswered vs skipped indistinguishable | Cannot apply distinct treatment | `[APPROVAL]` treatment; `[PROPOSED]` persisted skip marker |
| G5 | Answer overwrite history lost | Cannot audit pre-submission edits | `[PROPOSED]` digest in `ANSWER_SUBMITTED` event (later), input digest in result |
| G6 | `AttemptAnswer` has no terminal-state guard at model level | Admin/ORM writes after submission possible | `[PROPOSED]` model-level guard + append-only result rows |
| G7 | No mastery write service or formula | Mastery models are dead data | `[APPROVAL]` formula; `[PROPOSED]` evidence ledger + deterministic projection |
| G8 | No XP infrastructure | Rewards cannot be audited | `[PROPOSED]` separate ledger app |
| G9 | Expiry/cancel produce no outcome | Terminal attempts without results | `[APPROVAL]` whether expired attempts are graded |
| G10 | No eligibility check that `correct_payload` matches `content_payload` option IDs | Authoring can create ungradeable questions | `[PROPOSED]` publication-time validation (Phase 2E.2) |

---

## 3. Question evaluation design

### 3.1 Inputs available to an evaluator

Per attempt question, the evaluator receives (all from frozen or immutable sources):

| Input | Source | Frozen? |
|---|---|---|
| `question_type` | `AttemptQuestion.question_type_snapshot` | Yes |
| presentation `content_payload` | `AttemptQuestion.content_payload_snapshot` (sanitized, options shuffled) | Yes |
| candidate answer | `AttemptAnswer.answer_payload` | At evaluation time only |
| grading strategy | `QuestionEvaluationData.grading_strategy` | Immutable after publish, **not** frozen in attempt |
| correct criteria | `QuestionEvaluationData.correct_payload` | Immutable after publish, **not** frozen |
| rubric | `QuestionEvaluationData.scoring_rubric` | Immutable after publish, **not** frozen |
| competency mappings | `QuestionVersion.primary_competency`, `QuestionCompetencyMapping` | Immutable after publish, **not** frozen |
| question weight | `AttemptQuestion.weight` | Yes |
| scoring policy | `[PROPOSED]` `ScoringPolicy` | Yes, via FK snapshot |

`[PROPOSED]` The evaluator must consume only snapshotted values. Reading live `QuestionEvaluationData` is acceptable only to *build* the snapshot, inside the same transaction.

### 3.2 Evaluator contract

`[PROPOSED]` Pure, side-effect-free functions registered by `(question_type, grading_strategy)`:

```python
@dataclass(frozen=True)
class EvaluationInput:
    question_type: str
    grading_strategy: str
    criteria: dict           # QuestionEvaluationData.correct_payload snapshot
    rubric: dict             # QuestionEvaluationData.scoring_rubric snapshot
    content_payload: dict    # AttemptQuestion.content_payload_snapshot
    answer: dict | None      # AttemptAnswer.answer_payload
    max_weight: Decimal
    policy: ScoringRules     # snapshot of scoring policy JSON

@dataclass(frozen=True)
class EvaluationOutcome:
    outcome: str             # CORRECT | INCORRECT | PARTIAL | UNANSWERED |
                             # SKIPPED | INVALID | PENDING_REVIEW | ERROR
    awarded_weight: Decimal
    score_fraction: Decimal
    detail: dict             # machine-readable rationale, never candidate-facing
    requires_review: bool
    evaluator: str
    evaluator_version: str
```

Rules:

- An evaluator never raises for bad candidate data; it returns `INVALID` with a detail code.
- An evaluator never raises for bad *question* configuration; it returns `ERROR` with a configuration code. Silent zero is forbidden.
- Unknown `(type, strategy)` pairs return `ERROR` and are excluded from release gating until mapped.
- All comparisons are on **option IDs**, never positional indices, because `AttemptQuestion` options are shuffled at attempt creation.
- Boolean/numeric canonicalisation must reuse one shared helper so validation and evaluation cannot drift; the helper is versioned and recorded in `evaluator_version`.

### 3.3 Strategy matrix

| Question type | Objective evaluation | Current modelled strategy | Verdict |
|---|---|---|---|
| `SINGLE_CHOICE` | **Yes** | `EXACT_MATCH` | `[PROPOSED]` compare `selected_option_id` to one correct ID. |
| `MULTIPLE_CHOICE` | **Yes, all-or-nothing only** | `SET_MATCH` | `[PROPOSED]` exact set equality. Any partial-credit rule is `[APPROVAL]`. |
| `TRUE_FALSE` | **Yes, after canonicalisation** | `EXACT_MATCH` | `[PROPOSED]` normalise `bool / 'TRUE' / 'T' / '1'` then compare. |
| `NUMERICAL` | **Conditional** | `NUMERIC_TOLERANCE` | `[APPROVAL]` tolerance must be authored; no tolerance is invented. |
| `SHORT_TEXT` | **No, not yet** | `NORMALIZED_STRING`, `REGEX_MATCH` | `[APPROVAL]` accepted-answer schema and normalisation rules are undefined. |
| `CODE_OUTPUT` | **Conditional** | `STDOUT_MATCH` | `[APPROVAL]` string normalisation; no code execution exists or is proposed. |

### 3.4 Per-type specification

#### SINGLE_CHOICE — objective `[IMPLEMENTED input / PROPOSED evaluator]`

- Expected criteria shape: a single correct option identifier (`correct_option_id` is already a reserved confidential key in `apps/arena/models.py`).
- Answer shape (validated today): `{"selected_option_id": <id>}`.
- Evaluation: `CORRECT` if `str(selected) == str(correct)`, else `INCORRECT`.
- Configuration errors: missing key, more than one correct option, or correct ID absent from `content_payload.options` → `ERROR` (`CRITERIA_INVALID`).
- Partial credit: not applicable.

#### MULTIPLE_CHOICE — objective, all-or-nothing `[PROPOSED]`

- Criteria shape: `{"correct_option_ids": [...]}` (reserved key already exists).
- Answer shape: `{"selected_option_ids": [...]}`; empty selections are rejected at submission today.
- Evaluation: exact set equality (order-insensitive, duplicate-insensitive after a documented canonicalisation) → `CORRECT`; otherwise `INCORRECT`.
- Partial credit: `[APPROVAL]`. If approved later, the formula must live in `scoring_rubric` and be versioned in the result; it must not become a global constant.
- Configuration error: duplicate correct IDs, empty correct set, or IDs absent from the presentation payload.

#### TRUE_FALSE — objective `[PROPOSED]`

- Criteria shape: `{"correct_value": true|false}`.
- Answer shape: `{"selected_value": bool | 'TRUE' | 'FALSE' | 'T' | 'F' | '1' | '0'}` (already accepted by `validate_answer_payload_for_type`).
- Evaluation: canonicalise with the same helper used at submission, then compare.
- Risk: the current validator also accepts an option ID stored in `selected_value` for option-based true/false questions. The evaluator must accept both shapes or the validator must be tightened; this is an engineering decision for Phase 2E.2, not a product decision.

#### NUMERICAL — conditional `[APPROVAL]`

- Criteria shape: `{"target_value": "<decimal string>"}`.
- Required rubric keys (none exist today): tolerance magnitude and tolerance mode (`ABSOLUTE` / `RELATIVE`), or an explicit "exact" declaration.
- `[APPROVAL]` Whether equality without an authored tolerance is allowed, and what default tolerance (if any) applies. **This document intentionally proposes no number.**
- Missing/invalid tolerance → `ERROR` (`TOLERANCE_NOT_CONFIGURED`) unless product explicitly approves a fallback.
- Parsing must use `Decimal`, never `float`.

#### SHORT_TEXT — requires a separately approved mechanism `[APPROVAL]`

Three viable mechanisms, all needing product sign-off:

1. Normalised exact match against a set of accepted answers. Requires approved normalisation rules (case, Unicode, whitespace, punctuation, accent handling, numeric words) and an accepted-answer schema in `scoring_rubric`.
2. Regex match. Requires an approved authoring guide and catastrophic-backtracking protection.
3. Manual review queue. Requires reviewer roles, SLA, and a `PENDING_REVIEW` lifecycle.

Until approved: `SHORT_TEXT` questions may exist in the bank, but assessments containing them must be flagged as non-auto-gradable. The evaluation service must return `PENDING_REVIEW`, never guess.

#### CODE_OUTPUT — conditional `[APPROVAL]`

- Today the answer shape is a **string** (`{"output": "..."}` or `{"text": "..."}`), i.e. the candidate predicts program output. This is comparable with `STDOUT_MATCH`.
- `[APPROVAL]` Normalisation rules for output comparison (trailing newline, trailing whitespace, tabs, line endings, case sensitivity).
- **No code execution, sandbox, container, or compiler is proposed or assumed.** If ZENTIQ later wants to execute candidate code, that is a separate infrastructure programme with its own security review and is explicitly out of scope for Phase 2E.

### 3.5 Outcome vocabulary

`[PROPOSED]`

| Outcome | Meaning | Score |
|---|---|---|
| `CORRECT` | Fully correct per policy | Full weight |
| `PARTIAL` | Partially correct per approved policy | Policy-defined |
| `INCORRECT` | Answered and wrong | 0 (or penalty if approved) |
| `UNANSWERED` | No answer row, or `is_answered = False` | `[APPROVAL]` default 0 |
| `SKIPPED` | Explicit skip event and no answer | `[APPROVAL]` default 0 |
| `INVALID` | Stored answer violates the evaluator contract | 0, flagged for audit |
| `PENDING_REVIEW` | Needs a human or an unapproved mechanism | Held, blocks finalisation |
| `ERROR` | Question configuration is ungradeable | Assessment evaluation fails loudly |

### 3.6 Manual review mechanism `[APPROVAL]`

If approved, it is a separate bounded workflow:

- `QuestionEvaluation.requires_review = True`, evaluation stays `PENDING`.
- Reviewer permission (new, e.g. `evaluation.review_questionevaluation`), author cannot review own attempt.
- Every decision produces an `EvaluationEvent` with actor, reason, and prior outcome.
- The final assessment result cannot be `COMPLETED` while any question is `PENDING_REVIEW`.

This document does not design reviewer SLAs or queues; those are product operations.

---

## 4. Scoring model

### 4.1 Already implemented vs proposed

| Aspect | `[IMPLEMENTED]` today | `[PROPOSED]` |
|---|---|---|
| Per-question weight | `AssessmentVersionQuestion.weight Decimal(5,2) >= 0.01`, frozen into `AttemptQuestion.weight` | Weight is a relative multiplier; per-question contribution = `weight × score_fraction` |
| Per-question score | None | `awarded_weight`, `max_weight`, `score_fraction` stored per question |
| Assessment score | None | `score_percentage` in `[0, 100]`, plus unrounded value |
| Passing threshold | None | `[APPROVAL]`; field nullable until approved |
| Partial credit | None | `[APPROVAL]`; default policy is all-or-nothing |
| Unanswered/skipped | Not distinguishable; both simply absent from `answer_count` | Persisted outcome per question; treatment `[APPROVAL]` |
| Rounding | N/A | Policy-controlled; raw values stored unrounded |
| Negative marking | Not present | `[APPROVAL]`; default disallowed |
| Scoring policy version | None | `ScoringPolicy` row pinned by every result |

### 4.2 Per-question scoring

`[PROPOSED]`

```
max_weight_i     = AttemptQuestion.weight
score_fraction_i = awarded_weight_i / max_weight_i     # [0,1] unless penalties approved
awarded_weight_i = score_fraction_i × max_weight_i
```

- `score_fraction` is stored at 6 decimal places; `awarded_weight` at 4.
- Division by zero is impossible while `weight >= 0.01` is enforced by model and check constraint.
- `PARTIAL` fractions come only from an approved rubric; the evaluator must not invent one.

### 4.3 Question weights

`[PROPOSED]` Weight is a **relative multiplier**, not a point value:

- Assessment percentage is normalised: `100 × Σ(weight_i × fraction_i) / Σ(weight_i)`.
- The denominator includes every question in the attempt, including unanswered and skipped ones (see 4.5).
- Per-question "points" are a presentation concern. Exposing them requires `[APPROVAL]` because it changes the client contract and candidate perception of equal-weight questions.
- Weights are frozen at attempt creation, so editing a draft assessment after an attempt cannot change its score.

Current constraints to preserve: `weight > 0`, two-decimal precision, `Decimal` only (booleans and NaN rejected by `normalize_question_weight`).

### 4.4 Assessment-level aggregation

`[PROPOSED]` Single aggregation mode for v1:

```
score_percentage_raw = 100 × Σ awarded_weight / Σ max_weight
```

`[APPROVAL]` Alternatives that must be explicitly chosen if desired:

- Exclude unanswered/skipped from the denominator (rewards skipping).
- Sectioned aggregation (does not exist in the schema; would require a new composition model).
- Difficulty-weighted or time-decay scoring (mentioned as a provisional target in `docs/architecture.md`; no rule exists and none is proposed here).
- Bonus/penalty modifiers, streaks, or speed bonuses — all out of scope.

`Σ max_weight == 0` must fail evaluation with `ASSESSMENT_NO_WEIGHT` rather than produce `NaN` or `0`.

### 4.5 Unanswered and skipped treatment

`[IMPLEMENTED]` facts:

- No answer row, or `is_answered = False`, means unanswered.
- `skip_question` writes a `QUESTION_SKIPPED` event, does not create an answer, and leaves a previously stored answer intact.
- Therefore a question can be "answered then skipped"; today the answer still counts.

`[PROPOSED]` data model: add an explicit per-question outcome on the evaluation (not on `AttemptQuestion`), derived as:

```
if answer exists and is_answered:      evaluate answer
elif QUESTION_SKIPPED event exists:    SKIPPED
else:                                  UNANSWERED
```

`[APPROVAL]` decisions:

1. Does an answered-then-skipped question count as answered or skipped? Recommendation: **answered wins**; skip is informational only when an answer exists, because answers are deliberate submissions and skip does not delete data.
2. Is a skipped question scored as zero, excluded from the denominator, or penalised?
3. Does an unanswered question count as incorrect for mastery evidence?

Recommended default (approval required): both score zero and remain in the denominator; neither produces correctness evidence.

### 4.6 Partial credit policy

`[APPROVAL]` Nothing exists today. The proposal:

- Policy enum: `NONE` (default, exact match), `PROPORTIONAL`, `PENALTY`, `THRESHOLD` — all but `NONE` require a written rule with worked examples.
- Rule storage: `QuestionEvaluationData.scoring_rubric` for question-level rules; `ScoringPolicy.rules` for global defaults.
- Precedence: question rubric overrides policy default; the resolved rule is snapshotted into `QuestionEvaluation`.
- No penalty may reduce `awarded_weight` below zero unless negative marking is separately approved.

### 4.7 Score precision and rounding

`[PROPOSED]`

| Quantity | Storage | Notes |
|---|---|---|
| `awarded_weight`, `max_weight` | `Decimal(max_digits=12, decimal_places=4)` | Aggregation only, never display |
| `score_percentage_raw` | `Decimal(max_digits=9, decimal_places=6)` | Authoritative unrounded |
| `score_percentage` | `Decimal(max_digits=5, decimal_places=2)` | Display/contract value, clamped 0..100 |
| `score_fraction` | `Decimal(max_digits=9, decimal_places=6)` | Per question |

- Round only once, at the display boundary; never round intermediates.
- `[APPROVAL]` Rounding mode: recommendation `ROUND_HALF_UP` (Django `Decimal` default context is half-even, so this must be explicit). Mode is stored in the policy snapshot.
- `[APPROVAL]` Display precision (2 dp assumed) and whether the API returns the raw value.

### 4.8 Maximum and minimum score boundaries

`[PROPOSED]`

- Database check: `0.00 <= score_percentage <= 100.00` (consistent with existing mastery fields).
- Raw percentage check: `0 <= score_percentage_raw <= 100` unless negative marking is approved, in which case a documented floor applies.
- Clamp defensively at write time; a negative or >100 result indicates an evaluator bug and must also emit `EVALUATION_ANOMALY`.
- No passing score, grade band, percentile, or rank is proposed. `is_passed` stays `NULL` until product supplies a threshold.

---

## 5. Historical result integrity

### 5.1 Invariants

`[PROPOSED]`

1. A result is **created once** and never updated in place.
2. Every result pins the exact `AssessmentVersion`, every `QuestionVersion`, and every `QuestionEvaluation`.
3. Every result pins the `ScoringPolicy` version and evaluator version used.
4. Every result stores the exact answer payloads and the criteria/rubric/mappings that were applied.
5. Replaying a stored result with stored inputs reproduces the same outcome bit-for-bit.
6. Corrections are append-only revisions that supersede, never overwrite.
7. Any change to a future question, rubric, weight, mastery formula, or policy leaves historical rows untouched.
8. `AttemptEvaluation` and `QuestionEvaluation` reject ORM `update()`/`delete()` after completion, using the same guard style as `AttemptEvent`.

### 5.2 Proposed models

All new tables live in a new app `apps.evaluation` (rationale in §9.1).

#### `ScoringPolicy`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `code` | CharField(50) | e.g. `DEFAULT_ASSESSMENT_SCORING` |
| `version` | PositiveInteger | monotonic per code |
| `name`, `description` | Char/Text | |
| `status` | `DRAFT / ACTIVE / RETIRED` | new rows must be `DRAFT` |
| `rules` | JSON | schema in §4; validated by a service, not free-form |
| `rules_schema_version` | CharField(20) | |
| `created_by` | FK user, SET_NULL | |
| `activated_at`, `created_at`, `updated_at` | DateTime | |

Constraints: `Unique(code, version)`, check `version > 0`, check status in enum. Immutable after `ACTIVE` except transition to `RETIRED`.

#### `ActiveScoringPolicy` (activation pointer)

`code` (unique), `policy` (OneToOne), `created_at`. Mirrors `ActiveAssessmentReservation` so "one ACTIVE policy per code" is enforced without partial indexes.

#### `AttemptEvaluation`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `attempt` | FK `AssessmentAttempt`, `PROTECT` | |
| `revision` | PositiveInteger default 1 | |
| `supersedes` | OneToOne self, null | set only when a correction recomputes |
| `assessment_version` | FK `AssessmentVersion`, `PROTECT` | redundant but pinned |
| `scoring_policy` | FK `ScoringPolicy`, `PROTECT` | |
| `evaluator_version` | CharField(40) | engine version, e.g. `zentiq-eval/1` |
| `status` | `PENDING / COMPLETED / FAILED / SUPERSEDED` | |
| `question_count` | PositiveInteger | |
| `correct_count`, `incorrect_count`, `partial_count`, `unanswered_count`, `skipped_count`, `pending_review_count` | PositiveInteger | summary only |
| `earned_weight` | Decimal(12,4) | |
| `max_weight` | Decimal(12,4) | |
| `score_percentage_raw` | Decimal(9,6) | |
| `score_percentage` | Decimal(5,2) | |
| `is_passed` | Boolean null | approval pending |
| `input_digest` | CharField(64) | SHA-256 of canonical inputs |
| `result_snapshot` | JSON | full reproducibility payload |
| `failure_code`, `failure_message` | Char/Text | when `FAILED` |
| `evaluated_at`, `created_at` | DateTime | |

Constraints: `Unique(attempt, revision)`, check `max_weight > 0`, check counters `>= 0`, check `score_percentage` range, check status enum.

#### `ActiveAttemptEvaluation` (current-result pointer)

`attempt` (unique OneToOne), `evaluation` (OneToOne), `created_at`. Guarantees exactly one current result per attempt without partial unique indexes. When a revision supersedes, the pointer row is updated in the same transaction as the status change, and the old row becomes `SUPERSEDED`.

#### `QuestionEvaluation`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `attempt_evaluation` | FK CASCADE | |
| `attempt_question` | OneToOne `AttemptQuestion`, `PROTECT` | |
| `question_version` | FK `QuestionVersion`, `PROTECT` | |
| `order_index` | PositiveInteger | snapshot |
| `question_type`, `grading_strategy` | CharField | snapshot |
| `criteria_snapshot`, `rubric_snapshot` | JSON | exact applied rules |
| `criteria_digest` | CharField(64) | tamper detection |
| `competency_mappings_snapshot` | JSON | `[{competency_id, code, weight, is_primary}]` |
| `answer_snapshot` | JSON null | exact candidate payload |
| `answer_digest` | CharField(64) | |
| `outcome` | CharField | §3.5 |
| `awarded_weight` | Decimal(12,4) | |
| `max_weight` | Decimal(12,4) | |
| `score_fraction` | Decimal(9,6) | |
| `detail` | JSON | machine rationale (not candidate-facing) |
| `evaluator`, `evaluator_version` | CharField | |
| `requires_review`, `reviewed_by`, `reviewed_at` | Bool / FK null / DateTime null | |
| `created_at` | DateTime | |

Constraints: `Unique(attempt_evaluation, attempt_question)`, check `max_weight > 0`, check `awarded_weight >= 0` (unless penalties approved), check `score_fraction` range, check outcome enum. Indexes: `(attempt_evaluation, order_index)`, `(question_version)`, `(outcome)`.

#### `CompetencyEvidence`

`attempt_evaluation` FK, `competency` FK PROTECT, `is_primary`, `mapping_weight Decimal(4,2)`, `awarded_weight`, `max_weight`, `evidence_fraction`, `question_count`, `created_at`.
Constraint: `Unique(attempt_evaluation, competency)`.

#### `EvaluationEvent`

`attempt_evaluation` FK PROTECT, `event_type`, `payload` JSON, `created_at`. Append-only QuerySet and instance guards copied from `AttemptEvent`. Event types: `EVALUATION_STARTED`, `EVALUATION_COMPLETED`, `EVALUATION_FAILED`, `EVALUATION_SUPERSEDED`, `REVIEW_DECIDED`, `XP_AWARDED`, `XP_SKIPPED`.

### 5.3 What the snapshot must contain

`result_snapshot` (JSON) is the self-contained record:

```json
{
  "schema_version": "1",
  "evaluator_version": "zentiq-eval/1",
  "attempt": {"id": "...", "attempt_number": 3, "status": "SUBMITTED"},
  "assessment": {"id": "...", "code": "ASM-...", "version_id": "...", "version_number": 2},
  "scoring_policy": {"code": "...", "version": 1, "rules": {...}},
  "questions": [
    {
      "order_index": 1,
      "attempt_question_id": "...",
      "question_version_id": "...",
      "question_type": "SINGLE_CHOICE",
      "grading_strategy": "EXACT_MATCH",
      "weight": "2.00",
      "criteria": {"correct_option_id": "opt_b"},
      "rubric": {},
      "competencies": [{"competency_id": "...", "code": "NUM-ARITH-01", "weight": "1.00", "is_primary": true}],
      "answer": {"selected_option_id": "opt_b"},
      "outcome": "CORRECT",
      "awarded_weight": "2.0000",
      "score_fraction": "1.000000",
      "detail": {"matched_option_id": "opt_b"}
    }
  ],
  "aggregate": {
    "earned_weight": "7.0000",
    "max_weight": "10.0000",
    "score_percentage_raw": "70.000000",
    "score_percentage": "70.00",
    "counts": {"correct": 3, "incorrect": 1, "unanswered": 1, "skipped": 0}
  }
}
```

Notes:

- Decimals are serialised as **strings** to avoid binary-float drift across replays.
- Canonical JSON: `sort_keys=True`, `separators=(',', ':')`, UTF-8, `ensure_ascii=False`.
- `input_digest = sha256(canonical_json({attempt_id, assessment_version_id, scoring_policy_id, questions:[{attempt_question_id, question_version_id, answer_snapshot, criteria_digest}]}))`.
- The snapshot intentionally duplicates `QuestionEvaluation` rows: defence in depth, and it lets an auditor reproduce without joining mutable tables.

### 5.4 Reproducibility procedure

`[PROPOSED]` A read-only management command / service `replay_attempt_evaluation(evaluation_id)`:

1. Load the `AttemptEvaluation` and its snapshot.
2. Recompute `input_digest` from the stored snapshots; mismatch → `INTEGRITY_VIOLATION`.
3. Re-run each evaluator with `criteria_snapshot`, `rubric_snapshot`, `answer_snapshot`, `policy.rules`, and the stored `max_weight`.
4. Compare each `outcome`, `awarded_weight`, `score_fraction`; any difference → report.
5. Recompute aggregates and compare with stored values at 6 dp.
6. Perform **no writes** and require no access to `QuestionEvaluationData` or the current scoring policy.

Because the evaluators are pure and versioned, a future change to a question, rubric, weight, or policy cannot affect this procedure.

### 5.5 Corrections and recomputation

`[PROPOSED]`

- **Discretionary adjustment** (e.g. accepted appeal): append an `EvaluationAdjustment` row (`attempt_evaluation`, `delta_weight`, `reason`, `actor`, `approved_by`, `created_at`, append-only), unique per `(attempt_evaluation, reason_code)` if needed. Effective score = base + Σ adjustments, computed at read time and stored in the API response as `adjusted_score_percentage`. Base rows never change. `[APPROVAL]` whether adjustments are allowed and who approves them.
- **Defect recomputation** (evaluator bug): create a new `AttemptEvaluation` with `revision = previous + 1`, `supersedes = previous`, `status = COMPLETED`; set previous to `SUPERSEDED`; update `ActiveAttemptEvaluation`. Requires staff permission, a mandatory reason, and an `EvaluationEvent`. Historical revision remains queryable.
- **No in-place edit** is ever permitted, including by Django admin. Admin exposes result rows as read-only.

`[APPROVAL]` Retention period for superseded revisions and whether candidate-visible history shows only the current revision.

---

## 6. Competency evidence and mastery

### 6.1 Existing taxonomy facts

`[IMPLEMENTED]`

- `Domain → Subdomain → Competency`, codes immutable, `is_active` flags.
- `QuestionVersion.primary_competency` is mandatory and protected.
- `QuestionCompetencyMapping` adds weighted secondaries (0.05–1.00) and requires exactly one primary mapping per question version; immutable after publication.
- `UserCompetencyMastery`: unique per `(user, competency)`, `mastery_score Decimal(5,2)` 0–100, `evaluations_count`, `last_assessed_at`.
- `UserDomainMastery`: unique per `(user, domain)`, `mastery_score Decimal(5,2)` 0–100, `confidence_tier` (`UNASSESSED / CALIBRATING / DEVELOPING / PROFICIENT / MASTERY`), `total_assessments_completed`, `last_assessed_at`.
- `SkillPrerequisite.min_mastery_percentage` defaults to `70.00`, but no code consumes it for unlocking.
- Nothing writes either mastery table.

### 6.2 Mapping evaluated outcomes to competencies

`[PROPOSED]`

1. For each `QuestionEvaluation`, read the snapshot of `primary_competency` and `QuestionCompetencyMapping` rows (captured at evaluation time from immutable published data).
2. Multipliers:
   - Primary mapping contributes with its mapping weight (default `1.00`).
   - Secondary mappings contribute with their `0.05..1.00` weight.
3. Only **answered and objectively evaluated** questions produce evidence. `UNANSWERED`, `SKIPPED`, `PENDING_REVIEW`, and `ERROR` produce no evidence by default `[APPROVAL]`.
4. Per competency per attempt:

```
evidence_weight_c    = Σ (mapping_weight_q × max_weight_q)      for questions mapped to c
evidence_earned_c    = Σ (mapping_weight_q × awarded_weight_q)   for questions mapped to c
evidence_fraction_c  = evidence_earned_c / evidence_weight_c
```

5. Store one `CompetencyEvidence` row per competency per evaluation. This is the auditable link between performance and mastery; the mastery tables become derived caches.

`[PROPOSED]` Auto-generation: whenever `AttemptEvaluation` becomes `COMPLETED`, evidence generation runs in the same transaction. On supersession, evidence rows belong to the superseded evaluation and are not edited; the projection reads the current evaluation only.

### 6.3 Updating `UserCompetencyMastery`

The formula is not defined anywhere. `[APPROVAL]` Options to put to product:

| Option | Description | Consequences |
|---|---|---|
| A. Cumulative weighted average | `mastery = Σ earned / Σ possible` over all evidence ever | Stable, order-independent, never decays, slow to react |
| B. Exponential moving average | `mastery = α × new + (1-α) × old` | Responsive; requires α, seeding rule, and ordering; "recency" policy needed |
| C. Windowed average | Last N evaluations or last N days | Requires N and a definition of a "session" |
| D. Best-evidence | Highest evidence fraction per competency | Rewards peaks, ignores inconsistency |
| E. Prerequisite-aware | Weighted by Bloom/difficulty or prerequisite depth | Requires additional approved weighting scheme |

Recommendation to product: **A** for v1 (deterministic, replayable, no arbitrary constants), with **B** explicitly deferred. This document does not pick α or any threshold.

`[APPROVED]`-independent mechanics `[PROPOSED]`:

- `evaluations_count` increments by the number of evidence-bearing questions for that competency in the attempt, not by 1.
- `last_assessed_at = evaluation.evaluated_at`.
- `mastery_score` is clamped to `[0, 100]` and stored at 2 dp, matching existing validators.
- Row is created on first evidence with `0.00` then updated, inside `select_for_update` on `(user, competency)`.

### 6.4 Updating `UserDomainMastery`

`[IMPLEMENTED]` The model exists but defines no relationship to competency scores beyond the FK hierarchy.

`[APPROVAL]` Required decisions:

1. Aggregation of competency mastery into a domain: equal-weight mean, evidence-weighted mean, or subdomain-then-domain two-level mean.
2. Whether inactive competencies or competencies with zero evidence are included.
3. `total_assessments_completed`: increment per completed assessment, or per distinct assessment series, or per domain-touching attempt.
4. `confidence_tier` thresholds. The enum exists; no numeric cutoffs do. Nothing may be hardcoded until approved.
5. Whether domain mastery is recomputed from evidence (recommended, deterministic) or incrementally updated.

### 6.5 Idempotency and correctness of mastery updates

`[PROPOSED]` Prefer **derived projection over incremental mutation**:

- `MasteryProjection` audit row per run: `user`, `trigger_evaluation`, `formula_code`, `formula_version`, `status`, `started_at`, `completed_at`, `evidence_digest`.
- Unique `(user, trigger_evaluation)` prevents double application.
- Projection recomputes the user's competency mastery from `CompetencyEvidence` joined to current, non-superseded evaluations, in a deterministic order (`evaluated_at`, `evaluation_id`).
- If a formula requires order (EMA), the order is explicit and versioned; replay of the same evidence set always yields the same value.
- A management command `recompute_user_mastery` supports repair after a defect without hand-editing scores.
- `[APPROVAL]` Whether mastery may decrease, and how that is communicated to candidates.

### 6.6 Prerequisite unlocking

`[IMPLEMENTED]` `SkillPrerequisite` exists; no consumer.
`[APPROVAL]` Whether mastery thresholds unlock assessments/missions, and whether the existing `70.00` default is meaningful or merely a placeholder. Phase 2E should not implement unlocking.

---

## 7. XP and gamification

### 7.1 Principles

`[PROPOSED]` and consistent with `docs/architecture.md` §6:

1. XP is **not** equal to assessment score. Score is a performance measure; XP is a reward decision.
2. XP is append-only. Balances are derived from the ledger and cached in a locked account row.
3. Every award is idempotent at the database level.
4. Every award records the rule, rule version, source entity, and the inputs used.
5. No candidate-supplied XP value is ever accepted.
6. Reversals are new entries, never deletions or updates.

### 7.2 Proposed models (`apps.gamification`)

#### `XpRule`

`code`, `version`, `status (DRAFT/ACTIVE/RETIRED)`, `source_type (ASSESSMENT_COMPLETION/... )`, `award_type (FIXED/FORMULA)`, `amount` (nullable integer), `formula` JSON, `conditions` JSON, `created_by`, `activated_at`, `created_at`.
`Unique(code, version)`; immutable after activation. An `ActiveXpRule` pointer enforces one active version per code, same pattern as scoring policy.
`[APPROVAL]` All rule content. No amount, multiplier, or condition is proposed.

#### `XpAccount`

`user` OneToOne, `balance` BigInteger, `updated_at`. Check `balance >= 0` unless negative balances are approved. Locked with `select_for_update()` for every award.

#### `XpLedgerEntry` (append-only)

| Field | Notes |
|---|---|
| `id` UUID | |
| `user` FK PROTECT | |
| `amount` BigInteger | signed, non-zero |
| `balance_after` BigInteger | under account lock |
| `source_type` CharField | `ASSESSMENT_COMPLETION`, `RETRY_BONUS`, `MANUAL_ADJUSTMENT`, ... |
| `source_id` UUID/CharField | attempt id, evaluation id, etc. |
| `attempt_evaluation` FK null PROTECT | lineage for assessment awards |
| `rule` FK PROTECT | exact rule row |
| `rule_version` CharField | snapshot for audit |
| `idempotency_key` CharField(64) unique | deterministic: `xp:{source_type}:{source_id}:{rule_code}:{rule_version}` |
| `reverses` OneToOne self null | unique, prevents double reversal |
| `reason` Text | required for manual entries |
| `created_by` FK null | null for system awards |
| `created_at` DateTime | |

Constraints: `Unique(user, source_type, source_id, rule)`; unique `idempotency_key`; unique `reverses`; check `amount != 0`.
Guards: `update()`/`delete()` rejected on QuerySet and instance, exactly like `AttemptEvent`.

### 7.3 Award pipeline

`[PROPOSED]`

```
AttemptEvaluation COMPLETED
  → load ACTIVE XpRules for source_type=ASSESSMENT_COMPLETION
  → resolve eligibility conditions against the immutable result snapshot
  → for each eligible rule:
        idempotency_key = xp:{source_type}:{evaluation_id}:{rule.code}:{rule.version}
        transaction.atomic():
            lock XpAccount (select_for_update)
            if entry with key exists: return existing   # idempotent
            new_balance = balance + amount
            insert ledger entry (balance_after=new_balance)
            update account balance
  → append EvaluationEvent XP_AWARDED / XP_SKIPPED with reason
```

- Awards run **after** the evaluation transaction commits, in their own transaction, because XP rules may be disabled and a rule failure must not roll back a valid result.
- If XP is enabled and the award fails, the result remains valid; a retry job/command reconciles by idempotency key.
- `[APPROVAL]` whether awards are synchronous with submission or asynchronous.

### 7.4 Idempotency and duplicate prevention

Three independent layers:

1. Unique `idempotency_key` at the database.
2. `get_or_create`/pre-check inside the account lock.
3. Unique `(user, source_type, source_id, rule)` as a semantic guard.

A duplicate HTTP submission cannot produce duplicate XP because `submit_attempt` already rejects terminal attempts and evaluation is unique per `(attempt, revision)`.

### 7.5 Assessment retakes

`[IMPLEMENTED]` `attempt_number` is sequential per `(user, assessment)`; the active reservation prevents parallel attempts; nothing limits the number of retakes.

`[APPROVAL]` XP policy for retakes. Options:

- Award only on the first completed attempt.
- Award on every attempt (source_id = attempt id) up to a cap.
- Award only when the new score exceeds the previous best.
- Award a fixed smaller "practice" amount after the first attempt.
- No XP for retakes.

Because `source_id` is the attempt id, "every attempt" is trivially supported; the other policies require an explicit condition in the rule snapshot. No default is assumed.

### 7.6 Reversals and corrections

`[PROPOSED]`

- Reversal = new ledger entry with `amount = -original.amount`, `reverses = original`, unique constraint prevents double reversal.
- Reversal requires a reason and an authorised actor (`[APPROVAL]` which role).
- XP is never recomputed by editing history. If a result is superseded, the original award is reversed and a new award is issued for the current revision; both remain visible.
- `balance_after` must be recomputed under the account lock; a reversal that would drive the balance negative is rejected unless negative balances are approved.

### 7.7 Historical auditability

`[PROPOSED]`

- Query by `user`, `source_type`, `source_id`, `rule`, and date range.
- Reconstruct balance at any timestamp by summing entries ordered by `(created_at, id)`; a `verify_xp_balance` command compares cached `balance` with the ledger sum.
- Export includes rule snapshot and evaluation digest, so an auditor can trace XP → result → question → criteria.
- `[APPROVAL]` Retention and candidate-visible XP history (full ledger vs summary).

---

## 8. Security and integrity

### 8.1 Threat and control matrix

| # | Risk | Current state | Control `[PROPOSED]` |
|---|---|---|---|
| S1 | Candidate reads correct answers | Serializers sanitize payload; `QuestionEvaluationData` is a separate table with no API | Keep criteria exclusively in `apps.evaluation` and never in candidate serializers; result API exposes only score/outcome after submission |
| S2 | Candidate reads results of others | `check_can_access_attempt` allows owner or staff | Result endpoint reuses the same guard and is scoped to `attempt.user` |
| S3 | Candidate reads results before submission | No result exists | Result endpoint returns 409/404 until the attempt is terminal |
| S4 | Repeated submission causes double evaluation | Terminal status rejects submit | Evaluation unique per attempt/revision; `ActiveAttemptEvaluation` pointer |
| S5 | Concurrent evaluation of one attempt | Row locks on attempt | `select_for_update(Attempt)` + unique evaluation constraint + deadlock retry |
| S6 | Duplicate background processing | No async infrastructure | Idempotent service: if a current `COMPLETED` evaluation exists, return it |
| S7 | Tampering with stored results | `AttemptEvent` guarded; answers editable pre-submit | Append-only guards on evaluation tables; admin read-only; digests + `result_snapshot`; optional DB-level restricted role `[APPROVAL]` |
| S8 | Answer edited after submission via ORM/admin | No model-level guard | Add `AttemptAnswer` guard: reject save when `attempt.status != IN_PROGRESS` (Phase 2E.2, changes existing model) |
| S9 | Answer overwritten pre-submission with no history | `ANSWER_SUBMITTED` event lacks payload | Add payload digest + answer revision count to the event in a later phase; result snapshots final answer only |
| S10 | Deadline bypass / late answers | Service rejects after deadline | Evaluation uses `completed_at`; answers post-deadline are already rejected |
| S11 | Expired attempt silently unevaluated | Expiry paths have no hook | Decide policy `[APPROVAL]`; if graded, hook `_expire_attempt_locked` with a result marked `late_submission` |
| S12 | Option shuffle makes answers ambiguous | Snapshot preserves shuffled order; answers use IDs | Evaluator resolves by ID only; validate criteria IDs against presentation payload |
| S13 | Question/config changed after attempt | Published versions immutable | Freeze criteria/rubric/mappings in the result; never read live rows at replay |
| S14 | Weight tampering | Weight frozen into `AttemptQuestion` | Result snapshots weight; admin read-only after attempt start |
| S15 | Scoring policy changed later | No policy exists | Versioned `ScoringPolicy` + FK from result |
| S16 | XP farming via retakes | Unlimited retakes | `[APPROVAL]` retake rule; per-rule conditions evaluated against the snapshot |
| S17 | XP double award | No XP yet | Unique idempotency key + account lock + unique semantic key |
| S18 | Manual reviewer bias / self-review | No review flow | Author cannot review own attempt; reviewer permission; mandatory reason; audit event |
| S19 | Result leakage through admin | Admin exposes models by default | Result models read-only in admin; criteria hidden from non-reviewer staff |
| S20 | Deadlock storm during batch evaluation | Retry decorator exists (3 attempts) | Evaluate per attempt; avoid cross-attempt locks; batch jobs process in bounded chunks |
| S21 | Large JSON snapshots | N/A | Snapshot only necessary fields; one result per attempt; index `attempt` and `question_version` |
| S22 | Time-zone / clock drift in deadlines | `USE_TZ=True`, UTC | Store UTC, compare server-side only |
| S23 | Error envelope leaks internals | Domain errors mapped | New evaluation exceptions use the same mapper; `detail` never returned to candidates |
| S24 | `PENDING_REVIEW` blocks results indefinitely | N/A | Explicit `PENDING` state, admin visibility, no silent zero |

### 8.2 Transaction boundaries

`[PROPOSED]`

**Submit path (synchronous objective evaluation):**

```
transaction.atomic():
    attempt = select_for_update(AssessmentAttempt)
    assert IN_PROGRESS, deadline
    attempt.status = SUBMITTED; save
    delete ActiveAssessmentReservation
    build criteria snapshots from QuestionEvaluationData (read-only)
    evaluate every question (pure functions, no I/O)
    insert AttemptEvaluation + QuestionEvaluation rows + EvaluationEvent
    insert/update ActiveAttemptEvaluation
    insert AttemptEvent ATTEMPT_SUBMITTED (with evaluation_id)
commit
```

- Everything is local DB work; no external calls inside the transaction.
- If any question returns `ERROR`, the transaction may still commit a `FAILED` evaluation with a clear code, or roll back to `IN_PROGRESS`. `[APPROVAL]` on the operational preference; recommendation: commit `FAILED` and raise a domain error, because a submitted attempt must not remain writable.
- XP awards occur after commit.
- Manual review transitions use a separate transaction with a locked `QuestionEvaluation`.
- Replay/recompute never holds the attempt lock for longer than the insert of the new revision.

**Expiry path:** if expired attempts are graded, `_expire_attempt_locked` must invoke the same evaluation builder inside its existing transaction; otherwise no result is produced.

### 8.3 API exposure rules

`[PROPOSED]`

| Endpoint | Method | Access | Returns |
|---|---|---|---|
| `/api/v1/assessments/attempts/{id}/result/` | GET | Owner or staff | Score summary, per-question outcome (no criteria), pass flag if approved, evaluation status |
| `/api/v1/assessments/attempts/{id}/result/questions/{order_index}/` | GET | Owner, only if review visibility approved | Prompt snapshot, candidate answer, outcome, maybe explanation; never correct option unless explicitly approved |
| `/api/v1/assessments/attempts/{id}/result/replay/` | POST | Staff with evaluation permission | Integrity verification report; no mutation |
| Admin/correction endpoints | — | Staff only | Append adjustment or create revision with reason |

Candidate-visible fields must exclude: `criteria_snapshot`, `rubric_snapshot`, `detail`, `competency_mappings_snapshot`, `input_digest`, evaluator internals.

`[APPROVAL]` Post-submission review visibility: score only, per-question correctness, correct answers, or explanations. The existing `QuestionVersion.explanation` is explicitly "post-assessment explanation" but no rule defines when/whether candidates see it.

---

## 9. Data model proposal summary

### 9.1 App placement

`[PROPOSED]` New app `apps.evaluation`, dependencies: `assessments`, `arena`, `skills`, `accounts`.
Rationale:

- Evaluation is a distinct bounded context that reads three existing apps; placing it inside `assessments` would grow an already large model module and blur authoring vs grading.
- `apps.gamification` is already a planned separate target in `docs/architecture.md`; evaluation results are its natural source.
- No circular dependency: `assessments` must never import `evaluation`. The submit hook is invoked by a thin integration service inside `assessments` that imports `evaluation` (one-directional) or, preferably, the evaluation service subscribes through an explicit call from the submit flow.

Alternative considered: add `AttemptResult` to `apps.assessments`. Rejected because it couples candidate execution with grading policy and makes the eventual extraction of evaluation/insights harder. If the team prefers fewer apps, the same models can live in `apps.assessments` with identical fields; the design is otherwise unchanged.

Second new app: `apps.gamification` for XP.

### 9.2 New tables

| Table | Key constraints |
|---|---|
| `evaluation_scoring_policy` | `Unique(code, version)`, status enum, version > 0 |
| `evaluation_active_scoring_policy` | `Unique(code)`, OneToOne policy |
| `evaluation_attempt_evaluation` | `Unique(attempt, revision)`, FK PROTECT, score range checks |
| `evaluation_active_attempt_evaluation` | `Unique(attempt)`, OneToOne evaluation |
| `evaluation_question_evaluation` | `Unique(attempt_evaluation, attempt_question)`, outcome enum, weight checks |
| `evaluation_competency_evidence` | `Unique(attempt_evaluation, competency)` |
| `evaluation_evaluation_event` | append-only |
| `evaluation_adjustment` (optional, if approved) | append-only, reason required |
| `gamification_xp_rule` | `Unique(code, version)` |
| `gamification_active_xp_rule` | `Unique(code)` |
| `gamification_xp_account` | `Unique(user)`, balance check |
| `gamification_xp_ledger_entry` | `Unique(idempotency_key)`, `Unique(user, source_type, source_id, rule)`, `Unique(reverses)` |

### 9.3 MySQL 8.4 / migration notes

`[PROPOSED]`

- Use `Decimal`, never `FloatField`.
- JSON columns for snapshots; do not query inside them for business logic.
- No partial/conditional unique indexes; use the pointer-table pattern already established by `ActiveAssessmentReservation`.
- All FKs to historical entities use `PROTECT`.
- Constraint/index names must stay ≤ 64 characters.
- New migrations depend on the latest `assessments`, `arena`, `skills`, and `accounts` migrations; no changes to existing tables in Phase 1–3.
- If §8 S8 (answer terminal guard) is approved, it is a separate migration altering existing model behaviour and must be reviewed independently.

### 9.4 Non-goals in the data model

- No `AssessmentAttempt.score` denormalisation in v1; the canonical score lives in `AttemptEvaluation`.
- No question-level answer-key duplication in `AttemptQuestion`.
- No section/blueprint model.
- No XP level curve or badge tables in this phase.

---

## 10. Decision register

| ID | Topic | Existing | Options | Recommendation | Status |
|---|---|---|---|---|---|
| D-01 | Weight semantics | Weight exists, unused | Relative multiplier vs point value | Relative multiplier; expose percentage | `[APPROVAL]` |
| D-02 | Assessment aggregation | None | Weighted mean; exclude-unanswered; sections; time-decay | Weighted mean over all questions | `[APPROVAL]` |
| D-03 | Multiple-choice partial credit | None | All-or-nothing; proportional; penalty; threshold | All-or-nothing for v1 | `[APPROVAL]` |
| D-04 | Negative marking | None | None; per-wrong-option penalty | None | `[APPROVAL]` |
| D-05 | Unanswered treatment | Not distinguished | Zero and in denominator; excluded; penalty | Zero, in denominator | `[APPROVAL]` |
| D-06 | Skipped treatment | Event only | Same as unanswered; excluded; penalty | Same as unanswered, recorded separately | `[APPROVAL]` |
| D-07 | Answer-then-skip precedence | Answer survives skip | Answer wins; skip wins | Answer wins | `[APPROVAL]` |
| D-08 | Expired attempt scoring | No evaluation | Grade recorded answers; no result; zero | Grade recorded answers, flagged late | `[APPROVAL]` |
| D-09 | Cancelled attempt scoring | No evaluation | No result; zero result | No result | `[APPROVAL]` |
| D-10 | Pass threshold | None | No pass/fail; fixed %; per-assessment % | `is_passed = NULL` until supplied | `[APPROVAL]` |
| D-11 | Rounding mode | N/A | Half-up; half-even; truncate | Half-up, 2 dp display | `[APPROVAL]` |
| D-12 | Numerical tolerance | Field exists, unused | Authored absolute; authored relative; exact only | Require authored tolerance | `[APPROVAL]` |
| D-13 | Short-text mechanism | Strategies declared | Accepted-answer set; regex; manual; LLM | Not selected | `[APPROVAL]` |
| D-14 | Code-output semantics | `STDOUT_MATCH` declared | String comparison; real execution | String comparison only; execution out of scope | `[APPROVAL]` |
| D-15 | Result visibility | None | Score only; per-question outcome; answers; explanations | Phased: score, then outcome | `[APPROVAL]` |
| D-16 | Mastery formula | None | Cumulative average; EMA; window; best; prerequisite-aware | Cumulative weighted average for v1 | `[APPROVAL]` |
| D-17 | Unanswered evidence | None | No evidence; zero evidence | No evidence | `[APPROVAL]` |
| D-18 | Domain aggregation | Model only | Equal mean; evidence-weighted; subdomain two-level | Not selected | `[APPROVAL]` |
| D-19 | Confidence tiers | Enum only | Thresholds undefined | Not selected | `[APPROVAL]` |
| D-20 | XP award rule | None | Fixed; score-scaled; threshold; completion | Not selected; XP independent of score | `[APPROVAL]` |
| D-21 | Retake XP | Unlimited attempts | First only; every; best-only; reduced; none | Not selected | `[APPROVAL]` |
| D-22 | XP reversal authority | None | Staff; superuser; dual approval | Staff with audit, reason mandatory | `[APPROVAL]` |
| D-23 | Correction policy | None | In-place edit; append revision; adjustment ledger | Append revision + adjustment ledger | `[APPROVAL]` (engineering sign-off) |
| D-24 | Result API shape | None | Summary only; summary + per-question | Summary first | `[APPROVAL]` |
| D-25 | Async vs sync evaluation | No async infra | In-transaction; background worker | In-transaction for objective; background only for manual | `[APPROVAL]` (engineering sign-off) |
| D-26 | Persist explicit skip state | Event only | New attempt-question state; derive from events | Derive at evaluation, store outcome only | `[PROPOSED]` |
| D-27 | New apps vs additions | N/A | `apps.evaluation` + `apps.gamification`; extend `assessments` | New apps | `[PROPOSED]` |

---

## 11. Security and integrity risk register (prioritised)

| ID | Risk | Likelihood | Impact | Mitigation | Residual |
|---|---|---|---|---|---|
| R-01 | Correct answers exposed via result API | Medium | Critical | Strict serializer allow-list; criteria only in evaluation tables; tests asserting absence | Low |
| R-02 | Answers written after submission by a non-service path | Medium | High | Model-level terminal guard; admin read-only; snapshot digest | Low after guard |
| R-03 | Duplicate evaluation / XP on retry | Medium | High | Unique constraints + account lock + idempotent service | Low |
| R-04 | Result mutated by ORM/admin | Low | Critical | Append-only guards, read-only admin, revision model | Low |
| R-05 | Expired attempts never graded, candidates see nothing | High | Medium | `[APPROVAL]` D-08; explicit terminal result state | Medium until decided |
| R-06 | Ungradeable published question (bad criteria) | Medium | High | Publication-time validation of criteria vs presentation payload; `ERROR` outcome is loud | Medium |
| R-07 | Numerical/short-text graded by invented rules | Medium | Critical | No defaults; `ERROR`/`PENDING_REVIEW` until approved | Low if enforced |
| R-08 | Mastery updated twice or out of order | Medium | High | Evidence ledger + projection run uniqueness + recompute command | Low |
| R-09 | XP balance drifts from ledger | Low | Medium | Ledger is source of truth; reconciliation command; row lock | Low |
| R-10 | Lock contention during batch evaluation | Medium | Medium | Bounded batches, per-attempt transactions, deadlock retry | Medium |
| R-11 | Snapshot too large / slow queries | Low | Medium | Store only required fields; indexes; avoid JSON filtering | Low |
| R-12 | Manual reviewer self-dealing | Low | High | Separation of duties, permissions, audit | Low |
| R-13 | Policy/version drift in replay | Low | High | Policy FK + full snapshot + digest verification | Low |
| R-14 | Time-zone drift in deadlines | Low | Medium | UTC everywhere, server-side comparison | Low |
| R-15 | Score anomaly (NaN, >100, negative) | Low | High | Decimal math, validation, clamping, anomaly event | Low |
| R-16 | Candidate infers answers from timing/response differences | Low | Medium | Uniform error responses; no per-question grading feedback mid-attempt | Medium |
| R-17 | Deletion of historical entities | Low | Critical | `PROTECT` FKs; no cascade from results | Low |
| R-18 | XP awarded for a superseded result | Medium | Medium | Reverse original, award new; idempotency key includes revision/evaluation | Low |

---

## 12. Suggested implementation sequence

Each phase is independently testable and shippable behind no feature flag unless noted. No phase may encode an `[APPROVAL]` decision.

### Phase 1 — Evaluation foundation and policy registry

- **Models:** `ScoringPolicy`, `ActiveScoringPolicy`, `AttemptEvaluation`, `ActiveAttemptEvaluation`, `QuestionEvaluation`, `EvaluationEvent` (schema only; no evaluators).
- **Services:** `ScoringPolicyService.activate()`, `EvaluationRegistry` with a `NotImplemented` evaluator, model-level append-only guards.
- **Constraints:** all uniques/checks from §9.2; no partial indexes.
- **Migrations:** one initial migration for `apps.evaluation`; no changes to existing tables.
- **APIs:** none (admin registration read-only for results; policy editing for staff only if approved).
- **Tests:** model constraints, immutability guards, policy activation pointer uniqueness, migration applies on SQLite; no MySQL connection.
- **Exit:** empty result schema in place, policy can be created/activated/retired, no behaviour change to attempts.

### Phase 2 — Objective evaluators (pure functions)

- **Services:** `evaluate_single_choice`, `evaluate_true_false`, `evaluate_multiple_choice` (all-or-nothing), shared canonicalisation helper, registry mapping.
- **Models:** none.
- **APIs:** none.
- **Tests:** table-driven unit tests for correct/incorrect/missing option/duplicate IDs/empty criteria/type-strategy mismatch; determinism; option-order independence; `Decimal` behaviour.
- **Exit:** evaluators produce `EvaluationOutcome` with no DB access.

### Phase 3 — Numerical evaluation (gated on D-12)

- **Services:** `evaluate_numerical` using authored tolerance only; `TOLERANCE_NOT_CONFIGURED` error path.
- **APIs:** none.
- **Tests:** exact, absolute tolerance, relative tolerance, missing tolerance, invalid decimal, bool rejection, huge exponents.
- **Exit:** evaluator never guesses a tolerance.

### Phase 4 — Transactional evaluation on submit/expire

- **Services:** `EvaluationService.evaluate_attempt()`; integration in `AssessmentAttemptService.submit_attempt` and, if approved, `_expire_attempt_locked`.
- **Models:** no new tables; uses Phase 1 schema.
- **Constraints:** evaluation insert inside the attempt transaction; `ActiveAttemptEvaluation` pointer.
- **Migrations:** none beyond Phase 1.
- **APIs:** `GET /attempts/{id}/result/` (summary only), candidate-owned; staff replay/verify command (no HTTP yet).
- **Tests:** submit transitions and produces exactly one result; duplicate submit yields 409 and no second result; expired path per D-08; unanswered/skipped classification; unauthorised result access; candidate payload contains no criteria.
- **Exit:** every terminal (eligible) attempt has a reproducible result; no XP or mastery changes.

### Phase 5 — Competency evidence

- **Models:** `CompetencyEvidence`.
- **Services:** `EvidenceService.build_for_evaluation()` — primary + secondary mappings, only answered/evaluated questions.
- **Migrations:** one migration.
- **Tests:** multi-competency question, zero-evidence question, mapping weights, superseded evaluation exclusion, idempotent rebuild, correct aggregation math.
- **Exit:** evidence rows exist and reconcile to the result totals.

### Phase 6 — Mastery projection (gated on D-16, D-17, D-18, D-19)

- **Models:** `MasteryProjection` (audit) if not already added; uses existing `UserCompetencyMastery` / `UserDomainMastery`.
- **Services:** `MasteryProjectionService.recompute(user)` plus `recompute_user_mastery` management command.
- **Migrations:** one migration for the audit table; no changes to existing mastery fields.
- **APIs:** none in this phase; read-only mastery endpoints only after approval.
- **Tests:** deterministic ordering, idempotency, range clamping, zero-evidence behaviour, domain aggregation, inactive competency handling, recompute after evidence correction.
- **Exit:** mastery is fully derived and reproducible; no `[APPROVAL]` constant is embedded.

### Phase 7 — XP ledger and award pipeline (gated on D-20, D-21, D-22)

- **Models:** `XpRule`, `ActiveXpRule`, `XpAccount`, `XpLedgerEntry`.
- **Services:** `XpService.award_for_evaluation()`, `reverse_entry()`, `reconcile_balance` command.
- **Migrations:** initial `apps.gamification` migration.
- **APIs:** none candidate-facing until approval; staff ledger inspection.
- **Tests:** idempotent duplicate award, concurrent awards (SQLite limitation acknowledged; row-lock logic unit-tested), retake policies, reversal uniqueness, negative balance rejection, ledger/account reconciliation.
- **Exit:** XP is auditable end-to-end; disabled by configuration until rules are approved.

### Phase 8 — SHORT_TEXT / CODE_OUTPUT (gated on D-13, D-14)

- **Services:** whichever mechanism is approved, behind a strategy registry entry.
- **Tests:** normalisation fixtures agreed with product; malformed regex; output whitespace.
- **Exit:** no assessment containing these types can be published unless a supported mechanism is configured.

### Phase 9 — Corrections, replay tooling, and review workflow

- **Services:** revision service, adjustment ledger (if approved), replay command, review decision service.
- **APIs:** staff-only correction endpoints; candidate result history if approved.
- **Tests:** supersession chain, pointer integrity, replay equality, permission separation, adjustment aggregation.
- **Exit:** historical results can be corrected without mutation; replay reproduces stored outcomes.

### Cross-phase requirements

- No phase connects to MySQL or runs migrations against a real database; tests use the existing SQLite `config.settings.testing`.
- Every phase adds tests before merging; existing suites must remain green.
- Frontend changes are out of scope for all phases.
- Each phase requires explicit authorisation after review of this document.

---

## 13. Unresolved product decisions (explicit list)

1. What does a question weight mean to the candidate: relative importance or points?
2. Does the assessment score include unanswered questions in the denominator?
3. Are skipped and unanswered treated identically?
4. If a candidate answers and then skips, which state wins?
5. Is there partial credit for multiple choice; if so, what formula and what penalty for wrong selections?
6. Is negative marking ever allowed?
7. Are expired attempts graded on the answers recorded before the deadline?
8. Do cancelled attempts produce a result?
9. Is there a pass/fail threshold; global or per assessment?
10. What rounding mode and display precision are contractual?
11. What tolerance applies to numerical answers, and who authors it?
12. What is the accepted-answer and normalisation policy for short text?
13. Does `CODE_OUTPUT` mean output prediction or actual code execution?
14. What does a candidate see after submission: score, per-question outcome, correct answers, explanations, competency breakdown?
15. How is competency mastery computed, and may it decrease?
16. Do unanswered/skipped questions count as incorrect evidence for mastery?
17. How are competency scores aggregated into domain mastery, and what do the confidence tiers mean numerically?
18. What are the XP award rules, and is XP independent of score?
19. How do retakes affect XP?
20. Who may reverse XP or correct a result, and what approval is required?
21. How long are superseded results and evaluation events retained?
22. Is evaluation synchronous with submission or handled by a worker?
23. Which existing attempts, if any, should be backfilled with results after launch? (None is recommended; history remains result-less but explainable.)

---

## 14. Explicitly out of scope / not done

- No source file was edited or created.
- No migration was created or run.
- No database connection was opened; MySQL was not contacted.
- No model, service, serializer, view, or URL was changed.
- No scoring, mastery, XP, reward, or badge logic was implemented.
- No frontend change.
- No commit or push.
- No code execution sandbox, AI grading, LLM evaluation, adaptive testing, anti-cheat timing analysis, percentile/rank computation, level curves, or badge design.
- No backfill, data migration, or admin workflow.
- Phase 2E.2 was not started.

---

## 15. Review gate

Implementation may begin only after:

1. Every `[APPROVAL]` item relevant to Phase 1–4 has a recorded decision with an owner and date.
2. The decision register is updated with the chosen option rather than the recommendation.
3. Engineering signs off on the two-app placement (D-27), transaction boundary (D-25), and correction model (D-23).
4. The candidate result contract (D-15/D-24) is agreed with the frontend team, even though no frontend work occurs in Phase 2E.
5. Explicit authorisation to start Phase 2E.2 is given.
