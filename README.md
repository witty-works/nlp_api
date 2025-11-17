# NLP API

- What it is: a FastAPI service that checks text for inclusive language (en/de/fr) using spaCy and an in-memory SQLite rules database. It can optionally use LanguageTool for spelling/grammar and an LLM for grammatically correct alternatives or rephrasing.
- Key capabilities:
  - Detect issues and surface inclusive alternatives across multiple diversity dimensions (see public overview: https://www.witty.works/en/categories.html)
  - Optional grammar/spell checks via LanguageTool (self-hosted or public API)
  - Optional LLM-powered alternatives and rephrasing
  - Reducing bias in LLM output (through prompt injection and automatic follow-ups prompts)
  - Custom, organization-specific rules
- Integrations:
  - Use https://github.com/witty-works/dashboard to manage to user/organization configuration
  - Use https://github.com/witty-works/browser-extension and https://github.com/witty-works/world-plugin UI clients
  - Use https://github.com/witty-works/rule-editor to manage the rules
- Quick start links:
  - Install and run: see Installation instructions (with PDM) and Run Locally; containerized setup in Using Docker and Using docker compose
  - Configure the app: see Configuration and Core settings; adjust spaCy models in Changing spaCy models
  - Explore the API: interactive docs at /docs; see API Endpoints for examples
- Where to look in the code:
  - `app/main.py` — FastAPI app factory and route inclusion
  - `app/routes/` — request handlers and route wiring
  - `app/settings.py` — environment-driven configuration (pydantic-settings)
  - `app/language_processor.py` — spaCy loading and NLP pipeline helpers
  - `app/categories.py` — category logic and helpers
  - `app/model.py` — core rule matching; includes `_fetch_word_type()` POS heuristics
  - `app/languagetool.py` — LanguageTool client integration
  - `app/context_checker.py` — local SetFit or remote API context checking
  - `bin/convert_to_cpu.py`, `bin/download_from_huggingface.py`, `bin/test_cpu.py` — context model utilities
  - `app/auth_service.py`, `app/middleware.py` — auth (API key/OAuth2) and docs protection
  - `app/redis.py` — Redis client and helpers

## Documentation Index

To keep this README scannable, detailed sections have moved to `docs/`. Quick links:

- Technical Notes: `./docs/technical-notes.md`
- Database Seed (dump.sql): `./docs/database-seed.md`
- Configuration & Environment Variables: `./docs/configuration.md`
- Setup & Deployment: `./docs/setup.md`
- API Endpoints: `./docs/api.md`
- Request Configuration & Categories: `./docs/request-configuration.md`
- Tests: `./docs/tests.md`
- Training Data & Lookups: `./docs/training-data.md`

---
