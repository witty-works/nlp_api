# Configuration

## Table of Contents

- [Notes](#notes)
- [Quick start: minimal .env for local dev](#quick-start-minimal-env-for-local-dev)
- [Core settings](#core-settings)
- [API docs protection](#api-docs-protection)
- [Sentry.io](#sentryio)
- [LanguageTool](#languagetool)
- [Context Checker](#context-checker)
  - [Local SetFit Models](#local-setfit-models)
  - [Remote API](#remote-api)
- [Redis](#redis)
- [AWS (LLM-assisted alternatives and rephrasing)](#aws-llm-assisted-alternatives-and-rephrasing)
- [Slack](#slack)
- [Authentication](#authentication)
- [Platform.sh](#platformsh)
- [Optional profiling (Blackfire)](#optional-profiling-blackfire)
- [What's configured by default](#whats-configured-by-default)
- [Changing spaCy models](#changing-spacy-models)

---

The API is configured via environment variables (loaded from a local .env file and the process environment using pydantic-settings). Below you'll find all relevant options with defaults, what they do, and sample configs for local, Docker, and Platform.sh deployments.

## Notes

- For macOS development with spaCy, copy the provided snippet to avoid MKL warnings: `cp .env.development.mac .env`
- If you want to use smaller spaCy models, update BOTH the MODELS setting and `pyproject.toml` (so the model wheels are available) before installing dependencies.

## Quick start: minimal .env for local dev

```bash
# Logging
LOGGING_ENABLED=true
LOGGING_CONFIG_FILENAME=stdout
LOGGING_CONFIG_LEVEL=INFO

# LanguageTool (run locally or use public API)
LANGUAGETOOL_API=http://localhost:8000/v2
LANGUAGETOOL_VERIFY_SSL=false

# Use in-memory fake Redis by omitting REDIS_HOST
# REDIS_HOST=localhost

# Docs auth (disabled by default)
API_DOCS_AUTH_ENABLED=false

# Disable Sentry in dev
SENTRY_DSN=
SENTRY_SAMPLE_RATE=0.0
SENTRY_TRACES_SAMPLE_RATE=0.0
SENTRY_PROFILES_SAMPLE_RATE=0.0

# Feature flags
ALTERNATIVES_MAX_COUNT=5
TEXT_MAX_LENGTH=1000
LOG_METRICS=false
```

Tip: Keys are shown here in UPPERCASE to match common .env style. They map 1:1 to the settings fields in `app/settings.py` (e.g., `API_DOCS_AUTH_ENABLED` -> `api_docs_auth_enabled`).

## Core settings

| Variable                    | Default                                                | Description                                                                                                        |
| --------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| LOGGING_ENABLED             | false                                                  | Enables application logging.                                                                                       |
| LOGGING_CONFIG_FILENAME     | ./logs/error.log                                       | Destination for logs. Use "stdout" to log to console.                                                              |
| LOGGING_CONFIG_LEVEL        | ERROR                                                  | Log level (e.g., DEBUG, INFO, WARNING, ERROR).                                                                     |
| PLATFORM_ENVIRONMENT_TYPE   | development                                            | Controls production behavior flags (sets `is_prod`). Set to "production" in prod.                                  |
| PLATFORM_ENVIRONMENT        | local                                                  | Logical environment name (used for Sentry environment).                                                            |
| TEXT_MAX_LENGTH             | 1000                                                   | Max characters processed per request; longer texts are truncated on word boundary.                                 |
| ALTERNATIVES_MAX_COUNT      | 5                                                      | Default max count of alternatives returned unless overridden by request.                                           |
| TERMS_OF_SERVICE            |                                                        | Link surfaced in OpenAPI metadata.                                                                                 |
| CONTACT                     |                                                        | Contact email in OpenAPI metadata.                                                                                 |
| TESTING                     | false                                                  | Enables testing shortcuts (e.g., `X-TESTING-AUTH` header) and disables Sentry.                                     |
| MODELS                      | ["en_core_web_lg",<br>"de_core_news_lg",<br>"fr_core_news_lg"] | spaCy models to load. If you change these, also align `pyproject.toml` dependencies.                               |
| IMPORT_FROM_DUMP            | true                                                   | On first boot, initialize the in-memory SQLite DB from `database/dump.sql` (otherwise from `database/db.sqlite3`). |
| LOG_MISSING_DECLENSION      | true                                                   | Log missing declension cases to help enrich the database.                                                          |
| MINIMUM_VERSION_WEB_EXT     | (empty)                                                | If set, reject requests from the browser extension below this semver.                                              |
| MINIMUM_VERSION_WORD_PLUGIN | (empty)                                                | If set, reject requests from the Word plugin below this semver.                                                    |

## API docs protection

Protect `/docs` and `/openapi.json` via HTTP Basic when needed.

| Variable              | Default | Description                                        |
| --------------------- | ------- | -------------------------------------------------- |
| API_DOCS_AUTH_ENABLED | false   | Enable Basic Auth for Swagger UI and OpenAPI JSON. |
| API_DOCS_USERNAME     | (empty) | Username for docs auth.                            |
| API_DOCS_PASSWORD     | (empty) | Password for docs auth.                            |

## Sentry.io

Enable error and performance telemetry. If `SENTRY_DSN` is empty or `TESTING=true`, Sentry is disabled.

| Variable                    | Default | Description                                |
| --------------------------- | ------- | ------------------------------------------ |
| SENTRY_DSN                  | (empty) | Project DSN.                               |
| SENTRY_SAMPLE_RATE          | 0.0     | Error event sampling rate (0.0–1.0).       |
| SENTRY_TRACES_SAMPLE_RATE   | 0.0     | Performance tracing sample rate (0.0–1.0). |
| SENTRY_PROFILES_SAMPLE_RATE | 0.0     | Profiling sample rate (0.0–1.0).           |

Sentry uses `PLATFORM_ENVIRONMENT` as the environment name and includes FastAPI/Starlette/AIOHTTP integrations. Sensitive request variables and input text are sanitized before send.

## LanguageTool

Optional spell/grammar checking. You can use the public API or self-host LanguageTool.

| Variable                | Default                             | Description                                                                            |
| ----------------------- | ----------------------------------- | -------------------------------------------------------------------------------------- |
| LANGUAGETOOL_API        | https://api.languagetoolplus.com/v2 | Base URL of your LanguageTool instance (must include `/v2`).                           |
| LANGUAGETOOL_VERIFY_SSL | true                                | Verify TLS certs when calling LanguageTool. Set to false for local/self-signed setups. |

Self-hosted: https://github.com/languagetool-org/languagetool

Platform.sh integration: If `PLATFORM_RELATIONSHIPS` is present, the app auto-detects the `languagetool` relationship and rewrites `LANGUAGETOOL_API` to the internal service URL with `LANGUAGETOOL_VERIFY_SSL=false`.

## Context Checker

Reduces false positives by checking rule hits in their sentence context. Two modes are supported:

1. Local SetFit Models (recommended): Uses locally-hosted SetFit models for fast, privacy-preserving inference
2. Remote API: External service endpoints

### Local SetFit Models

| Variable              | Default | Description                                                     |
| --------------------- | ------- | --------------------------------------------------------------- |
| CONTEXT_CHECKER_LOCAL | false   | When true, use local SetFit models instead of remote API calls. |

When enabled, the app loads SetFit models from `models/context_aware_model/{lang}/` where `{lang}` is `en`, `de`, or `fr`. Models are loaded into shared memory for multi-process use.

#### Setup Local SetFit Models

Option 1: Download from Hugging Face (Recommended)

```bash
# Install huggingface-hub if not already installed
pdm add huggingface-hub

# Download all models (en, de, fr)
pdm run python -m bin.download_from_huggingface --lang all

# Or download a specific language
pdm run python -m bin.download_from_huggingface --lang en
```

Why CPU format is required: The API launches multiple worker processes for concurrency. It leverages PyTorch shared memory to avoid duplicating model weights in each worker. GPU tensors cannot be shared with this mechanism out of the box, while CPU tensors can. Using CPU models allows `ContextChecker` to call `share_memory()` on the underlying backbone, reducing RAM and speeding up startup.

Test the CPU model:

```bash
pdm run python -m bin.test_cpu -i models/context_aware_model/en
```

Deployment (Platform.sh)

```bash
rsync -azP models/ "$(platform ssh -e main --pipe)":models/
platform environment:redeploy -e main
```

#### convert_to_cpu.py reference (optional)

If you obtain raw SetFit model dumps from another source and need to ensure they run on CPU, `bin/convert_to_cpu.py` converts a downloaded SetFit model directory to a CPU-only version and writes it to `models/context_aware_model/<lang>`.

Usage:

```bash
pdm run python -m bin.convert_to_cpu -i path/to/downloaded/model -l en
```

Arguments:

- `-i, --in` Path to source model directory (must contain SetFit artifacts like `config.json`, `model.safetensors` or `pytorch_model.bin`)
- `-l, --lang` Language code used for the destination folder (`en`, `de`, `fr`)

Notes:

- Output directory is created if missing and may overwrite existing files
- If the input model is already CPU-only, the script simply writes a copy
- CPU models enable shared-memory loading for multi-process inference

### Remote API

Configure per-language endpoints and Bearer API keys using the structured `CONTEXT_CHECKER` environment variable. If not provided and `CONTEXT_CHECKER_LOCAL=false`, context checking is skipped.

Environment Variable Format:

```bash
CONTEXT_CHECKER='{"en": {"url": "https://api.example.com/en", "api_key": "key123"}, "de": {"url": "https://api.example.com/de", "api_key": "key456"}}'
```

Structure:

```json
{
  "en": {
    "url": "https://your-api-endpoint.com/context-check",
    "api_key": "your-bearer-token"
  },
  "de": {
    "url": "https://your-api-endpoint.com/context-check-de",
    "api_key": "your-bearer-token-de"
  },
  "fr": {
    "url": "https://your-api-endpoint.com/context-check-fr",
    "api_key": "your-bearer-token-fr"
  }
}
```

Request format: The remote service receives `{ "data": ["sentence 1", "sentence 2", ...] }` and must return a list where each item is `"1"` to keep the match or any other value to discard it as a false positive.

Behavior:

- Local models (`CONTEXT_CHECKER_LOCAL=true`) are preferred when available
- If local models are not available for a language, the app falls back to remote API (if configured)
- If neither local nor remote is available, context checking is skipped for that language

## Redis

Redis stores user/organization configs, API key mappings, optional request/response logs, and metrics. If `REDIS_HOST` is empty, a fake in-memory Redis is used (great for development and tests).

| Variable         | Default | Description                                                                                             |
| ---------------- | ------- | ------------------------------------------------------------------------------------------------------- |
| REDIS_HOST       | (empty) | Redis hostname. Leave empty to use in-memory fake Redis.                                                |
| REDIS_PORT       | (empty) | Redis port.                                                                                             |
| REDIS_USERNAME   | (empty) | Redis username.                                                                                         |
| REDIS_PASSWORD   | (empty) | Redis password.                                                                                         |
| REDIS_VERIFY_SSL | true    | Verify TLS certs when connecting to Redis over SSL.                                                     |
| REDIS_LOG_EMAILS | (empty) | JSON array of email addresses to enable per-user request/response logging. Example: ["dev@witty.works"] |
| LOG_METRICS      | false   | When true, counters are incremented in Redis for auth/check/rephrase usage.                             |
| TESTING_API_KEY  | (empty) | When using fake Redis, pre-seed a test API key mapping to `TESTING_EMAIL`.                              |
| TESTING_EMAIL    | (empty) | Email used with `TESTING_API_KEY` when fake Redis is active.                                            |

Platform.sh integration: When `PLATFORM_RELATIONSHIPS` contains a `rediscache` service, Redis credentials are auto-configured.

## AWS (LLM-assisted alternatives and rephrasing)

Used for LLM-powered features (e.g., grammatically correct alternatives, rephrasing). These routes are restricted by plan and feature flags in configs; in debug mode you can test locally.

| Variable        | Default                            | Description                                                   |
| --------------- | ---------------------------------- | ------------------------------------------------------------- |
| AWS_REGION_NAME | (empty)                            | AWS region (e.g., eu-central-1).                              |
| AWS_KEY         | (empty)                            | AWS access key ID.                                            |
| AWS_SECRET_KEY  | (empty)                            | AWS secret access key.                                        |
| AWS_MODEL_ID    | mistral.mixtral-8x7b-instruct-v0:1 | Default model ID used when a request doesn’t specify `model`. |

## Slack

Opt-in Slack integration. When enabled, the API registers the `/slack/commands` endpoint and provides the `/witty` command handler.

| Variable              | Default | Description                                                                           |
| --------------------- | ------- | ------------------------------------------------------------------------------------- |
| SLACK_ENABLED         | false   | When true, initialize Slack Bolt and include the Slack routes.                        |
| SLACK_SIGNING_SECRET  | (empty) | Slack app signing secret used to verify requests.                                     |
| SLACK_BOT_TOKEN       | (empty) | Bot token to call Slack APIs.                                                         |
| SLACK_ORGANIZATION_ID | (empty) | Optional: fallback organization ID for config lookup when user email isn’t available. |

Notes

- If `SLACK_ENABLED=false` (default), no Slack code is initialized and the Slack routes are not included.
- With `SLACK_ENABLED=true` but empty Slack credentials, the app uses a local/dev Slack client for testing (no external calls).

## Authentication

Supported methods:

- API Keys: manage with the `/api_key` endpoints (stored in Redis)
- Azure AD B2C (per-tenant)
- Microsoft Office SSO (multi-tenant)

Azure AD B2C
| Variable | Description |
|---|---|
| AADB2C_TENANT_ID | B2C tenant ID (GUID). |
| AADB2C_CLIENT_ID | Application (client) ID registered in B2C. |
| AADB2C_POLICY | B2C user flow/policy name used by your app. |
| AADB2C_DOMAIN | B2C domain (e.g., wittyworksdev). |
| AADB2C_EXPECTED_SCOPE | Scope expected in access tokens (e.g., access_as_user). |

Office/Microsoft 365 SSO
| Variable | Description |
|---|---|
| OFFICE_SSO_CLIENT_ID | Application (client) ID. |
| OFFICE_SSO_EXPECTED_SCOPE | Scope expected in access tokens. |

If an `Authorization: Bearer <token>` is present, the API validates the token against the configured client(s) and required scope. Alternatively, pass an `x-key` header with a valid API key mapping to a user email in Redis. For local testing you can also use `X-TESTING-AUTH: user@example.com` when `TESTING=true`.

## Platform.sh

The app auto-detects Platform.sh relationships and environment:

- `PLATFORM_RELATIONSHIPS` (base64 JSON) is parsed to wire internal service URLs for LanguageTool and Redis.
- `PLATFORM_APPLICATION_NAME` is used when Blackfire continuous profiling is enabled.

## Optional profiling (Blackfire)

To enable continuous profiling in supported environments, set:

```bash
BLACKFIRE_ENABLE_CONTINUOUS_PROFILING=1
PLATFORM_APPLICATION_NAME=app
```

Also configure Blackfire credentials in `~/.blackfire.ini` or environment variables as per Blackfire docs.

---

## What’s configured by default

- Fake Redis in development (when no `REDIS_HOST` is provided).
- LanguageTool enabled against the public API by default; set `LANGUAGETOOL_API` to your self-hosted URL or set it empty to disable.
- Sentry disabled unless `SENTRY_DSN` is set and `TESTING` is false.
- Context checker disabled unless the per-language URL and API key are provided.

## Changing spaCy models

- Update `MODELS` in your environment to the desired packages (e.g., use `en_core_web_md`).
- Update `pyproject.toml` to include matching wheel URLs or pip names for those models.
- Reinstall dependencies so spaCy can load the specified models.
