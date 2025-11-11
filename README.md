# NLP API

The NLP uses spaCy to deconstruct sentences and apply rules for inclusive language stored in an in-memory SQLite database.
It can also use LanguageTool.org for spellchecking and grammar.

The diversity dimensions covered in the rules are documented here: https://www.witty.works/en/categories.html

While the code can generate alternatives in the correct grammar form, it can optionally also use an LLM for this purpose which may provide more reliable results, especially for French.

It can also be used to improve inclusive language in LLMs by prompt-injection as well as generation of follow up prompts to address issues in the initial LLM generated response.

Finally it is possible to store simple custom rules that can be used to for example maintain an organization specific set of rules related to any topic.

## Technical Notes

Review the API docs for details on how to store user/organization configuration to be able to customize the behavior of the application. Some of those management endpoints are optionally protected via HTTP basic. The non management part of the API is protected using either OAuth2 or API Keys.

The API is based on FastAPI (https://fastapi.tiangolo.com) and works best when using the large spaCy models (https://spacy.io). It should also work with the smaller models but will then cause more false positives. The transformer models tend to provide even better results. However not all of them contain NER data, which is used for some false positive detection. So adopting the transformer models would require disabling those code paths or integration of a different solution for NER.

As the API uses the default spaCy models there are however still issues with detection of what is a verb, adjective, noun etc. To handle this to some degree the `model._fetch_word_type()` methods uses some static "rules" to correct some common mistake. A better approach would be to retrain/finetune the models on the specific words/phrases used in the rules database.

While the NLP API can work with any LanguageTool instance, there are some customizations, specifically words to ignore that ideally should be added, which can be found in the "languagetool" subdirectory. That being said, updating this ignore file is tedious. There used to be a script for this, which could be restored https://github.com/witty-works/nlp_api/commit/125712651446308a27fee4d7c69c918f3e682ee5

---

# Configuration

The API is configured via environment variables (loaded from a local .env file and the process environment using pydantic-settings). Below you’ll find all relevant options with defaults, what they do, and sample configs for local, Docker, and Platform.sh deployments.

Notes

- For macOS development with spaCy, copy the provided snippet to avoid MKL warnings: cp .env.development.mac .env
- If you want to use smaller spaCy models, update BOTH the MODELS setting and pyproject.toml (so the model wheels are available) before installing dependencies.

## Quick start: minimal .env for local dev

```
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
| TERMS_OF_SERVICE            | https://www.witty.works/privacy                        | Link surfaced in OpenAPI metadata.                                                                                 |
| CONTACT                     | support@witty.works                                    | Contact email in OpenAPI metadata.                                                                                 |
| TESTING                     | false                                                  | Enables testing shortcuts (e.g., `X-TESTING-AUTH` header) and disables Sentry.                                     |
| MODELS                      | ["en_core_web_lg","de_core_news_lg","fr_core_news_lg"] | spaCy models to load. If you change these, also align `pyproject.toml` dependencies.                               |
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

Reduces false positives by checking rule hits in their sentence context via an external service. Configure per-language endpoints and Bearer API keys. If not provided, context checking is skipped.

| Variable                                            | Description                       |
| --------------------------------------------------- | --------------------------------- |
| CONTEXT_CHECKER_URL / CONTEXT_CHECKER_API_KEY       | Endpoint and API key for English. |
| CONTEXT_CHECKER_URL_DE / CONTEXT_CHECKER_API_KEY_DE | Endpoint and API key for German.  |
| CONTEXT_CHECKER_URL_FR / CONTEXT_CHECKER_API_KEY_FR | Endpoint and API key for French.  |

Request format: the service receives `{ "data": ["sentence 1", "sentence 2", ...] }` and must return a list where each item is "1" to keep the match or any other value to discard it for that sentence.

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

```
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

# Installation instructions (with python3.12)

## Using pdm

```
pdm venv create 3.12
pdm use
pdm venv activate
pdm sync --dev
wget -P training_data https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin
```

## Using Docker

1. Install Docker engine - https://docs.docker.com/engine/install/
2. Pull images from Azure container registry:

```
az login
az acr login --name wittyworks
docker pull wittyworks.azurecr.io/nlpapi:main
docker pull wittyworks.azurecr.io/languagetool:main
```

3. Run images:

First run the LanguageTool image:

```
docker run --rm --name lt -p 8000:8000 wittyworks.azurecr.io/languagetool:main
```

Open another terminal tab and check LanguageTool container local address:

```
lt_api=`docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' lt`
```

As a last step run the NLP API image:

```
docker run --rm --name nlp_api -p 8080:8080 --network "bridge" --env languagetool_api="$lt_api/v2" wittyworks.azurecr.io/nlpapi:main
```

You should see the application running under http://localhost:8080/docs

## Update dependencies locally

To update packages locally after pyproject.toml/pdm.lock was changed, run the
command:

```
pdm sync --dev
```

## Add new package

When adding a new package to the project, you need to update the existing
pyproject.toml. The following command will install the package and add it to the
`pyproject.toml/pdm.lock`:

```
pdm add <package_name>
```

## Docker image

### Build Docker image:

After making changes in the code or in the Dockerfile, you can run the local
setup. Build new image with the following commands:

```
pdm export --prod -o requirements.txt
DOCKER_BUILDKIT=0 docker build -t nlpapi . --no-cache
docker run nlpapi
```

## Install Platform.sh CLI

- Run `platform login`
- Run `platform project:set-remote`
- Run `platform list` to find out what commands are available
- Run `platform help [command]` to find out details about a command

see https://docs.platform.sh/development/cli.html for details

### Adjust size on platform.sh

Adjust server size:

```
platform e:curl -e main /deployments/next -X PATCH -d '{"webapps":
  {"app": {"resources": {"profile_size": "8"}},"languagetool": {"resources": {"profile_size": "4"}}}}'
```

Adjust instance count:

```
platform e:curl -e main /deployments/next -X PATCH -d '{"webapps":
  {"app": {"resources": {"instance_count": "2"}},"languagetool": {"resources": {"instance_count": "2"}}}}'
```

## Run Locally

---

Note for the Mac users. Set environment variables with the following snippet:

```
cp .env.development.mac .env
```

---

```
pdm run uvicorn app.main:app --reload
```

or

```
uvicorn app.main:app --reload
```

Open your browser to http://localhost:8000/docs to view the OpenAPI UI.

For an alternate view of the docs navigate to http://localhost:8000/redoc

## Profiling locally with Blackfire

```
pdm run blackfire-python uvicorn app.main:app --reload
```

Make sure you have a `.blackfire.ini`, get the settings from
https://blackfire.io/docs/php/configuration

```
BLACKFIRE_SERVER_ID=""
BLACKFIRE_SERVER_TOKEN=""
```

## Production Deployment

Set an env variable `API_DOCS_AUTH_ENABLED` to `"true"` and for the
username/password called `API_DOCS_USERNAME` and `API_DOCS_PASSWORD` for basic
auth for the API docs.

If the build fails due to "No space left on device" while installing the
dependencies run:

```
platform project:clear-build-cache
```

see:
https://docs.platform.sh/development/troubleshoot.html#clear-the-build-cache

## API Endpoints

The API provides several categories of endpoints for different purposes. All authenticated endpoints require either an API key (`x-key` header), OAuth2 Bearer token (`Authorization` header), or testing authentication (when `TESTING=true`).

### Core Endpoints

These are the main endpoints for checking and rephrasing text.

| Endpoint         | Method | Auth Required | Description                                                   |
| ---------------- | ------ | ------------- | ------------------------------------------------------------- |
| `/v2.4/check`    | POST   | Yes           | Check text for inclusive language issues and get alternatives |
| `/v1.0/rephrase` | POST   | Yes           | Rephrase text using LLM (requires plan with LLM access)       |
| `/v1.0/prompt`   | POST   | Yes           | Generate LLM prompt for inclusive language improvement        |
| `/v2.0/auth`     | POST   | Yes           | Validate authentication and retrieve user configuration       |

**Example `/v2.4/check` request:**

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/v2.4/check' \
  -H 'x-key: your-api-key' \
  -H 'Content-Type: application/json' \
  -d '{
  "text": "The chairman called the policeman.",
  "lang": "en"
}'
```

**Example `/v1.0/rephrase` request:**

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/v1.0/rephrase' \
  -H 'x-key: your-api-key' \
  -H 'Content-Type: application/json' \
  -d '{
  "text": "The chairman called the policeman.",
  "lang": "en",
  "config": {
    "llm_alternatives": true
  }
}'
```

### Management Endpoints

These endpoints manage user and organization configurations. All require HTTP Basic authentication (configured via `API_DOCS_AUTH_ENABLED`, `API_DOCS_USERNAME`, and `API_DOCS_PASSWORD`).

#### User Configuration

| Endpoint                             | Method | Description                                                                 |
| ------------------------------------ | ------ | --------------------------------------------------------------------------- |
| `POST /user/configs`                 | POST   | Create or update user configuration                                         |
| `GET /user/configs?email={email}`    | GET    | Retrieve user configuration by email                                        |
| `DELETE /user/configs?email={email}` | DELETE | Delete user configuration                                                   |
| `GET /user/logs?email={email}`       | GET    | Retrieve request/response logs for user (if enabled via `REDIS_LOG_EMAILS`) |

**Example: Store user configuration**

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/user/configs' \
  -u 'admin:password' \
  -H 'Content-Type: application/json' \
  -d '{
  "email": "user@example.com",
  "organization_id": "org-123",
  "config": {
    "german_gender_ending": ":in",
    "preferred_variants": ["de-CH"]
  },
  "false_positives": ["DataOps", "DevOps"],
  "term_replacements": {
    "mankind": {
      "alternatives": ["humankind", "humanity"],
      "explanation": "Use gender-neutral alternatives"
    }
  }
}'
```

#### Organization Configuration

| Endpoint                                            | Method | Description                                 |
| --------------------------------------------------- | ------ | ------------------------------------------- |
| `POST /organization/configs`                        | POST   | Create or update organization configuration |
| `GET /organization/configs?organization_id={id}`    | GET    | Retrieve organization configuration         |
| `DELETE /organization/configs?organization_id={id}` | DELETE | Delete organization configuration           |

**Example: Store organization configuration**

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/organization/configs' \
  -u 'admin:password' \
  -H 'Content-Type: application/json' \
  -d '{
  "id": "org-123",
  "name": "Acme Corp",
  "config": {
    "gendered_roles_format": "inclusive_gender",
    "disabled_categories": ["age"]
  }
}'
```

#### API Key Management

| Endpoint                                    | Method | Description                     |
| ------------------------------------------- | ------ | ------------------------------- |
| `POST /api_key?api_key={key}&email={email}` | POST   | Create API key mapping to email |
| `GET /api_key?api_key={key}`                | GET    | Retrieve email for API key      |
| `DELETE /api_key?api_key={key}`             | DELETE | Delete API key mapping          |

**Example: Create API key**

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/api_key?api_key=my-secret-key&email=user@example.com' \
  -u 'admin:password'
```

### Health & Utility Endpoints

These endpoints provide health checks and utility functions. Most do not require authentication.

| Endpoint                      | Method | Auth Required | Description                                                                       |
| ----------------------------- | ------ | ------------- | --------------------------------------------------------------------------------- |
| `/health`                     | GET    | No            | Health check endpoint. Returns status of API and optionally external dependencies |
| `/health?check_external=true` | GET    | No            | Health check including LanguageTool connectivity                                  |
| `/`                           | GET    | No            | Root endpoint. In dev, redirects to `/docs`. In prod, returns API info            |
| `/docs`                       | GET    | Optional\*    | Interactive Swagger UI documentation                                              |
| `/openapi.json`               | GET    | Optional\*    | OpenAPI schema JSON                                                               |

\* Requires HTTP Basic auth if `API_DOCS_AUTH_ENABLED=true`

**Example health check:**

```bash
curl 'http://127.0.0.1:8000/health?check_external=true'
```

**Response:**

```json
{
  "status": "healthy",
  "languagetool": "connected"
}
```

### Debug Endpoints

Debug endpoints are only available when `PLATFORM_ENVIRONMENT_TYPE != "production"`. They provide additional testing and debugging capabilities.

| Endpoint               | Method | Auth Required | Description                                  |
| ---------------------- | ------ | ------------- | -------------------------------------------- |
| `/debug/check`         | POST   | Yes           | Check text with additional debug information |
| `/debug/rephrase`      | POST   | Yes           | Rephrase text with debug output              |
| `/debug/prompt`        | POST   | Yes           | Generate prompt with debug information       |
| `/debug/review_prompt` | POST   | Yes           | Generate review prompt for LLM output        |
| `/debug/rule`          | POST   | Yes           | Test a specific rule against text            |
| `/lemmatize`           | GET    | Yes           | Get lemma form of a word                     |
| `/tokenize`            | GET    | Yes           | Tokenize text using spaCy                    |
| `/settings`            | GET    | Yes           | View current server settings                 |
| `/lt`                  | GET    | Yes           | View LanguageTool API URL                    |
| `/save_openapi_json`   | GET    | Yes           | Export OpenAPI schema to file                |

**Example: Test a specific rule**

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/debug/rule' \
  -u 'admin:password' \
  -H 'Content-Type: application/json' \
  -d '{
  "text": "The chairman is here.",
  "lang": "en",
  "rule": {
    "trigger": "chairman",
    "alternatives": ["chair", "chairperson"],
    "category": "gender"
  }
}'
```

**Example: Lemmatize a word**

```bash
curl 'http://127.0.0.1:8000/lemmatize?text=running&lang=en' \
  -u 'admin:password'
```

### Slack Integration Endpoint

Available only when `SLACK_ENABLED=true`.

| Endpoint          | Method | Auth Required   | Description                          |
| ----------------- | ------ | --------------- | ------------------------------------ |
| `/slack/commands` | POST   | Slack signature | Handles Slack `/witty` slash command |

The `/witty` command in Slack allows users to check text for inclusive language directly in Slack channels. Configure your Slack app to send slash commands to this endpoint.

## Request Configuration

The `/check` endpoint accepts an optional `config` object that allows you to customize the behavior of the inclusive language checker on a per-request basis. This configuration can override stored user/organization settings or provide settings when no stored configuration exists.

### Authentication

The API supports multiple authentication methods for accessing protected endpoints like `/check`, `/rephrase`, and other core features.

#### API Key Authentication

Pass an API key using the `x-key` header. API keys are managed through the `/api_key` endpoints and stored in Redis, mapping to user email addresses.

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/v2.4/check' \
  -H 'x-key: your-api-key-here' \
  -H 'Content-Type: application/json' \
  -d '{
  "text": "Your text to check"
}'
```

**Managing API Keys:**

- `POST /api_key` - Create a new API key for a user email
- `GET /api_key/{email}` - Retrieve API key for an email
- `DELETE /api_key/{email}` - Delete API key for an email

These management endpoints require HTTP Basic authentication (see [API docs protection](#api-docs-protection)).

#### OAuth2 Bearer Token Authentication

The API supports OAuth2 Bearer token authentication through two providers:

**1. Azure AD B2C (Single-tenant)**

Used for organization-specific authentication. Configure using environment variables:

- `AADB2C_TENANT_ID` - Your B2C tenant ID
- `AADB2C_CLIENT_ID` - Application client ID
- `AADB2C_POLICY` - User flow/policy name
- `AADB2C_DOMAIN` - B2C domain
- `AADB2C_EXPECTED_SCOPE` - Required scope (e.g., `access_as_user`)

**2. Microsoft Office SSO (Multi-tenant)**

Used for Office 365 / Microsoft 365 integrations. Configure using:

- `OFFICE_SSO_CLIENT_ID` - Application client ID
- `OFFICE_SSO_EXPECTED_SCOPE` - Required scope

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/v2.4/check' \
  -H 'Authorization: Bearer your-oauth-token-here' \
  -H 'Content-Type: application/json' \
  -d '{
  "text": "Your text to check"
}'
```

The API validates the token against the configured provider(s) and required scopes.

#### Testing Authentication (Development Only)

When `TESTING=true` is set in environment variables, you can use a special header for testing without real authentication:

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/v2.4/check' \
  -H 'X-TESTING-AUTH: user@example.com' \
  -H 'Content-Type: application/json' \
  -d '{
  "text": "Your text to check"
}'
```

**⚠️ Warning**: This bypass is only active when `TESTING=true` and should NEVER be enabled in production environments.

#### Authentication Priority

When multiple authentication methods are provided, the API checks them in this order:

1. OAuth2 Bearer token (if `Authorization` header is present)
2. API Key (if `x-key` header is present)
3. Testing header (if `TESTING=true` and `X-TESTING-AUTH` is present)

#### Unauthenticated Endpoints

Some endpoints do not require authentication:

- Health checks and status endpoints
- Public documentation (`/docs`, `/redoc`) - unless `API_DOCS_AUTH_ENABLED=true`
- OpenAPI schema (`/openapi.json`) - unless `API_DOCS_AUTH_ENABLED=true`

### Basic Config Structure

The `config` object in a `/check` request supports the following options.

#### Context and Storage

| Field              | Type    | Default |
| ------------------ | ------- | ------- |
| `store_context`    | boolean | `true`  |
| `llm_alternatives` | boolean | `false` |

**`store_context`**: When true, includes surrounding text context (±100 chars) in results. Context is sanitized for privacy. Clients use this flag to decide whether to persist data with analytics.

**`llm_alternatives`**: Enable LLM-powered grammatically correct alternatives (requires plan with LLM access).

#### Plan and Features

| Field    | Type             | Default |
| -------- | ---------------- | ------- |
| `plan`   | string           | `null`  |
| `addons` | array of strings | `null`  |

**`plan`**: Plan identifier (e.g., "premium", "enterprise").

**`addons`**: List of enabled addon features.

#### Language Settings

| Field                 | Type           | Default                       |
| --------------------- | -------------- | ----------------------------- |
| `primary_language`    | enum           | `null`                        |
| `preferred_languages` | array of enums | `["en", "de", "fr"]`          |
| `preferred_variants`  | array of enums | `["en-US", "de-DE", "fr-FR"]` |

**`primary_language`**: Primary language variant. Supported values: `"en"`, `"de"`, `"fr"`, `"en-US"`, `"en-GB"`, `"de-DE"`, `"de-CH"`, `"de-AT"`, `"fr-FR"`, or `"auto"` for automatic detection.

**`preferred_languages`**: Languages to check. Supported values: `"en"`, `"de"`, `"fr"`.

**`preferred_variants`**: Language variants for spelling/grammar. Supported values: `"en-US"`, `"en-GB"`, `"de-DE"`, `"de-CH"`, `"de-AT"`, `"fr-FR"`.

#### Gender-Inclusive Formatting

| Field                     | Type | Default  |
| ------------------------- | ---- | -------- |
| `german_gender_ending`    | enum | `"*in"`  |
| `french_gender_separator` | enum | `"·"`    |
| `gendered_roles_format`   | enum | `"both"` |

**`german_gender_ending`**: German gender-inclusive ending format. Supported values:

- `"*in"` - Star/Asterisk (e.g., `Lehrer*in`)
- `"_in"` - Underscore (e.g., `Lehrer_in`)
- `":in"` - Colon (e.g., `Lehrer:in`)
- `"/in"` - Slash (e.g., `Lehrer/in`)
- `"/-in"` - Slash-Dash (e.g., `Lehrer/-in`)
- `"In"` - Capital Letter (e.g., `LehrerIn`)
- `"()"` - Parenthesis (e.g., `Lehrer(in)`)
- `"(-)"` - Parenthesis-Dash (e.g., `Lehrer(-in)`)

**`french_gender_separator`**: French gender-inclusive separator format (Point médian). Supported values:

- `"·"` - Point médian (e.g., `auteur·rice`)
- `"·s"` - Point médian with S (e.g., `auteur·rice·s`)
- `"."` - Point (e.g., `auteur.rice`)
- `".s"` - Point with S (e.g., `auteur.rice.s`)
- `"/"` - Slash (e.g., `auteur/rice`)
- `"/s"` - Slash with S (e.g., `auteur/rice/s`)

**`gendered_roles_format`**: How to suggest gendered role alternatives. Supported values:

- `"none"` - No gendered role alternatives
- `"both"` - Show both inclusive and binary gender alternatives
- `"inclusive_gender"` - Show only gender-inclusive alternatives (e.g., "firefighter" instead of "fireman")
- `"binary_gender"` - Show only binary gender alternatives (e.g., "fireman/firewoman")

#### Category and Alternative Settings

| Field                           | Type             | Default |
| ------------------------------- | ---------------- | ------- |
| `disabled_categories`           | array of strings | `[]`    |
| `show_inspiration_alternatives` | boolean          | `false` |
| `alternatives_max_count`        | integer          | `null`  |

**`disabled_categories`**: List of category names to disable (e.g., ["orthography", "gender"]). See [supported categories](#supported-categories) below.

**`show_inspiration_alternatives`**: Include inspirational (💡) suggestions in alternatives.

**`alternatives_max_count`**: Maximum number of alternatives to return per result (defaults to server setting).

### Supported Categories

The API checks text against multiple diversity dimensions and language categories. You can selectively disable categories using the `disabled_categories` configuration option.

#### Finding Available Categories

The complete list of supported categories can be found in multiple locations:

1. **Public Documentation** (with explanations and examples):

   - English: https://www.witty.works/en/categories.html
   - German: https://www.witty.works/de/kategorien.html
   - French: https://www.witty.works/fr/categories.html

2. **Source Code** (technical reference):

   - [`training_data/categories.json`](training_data/categories.json) - Main category definitions with translations, proficiency levels, and metadata
   - [`training_data/diversity_dimension_drivers.json`](training_data/diversity_dimension_drivers.json) - Additional diversity dimension drivers
   - [`app/categories.py`](app/categories.py) - Category logic, utilities, and helper functions

3. **API Documentation** (interactive):
   - OpenAPI/Swagger UI at `/docs` (when running locally or in production)
   - The `/docs` endpoint provides interactive documentation with all available configuration options

#### Common Categories

The API organizes checks using **subcategories** (diversity dimension drivers) defined in `diversity_dimension_drivers.json`. Each subcategory belongs to a top-level category defined in `categories.json`.

**Top-level categories** (from `categories.json`):

- `cultural-diversity` - Biases and stereotypes surrounding ethnicity, nationality, and race; language barriers in multilingual environments
- `gender-orientation` - Gender-inclusive language, sexual orientation, and representation of marginalized genders
- `ability-physicality` - Ableist language, disability-related terminology, and physicality biases
- `religion` - Faith-based expressions, antisemitism, and anti-muslim language
- `acquired-diversity` - Age, education, socioeconomic status, and other acquired characteristics
- `social-motive` - Language that promotes collaboration vs. competition, community vs. individualism

**Subcategories** (examples from `diversity_dimension_drivers.json`):

- Under `gender-orientation`: `gender_identity`, `gender_specific_abbreviation`, `gendered_denominations_ending`, `LGBTQIA-hate`, `homophobia`, `sexism`, `transphobia`, `binary_pronouns`, `female_stereotype`, `male_stereotype`, `leadership`, `sexual_orientation`, `titles`, `function`, `hidden_image`
- Under `cultural-diversity`: `abbreviation`, `anglicism`, `filler`, `hollow`, `plain_language`, `color`, `racist_source`, `culture`, `migration`, `nazi_language`, `yiddish-pejoratives`, `racism`, `xenophobia`
- Under `ability-physicality`: `ability`, `physicality`, `ableism`, `behavior`, `medical_state`, `mobility`, `cognitive_ability`, `cognitive_perception`, `hearing`, `learning`, `mental_wellbeing`, `speech`, `vision`
- Under `religion`: `antimuslim`, `antisemitism`, `belief`
- Under `acquired-diversity`: `age`, `age_old`, `age_young`, `classism`, `formality`
- Under `social-motive`: `agentic`, `exaggerating`, `military_source`, `sports_terms`, `communal`, `d_and_i`, `emotional_security`, `offensive_language`

To disable specific checks, use subcategory names in the `disabled_categories` configuration field.

**Note on proficiency levels**: Most subcategories have both basic and `_advanced` variations (e.g., `ability` and `ability_advanced`). However, subcategories with proficiency level `inclusive` (such as `communal`, `d_and_i`, `emotional_security`) or `openly_discriminating` (such as `ableism`, `racism`, `sexism`, `transphobia`, `homophobia`, `antisemitism`, `antimuslim`, `xenophobia`) do NOT have `_advanced` variations - they only exist in their base form.

**Note**: Category names may include subcategories and can have an `_advanced` suffix for advanced proficiency level checks. Refer to the categories documentation or source files for the complete and up-to-date list.

### Example API Calls

#### Basic check without configuration

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/v2.4/check' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "text": "Wer sind unsere Kunden?"
}'
```

#### Check with automatic language detection

The API automatically detects the language when no `lang` parameter is provided (or when `lang: "auto"` is explicitly set). The detection uses fastText language identification and respects your `preferred_languages` and `preferred_variants` configuration.

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/v2.4/check' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "text": "The chairman called a meeting with the policeman."
}'
```

You can also explicitly specify a language to override detection:

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/v2.4/check' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "text": "Wer sind unsere Kunden?",
  "lang": "de-DE"
}'
```

Supported language codes:

- `"auto"` - Automatic detection (default)
- `"en"` - English (uses default variant from config)
- `"de"` - German (uses default variant from config)
- `"fr"` - French (uses default variant from config)
- `"en-US"` - English (US spelling)
- `"en-GB"` - English (UK spelling)
- `"de-DE"` - German (Germany)
- `"de-CH"` - German (Switzerland)
- `"de-AT"` - German (Austria)
- `"fr-FR"` - French (France)

**How automatic detection works:**

1. The API uses a fastText model to identify the language(s) in the text
2. It filters detected languages to only those in `preferred_languages` (defaults to en, de, fr)
3. If `preferred_variants` is configured, it selects the matching variant (e.g., "en-GB" over "en-US")
4. Otherwise, it uses the default variant for the detected language
5. If no supported language is detected, the request fails with an error

#### Check with custom configuration

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/v2.4/check' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "text": "The fireman helped the chairman organize the meeting.",
  "lang": "en",
  "config": {
    "store_context": false,
    "preferred_variants": ["en-GB"],
    "gendered_roles_format": "inclusive_gender",
    "show_inspiration_alternatives": true,
    "alternatives_max_count": 3
  }
}'
```

#### Check German text with specific gender ending

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/v2.4/check' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "text": "Unsere Mitarbeiter sind sehr engagiert.",
  "lang": "de",
  "config": {
    "german_gender_ending": ":in",
    "preferred_variants": ["de-CH"]
  }
}'
```

#### Check with disabled categories

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/v2.4/check' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "text": "The policeman arrested the suspect.",
  "config": {
    "disabled_categories": ["orthography"]
  }
}'
```

### Configuration Precedence

When a `/check` request is made with authentication (via API key or OAuth token):

1. **Request config**: Settings provided in the request `config` object take highest priority
2. **User config**: User-specific settings stored in Redis
3. **Organization config**: Organization-level settings (if user belongs to an organization)
4. **Default config**: Server defaults as documented above

Settings are merged with this precedence, meaning you can override specific fields per request while keeping other settings from stored configurations.

### Stored Configuration via Management API

Instead of passing configuration with each request, you can store user and organization configurations using the configuration management endpoints. See the API documentation at `/docs` for:

- `POST /user` - Store user configuration
- `GET /user/{email}` - Retrieve user configuration
- `POST /organization` - Store organization configuration
- `GET /organization/{id}` - Retrieve organization configuration

These endpoints require HTTP Basic authentication (configured via `API_DOCS_AUTH_ENABLED`, `API_DOCS_USERNAME`, and `API_DOCS_PASSWORD` environment variables).

Stored configurations support additional features beyond the request `config` object:

- **False positives**: List of terms/phrases to ignore globally
- **Term replacements**: Custom replacement rules with explanations
- **Domain restrictions**: Allowlist or denylist of domains where the checker should operate
- **Config versioning**: `config_hash` and `sync_date` for cache invalidation

### Privacy and Context Sanitization

When `store_context` is enabled (the default), the API includes surrounding text context (±100 characters) in the response. This context is automatically sanitized to protect user privacy before being included in results or sent to external services (like Sentry for error reporting).

#### What Gets Sanitized

The privacy filter automatically replaces sensitive information with placeholder tokens:

| Sensitive Data  | Replacement | Example                                  |
| --------------- | ----------- | ---------------------------------------- |
| Email addresses | `<EMAIL>`   | `john.doe@example.com` → `<EMAIL>`       |
| URLs            | `<URL>`     | `https://www.example.com/path` → `<URL>` |
| Numbers         | `<NUMBER>`  | `Invoice 12345` → `Invoice <NUMBER>`     |

#### Where Sanitization Applies

Privacy filtering is applied to:

1. **Context fields** in check results (when `store_context` is enabled)
2. **Error reports** sent to Sentry (all request data is sanitized)
3. **Request/response logs** stored in Redis (when enabled via `REDIS_LOG_EMAILS`)

#### Implementation Details

The privacy filter uses sophisticated regular expressions to identify:

- **Emails**: Standard email formats including subdomains and international TLDs
- **URLs**: HTTP/HTTPS URLs, IP addresses (IPv4 and IPv6), localhost, and internationalized domain names
- **Numbers**: Any sequence of digits (to protect account numbers, IDs, phone numbers, etc.)

The original text being checked is **never** sanitized - only metadata like context, error reports, and logs undergo privacy filtering.

#### Disabling Context Storage

To prevent context from being stored entirely (e.g., for maximum privacy), set `store_context: false` in your request configuration:

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/v2.4/check' \
  -H 'Content-Type: application/json' \
  -d '{
  "text": "Your text here",
  "config": {
    "store_context": false
  }
}'
```

When disabled, the `context` field in results will be `null`, and clients typically won't persist analytics data for that request.

## Run tests

To run the entire test suite

```
pdm run pytest -vv
```

To only run the last failing tests

```
pdm run pytest -vv --lf
```

To update the fixtures with the current API responses run

```
pdm run pytest --snapshot-update
```

Make sure to review the changes if they are indeed intended before committing!

## Incorrect/Missing German Articles

See https://www.verbformen.de/deklination/pronomen and update
./training_data/de-DE/articles.csv accordingly.
