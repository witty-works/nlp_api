# Configuration

## Table of Contents

- [Notes](#notes)
- [Quick start: minimal .env for local dev](#quick-start-minimal-env-for-local-dev)
- [Core settings](#core-settings)
- [Reducing Resource Usage](#reducing-resource-usage)
- [Personal server](#personal-server)
- [API docs protection](#api-docs-protection)
- [Protecting the management endpoints](#protecting-the-management-endpoints)
- [Sentry.io](#sentryio)
- [LanguageTool](#languagetool)
- [Context Checker](#context-checker)
  - [Local SetFit Models](#local-setfit-models)
  - [Remote API](#remote-api)
- [Redis](#redis)
- [LLM provider (LLM-assisted alternatives and rephrasing)](#llm-provider-llm-assisted-alternatives-and-rephrasing)
  - [AWS Bedrock](#aws-bedrock)
  - [Who may spend the LLM budget](#who-may-spend-the-llm-budget)
- [Slack](#slack)
- [Textarea page](#textarea-page)
- [Authentication](#authentication)
- [Optional profiling (Blackfire)](#optional-profiling-blackfire)
- [What's configured by default](#whats-configured-by-default)
- [Changing spaCy models](#changing-spacy-models)

---

The API is configured via environment variables (loaded from a local .env file and the process environment using pydantic-settings). Below you'll find all relevant options with defaults, what they do, and sample configs for local and Docker deployments.

## Notes

- For macOS development with spaCy, copy the provided snippet to avoid MKL warnings: `cp .env.development.mac .env`

## Quick start: minimal .env for local dev

```bash
# The default is production, which hides the development helpers
ENVIRONMENT_TYPE=development

# Logging
LOGGING_ENABLED=true
LOGGING_CONFIG_FILENAME=stdout
LOGGING_CONFIG_LEVEL=INFO

# LanguageTool: off unless set; run it locally (see setup.md)
LANGUAGETOOL_API=http://127.0.0.1:8210/v2
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

Tip: Keys are shown here in UPPERCASE to match common .env style. They map 1:1 to the settings fields in [app/settings.py](../app/settings.py) (e.g., `API_DOCS_AUTH_ENABLED` -> `api_docs_auth_enabled`).

## Core settings

| Variable                    | Default                                                        | Description                                                                                                                                                      |
| --------------------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| LOGGING_ENABLED             | false                                                          | Enables application logging.                                                                                                                                     |
| LOGGING_CONFIG_FILENAME     | ./logs/error.log                                               | Destination for logs. Use "stdout" to log to console.                                                                                                            |
| LOGGING_CONFIG_LEVEL        | ERROR                                                          | Log level (e.g., DEBUG, INFO, WARNING, ERROR).                                                                                                                   |
| ENVIRONMENT_TYPE            | production                                                     | Controls production behavior flags (sets `is_prod`). In production the development helpers (`/debug/*`, `/lemmatize`, `/tokenize`, `/parse-word-types`, `/save_openapi_json`) answer `404`. Set `development` explicitly for local work. |
| ENVIRONMENT                 | local                                                          | Logical environment name (used for Sentry environment).                                                                                                          |
| ROOT_REDIRECT               | (empty)                                                        | Where `/` redirects, e.g. `/textarea` or `/docs`; a path on this host only, anything else stops the start. When set, `/` is open behind `REQUIRE_API_KEY` (its target is not). Empty: `/docs` outside production, a line of text in it. |
| TEXT_MAX_LENGTH             | 1000                                                           | Max characters processed per request; longer texts are truncated on word boundary.                                                                               |
| GUARDRAIL_MESSAGES_MAX_COUNT, GUARDRAIL_TEXTS_MAX_COUNT, GUARDRAIL_CHECK_MAX_LENGTH, GUARDRAIL_REQUEST_MAX_LENGTH | 1000, 20, 40000, 1000000 | What one guardrail request may ask of the server; more is refused with a `422`. See [Request limits](./guardrails.md#request-limits). |
| REQUEST_MAX_BYTES           | 8388608 (8 MiB)                                                | The largest request body accepted; larger is refused with a `413` before it is parsed, by `Content-Length` or, for a chunked body, as it arrives. The default fits a guardrail request of `GUARDRAIL_REQUEST_MAX_LENGTH` characters even if every one is JSON-escaped (6 bytes each); raise it with that setting. |
| ALTERNATIVES_MAX_COUNT      | 5                                                              | Default max count of alternatives returned unless overridden by request.                                                                                         |
| TERMS_OF_SERVICE            |                                                                | Link surfaced in OpenAPI metadata.                                                                                                                               |
| CONTACT                     |                                                                | Contact email in OpenAPI metadata.                                                                                                                               |
| MODELS                      | ["en_core_web_lg",<br>"de_core_news_lg",<br>"fr_core_news_lg"] | spaCy models to load. They must be installed: see [Using Smaller spaCy Models](#using-smaller-spacy-models).                                                                             |
| IMPORT_FROM_DUMP            | true                                                           | On first boot, initialize the in-memory SQLite DB from [database/dump.sql](../database/dump.sql) (otherwise from [database/db.sqlite3](../database/db.sqlite3)). |
| LOG_MISSING_DECLENSION      | true                                                           | Log missing declension cases at `DEBUG` to help enrich the database: the word type and form that is missing, never the word, which comes from the user's text. |
| MINIMUM_VERSION_WEB_EXT     | (empty)                                                        | If set, reject requests from the browser extension below this semver.                                                                                            |
| MINIMUM_VERSION_WORD_PLUGIN | (empty)                                                        | If set, reject requests from the Word plugin below this semver.                                                                                                  |
| MINIMUM_VERSION_WITTY_EDITOR| (empty)                                                        | If set, reject requests from the Witty editor (client `witty-editor:<version>`, e.g. the /textarea page) below this semver.                                      |

The `MINIMUM_VERSION_*` settings apply to /v2.4/check, /v2.0/auth, /v1.0/rephrase and /v1.0/write. A client below its minimum gets a 400 whose `detail` names the version to upgrade to; clients show it as "this version is no longer supported". The client comes from the request's `client` field (`<name>:<version>`, a bare version counts as `web-ext`); a request without one is never rejected.

## Reducing Resource Usage

The API can be configured to use significantly fewer system resources (CPU and memory) by disabling or optimizing certain features. This is particularly useful for development environments, smaller deployments, or when running on resource-constrained infrastructure.

### Using Smaller spaCy Models

By default, the API loads large spaCy models (`en_core_web_lg`, `de_core_news_lg`, `fr_core_news_lg`) which provide high accuracy but consume substantial memory (400-500 MB per language).

**To use smaller models:**

1. Update the `MODELS` environment variable to use medium or small models:

   ```bash
   # Medium models (~100 MB each)
   MODELS=["en_core_web_md","de_core_news_md","fr_core_news_md"]

   # Small models (~10-15 MB each)
   MODELS=["en_core_web_sm","de_core_news_sm","fr_core_news_sm"]
   ```

2. Install them. The wheels are pinned by hash in
   [bin/spacy-models.json](../bin/spacy-models.json):

   ```bash
   uv run python -m bin.install_spacy_models --size md   # or sm
   ```

   The Docker image takes the size as a build argument:
   `docker build --build-arg SPACY_MODEL_SIZE=md .`

**Trade-offs:**

- Small models: ~95% of large model accuracy, 30x smaller — see [spaCy Facts & Figures](https://spacy.io/usage/facts-figures) for benchmark comparisons
- Medium models: ~98% of large model accuracy, 4-5x smaller — see [spaCy Facts & Figures](https://spacy.io/usage/facts-figures)
- Reduced accuracy primarily affects named entity recognition and dependency parsing

### Disabling LLM-Assisted Rephrasing

LLM-powered alternatives and rephrasing are optional.

**To ensure it's disabled:**

```bash
LLM_ACCESS=disabled
```

That is the switch to use: it refuses the call whatever any config asks for, so
it holds even where credentials happen to be present. Leaving the provider
variables empty also stops the calls, but by failing them rather than by
declining them.

**Benefits:**

- No provider API costs
- Eliminates external API latency
- LLM routes (`/v1.0/rephrase`, `/v1.0/write`) will return appropriate error responses; the guardrail endpoints need no LLM and keep working

**Note:** LLM features are also gated by `LLM_ACCESS` and by the `llm_alternatives` flag in the user/organization config, so even with a provider configured, users need explicit access. See [Who may spend the LLM budget](#who-may-spend-the-llm-budget).

### Disabling Context Checker (False Positive Filtering)

The context checker reduces false positives but adds computational overhead—either through local SetFit model inference or remote API calls.

**To disable context checking:**

```bash
# Disable local models
CONTEXT_CHECKER_LOCAL=false

# Don't configure remote API endpoints
CONTEXT_CHECKER=
```

**Benefits:**

- Saves 200-400 MB RAM per language when local models are disabled (no SetFit models loaded)
- Reduces inference latency by 50-200ms per request
- Eliminates external API dependencies (if using remote mode)

**Trade-offs:**

- Slightly higher false positive rate on grammar rules (typically 5-10% more false positives)
- Most impactful for rules that are context-sensitive

**When to disable:**

- Development environments where false positives are acceptable
- Resource-constrained deployments
- When prioritizing speed over precision

### Disabling LanguageTool

LanguageTool provides spell-checking and additional grammar rules but requires either running a separate LanguageTool server or making external API calls.

**To disable LanguageTool:**

```bash
# Set to empty string to disable
LANGUAGETOOL_API=
```

**Benefits:**

- No need to run/maintain a separate LanguageTool server
- Eliminates external API calls and latency (100-500ms per request)
- No LanguageTool API costs if using premium service

**Trade-offs:**

- No spell-checking functionality
- Missing some grammar rules that LanguageTool provides but the API doesn't
- Reduced coverage for certain error types

**Note:** The API's core rule engine will continue to function—you'll still get alternatives, declensions, and custom rules. Only LanguageTool-specific features are disabled.

### Resource Optimization Example Configuration

For minimal resource usage in development:

```bash
# Use small spaCy models
MODELS=["en_core_web_sm","de_core_news_sm","fr_core_news_sm"]

# Disable LLM features
LLM_MODEL=

# Disable context checker
CONTEXT_CHECKER_LOCAL=false
CONTEXT_CHECKER=

# Disable LanguageTool
LANGUAGETOOL_API=

# Use fake in-memory Redis
REDIS_HOST=

# Basic logging
LOGGING_ENABLED=true
LOGGING_CONFIG_FILENAME=stdout
LOGGING_CONFIG_LEVEL=INFO
```

This configuration reduces memory usage from ~2-3 GB to ~300-500 MB while maintaining core functionality.

## Personal server

A server for yourself, checked from a LanguageTool client such as the desktop app, needs three things set. Nothing here suits a public host.

```bash
REQUIRE_AUTH=false                 # answer anyone who can reach it
DEFAULT_USER_CONFIG_ENABLED=true   # or /v2.0/auth answers 403 and clients go quiet
LANGUAGETOOL_COMPAT_ROOT=true      # serve the endpoints at the root as well
DEFAULT_CONFIG='{"german_gender_ending": "de-e"}'
```

`DEFAULT_USER_CONFIG_ENABLED` is the one that is easy to miss. Without a dashboard there is no job filling Redis with a config for the email an API key resolves to, so `/v2.0/auth` refuses it and a client concludes it is signed out. Checking still works if you call it directly, which is what makes this confusing: the browser extension simply stops highlighting and says nothing.

Watch for a forced config too. A `force` entry in a synced user or organisation config, including the ones `TESTING_RULES` and `TESTING_ORGANIZATION_RULES` carry, beats whatever a request asks for. That is deliberate, so an organisation can pin a house style, but it means a request asking for `de-e` can come back checked against `*in`. The `gender_separator` field in the response says which ending actually applied, so read that first when the results are not what the config asked for.

Then run it on LanguageTool's local port, because the desktop app has no host or port field:

```bash
REQUIRE_AUTH=false LANGUAGETOOL_COMPAT_ROOT=true \
  DEFAULT_CONFIG='{"german_gender_ending": "de-e"}' \
  uv run uvicorn app.main:app --port 8081
```

`DEFAULT_CONFIG` is what makes an option like the gender ending reachable at all. The LanguageTool protocol carries a language, a mother tongue and a list of disabled categories, and nothing else, so every other option would otherwise sit on its built-in default with no way to say so. It applies only to fields a request does not set for itself, so a client that does ask for something still gets it, and a synced user or organisation config layered on afterwards still wins. It is checked when the API starts: an option that does not exist or a value that does not validate stops the start with a message naming it.

A request's config is built in this order, each layer filling in or overriding the one before (`fetch_configs_for_request` in [config_manager.py](../app/config_manager.py)):

1. the built-in defaults;
2. what the request sent (`store_context` and `llm_alternatives` only with `CLIENT_CONFIG_ENABLED`);
3. `DEFAULT_CONFIG`, for fields the request did not send;
4. a synced API key's `config`, for fields the request did not send;
5. suggestions in a synced user config, for `store_context` and `llm_alternatives`;
6. `force` rules in the user's, then the organisation's config;
7. `LLM_ACCESS` / `LLM_ALLOWED_USERS`, which can only turn the LLM off.

Every value is validated as it is applied, the way a request's own config is; one that does not validate is logged and left out.

Any field of the check config can go in it. Unknown keys and values the config rejects are logged and skipped rather than taken, so a typo does not silently change what the server checks for.

Note that port 8081 is where a real local LanguageTool server would sit, so run one or the other, not both. The [Tests](./tests.md#languagetool) page uses a different port for exactly that reason.

### From the browser extension

The extension authenticates with an API key, which the LanguageTool clients do not. `DEFAULT_API_KEY` gives the deployment one without a dashboard to mint it or a Redis to keep it in; it is written on every start, so it survives restarts on the in-memory fallback too. It must pass the check `POST /api_key` applies, at least 20 letters, digits, `-` or `_`; anything else, such as the placeholder in `.env.example`, stops the start.

```bash
DEFAULT_API_KEY=pick-something-long-and-random
API_KEY_HMAC_KEY=another-long-random-secret
DEFAULT_USER_EMAIL=you@example.com
DEFAULT_USER_CONFIG_ENABLED=true
```

`API_KEY_HMAC_KEY` keeps the key in Redis as a digest. In production, the
default `ENVIRONMENT_TYPE`, the API refuses to start while Redis holds a key as
written and it is empty.

`DEFAULT_USER_CONFIG_ENABLED` belongs with it: the key resolves to an email that has no config stored, and without the fallback `/v2.0/auth` answers 403 and the extension concludes it is signed out. Checking still works if you call it directly, which is what makes that one confusing to diagnose.

This is for a deployment whose users are you. Anyone with the key is that user, and it is only as protected as the environment it sits in. Where there is more than one of you, run a real Redis and mint a key each:

```bash
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
```

```bash
uv run python -m bin.api_key create you@example.com
```

The in-memory Redis is per process, so without `REDIS_HOST` that script would write to its own memory and never reach the API. It refuses to run rather than appearing to succeed.

## API docs protection

Protect `/docs` and the development helpers (`/save_openapi_json`,
`/lemmatize`, `/tokenize`, `/parse-word-types`, `/debug/*`) via HTTP Basic when
needed. `/openapi.json` is served unguarded either way.

| Variable              | Default | Description                                        |
| --------------------- | ------- | -------------------------------------------------- |
| API_DOCS_AUTH_ENABLED | false   | Enable Basic Auth for the docs UI and dev helpers. |
| API_DOCS_USERNAME     | (empty) | Username for docs auth and the [management endpoints](#protecting-the-management-endpoints). |
| API_DOCS_PASSWORD     | (empty) | Password for docs auth and the [management endpoints](#protecting-the-management-endpoints). |

Behind `REQUIRE_API_KEY`, `/docs` needs a key unless `API_DOCS_AUTH_ENABLED` asks for the password instead, and the page loads `/openapi.json`, which needs one too: add `"/openapi.json"` to `PUBLIC_PATHS`, or the docs page renders without any endpoints. Add `"/docs"` as well to make the docs public.

`/docs` loads Swagger UI from jsDelivr at an exact version, with Subresource
Integrity hashes, so the browser refuses a file that differs from the one
published. Only `/docs` is allowed to load from there: its
Content-Security-Policy names the two files and allows its inline start-up
script by hash, while every other response allows no third-party or inline
script. To move to another Swagger UI version, change `SWAGGER_UI_URL` and
both hashes in [app/routes/utility.py](../app/routes/utility.py).

## Protecting the management endpoints

Separate from the docs switch, because reading the schema and minting a
credential are not the same risk. This one guards `/api_key`, `/managed_keys`,
`/user/configs`, `/organization/configs`, `/settings` and `/languagetool_api` —
the endpoints that hand out or expose credentials and configuration, or act on
a named user's behalf — and defaults to **on**, so a deployment nobody
configured is closed rather than open.

| Variable                | Default | Description                                                                             |
| ----------------------- | ------- | ---------------------------------------------------------------------------------------- |
| MANAGEMENT_AUTH_ENABLED | true    | Require Basic Auth on the management endpoints. Set to `false` for local development only: with `ENVIRONMENT_TYPE=production` it stops the start. |

It reuses `API_DOCS_USERNAME` and `API_DOCS_PASSWORD` for the credentials, so
there is one pair to configure rather than two. These are the management
credentials the dashboard signs in with to write settings and manage API keys:
its `APP_NLP_API_SYNC_USER` and `APP_NLP_API_SYNC_PASSWORD`. With auth enabled and no
password set, those endpoints answer 500 rather than letting anyone through.

## Sentry.io

Enable error and performance telemetry. If `SENTRY_DSN` is empty or `TESTING=true`, Sentry is disabled.

| Variable                    | Default | Description                                |
| --------------------------- | ------- | ------------------------------------------ |
| SENTRY_DSN                  | (empty) | Project DSN.                               |
| SENTRY_SAMPLE_RATE          | 0.0     | Error event sampling rate (0.0–1.0).       |
| SENTRY_TRACES_SAMPLE_RATE   | 0.0     | Performance tracing sample rate (0.0–1.0). |
| SENTRY_PROFILES_SAMPLE_RATE | 0.0     | Profiling sample rate (0.0–1.0).           |

Sentry uses `ENVIRONMENT` as the environment name and includes FastAPI/Starlette/AIOHTTP integrations. Sensitive request variables and input text are sanitized before send.

## LanguageTool

Optional spell/grammar checking, off by default. Self-host LanguageTool (see
[Using docker compose](./setup.md#using-docker-compose-recommended-for-local-multi-service-setup)),
or name LanguageTool's hosted API (`https://api.languagetoolplus.com/v2`),
which sends the text being checked to LanguageTool.

| Variable                | Default                             | Description                                                                            |
| ----------------------- | ----------------------------------- | -------------------------------------------------------------------------------------- |
| LANGUAGETOOL_API        | (empty)                             | Base URL of your LanguageTool instance (must include `/v2`). Empty: no LanguageTool.   |
| LANGUAGETOOL_VERIFY_SSL | true                                | Verify TLS certs when calling LanguageTool. Set to false for local/self-signed setups. |
| LANGUAGETOOL_USERNAME   | (empty)                             | Optional: your username/email for premium LanguageTool accounts (used for API access). |
| LANGUAGETOOL_API_KEY    | (empty)                             | Optional: your API key / access token for premium LanguageTool accounts.               |
| LANGUAGETOOL_COMPAT_ROOT | false                              | Serve the [LanguageTool-compatible API](./api.md#languagetool-compatible-api) additionally at the root (`/v2/check`, ...), the exact path layout of a real LanguageTool server. Needed for clients that cannot be given a path in their server URL, e.g. the desktop app pointed at localhost. |

Self-hosted: https://github.com/languagetool-org/languagetool

## Context Checker

Reduces false positives by checking rule hits in their sentence context. Two modes are supported:

1. Local SetFit Models (recommended): Uses locally-hosted SetFit models for fast, privacy-preserving inference
2. Remote API: External service endpoints

### Local SetFit Models

| Variable              | Default | Description                                                     |
| --------------------- | ------- | --------------------------------------------------------------- |
| CONTEXT_CHECKER_LOCAL | false   | When true, use local SetFit models instead of remote API calls. |

When enabled, the app loads SetFit models from `models/context_aware_model/{lang}/` where `{lang}` is `en`, `de`, or `fr`. Models are loaded into shared memory for multi-process use. A language without a model there is not checked locally.

Witty Works publishes models for English and German. No French model has been trained; one placed in `models/context_aware_model/fr/`, for example with [bin/convert_to_cpu.py](../bin/convert_to_cpu.py), is used like the others.

#### Setup Local SetFit Models

Option 1: Download from Hugging Face (Recommended)

The script downloads a fixed commit of [witty-works/setfit-context-checker](https://huggingface.co/witty-works/setfit-context-checker), set in `REVISION` in [bin/download_from_huggingface.py](../bin/download_from_huggingface.py), so every deployment runs the same model weights. Moving it is a reviewed change: new weights can change which findings the context checker keeps.

```bash
# Download every model the repository has (en, de)
uv run python -m bin.download_from_huggingface --lang all

# Or download a specific language
uv run python -m bin.download_from_huggingface --lang en
```

Why CPU format is required: The API launches multiple worker processes for concurrency. It leverages PyTorch shared memory to avoid duplicating model weights in each worker. GPU tensors cannot be shared with this mechanism out of the box, while CPU tensors can. Using CPU models allows `ContextChecker` to call `share_memory()` on the underlying backbone, reducing RAM and speeding up startup.

Test the CPU model:

```bash
uv run python -m bin.test_cpu -i models/context_aware_model/en
```

#### convert_to_cpu.py reference (optional)

If you obtain raw SetFit model dumps from another source and need to ensure they run on CPU, [bin/convert_to_cpu.py](../bin/convert_to_cpu.py) converts a downloaded SetFit model directory to a CPU-only version and writes it to [models/context_aware_model/<lang>](../models/context_aware_model/).

Usage:

```bash
uv run python -m bin.convert_to_cpu -i path/to/downloaded/model -l en
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

| Variable         | Default     | Description                                                                                                                                                   |
| ---------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| REDIS_HOST       | (empty)     | Redis hostname. Leave empty to use in-memory fake Redis.                                                                                                      |
| REDIS_PORT       | (empty)     | Redis port.                                                                                                                                                   |
| REDIS_USERNAME   | (empty)     | Redis username.                                                                                                                                               |
| REDIS_PASSWORD   | (empty)     | Redis password.                                                                                                                                               |
| REDIS_VERIFY_SSL | true        | Connect over TLS and check the server's certificate; a connection to a Redis whose certificate does not check out fails at startup. `false`: plain TCP, for a Redis on the same host or private network, as in `compose.yml`. |
| API_KEY_HMAC_KEY | (empty)     | Secret for storing and looking up API keys as an HMAC-SHA256 digest, so a copy of Redis holds no working key. With it set, a key stored as written does not resolve: run `uv run python -m bin.api_key rehash` once after setting it. Changing it later invalidates every key, as digests cannot be converted; mint new ones. In production the start is refused while Redis holds a key as written and this is empty; elsewhere, and with `REQUIRE_API_KEY` on, it logs a warning. |
| REDIS_SSL_CA_CERTS | (empty)   | Path to the CA certificate(s) to check a Redis certificate against, for one signed by a private CA. Empty: the system's CAs.                                     |
| LOG_METRICS      | false       | When true, counters are incremented in Redis for auth/check/rephrase usage.                                                                                   |
| TESTING\_\*      | (see below) | Fixtures for the test suite: `TESTING_RULES` and `TESTING_ORGANIZATION_RULES`. Only loaded when `TESTING` is set. See [Testing variables](#testing-variables). |

## LLM provider (LLM-assisted alternatives and rephrasing)

Used for LLM-powered features (e.g., grammatically correct alternatives, rephrasing).

Calls go through [LiteLLM](https://docs.litellm.ai/docs/providers), so the
provider is the prefix of the model identifier and switching providers is a
config change:

| Variable       | Default  | Description                                                                                        |
| -------------- | -------- | ---------------------------------------------------------------------------------------------------- |
| `LLM_MODEL`    | (empty)  | Model identifier, e.g. `bedrock/anthropic.claude-…`, `anthropic/claude-…`, `openai/…`, `openrouter/…`. Empty means the deployment has no LLM.       |
| `LLM_API_KEY`  | (empty)  | Credential for the provider. Not used for Bedrock, which signs with the AWS credentials below.     |
| `LLM_API_BASE` | (empty)  | Only for a provider that is not at its vendor's own address: self-hosted vLLM or Ollama, a gateway, an Azure deployment. |
| `LLM_MAX_TOKENS` | 2000 | What one LLM call may generate. Reasoning models spend from a few hundred to over 3,000 tokens thinking before a rephrasing, unless `LLM_EXTRA_BODY` switches thinking off; an answer cut off by this limit is refused (502, logged) rather than used. `/v1.0/write` gets 1500 more for the text itself. |
| `LLM_EXTRA_BODY` | (empty) | Provider-specific fields sent in the body of every call, as a JSON object, for what LiteLLM has no parameter of its own. `{"chat_template_kwargs": {"enable_thinking": false}}` switches off a Qwen3 model's thinking on a server that passes chat-template arguments on; rephrasing does not need it. See [Choosing a language model](./llm-models.md). |
| `LLM_PROVIDER` | `openai-compatible` | Which adapter handles what differs between providers: `openai-compatible` (vLLM, Ollama and any provider LiteLLM reaches directly), `litellm-proxy` (a LiteLLM proxy; reads the served model from a response header), `openai`. Chosen by name, never guessed from the model id; an unknown name stops the start. See [Choosing a language model](./llm-models.md#choosing-an-adapter). |
| `LLM_TASK_EXTRA_BODY` | (empty) | Extra body fields per task (`rephrase`, `write`, `other`), merged over `LLM_EXTRA_BODY` one level deep, so a task's `chat_template_kwargs` adds to the global one's: `{"rephrase": {…}, "write": {…}}`. For example, thinking switched off for rephrasing only. Another task name stops the start. |
| `LLM_SERVED_MODEL_HEADER` | `x-litellm-model-name` | `litellm-proxy` only: the response header that names the model that answered. |
| `LLM_EXPECTED_MODEL` | (empty) | The model the deployment expects to answer, as the adapter reports it (for `litellm-proxy`, the header's value, e.g. `openai/Qwen3.8-Flash-Next-oQ4e-mtp`). Empty: the served model is logged and counted but not compared. A provider that does not say which model answered counts as a mismatch. Wherever a model's name is shown, logged or counted, an AWS account id in an ARN is masked and the name is cut at 200 characters. |
| `LLM_MODEL_MISMATCH` | `warn` | On a mismatch with `LLM_EXPECTED_MODEL`: `warn` logs and counts it and keeps the answer; `refuse` answers `503` instead, with `Retry-After: 300`, since a mismatch lasts until the deployment changes. |
| `LLM_TIMEOUT` | 60 | Seconds before an LLM call is given up (503 with `Retry-After`). |
| `LLM_MAX_CONCURRENCY` | 2 | LLM calls one worker runs at once; more wait up to `LLM_TIMEOUT` for a slot. Keep it times `WORKERS` within the provider's limit on concurrent requests. `0` for no limit. |
| `LLM_MAX_REQUESTS_PER_MINUTE` | 0 | LLM calls the whole deployment makes per minute, counted in Redis so all workers share one budget. Past it, a call is refused with 503 and a `Retry-After` up to the next minute, without reaching the provider. Set it below the provider's per-key limit (60 for the BFH inference server) so the account is never the one that hits it. `0` for no limit; without a real Redis each process counts on its own. A team synced from the dashboard can also have its own limit (`llm_requests_per_minute`, see [api.md](./api.md#organization-configuration)). |
| `LLM_REFUSED_MESSAGE` | (empty) | What a user is told when the provider refuses a text (`422`): a deployment whose provider filters requests explains here what it refuses. Empty: the provider's own reason, if it gives one. |

A guardrail or content filter of the provider that refuses a text reaches the client as `422` with `LLM_REFUSED_MESSAGE` or the provider's reason, and is logged as a warning that names the guardrail, not the reason, as a guardrail may quote what it matched: it is about the text, not the deployment. Witty recognises a LiteLLM proxy's guardrails and LiteLLM's content-policy error; any other `400` from the provider stays an error (500, logged).

```bash
# Anthropic directly
LLM_MODEL="anthropic/claude-sonnet-4-5"
LLM_API_KEY="sk-ant-…"

# Anything OpenAI-compatible you host yourself
LLM_MODEL="openai/my-model"
LLM_API_BASE="http://localhost:8000/v1"
```

Parameters a given provider does not support are dropped rather than raising, so
the same `max_tokens` / `temperature` / `top_p` settings work across all of them.

There is no default model — no one identifier is reachable from every
deployment. Leaving `LLM_MODEL` empty is a valid configuration meaning "this
deployment has no LLM": the features are refused the same way
`LLM_ACCESS=disabled` refuses them, rather than failing a call at the provider.

### AWS Bedrock

Bedrock signs with AWS credentials rather than a bearer token, so
`LLM_API_KEY` is not used for it. The API passes no credentials of its own:
LiteLLM finds them the standard AWS way, from `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY`, an AWS profile or an instance role. The model comes
from `LLM_MODEL`, as `bedrock/<model id>`. Leave `LLM_API_KEY` empty for
Bedrock: when set, it is passed on as for any model, and LiteLLM uses it as a
Bedrock API key instead of the AWS credentials.

| Variable              | Default | Description                                                          |
| --------------------- | ------- | -------------------------------------------------------------------- |
| AWS_REGION_NAME       | (empty) | AWS region (e.g., eu-central-1).                                     |
| AWS_ACCESS_KEY_ID     | (empty) | AWS access key ID, read by LiteLLM, not by the API.                  |
| AWS_SECRET_ACCESS_KEY | (empty) | AWS secret access key, read by LiteLLM, not by the API.              |

The old names `AWS_KEY` and `AWS_SECRET_KEY` stop the start, so that no
deployment calls Bedrock without its keys unnoticed.

LiteLLM reads the AWS variables from the process environment, not from the
API's `.env` file. With `compose.yml`, which passes `.env` to the container
(`env_file`), they arrive there; run any other way (`uv run`, gunicorn
directly), export them in the environment yourself, or Bedrock is called
without credentials and every call fails.

### Who may spend the LLM budget

These calls are billed to whoever runs the API, so who may make them is the
operator's decision and nothing else can overrule it.

| Variable            | Default | Description                                                                                                       |
| ------------------- | ------- | ------------------------------------------------------------------------------------------------------------------- |
| `LLM_ACCESS`        | `users` | `disabled`, `users` or `everyone` — see below.                                                                    |
| `LLM_ALLOWED_USERS` | `[]`    | With `users`, narrows it to these emails. JSON list, e.g. `LLM_ALLOWED_USERS='["a@example.com","b@example.com"]'`. |

- **`disabled`** — no LLM calls, whoever asks. A `force: true` rule in a synced
  config does not override it, and neither do the debug routes.
- **`users`** — anyone the request resolved to a user for. That covers a
  dashboard token and an `x-key` alike: an API key *is* its user's email by the
  time this is checked, so `LLM_ALLOWED_USERS` lists emails and one list
  narrows both. Leave it empty to allow every user. This is the default.
- **`everyone`** — anyone who can reach the API, resolved user or not. Pair it
  with `REQUIRE_AUTH=false` for a deployment that is open by design.

The policy says who **may**, not who **does**: it can only ever turn
`llm_alternatives` off. Something still has to turn it on —

| To turn it on for                       | Set                                                                |
| --------------------------------------- | -------------------------------------------------------------------- |
| every user of a dashboard-less deployment | `DEFAULT_USER_LLM_ALTERNATIVES=true` (with `DEFAULT_USER_CONFIG_ENABLED`) |
| whoever asks per request                | `CLIENT_CONFIG_ENABLED=true`, then the client sends `config.llm_alternatives` |
| a specific dashboard organization       | the dashboard's own LLM alternatives setting, which syncs as a `force` rule |

So `LLM_ACCESS=everyone` on its own changes nothing until one of those applies.

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
- With `SLACK_ENABLED=true`, both `SLACK_SIGNING_SECRET` and `SLACK_BOT_TOKEN` are required; without either the start is refused.

## Textarea page

Opt-in page for checking and rewriting text by hand with an API key: Witty's editor and a prompt. Setup, including installing the editor script, is in [textarea.md](./textarea.md).

| Variable         | Default | Description                                                                                          |
| ---------------- | ------- | ---------------------------------------------------------------------------------------------------- |
| TEXTAREA_ENABLED | false   | Serve `/textarea`. Opens it and its script without a key behind `REQUIRE_API_KEY`; checks stay gated. |
| TEXTAREA_CONTACT | api@witty.works | Where the page tells visitors to request an API key (a mailto link). Empty leaves the section out. |
| TEXTAREA_IMPRINT_URL | (empty) | Link to the deployment's legal information (imprint), shown in the page footer. Empty leaves it out; only http(s) addresses are linked. |
| TEXTAREA_IMPRINT_FILE | (empty) | Instead of a link: a Markdown file with the imprint, rendered at `/textarea/imprint` (public, like the page) and linked from the footer. Write it in English: the page around it is, and says so (`lang="en"`). Raw HTML in it stays text. Setting both, or a file that cannot be read, stops the start; read once, so a change needs a restart. |

The editor script is installed separately with `python bin/fetch_editor.py`; the Docker image always carries it.

## Authentication

Supported methods:

- API Keys: mint with [bin/api_key.py](../bin/api_key.py) or the `/api_key` endpoints (stored in Redis)
- Dashboard access tokens (Laravel Passport, verified against a JWKS document)
- Azure AD B2C (per-tenant)
- Microsoft Office SSO (multi-tenant)

Which one a token is checked against is decided by its `aud` claim: it has to
equal the client id of exactly one configured issuer. A token whose audience
matches nothing configured is rejected with a 401.

A token that is missing, malformed, expired, for another audience or not
signed by its issuer is answered with `401` and
`WWW-Authenticate: Bearer error="invalid_token"`, so a client may get a new one
and try again. A valid token whose user is not let in (a missing scope, an
unverified email, no config for the user at `/v2.0/auth`) is answered with
`403`. When the issuer's keys cannot be fetched the answer is `503`: that says
nothing about the token.

Dashboard (Laravel Passport)
| Variable | Description |
|---|---|
| DASHBOARD_CLIENT_ID | OAuth client id the dashboard issues tokens for; also the `aud` claim. Setting it enables this issuer. Several clients of the one dashboard, comma-separated (the browser extension's and the dashboard's write page's): a token is accepted when its `aud` is any of them. Passport issues UUIDs, such as `9a1f3c52-6d0e-4b7a-8f21-3c5d9e0b7a64, 9a1f3c5b-2e4f-4c8d-9b17-6a0e2f4d8c31`; the dashboard prints the write page's when it creates the client at its first start. |
| DASHBOARD_URL | Base URL of the dashboard. The JWKS document is looked up at `{DASHBOARD_URL}/.well-known/jwks.json`. |
| DASHBOARD_JWKS_URL | Optional: the full JWKS URL, when it does not sit at the RFC 8615 path. |
| DASHBOARD_ISSUER | Required with `DASHBOARD_CLIENT_ID`: the `iss` claim the dashboard's tokens carry (its `OAuthIssuer`). Every dashboard token is checked for it; without it set the start is refused. |
| DASHBOARD_EXPECTED_SCOPE | Optional: scope required in the token. Passport's `scopes` claim is a JSON array and empty for the extension's client, so leave this unset. It applies to every client in `DASHBOARD_CLIENT_ID` alike, so a client whose tokens lack the scope is refused. |

The signing key is fetched from the JWKS document by the token header's `kid`
and cached in Redis, under the document's address and the `kid`, for the
lifetime the document's `Cache-Control` header allows (one hour when it says
nothing), so rotating the dashboard's Passport keys needs no redeploy here. A
`kid` the document does not have is remembered for a minute, so tokens with
made-up ones do not each send a request to the dashboard; a key published in
that minute is accepted once it has passed. A token without an `exp` claim is
refused.

A dashboard token names its user by the `email` claim, so it is accepted only
with `email_verified` set to `true`; without it the API answers `403`.

A dashboard behind a self-signed certificate — a local Lando one, for
instance — fails this fetch with `Failed to fetch RSA keys from issuer`. See
[Running against a dashboard on Lando](./setup.md#running-against-a-dashboard-on-lando).

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

Office tokens come from any Entra tenant, and a tenant's admin can set any address as a user's email. The API therefore takes the user from the `email` claim only when the token also carries `xms_edov: true`, which says the tenant verified the email's domain; otherwise it answers `403`. `preferred_username` is not used. The app registration has to issue both as optional claims in the access token: under **Token configuration**, add the optional claims `email` and `xms_edov` for the access token. Microsoft describes `xms_edov` in its [optional claims reference](https://learn.microsoft.com/en-us/entra/identity-platform/optional-claims-reference).

If an `Authorization: Bearer <token>` is present, the API validates the token against the configured client(s) and required scope. Alternatively, pass an `x-key` header with a valid API key mapping to a user email in Redis. For local testing you can also use `X-TESTING-AUTH: user@example.com` when `TESTING=true`.

## Running without the dashboard

Normally the dashboard's `SyncUserToNlpApi` job writes each user's config into
Redis, and a user with no config there is rejected: `/v2.0/auth` answers 403 and
clients read that as "not signed in". A deployment that runs this API on its own
has no such job, so the two settings below fill the gap.

|                        Variable | Default       | Description                                                                                                                                                                |
| ------------------------------: | :-----------: | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
|  `DEFAULT_USER_CONFIG_ENABLED`  | false         | Give a user with no stored config the defaults below instead of a 403. The `/user/configs` management endpoint still reports 404 for them, so "nothing is stored" stays visible. |
|  `DEFAULT_USER_STORE_CONTEXT`   | true          | Whether results carry the surrounding text. Reported as a suggestion when `CLIENT_CONFIG_ENABLED` is on, so a client may override it, and as a force otherwise.             |
| `DEFAULT_USER_LLM_ALTERNATIVES` | false         | Same, for LLM-generated alternatives.                                                                                                                                      |
| `DEFAULT_USER_CONFIRM_BEFORE_CHECKING` | false  | Whether clients ask before sending a field's text (`confirm_before_checking`). Always a suggestion, which the user may change; an API key's `force` keeps it on. |
|       `CLIENT_CONFIG_ENABLED`   | false         | Let a request set `store_context` and `llm_alternatives` for itself.                                                                                                       |
|                  `REQUIRE_AUTH` | true          | Whether a request has to resolve to a user before any text is checked. Off means the API answers anyone who can reach it, the [guardrail endpoints](./guardrails.md) included.                                                   |

`CLIENT_CONFIG_ENABLED` never overrules a deployment that has an opinion: a
`force` rule for either flag in a synced user or organisation config still wins.
`disabled_categories` and custom rules are unaffected — a client's
`disabled_categories` were already honoured.

Users are still identified by email, so an API-key deployment needs keys before
anyone can sign in — see [Setup & Deployment](./setup.md#api-keys).

## Optional profiling (Blackfire)

To enable continuous profiling in supported environments, set:

```bash
BLACKFIRE_ENABLE_CONTINUOUS_PROFILING=1
BLACKFIRE_APPLICATION_NAME=app
```

Blackfire is in the `profiling` dependency group (`uv sync --inexact --group profiling`; without `--inexact`, uv removes the spaCy models, which are not in the lock), not in a default install or the Docker image. If the variable is set without it, the app logs a warning at startup and runs without profiling.

Also configure Blackfire credentials in `~/.blackfire.ini` or environment variables as per Blackfire docs.

## Testing variables

These are fixtures for the test suite, which authenticates as the email they carry. They are only loaded when `TESTING` is set; a deployment that sets them without it gets an error in the log and they are ignored. That guard exists because an entry marked `"status": "force"` in either overrides what a request asks for, so a server that loaded them would quietly answer with something other than what its clients requested.

The following environment variables are used to seed test data and shortcuts when running the application in a development or test environment (for example when `REDIS_HOST` is empty and an in-memory fake Redis is used). These are loaded into `Settings` ([app/settings.py](../app/settings.py)) and applied during startup ([app/startup.py](../app/startup.py)).

|                     Variable | Default | Description                                                                                                                                                                                                                                  |
| ---------------------------: | :-----: | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
|                      TESTING |  false  | Enables testing shortcuts (e.g., `X-TESTING-AUTH` header, with which a request names its user) and disables Sentry. It is necessary for running the test suite. With `ENVIRONMENT_TYPE=production` it stops the start. Other settings listed below should be disabled while running the test suite. |
|              `TESTING_RULES` | (empty) | JSON string containing a user-level rules object. On startup the app parses this JSON and writes it to Redis under the seeded user's id (the `email` field). See `.env.example` for an example payload.                                      |
| `TESTING_ORGANIZATION_RULES` | (empty) | JSON string containing organization-level rules/config. On startup it is parsed and written to Redis under the configured organization id so the app can use organization configs during testing. See `.env.example` for an example payload. |

These variables are optional and intended for local development or CI scenarios to make it easier to test flows without external Redis or having to manually seed data.

---

## What’s configured by default

- Fake Redis in development (when no `REDIS_HOST` is provided).
- LanguageTool off; set `LANGUAGETOOL_API` to a LanguageTool server to enable it.
- Sentry disabled unless `SENTRY_DSN` is set and `TESTING` is false.
- Context checker disabled unless the per-language URL and API key are provided.

## Changing spaCy models

- Update `MODELS` in your environment to the desired packages (e.g., use `en_core_web_md`).
- Update `pyproject.toml` to include matching wheel URLs or pip names for those models.
- Reinstall dependencies so spaCy can load the specified models.

---

## See Also

- [Setup & Deployment](./setup.md) - Installation and deployment instructions
- [Request Configuration & Categories](./request-configuration.md) - Per-request configuration options
- [API Endpoints](./api.md) - Available endpoints and authentication
- Back to [📋 Documentation Index](../README.md#documentation-index)
Which one a token is checked against is decided by its `aud` claim: it has to
equal the client id of exactly one configured issuer. A token whose audience
matches nothing configured is rejected with a 401.

A token that is missing, malformed, expired, for another audience or not
signed by its issuer is answered with `401` and
`WWW-Authenticate: Bearer error="invalid_token"`, so a client may get a new one
and try again. A valid token whose user is not let in (a missing scope, an
unverified email, no config for the user at `/v2.0/auth`) is answered with
`403`. When the issuer's keys cannot be fetched the answer is `503`: that says
nothing about the token.

Dashboard (Laravel Passport)
| Variable | Description |
|---|---|
| DASHBOARD_CLIENT_ID | OAuth client id the dashboard issues tokens for; also the `aud` claim. Setting it enables this issuer. Several clients of the one dashboard, comma-separated (the browser extension's and the dashboard's write page's): a token is accepted when its `aud` is any of them. Passport issues UUIDs, such as `9a1f3c52-6d0e-4b7a-8f21-3c5d9e0b7a64, 9a1f3c5b-2e4f-4c8d-9b17-6a0e2f4d8c31`; the dashboard prints the write page's when it creates the client at its first start. |
| DASHBOARD_URL | Base URL of the dashboard. The JWKS document is looked up at `{DASHBOARD_URL}/.well-known/jwks.json`. |
| DASHBOARD_JWKS_URL | Optional: the full JWKS URL, when it does not sit at the RFC 8615 path. |
| DASHBOARD_ISSUER | Required with `DASHBOARD_CLIENT_ID`: the `iss` claim the dashboard's tokens carry (its `OAuthIssuer`). Every dashboard token is checked for it; without it set the start is refused. |
| DASHBOARD_EXPECTED_SCOPE | Optional: scope required in the token. Passport's `scopes` claim is a JSON array and empty for the extension's client, so leave this unset. It applies to every client in `DASHBOARD_CLIENT_ID` alike, so a client whose tokens lack the scope is refused. |

The signing key is fetched from the JWKS document by the token header's `kid`
and cached in Redis, under the document's address and the `kid`, for the
lifetime the document's `Cache-Control` header allows (one hour when it says
nothing), so rotating the dashboard's Passport keys needs no redeploy here. A
`kid` the document does not have is remembered for a minute, so tokens with
made-up ones do not each send a request to the dashboard; a key published in
that minute is accepted once it has passed. A token without an `exp` claim is
refused.

A dashboard token names its user by the `email` claim, so it is accepted only
with `email_verified` set to `true`; without it the API answers `403`.

A dashboard behind a self-signed certificate — a local Lando one, for
instance — fails this fetch with `Failed to fetch RSA keys from issuer`. See
[Running against a dashboard on Lando](./setup.md#running-against-a-dashboard-on-lando).

