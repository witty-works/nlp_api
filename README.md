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

## Example API call

```
curl -X 'POST' \
  'http://127.0.0.1:8000/v2.4/check' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "text": "Wer sind unsere Kunden?"
}'
```

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
