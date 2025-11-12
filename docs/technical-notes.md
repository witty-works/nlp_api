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

## Framework and models

- Built on FastAPI (https://fastapi.tiangolo.com) and spaCy (https://spacy.io).
  - Large spaCy models are recommended. Smaller models work but may increase false positives. Transformer models can help, but not all include NER; those code paths would need disabling or alternative NER solution needs to be integrated.
  - Change models via the `MODELS` setting and align `pyproject.toml`; see Changing spaCy models and Core settings.

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
