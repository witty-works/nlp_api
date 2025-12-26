# Technical Notes

## Table of Contents

- [Configuration and management endpoints](#configuration-and-management-endpoints)
- [Framework and models](#framework-and-models)
- [POS tagging corrections](#pos-tagging-corrections)
- [LanguageTool integration](#languagetool-integration)
- [Context checker (false-positive reduction)](#context-checker-false-positive-reduction)
- [Data initialization and storage](#data-initialization-and-storage)
- [Privacy and logging](#privacy-and-logging)

---

## Configuration and management endpoints

- Store user/organization configs to customize behavior; see Management Endpoints and Configuration.
- Docs can be protected via HTTP Basic; see API docs protection. Core endpoints use OAuth2 or API Keys; see Authentication.
- Relevant code: `app/middleware.py`, `app/auth_service.py`.

### Authentication

Authentication and authorization are implemented in `app/auth_service.py` and rely on two mechanisms:

- OAuth2/JWT (primary): JWTs issued by configured identity providers are validated using the provider's JWKS. The implementation:

  - Fetches JWKS with a request timeout and retries using exponential backoff for transient network errors.
  - Parses `Cache-Control: max-age` from JWKS responses and caches the converted RSA public key in Redis with that TTL; a conservative default TTL is used when no max-age is provided.
  - Validates tokens with algorithm `RS256`, checking `aud` and `iss`; unverified claims are used only to select the right issuer/config, and final validation always verifies the signature and standard claims.
  - Sanitizes and normalizes error responses so remote response bodies are not reflected to clients.

- API keys (fallback and service clients): API-key storage and lookup are centralized in `app/redis.py` via `get_api_key_email`, `set_api_key`, and `delete_api_key` helpers. Behavior:
  - When a hashing secret is configured (`api_key_hmac_key` or `secret_key`), API keys are HMAC-SHA256 hashed before lookup/storage.
  - If no secret is configured, the code falls back to plaintext key lookup for backward compatibility; enabling hashing is recommended for production.

Testing / local development:

- When `settings.testing` is enabled, the app will map requests to a testing user only when an explicit `X-TESTING-AUTH` header is supplied. This prevents local `.env` values (such as `TESTING_EMAIL`) from silently altering auth behavior during test runs.

## Framework and models

- Built on FastAPI (https://fastapi.tiangolo.com) and spaCy (https://spacy.io).
  - Large spaCy models are recommended. Smaller models work but may increase false positives. Transformer models can help, but not all include NER; those code paths would need disabling or alternative NER solution needs to be integrated.
  - Change models via the `MODELS` setting and align `pyproject.toml`; see Changing spaCy models and Core settings.

## Rule Engine Algorithm

The rule engine operates as follows:

- A shallow but strict check is performed via SQL on the in-memory SQLite database to find potential matching rules. This is handled in `app/db.py` (`fetch_rules`).
- If no rules match, a less strict check is performed, also via SQL, to broaden the candidate set (see `fetch_rules` with `suffix_check=True` in `app/db.py`).
- Once candidate rules are found, they are iterated over and evaluated for applicability in `RuleCheck.handle()` and related methods in `app/rule_check.py`.
- The rule checks are performed by relevant logic in `app/rule_engine/matchers/pattern.py`, which includes pattern (`check_pattern`), phrase (`is_phrase_match`) and word (`is_word_match`) matching.
- When a rule matches, the involved tokens are skipped for subsequent checks, preventing overlapping rules from triggering multiple times (see `skip_token` returned by the rule checks)
- Additional rules are applied to ensure alternatives are grammatically correct and to generate appropriate gendered noun variations. This logic is found in `app/alternatives_engine/utils.py` (`build_french_adjective_alternatives`) and related helpers in `app/alternatives.py`.
- However, it is also possible for the client to do an additional request to use an LLM to make alternatives grammatically correct via the route `POST /v1.0/rephrase` (see `app/routes/rephrase.py`).

## Witty GPT Algorithm

- Prompt is modified through prompt-injection to get a more inclusive initial response from the model (`Prompt.handle()`)
- Response from the model is analyzed using the standard rule-engine
- If the number of issues is below a configurable threshold the initial response is returned otherwise a follow up prompt is generated and the response returned (`app/routes/prompt.py`)

## POS tagging corrections

- spaCy may misclassify POS for certain tokens. See `app/model.py` (`_fetch_word_type()`) for heuristic fixes used by the rule engine.
  - Longer-term: consider (re)training/finetuning on project-specific vocabulary; see `training_data/`.

## LanguageTool integration

- Works with public or self-hosted LanguageTool; configure via `LANGUAGETOOL_*`; see LanguageTool.
  - Project-specific ignore words live in `languagetool/`. A historical update script exists and could be restored: https://github.com/witty-works/nlp_api/commit/125712651446308a27fee4d7c69c918f3e682ee5

## Context checker (false-positive reduction)

- Supports local SetFit models (CPU, shared memory) or a remote API; see Context Checker.
  - Models reside under `models/context_aware_model/<lang>/`. Utilities: `bin/download_from_huggingface.py`, `bin/convert_to_cpu.py`, `bin/test_cpu.py`.

## Data initialization and storage

- In-memory SQLite rules load at startup from `database/dump.sql` (default) or `database/db.sqlite3` based on `IMPORT_FROM_DUMP`; see Core settings.
  - See `app/db.py` and `app/startup.py` for initialization details.

## Privacy and logging

- Context is sanitized (emails/URLs/numbers) before logging and error reporting; see Privacy and Context Sanitization.
  - Optional request/response logging and metrics use Redis; see Redis and Core settings. Relevant code: `app/privacy_filter.py`, `app/redis.py`.
