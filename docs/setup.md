# Setup and Local/Production Usage

## Table of Contents

- [Installation (Python 3.12) using uv](#installation-python-312-using-uv)
- [Using Docker](#using-docker)
- [Using docker compose (recommended for local multi-service setup)](#using-docker-compose-recommended-for-local-multi-service-setup)
- [Update dependencies locally](#update-dependencies-locally)
- [Add new package](#add-new-package)
- [Docker image](#docker-image)
- [Run Locally](#run-locally)
- [Profiling locally with Blackfire](#profiling-locally-with-blackfire)
- [Running against a dashboard on Lando](#running-against-a-dashboard-on-lando)
- [API keys](#api-keys)
- [Production Deployment](#production-deployment)

---

## Installation (Python 3.12) using uv

[uv](https://docs.astral.sh/uv/) creates `.venv` with the Python in `.python-version` and installs the locked dependencies from `uv.lock`, the development ones included:

```bash
uv sync
uv run python -m bin.install_spacy_models
wget -P training_data https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin
```

The spaCy models are not in `uv.lock`: they are wheels on GitHub release
pages, which Dependabot cannot resolve. `bin/install_spacy_models.py`
installs the large English, German and French models from
[bin/spacy-models.json](../bin/spacy-models.json), checked against the hashes
pinned there (`--size sm` or `--langs en` for less). `uv sync` removes
packages that are not in the lock, so run it again after a `uv sync`, or sync
with `uv sync --inexact`; `uv run` leaves them in place.

## Using Docker

The image is built with BuildKit (the Dockerfile uses heredocs), which is the
default builder of current Docker versions. The build needs
`training_data/lid.176.bin` (see above) and checks it against a pinned hash.

```bash
docker build -t nlpapi .
docker run -d --name nlp_api -p 8080:8081 -e LANGUAGETOOL_API= nlpapi
```

The entrypoint serves the API on port 8081 inside the container, so the
example maps it to 8080 on the host: http://localhost:8080/docs. Two build
arguments decide which spaCy models go into the image, `SPACY_LANGS`
(default `en,de,fr`) and `SPACY_MODEL_SIZE` (`sm`, `md` or `lg`, default
`lg`); see [deployment-sizing.md](./deployment-sizing.md). Without Redis
(`REDIS_HOST`) the API answers every request with no findings, so for more
than a smoke test use docker compose.

## Using docker compose (recommended for local multi-service setup)

`compose.yml` starts the API with Redis, and LanguageTool on request:

- **The API** is built from the local Dockerfile and published on port 8080
  of the host (`API_HOST_PORT`), container port 8081. It reads `.env`.
- **Redis** (`redis:7-alpine`) keeps API keys and configs, in a named volume.
- **LanguageTool** is built from [languagetool/](../languagetool/), with this
  project's ignore lists and disabled rules, and only runs with the
  `languagetool` profile. It is published on host port 8210 (`LT_HOST_PORT`),
  container port 8010.
- `./database` and `./models` are mounted read-only into the API container:
  the checkout's rules, and the SetFit context-checker models if you
  downloaded them.

Quick start:

```bash
# The API and Redis
docker compose up -d

# With LanguageTool: start its profile, and point the API at it in .env with
# LANGUAGETOOL_API=http://languagetool:8010/v2
docker compose --profile languagetool up -d

curl http://localhost:8080/health
# http://localhost:8080/docs in your browser
```

`LANGUAGETOOL_API` is empty by default, so the API makes no spelling and
grammar checks and sends no text to a third party until you set it.

Enable local context checker models (if you downloaded them, see
[configuration.md](./configuration.md#local-setfit-models)):

```bash
CONTEXT_CHECKER_LOCAL=true docker compose up -d
```

Changes in `./models` on the host are visible in the container through the
read-only mount.

Stop and remove services:

```bash
docker compose down
```

Rebuild after code changes (forces image rebuild):

```bash
docker compose build --no-cache nlpapi
docker compose up -d
```

Tail logs:

```bash
docker compose logs -f nlpapi
docker compose --profile languagetool logs -f languagetool
```

## Update dependencies locally

To update packages locally after `pyproject.toml`/`uv.lock` was changed:

```bash
uv sync
uv run python -m bin.install_spacy_models   # uv sync removes the models
```

## Add new package

When adding a new package to the project, update `pyproject.toml` via:

```bash
uv add <package_name>
```

## Docker image

After making changes in the code or in the Dockerfile, build a fresh image:

```bash
docker build -t nlpapi . --no-cache
docker run -p 8080:8081 nlpapi
```

## Run Locally

The API defaults to `ENVIRONMENT_TYPE=production`, which hides the
development helpers. `.env.development.mac` sets `development`; on macOS it
also avoids MKL warnings, so copy it as your `.env`:

```bash
cp .env.development.mac .env
```

Start the dev server:

```bash
uv run uvicorn app.main:app --reload
```

or

```bash
uvicorn app.main:app --reload
```

Open your browser to http://localhost:8000/docs to view the OpenAPI UI.

Alternative docs: http://localhost:8000/redoc

## Profiling locally with Blackfire

Blackfire is in the `profiling` dependency group, which `uv sync` leaves out
and the Docker image does not contain:

```bash
uv run --group profiling blackfire-python uvicorn app.main:app --reload
```

Make sure you have a `.blackfire.ini`, get the settings from
https://blackfire.io/docs/php/configuration

```ini
BLACKFIRE_SERVER_ID=""
BLACKFIRE_SERVER_TOKEN=""
```

## Running against a dashboard on Lando

Account mode has the API verify the dashboard's access tokens against
`{DASHBOARD_URL}/.well-known/jwks.json`. A Lando dashboard serves that over
HTTPS with a certificate signed by Lando's own CA, which is not in the trust
store Python uses, so the fetch fails and every sign-in is rejected with:

```
Failed to fetch RSA keys from issuer
```

That message is deliberately sanitized — it says nothing about certificates, and
reads the same as the dashboard being unreachable. The underlying error is
logged, so `LOGGING_ENABLED=true` shows the real cause:

```
Fetching RSA keys from https://dashboard.lndo.site/.well-known/jwks.json failed:
ClientConnectorCertificateError: ... certificate verify failed: unable to get local issuer certificate
```

The fix is to trust Lando's CA in addition to the normal roots. Python takes one
bundle, not a directory of extras, so concatenate them and point `SSL_CERT_FILE`
at the result:

```bash
cat "$(uv run python -m certifi)" ~/.lando/certs/LandoCA.crt > .lando-ca-bundle.crt
export SSL_CERT_FILE="$PWD/.lando-ca-bundle.crt"
```

`SSL_CERT_FILE` is read by `ssl.create_default_context()`, which is what the
API's HTTPS session is built from ([app/http.py](../app/http.py)), so it covers
the JWKS fetch and every other outbound HTTPS call. Export it in the shell that
starts the API — putting it in `.env` does not work, since that is read by the
application rather than by the TLS layer.

Regenerate the bundle whenever `certifi` is updated; it is a copy, not a
reference. Nothing about this is needed for API-key mode, which makes no call
back to the dashboard.

## API keys

An `x-key` header is resolved against `api_key:<key>` entries in Redis, which
the dashboard normally writes. Where there is no dashboard, mint them with:

```bash
uv run python -m bin.api_key create user@example.com   # prints the new key
uv run python -m bin.api_key list
uv run python -m bin.api_key delete <key>
```

The CLI reads the same environment as the API, so run it wherever `REDIS_HOST`
points at the deployment's Redis — it refuses to run against the in-memory Redis
the API falls back to, since those writes would vanish on exit.

Set `API_KEY_HMAC_KEY` to store keys as an HMAC-SHA256 digest rather than
verbatim, so a Redis dump does not hand out working credentials. With it set,
keys are only looked up by their digest: keys minted before it was set stop
working until they are stored again, which `bin.api_key rehash` does for every
key in Redis. Revoking then needs the key itself rather than the email, because
the plaintext cannot be recovered from Redis.

```bash
uv run python -m bin.api_key rehash
```

In production (`ENVIRONMENT_TYPE=production`, the default) the API refuses to
start while Redis holds a key as written and `API_KEY_HMAC_KEY` is empty; the
message says how many, never which. To move a deployment that has such keys:
set `API_KEY_HMAC_KEY` in its environment, run `rehash` with that environment
against its Redis, then start the API. A `DEFAULT_API_KEY` needs no rehash: it
is written again, as a digest, on every start.

Run it before the next key-file sync (below): a sync before it no longer finds
the synced keys under their old names and revokes them. `rehash` leaves alone,
and reports, a key stored both ways for two different emails. It counts the
entries already named like a digest and leaves them as they are: a key that
is itself 64 lowercase hex characters, stored before the secret was set,
cannot be told from a digest and stays unconverted, unless its digest is
stored too. Its output names no key. Changing `API_KEY_HMAC_KEY` later invalidates every key, since a digest
cannot be converted: mint new ones.

### From a local file

For a few dozen keys handed out by hand, keep them in a YAML file on your own
machine and sync it to the API. Who each key is for goes in a comment, and a key
can come with its own config (see [api_keys.example.yaml](../api_keys.example.yaml)):

```yaml
# Jane Doe (ACME), HR pilot until 2026-12
- email: jane@acme.example
  key: replace-with-a-minted-key-0000000000000
  config:                   # optional: what a request gets where it says nothing
    german_gender_ending: ":in"
    disabled_categories: [plain_language]
  force:                    # optional: what a request gets whatever it says
    french_gender_separator: "·"
```

```bash
# mint a key: appends an entry with the note as its comment, prints the key
uv run python -m bin.api_key create jane@acme.example --file api_keys.yaml \
    --note "Jane Doe (ACME), HR pilot until 2026-12"

# make the API match the file: shows what changes and asks first
NLP_API_USERNAME=… NLP_API_PASSWORD=… \
    uv run python -m bin.sync_api_keys api_keys.yaml --url https://nlp-api.example
```

- **The sync makes the server match the file** through `PUT /api_keys`: new
  keys are added, keys an earlier sync added that are no longer listed are
  revoked, and each email's config is replaced. Revoke a key by deleting its
  entry and syncing. Keys minted any other way (the dashboard, `bin/api_key.py`
  without `--file`, `DEFAULT_API_KEY`) are left alone: listed for the same
  email they are reported as unmanaged and never revoked by a sync, and a sync
  that would take one over for another email is refused as a whole. A key
  that moves to another email is reported as moved. An empty file is refused,
  since it would revoke every synced key, unless `--allow-empty` is given.
  Reads and writes are one Redis transaction, so two syncs at once cannot
  leave a revoked key working.
- **It needs the management credentials** (`API_DOCS_USERNAME` /
  `API_DOCS_PASSWORD` on the server, `MANAGEMENT_AUTH_ENABLED` on). With
  `REQUIRE_API_KEY` on it needs no key on top, like every endpoint that asks
  for a username and password; with management auth off it checks nothing,
  and the key gate stays in front of it.
- **The file holds the keys themselves** — the server needs each one once and
  may keep only an HMAC of it (`API_KEY_HMAC_KEY`). Keep it on your machine:
  `api_keys.yaml` is in `.gitignore`, and the script sends it over https only
  (plain http to localhost for testing).
- **The email is who the key is for.** The rest of the API knows a user by it:
  their config, and the pseudonymous id in the metrics. It need not be a
  mailbox, but it has to be one per owner. Several keys may share one (while
  rotating a key, say) if their `config` and `force` agree. Synced users need
  no `DEFAULT_USER_CONFIG_ENABLED`.
- **`config` and `force`** take the fields of a request's `config` and are
  checked before anything is sent, so a typo fails locally. `config` fills in
  what a request does not set, instead of `DEFAULT_CONFIG`, and clients reading
  `/v2.0/auth` show it as the defaults; `force` applies whatever the request
  says. A config synced from the dashboard for the same email wins over both.
  `alternatives_max_count` is the deployment's limit, not a key's, and is
  refused.
- **The sync says what will not take effect**, before and after syncing: a
  config for an email the dashboard also has a config for, and
  `llm_alternatives` for a user `LLM_ACCESS` / `LLM_ALLOWED_USERS` does not let
  spend the LLM budget.

The `/api_key` HTTP endpoints do the same thing, behind the management password
(`MANAGEMENT_AUTH_ENABLED`, on unless turned off): anyone with that password can
mint a key for any email, so keep it out of reach or the endpoints off the
public routing. They take the key in the request body, never in the URL.

## Production Deployment

Set an env variable `API_DOCS_AUTH_ENABLED` to `"true"` and set `API_DOCS_USERNAME` and `API_DOCS_PASSWORD` for basic auth for the API docs.

---

## See Also

- [Configuration & Environment Variables](./configuration.md) - Environment setup and configuration options
- [API Endpoints](./api.md) - Available endpoints and authentication
- [Technical Notes](./technical-notes.md) - Architecture and implementation details
- Back to [📋 Documentation Index](../README.md#documentation-index)
