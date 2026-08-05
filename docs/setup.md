# Setup and Local/Production Usage

## Table of Contents

- [Installation (Python 3.12) using PDM](#installation-python-312-using-pdm)
- [Using Docker](#using-docker)
- [Using docker compose (recommended for local multi-service setup)](#using-docker-compose-recommended-for-local-multi-service-setup)
- [Update dependencies locally](#update-dependencies-locally)
- [Add new package](#add-new-package)
- [Docker image](#docker-image)
- [Install Platform.sh CLI](#install-platformsh-cli)
  - [Adjust size on platform.sh](#adjust-size-on-platformsh)
- [Run Locally](#run-locally)
- [Profiling locally with Blackfire](#profiling-locally-with-blackfire)
- [API keys](#api-keys)
- [Production Deployment](#production-deployment)

---

## Installation (Python 3.12) using PDM

```bash
pdm venv create 3.12
pdm use
pdm venv activate
pdm sync --dev
wget -P training_data https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin
```

## Using Docker

1. Install Docker engine - https://docs.docker.com/engine/install/
2. Start LanguageTool from Docker Hub (erikvl87/languagetool):

```bash
# Create an isolated network so containers can talk by name
docker network create nlp-net

# Start LanguageTool on port 8010
docker run -d --name lt --network nlp-net -p 8010:8010 erikvl87/languagetool:latest
```

LanguageTool API will be available at http://localhost:8010/v2

3. Build and run the NLP API locally:

```bash
# Build the API image from the local Dockerfile
docker build -t nlpapi .

# Run the API and point it to the LanguageTool container
docker run -d --name nlp_api --network nlp-net -p 8080:8080 \
  -e LANGUAGETOOL_API=http://lt:8010/v2 \
  nlpapi
```

You should see the application running under http://localhost:8080/docs

## Using docker compose (recommended for local multi-service setup)

A ready-made `compose.yml` is included to start both the NLP API and LanguageTool with one command. It:

- Launches `erikvl87/languagetool` on port `8010`
- Builds and runs the API on port `8080`
- Mounts your local `./models` directory read-only into the container (so local SetFit models can be used if present)
- Sets `LANGUAGETOOL_API` inside the API container to point to the LanguageTool service

Quick start:

```bash
# Start both services in the background
docker compose up -d

# Check health
curl http://localhost:8080/health

# Visit http://localhost:8080/docs in your browser
```

Enable local context checker models (if you downloaded them):

```bash
# Option 1: temporarily set env when starting
CONTEXT_CHECKER_LOCAL=true docker compose up -d

# Option 2: uncomment CONTEXT_CHECKER_LOCAL in compose.yml and re-run
```

Updating models: any changes you make in `./models` on the host are reflected in the container because of the bind mount. The mount is read-only (`:ro`) to prevent accidental writes from inside the container.

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
docker compose logs -f languagetool
```

If you only need the API without LanguageTool, you can still use the single-container commands above or remove the `languagetool` service from the compose file.

## Update dependencies locally

To update packages locally after `pyproject.toml`/`pdm.lock` was changed:

```bash
pdm sync --dev
```

## Add new package

When adding a new package to the project, update `pyproject.toml` via:

```bash
pdm add <package_name>
```

## Docker image

After making changes in the code or in the Dockerfile, build a fresh image:

```bash
pdm export --prod -o requirements.txt
DOCKER_BUILDKIT=0 docker build -t nlpapi . --no-cache
docker run nlpapi
```

## Install Platform.sh CLI

- Run `platform login`
- Run `platform project:set-remote`
- Run `platform list` to find out what commands are available
- Run `platform help [command]` to find out details about a command

See https://docs.platform.sh/development/cli.html for details

### Adjust size on platform.sh

Adjust server size:

```bash
platform e:curl -e main /deployments/next -X PATCH -d '{"webapps":
  {"app": {"resources": {"profile_size": "8"}},"languagetool": {"resources": {"profile_size": "4"}}}}'
```

Adjust instance count:

```bash
platform e:curl -e main /deployments/next -X PATCH -d '{"webapps":
  {"app": {"resources": {"instance_count": "2"}},"languagetool": {"resources": {"instance_count": "2"}}}}'
```

## Run Locally

Note for Mac users. Set environment variables with the following snippet:

```bash
cp .env.development.mac .env
```

Start the dev server:

```bash
pdm run uvicorn app.main:app --reload
```

or

```bash
uvicorn app.main:app --reload
```

Open your browser to http://localhost:8000/docs to view the OpenAPI UI.

Alternative docs: http://localhost:8000/redoc

## Profiling locally with Blackfire

```bash
pdm run blackfire-python uvicorn app.main:app --reload
```

Make sure you have a `.blackfire.ini`, get the settings from
https://blackfire.io/docs/php/configuration

```ini
BLACKFIRE_SERVER_ID=""
BLACKFIRE_SERVER_TOKEN=""
```

## API keys

An `x-key` header is resolved against `api_key:<key>` entries in Redis, which
the dashboard normally writes. Where there is no dashboard, mint them with:

```bash
pdm run python -m bin.api_key create user@example.com   # prints the new key
pdm run python -m bin.api_key list
pdm run python -m bin.api_key delete <key>
```

The CLI reads the same environment as the API, so run it wherever `REDIS_HOST`
points at the deployment's Redis — it refuses to run against the in-memory Redis
the API falls back to, since those writes would vanish on exit.

Set `API_KEY_HMAC_KEY` to store keys as an HMAC-SHA256 digest rather than
verbatim, so a Redis dump does not hand out working credentials. Keys minted
before it was set keep working: lookups fall back to the plaintext entry.
Revoking then needs the key itself rather than the email, because the plaintext
cannot be recovered from Redis.

The `/api_key` HTTP endpoints do the same thing, but they are only protected
when `API_DOCS_AUTH_ENABLED` is `"true"` — with it unset, anyone who can reach
the API can mint a key for any email. Turn it on for any deployment that is
reachable from outside, or keep the endpoints off the public routing.

## Production Deployment

Set an env variable `API_DOCS_AUTH_ENABLED` to `"true"` and set `API_DOCS_USERNAME` and `API_DOCS_PASSWORD` for basic auth for the API docs.

If the build fails due to "No space left on device" while installing dependencies run:

```bash
platform project:clear-build-cache
```

See:
https://docs.platform.sh/development/troubleshoot.html#clear-the-build-cache

---

## See Also

- [Configuration & Environment Variables](./configuration.md) - Environment setup and configuration options
- [API Endpoints](./api.md) - Available endpoints and authentication
- [Technical Notes](./technical-notes.md) - Architecture and implementation details
- Back to [📋 Documentation Index](../README.md#documentation-index)
