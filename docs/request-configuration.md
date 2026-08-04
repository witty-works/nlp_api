# Request Configuration

## Table of Contents

- [Authentication](#authentication)
  - [API Key Authentication](#api-key-authentication)
  - [OAuth2 Bearer Token Authentication](#oauth2-bearer-token-authentication)
  - [Testing Authentication (Development Only)](#testing-authentication-development-only)
  - [Authentication Priority](#authentication-priority)
  - [Unauthenticated Endpoints](#unauthenticated-endpoints)
- [Basic Config Structure](#basic-config-structure)
  - [Context and Storage](#context-and-storage)
  - [Addons](#addons)
  - [Language Settings](#language-settings)
  - [Gender-Inclusive Formatting](#gender-inclusive-formatting)
  - [Category and Alternative Settings](#category-and-alternative-settings)
- [Supported Categories](#supported-categories)
  - [Finding Available Categories](#finding-available-categories)
  - [Common Categories](#common-categories)
- [Example API Calls](#example-api-calls)
  - [Basic check without configuration](#basic-check-without-configuration)
  - [Check with automatic language detection](#check-with-automatic-language-detection)
  - [Check with custom configuration](#check-with-custom-configuration)
  - [Check German text with specific gender ending](#check-german-text-with-specific-gender-ending)
  - [Check with disabled categories](#check-with-disabled-categories)
- [Configuration Precedence](#configuration-precedence)
- [Stored Configuration via Management API](#stored-configuration-via-management-api)

---

The `/check` endpoint accepts an optional `config` object that allows you to customize the behavior of the inclusive language checker on a per-request basis. This configuration can override stored user/organization settings or provide settings when no stored configuration exists.

## Authentication

The API supports multiple authentication methods for accessing protected endpoints like `/check`, `/rephrase`, and other core features.

### API Key Authentication

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

Managing API Keys:

- `POST /api_key` - Create a new API key for a user email
- `GET /api_key/{email}` - Retrieve API key for an email
- `DELETE /api_key/{email}` - Delete API key for an email

These management endpoints require HTTP Basic authentication (see [API docs protection](./configuration.md#api-docs-protection)). Where there is no dashboard to create keys, [bin/api_key.py](../bin/api_key.py) does the same from the command line — see [API keys](./setup.md#api-keys).

### OAuth2 Bearer Token Authentication

The API supports OAuth2 Bearer token authentication through three providers:

1. The dashboard (Laravel Passport, verified against its JWKS document)
2. Azure AD B2C (Single-tenant)
3. Microsoft Office SSO (Multi-tenant)

The token's `aud` claim selects which of them verifies it — see
[Authentication](./configuration.md#authentication) for the variables that
register each one.

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

### Testing Authentication (Development Only)

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

Warning: This bypass is only active when `TESTING=true` and should NEVER be enabled in production environments.

### Authentication Priority

When multiple authentication methods are provided, the API checks them in this order:

1. OAuth2 Bearer token (if `Authorization` header is present)
2. API Key (if `x-key` header is present)
3. Testing header (if `TESTING=true` and `X-TESTING-AUTH` is present)

### Unauthenticated Endpoints

Some endpoints do not require authentication:

- Health checks and status endpoints
- The category list (`/v2.0/categories`) and the config options
  (`/v2.0/config-options`) - the same answer for everyone
- Public documentation (`/docs`) - unless `API_DOCS_AUTH_ENABLED=true`
- OpenAPI schema (`/openapi.json`)

## Basic Config Structure

The `config` object in a `/check` request supports the following options.

### Context and Storage

| Field              | Type    | Default |
| ------------------ | ------- | ------- |
| `store_context`    | boolean | `true`  |
| `llm_alternatives` | boolean | `false` |

`store_context`: When true, includes surrounding text context (±100 chars) in results. Context is sanitized for privacy. Clients use this flag to decide whether to persist data with analytics.

`llm_alternatives`: Enable LLM-powered grammatically correct alternatives. Requires
`CLIENT_CONFIG_ENABLED` to be settable per request, AWS credentials for the LLM
itself, and an [`LLM_ACCESS`](./configuration.md#who-may-spend-the-llm-budget)
policy that covers the requester — that last one is the operator's and can only
ever turn this off.

### Addons

| Field    | Type             | Default |
| -------- | ---------------- | ------- |
| `addons` | array of strings | `null`  |

`addons`: List of enabled addon features.

### Language Settings

| Field                 | Type           | Default                       |
| --------------------- | -------------- | ----------------------------- |
| `primary_language`    | enum           | `null`                        |
| `preferred_languages` | array of enums | `["en", "de", "fr"]`          |
| `preferred_variants`  | array of enums | `["en-US", "de-DE", "fr-FR"]` |

`primary_language`: Primary language variant. Supported values: `"en"`, `"de"`, `"fr"`, `"en-US"`, `"en-GB"`, `"de-DE"`, `"de-CH"`, `"de-AT"`, `"fr-FR"`, or `"auto"` for automatic detection.

`preferred_languages`: Languages to check. Supported values: `"en"`, `"de"`, `"fr"`.

`preferred_variants`: Language variants for spelling/grammar. Supported values: `"en-US"`, `"en-GB"`, `"de-DE"`, `"de-CH"`, `"de-AT"`, `"fr-FR"`.

### Gender-Inclusive Formatting

`GET /v2.0/config-options` returns these three fields' accepted values and
defaults, read off the request model, so a client can offer them without
hard-coding the lists below.

| Field                     | Type | Default  |
| ------------------------- | ---- | -------- |
| `german_gender_ending`    | enum | `"*in"`  |
| `french_gender_separator` | enum | `"·"`    |
| `gendered_roles_format`   | enum | `"both"` |

`german_gender_ending`: German gender-inclusive ending format. Supported values:

- `"*in"` - Star/Asterisk (e.g., `Lehrer*in`)
- `"_in"` - Underscore (e.g., `Lehrer_in`)
- `":in"` - Colon (e.g., `Lehrer:in`)
- `"/in"` - Slash (e.g., `Lehrer/in`)
- `"/-in"` - Slash-Dash (e.g., `Lehrer/-in`)
- `"In"` - Capital Letter (e.g., `LehrerIn`)
- `"()"` - Parenthesis (e.g., `Lehrer(in)`)
- `"(-)"` - Parenthesis-Dash (e.g., `Lehrer(-in)`)
- `"de-e"` - [Inklusivum](https://geschlechtsneutral.net/inklusivum/) (e.g., `de Lehrere`)

Unlike the other values, `"de-e"` is not a separator spliced into the word but a
separate declension system with its own articles, adjective endings and pronouns.
Support is currently limited to nouns and their articles.

`french_gender_separator`: French gender-inclusive separator format (Point médian). Supported values:

- `"·"` - Point médian (e.g., `auteur·rice`)
- `"·s"` - Point médian with S (e.g., `auteur·rice·s`)
- `"."` - Point (e.g., `auteur.rice`)
- `".s"` - Point with S (e.g., `auteur.rice.s`)
- `"/"` - Slash (e.g., `auteur/rice`)
- `"/s"` - Slash with S (e.g., `auteur/rice/s`)

`gendered_roles_format`: How to suggest gendered role alternatives. Supported values:

- `"none"` - No gendered role alternatives
- `"both"` - Show both inclusive and binary gender alternatives
- `"inclusive_gender"` - Show only gender-inclusive alternatives (e.g., "firefighter" instead of "fireman")
- `"binary_gender"` - Show only binary gender alternatives (e.g., "fireman/firewoman")

### Category and Alternative Settings

| Field                           | Type             | Default |
| ------------------------------- | ---------------- | ------- |
| `disabled_categories`           | array of strings | `[]`    |
| `show_inspiration_alternatives` | boolean          | `false` |
| `alternatives_max_count`        | integer          | `null`  |

`disabled_categories`: List of category names to disable (e.g., ["orthography", "gender"]). See supported categories below.

`show_inspiration_alternatives`: Include inspirational (💡) suggestions in alternatives.

`alternatives_max_count`: Maximum number of alternatives to return per result (defaults to server setting).

## Supported Categories

The API checks text against multiple diversity dimensions and language categories. You can selectively disable categories using the `disabled_categories` configuration option.

### Finding Available Categories

Ask the API: `GET /v2.0/categories` returns the keys this deployment accepts,
with their groups and their `advanced_key`. That is the one source that cannot
go stale against the running version, and it needs no authentication — an
options page can render the toggles before the user has entered a credential.
See [API Endpoints](./api.md#core-endpoints), and note that a category and its
`advanced_key` have to be disabled together.

The same list can also be read from:

1. Public Documentation (with explanations and examples):
   - English: https://www.witty.works/en/categories.html
   - German: https://www.witty.works/de/kategorien.html
   - French: https://www.witty.works/fr/categories.html

2. Source Code (technical reference):
   - [training_data/categories.json](../training_data/categories.json) - Main category definitions with translations, proficiency levels, and metadata
   - [training_data/diversity_dimension_drivers.json](../training_data/diversity_dimension_drivers.json) - Additional diversity dimension drivers
   - [app/categories.py](../app/categories.py) - Category logic, utilities, and helper functions

3. API Documentation (interactive):
   - OpenAPI/Swagger UI at `/docs` (when running locally or in production)

### Common Categories

Top-level categories (from `categories.json`):

- `cultural-diversity` - Biases and stereotypes surrounding ethnicity, nationality, and race; language barriers in multilingual environments
- `gender-orientation` - Gender-inclusive language, sexual orientation, and representation of marginalized genders
- `ability-physicality` - Ableist language, disability-related terminology, and physicality biases
- `religion` - Faith-based expressions, antisemitism, and anti-muslim language
- `acquired-diversity` - Age, education, socioeconomic status, and other acquired characteristics
- `social-motive` - Language that promotes collaboration vs. competition, community vs. individualism

Examples of subcategories (from `diversity_dimension_drivers.json`):

- Under `gender-orientation`: `gender_identity`, `gender_specific_abbreviation`, `gendered_denominations_ending`, `LGBTQIA-hate`, `homophobia`, `sexism`, `transphobia`, `binary_pronouns`, `female_stereotype`, `male_stereotype`, `leadership`, `sexual_orientation`, `titles`, `function`, `hidden_image`
- Under `cultural-diversity`: `abbreviation`, `anglicism`, `filler`, `hollow`, `plain_language`, `color`, `racist_source`, `culture`, `migration`, `nazi_language`, `yiddish-pejoratives`, `racism`, `xenophobia`
- Under `ability-physicality`: `ability`, `physicality`, `ableism`, `behavior`, `medical_state`, `mobility`, `cognitive_ability`, `cognitive_perception`, `hearing`, `learning`, `mental_wellbeing`, `speech`, `vision`
- Under `religion`: `antimuslim`, `antisemitism`, `belief`
- Under `acquired-diversity`: `age`, `age_old`, `age_young`, `classism`, `formality`
- Under `social-motive`: `agentic`, `exaggerating`, `military_source`, `sports_terms`, `communal`, `d_and_i`, `emotional_security`, `offensive_language`

Note on proficiency levels: Most subcategories have both basic and `_advanced` variations (e.g., `ability` and `ability_advanced`). However, subcategories with proficiency level `inclusive` (such as `communal`, `d_and_i`, `emotional_security`) or `openly_discriminating` (such as `ableism`, `racism`, `sexism`, `transphobia`, `homophobia`, `antisemitism`, `antimuslim`, `xenophobia`) do NOT have `_advanced` variations - they only exist in their base form.

Note: Category names may include subcategories and can have an `_advanced` suffix for advanced proficiency level checks. Refer to the [Finding Available Categories](#finding-available-categories) section above or the [Training Data & Resources](./training-data.md#categories) for the complete and up-to-date list.

## Example API Calls

### Basic check without configuration

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/v2.4/check' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "text": "Wer sind unsere Kunden?"
}'
```

### Check with automatic language detection

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

How automatic detection works:

1. The API uses a fastText model to identify the language(s) in the text
2. It filters detected languages to only those in `preferred_languages` (defaults to en, de, fr)
3. If `preferred_variants` is configured, it selects the matching variant (e.g., "en-GB" over "en-US")
4. Otherwise, it uses the default variant for the detected language
5. If no supported language is detected, the request fails with an error

### Check with custom configuration

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

### Check German text with specific gender ending

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

### Check with disabled categories

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

## Configuration Precedence

When a `/check` request is made with authentication (via API key or OAuth token):

1. Request config: Settings provided in the request `config` object take highest priority
2. User config: User-specific settings stored in Redis
3. Organization config: Organization-level settings (if user belongs to an organization)
4. Default config: Server defaults as documented

Settings are merged with this precedence, meaning you can override specific fields per request while keeping other settings from stored configurations.

A stored setting carrying `"status": "force"` reverses that for its own field
and overrides the request; one carrying `"status": "suggestion"` applies only
where the request left the field out. Two fields are not the request's to
set unless the deployment says so:

- `store_context` and `llm_alternatives` are ignored unless
  [`CLIENT_CONFIG_ENABLED`](./configuration.md#running-without-the-dashboard) is
  on.

## Stored Configuration via Management API

Instead of passing configuration with each request, you can store user and organization configurations using the configuration management endpoints. See the API documentation at `/docs` for:

- `POST /user` - Store user configuration
- `GET /user/{email}` - Retrieve user configuration
- `POST /organization` - Store organization configuration
- `GET /organization/{id}` - Retrieve organization configuration

Stored configurations support additional features beyond the request `config` object:

- False positives: List of terms/phrases to ignore globally
- Term replacements: Custom replacement rules with explanations
- Domain restrictions: Allowlist or denylist of domains where the checker should operate
- Config versioning: `config_hash` and `sync_date` for cache invalidation

---

## See Also

- [Configuration & Environment Variables](./configuration.md) - Server-side configuration
- [API Endpoints](./api.md) - Core endpoints and management endpoints
- [Technical Notes](./technical-notes.md) - Rules engine and authentication details
- Back to [📋 Documentation Index](../README.md#documentation-index)
