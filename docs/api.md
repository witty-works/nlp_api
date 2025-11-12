# API Endpoints

## Table of Contents

- [Core Endpoints](#core-endpoints)
- [Management Endpoints](#management-endpoints)
  - [User Configuration](#user-configuration)
  - [Organization Configuration](#organization-configuration)
  - [API Key Management](#api-key-management)
- [Health & Utility Endpoints](#health--utility-endpoints)
- [Debug Endpoints](#debug-endpoints)
- [Slack Integration Endpoint](#slack-integration-endpoint)

---

The API provides several categories of endpoints for different purposes. All authenticated endpoints require either an API key (`x-key` header), OAuth2 Bearer token (`Authorization` header), or testing authentication (when `TESTING=true`).

## Core Endpoints

These are the main endpoints for checking and rephrasing text.

| Endpoint         | Method | Auth Required | Description                                                   |
| ---------------- | ------ | ------------- | ------------------------------------------------------------- |
| `/v2.4/check`    | POST   | Yes           | Check text for inclusive language issues and get alternatives |
| `/v1.0/rephrase` | POST   | Yes           | Rephrase text using LLM (requires plan with LLM access)       |
| `/v1.0/prompt`   | POST   | Yes           | Generate LLM prompt for inclusive language improvement        |
| `/v2.0/auth`     | POST   | Yes           | Validate authentication and retrieve user configuration       |

Example `/v2.4/check` request:

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

Example `/v1.0/rephrase` request:

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

## Management Endpoints

These endpoints manage user and organization configurations. All require HTTP Basic authentication (configured via `API_DOCS_AUTH_ENABLED`, `API_DOCS_USERNAME`, and `API_DOCS_PASSWORD`).

### User Configuration

| Endpoint                             | Method | Description                                                                 |
| ------------------------------------ | ------ | --------------------------------------------------------------------------- |
| `POST /user/configs`                 | POST   | Create or update user configuration                                         |
| `GET /user/configs?email={email}`    | GET    | Retrieve user configuration by email                                        |
| `DELETE /user/configs?email={email}` | DELETE | Delete user configuration                                                   |
| `GET /user/logs?email={email}`       | GET    | Retrieve request/response logs for user (if enabled via `REDIS_LOG_EMAILS`) |

Example: Store user configuration

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

### Organization Configuration

| Endpoint                                            | Method | Description                                 |
| --------------------------------------------------- | ------ | ------------------------------------------- |
| `POST /organization/configs`                        | POST   | Create or update organization configuration |
| `GET /organization/configs?organization_id={id}`    | GET    | Retrieve organization configuration         |
| `DELETE /organization/configs?organization_id={id}` | DELETE | Delete organization configuration           |

Example: Store organization configuration

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

### API Key Management

| Endpoint                                    | Method | Description                     |
| ------------------------------------------- | ------ | ------------------------------- |
| `POST /api_key?api_key={key}&email={email}` | POST   | Create API key mapping to email |
| `GET /api_key?api_key={key}`                | GET    | Retrieve email for API key      |
| `DELETE /api_key?api_key={key}`             | DELETE | Delete API key mapping          |

Example: Create API key

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/api_key?api_key=my-secret-key&email=user@example.com' \
  -u 'admin:password'
```

## Health & Utility Endpoints

These endpoints provide health checks and utility functions. Most do not require authentication.

| Endpoint                      | Method | Auth Required | Description                                                                       |
| ----------------------------- | ------ | ------------- | --------------------------------------------------------------------------------- |
| `/health`                     | GET    | No            | Health check endpoint. Returns status of API and optionally external dependencies |
| `/health?check_external=true` | GET    | No            | Health check including LanguageTool connectivity                                  |
| `/`                           | GET    | No            | Root endpoint. In dev, redirects to `/docs`. In prod, returns API info            |
| `/docs`                       | GET    | Optional*     | Interactive Swagger UI documentation                                              |
| `/openapi.json`               | GET    | Optional*     | OpenAPI schema JSON                                                               |

\* Requires HTTP Basic auth if `API_DOCS_AUTH_ENABLED=true`

Example health check:

```bash
curl 'http://127.0.0.1:8000/health?check_external=true'
```

Response:

```json
{
  "status": "healthy",
  "languagetool": "connected"
}
```

## Debug Endpoints

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

Example: Test a specific rule

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

Example: Lemmatize a word

```bash
curl 'http://127.0.0.1:8000/lemmatize?text=running&lang=en' \
  -u 'admin:password'
```

## Slack Integration Endpoint

Available only when `SLACK_ENABLED=true`.

| Endpoint          | Method | Auth Required   | Description                          |
| ----------------- | ------ | --------------- | ------------------------------------ |
| `/slack/commands` | POST   | Slack signature | Handles Slack `/witty` slash command |

The `/witty` command in Slack allows users to check text for inclusive language directly in Slack channels. Configure your Slack app to send slash commands to this endpoint.
