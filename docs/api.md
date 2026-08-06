# API Endpoints

## Table of Contents

- [Core Endpoints](#core-endpoints)
- [LanguageTool-compatible API](#languagetool-compatible-api)
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
| `/v1.0/rephrase` | POST   | Yes           | Rephrase text using LLM (requires `llm_alternatives`)         |
| `/v1.0/prompt`   | POST   | Yes           | Generate LLM prompt for inclusive language improvement        |
| `/v2.0/auth`     | POST   | Yes           | Validate authentication and retrieve user configuration       |
| `/v2.0/categories` | GET  | No            | List the category keys `config.disabled_categories` accepts   |
| `/v2.0/config-options` | GET | No        | List the values the enumerated `config` fields accept         |

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

Example `/v2.0/categories` request:

```bash
curl 'http://127.0.0.1:8000/v2.0/categories?locale=de-DE'
```

```jsonc
{
  "categories": [
    {
      "key": "sexism",
      "label": "Sexismus",
      "parent": "gender-orientation",
      "advanced_key": "sexism_advanced",   // null where there is no variant
      "proficiency_level": "unconscious_bias"
    }
    // ...
  ],
  "groups": [{ "key": "gender-orientation", "label": "Gender + Orientation" }]
}
```

`/v2.0/auth` only reports the categories the dashboard synced into a user's
organization config, so this endpoint is how a deployment without a dashboard
tells clients what they may switch off. The list comes from the training data
and is therefore the same either way. `locale` accepts the same values as
`preferred_variants` and only affects the labels; keys and grouping do not
change. Labels are empty for categories that carry no translation.

**A category and its `advanced_key` are matched independently.** A result
comes back under whichever one fired, and disabling `sexism` leaves
`sexism_advanced` firing. One checkbox on an options page therefore has to
put **both** keys in `config.disabled_categories`:

```js
const off = [category.key, category.advanced_key].filter(Boolean);
```

Splitting them is what lets a deployment offer the stricter variant as its
own setting; the dashboard does exactly that.

No authentication: the answer is identical for everyone and says nothing about
any user. It is served with `Cache-Control: public, max-age=3600`, so clients
and any proxy can hold a copy instead of asking per user.

Example `/v2.0/config-options` request:

```bash
curl 'http://127.0.0.1:8000/v2.0/config-options'
```

```jsonc
{
  "options": {
    "german_gender_ending": {
      "values": ["/in", "/-in", "_in", "*in", ":in", "(-)", "()", "In"],
      "default": "*in",
      "labels": { "*in": "Genderstar, f.e Expert*in" }   // one per value
    },
    "french_gender_separator": {
      "values": ["·", "·s", ".", ".s", "/", "/s"],
      "default": "·"
    },
    "gendered_roles_format": {
      "values": ["none", "both", "inclusive_gender", "binary_gender"],
      "default": "both"
    }
  }
}
```

The `config` fields whose accepted values a client cannot guess — each is a
closed set of tokens rather than a boolean or free text. The values are read off
the request model itself, so the answer is what the running version accepts
rather than what was documented at some point. Unauthenticated and cacheable for
the same reason as the category list.

`labels` follows `locale`, and is the same wording the dashboard shows for the
same setting — both read
[training_data/config_options.json](../training_data/config_options.json),
which is copied from the dashboard's `resources/lang/*/guidelines.php`. A value
the dashboard has no wording for is returned without a label, and a client shows
the raw value.

See [Request Configuration](./request-configuration.md#gender-inclusive-formatting)
for what each value renders as.

## LanguageTool-compatible API

The service also speaks the [LanguageTool HTTP API v2
protocol](https://languagetool.org/http-api/), so any LanguageTool client with
a custom-server setting — the desktop app, the browser add-on, editor plugins —
can be pointed at this API and get the Witty checks rendered as LanguageTool
matches.

The endpoints live under the `/lt` prefix so they stay apart from the
versioned native API. LanguageTool clients append `/v2/check` to the
configured server URL, so enter `https://<host>/lt` (or `https://<host>/lt/v2`
where the client expects the URL including `/v2`) as the custom server.

Some clients cannot be given a path at all. For those, set
`LANGUAGETOOL_COMPAT_ROOT=true` (off by default) and the same endpoints are
additionally served at the root, the exact path layout of a real LanguageTool
server: `/v2/check`, `/v2/languages`, and so on. This does not collide with
the native API, whose paths (`/v2.4/check`, `/v2.0/auth`) are distinct.

The desktop app's localhost mode is the strictest case: it offers no URL, path
or port input and expects a server at LanguageTool's standard local port 8081.
To serve it, enable `LANGUAGETOOL_COMPAT_ROOT` and run the API on that port —
`uvicorn app.main:app --port 8081`, or map the container port with
`8081:8000` — with nothing else (such as a real local LanguageTool server)
bound to 8081.

| Endpoint                | Method | Auth Required | Description                                          |
| ----------------------- | ------ | ------------- | ---------------------------------------------------- |
| `/lt/v2/check`          | POST   | Yes           | Check text, LanguageTool request/response format     |
| `/lt/v2/languages`      | GET    | No            | List supported languages                             |
| `/lt/v2/maxtextlength`  | GET    | No            | The check text length limit, as plain text           |
| `/lt/v2/info`           | GET    | No            | Software name and version                            |
| `/lt/v2/words`          | GET    | No            | Personal dictionary stub: always `{"words": []}`     |
| `/lt/v2/words/add`      | POST   | No            | Personal dictionary stub: always `{"added": false}`  |
| `/lt/v2/words/delete`   | POST   | No            | Personal dictionary stub: always `{"deleted": false}` |

(With `LANGUAGETOOL_COMPAT_ROOT` the same endpoints exist without the `/lt`
prefix.)

Example request (form-encoded, as LanguageTool clients send it):

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/lt/v2/check' \
  --data-urlencode 'text=The chairman called.' \
  --data-urlencode 'language=en-US' \
  --data-urlencode 'apiKey=your-api-key'
```

Notes on how the protocol is mapped:

- **Authentication** uses the protocol's own `apiKey` form field (most clients
  offer a username/API-key setting next to the server URL), carrying the same
  key the `x-key` header takes on the native API; `username` is accepted but
  the key alone identifies the user. The `x-key` header and a Bearer token also
  work for clients that can send headers. An **invalid** key gets the same 401
  `AuthException` the LanguageTool server sends, so a mistyped key surfaces in
  the client; LanguageTool's `password` and `tokenV2` login styles are answered
  with a 401 explaining that only API keys are supported. A request without any
  credentials gets an empty match list rather than an error, as on the native
  endpoint. Where `REQUIRE_AUTH` is off, all of these check anonymously
  instead, mirroring LanguageTool's fall-back-to-anonymous behavior.
- `language` accepts the supported locales (`en-US`, `en-GB`, `de-DE`, `de-AT`,
  `de-CH`, `fr-FR`), bare codes (`en`, `de`, `fr`), and `auto` with optional
  `preferredVariants`. Unsupported codes get a 400; text whose language cannot
  be detected with `auto` gets an empty match list, since LanguageTool clients
  check on every edit and would surface an error each time.
- The `data` parameter (text-plus-markup JSON) is supported; markup is
  neutralized in place so returned offsets index into the original data
  stream, and matches inside markup are discarded. The desktop app's
  undocumented variants are also handled: a bare `{"text": ...}` document in
  `data` (with an empty `text` form field alongside), and `language=auto` on
  texts too short or misspelled to detect, which falls back to the first
  supported preferred variant instead of returning nothing.
- `motherTongue` maps to `config.primary_language`; `disabledCategories`
  accepts the Witty category keys (see `/v2.0/categories`), not LanguageTool's.
  The remaining rule-selection parameters (`enabledRules`, `disabledRules`,
  `enabledOnly`, `level`, `dicts`) are accepted and ignored. The
  personal-dictionary endpoints are stubs that store nothing.
- Offsets are UTF-16 code units, matching what LanguageTool's Java server
  produces and its clients expect.
- Matches carry synthetic rule IDs (`WITTY_<subcategory>`) and the Witty
  category as the rule category, so per-rule disabling in client UIs works per
  subcategory.

## Management Endpoints

These endpoints manage user and organization configurations. All require HTTP Basic authentication, on by default and configured via `MANAGEMENT_AUTH_ENABLED`, `API_DOCS_USERNAME` and `API_DOCS_PASSWORD` — see [Protecting the management endpoints](./configuration.md#protecting-the-management-endpoints).

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
| `/docs`                       | GET    | Optional\*    | Interactive Swagger UI documentation                                              |
| `/openapi.json`               | GET    | No            | OpenAPI schema JSON                                                               |
| `/textarea`                   | GET    | No            | Static HTML form for pasting text by hand during development                      |

\* Requires HTTP Basic auth if `API_DOCS_AUTH_ENABLED=true`. `/openapi.json` is
served unguarded either way.

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

Only listed in the schema when `PLATFORM_ENVIRONMENT_TYPE != "production"`, but
routed in every environment — the switches below are what actually guards them.

Protected by `API_DOCS_AUTH_ENABLED`, which is **off** by default:

| Endpoint               | Method | Description                                                                    |
| ---------------------- | ------ | -------------------------------------------------------------------------------- |
| `/debug/check`         | POST   | Check text with additional debug information                                   |
| `/debug/rephrase`      | POST   | Rephrase text with debug output. Accepts a `model` to override `LLM_MODEL`     |
| `/debug/prompt`        | POST   | Generate prompt with debug information                                         |
| `/debug/review_prompt` | POST   | Generate review prompt for LLM output                                          |
| `/debug/rule`          | POST   | Test a specific rule against text                                              |
| `/debug/spacy`         | GET    | spaCy's tokens for `?text=&lang=`, with the API's own word types. `detailed=true` adds the raw tagger output |
| `/debug/displacy`      | GET    | The dependency parse of `?text=&lang=` rendered as an SVG                      |
| `/debug/german_noun`   | GET    | The declension and gendered forms the rule engine has for `?word=`             |
| `/lemmatize`           | GET    | Get lemma form of a word                                                       |
| `/tokenize`            | GET    | Tokenize text using spaCy                                                      |
| `/parse-word-types`    | GET    | Parse a `?word_types=` spec (`n\|~v\|=conj`) against `?text=`, as the rule format does |
| `/save_openapi_json`   | GET    | Export OpenAPI schema to file                                                  |

Protected by `MANAGEMENT_AUTH_ENABLED`, which is **on** by default, because both
report configuration back:

| Endpoint    | Method | Description                                                     |
| ----------- | ------ | ----------------------------------------------------------------- |
| `/settings` | GET    | The whole settings object, including every secret it holds      |
| `/languagetool_api` | GET | View the LanguageTool backend URL (`LANGUAGETOOL_API`)     |

The LLM-backed ones among these are refused when `LLM_ACCESS=disabled` or no
`LLM_MODEL` is configured, the same as the client-facing routes.

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

---

## See Also

- [Request Configuration & Categories](./request-configuration.md) - Per-request configuration options
- [Configuration & Environment Variables](./configuration.md) - Server-side configuration and environment variables
- [Setup & Deployment](./setup.md) - Installation and deployment
- Back to [📋 Documentation Index](../README.md#documentation-index)
