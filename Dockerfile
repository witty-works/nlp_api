# syntax=docker/dockerfile:1.7

# Two build-time dimensions, both of which change the image size rather than
# only the runtime footprint:
#
#   SPACY_LANGS       which model wheels are installed at all
#   SPACY_MODEL_SIZE  sm | md | lg - lg is what the product is tuned against
#
# and two runtime ones, set as environment variables (see compose.yml):
#
#   MODELS                 which of the installed models are loaded
#   WORKERS                gunicorn worker processes
#   CONTEXT_CHECKER_LOCAL  whether the SetFit models under /code/models load
#
# See docs/deployment-sizing.md for what each costs.

ARG PYTHON_VERSION=3.12

# ------------------------------------------------------------------ deps ---
# pdm lives in its own stage. Installing it beside the application would put
# its own dependencies (httpx, certifi, ...) into site-packages, and a later
# `pip install --prefix` then treats those as already satisfied and leaves
# them out of the prefix - producing an image that is missing httpx, which
# spacy imports on `import spacy` by way of spacy.cli -> weasel.
FROM python:${PYTHON_VERSION}-slim-bookworm AS deps

ARG SPACY_LANGS="en,de,fr"
ARG SPACY_MODEL_SIZE="lg"

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install pdm

WORKDIR /src
COPY pyproject.toml pdm.lock ./

# The dependency set is generated from the lockfile rather than kept as a
# second, hand-maintained requirements.txt that can drift from it.
RUN pdm export --prod --no-hashes -f requirements -o /tmp/requirements.full.txt

# Drop the model wheels for languages this image does not serve, and rewrite
# the remaining ones to the requested size. The URLs are versioned by model
# release (…_lg-3.8.0/…_lg-3.8.0-py3-none-any.whl), so the substitution has to
# hit both the directory and the filename.
RUN set -eux; \
    python - "$SPACY_LANGS" "$SPACY_MODEL_SIZE" <<'PY'
import re, sys
langs = {l.strip() for l in sys.argv[1].split(",") if l.strip()}
size = sys.argv[2].strip()
if size not in {"sm", "md", "lg"}:
    raise SystemExit(f"SPACY_MODEL_SIZE must be sm, md or lg, got {size!r}")

kept, dropped = [], []
for line in open("/tmp/requirements.full.txt"):
    m = re.match(r"^(en|de|fr)-core-(web|news)-(sm|md|lg)\s*@", line)
    if m:
        lang = m.group(1)
        if lang not in langs:
            dropped.append(lang)
            continue
        line = re.sub(r"_(sm|md|lg)-", f"_{size}-", line)
        line = re.sub(r"^(\w\w)-core-(web|news)-(sm|md|lg)", rf"\1-core-\2-{size}", line)
    kept.append(line)

open("/tmp/requirements.txt", "w").writelines(kept)
# Recorded so the runtime default matches what was actually installed.
suffix = {"en": "core_web", "de": "core_news", "fr": "core_news"}
models = [f"{l}_{suffix[l]}_{size}" for l in ("en", "de", "fr") if l in langs]
if not models:
    raise SystemExit(f"SPACY_LANGS selected no models: {sys.argv[1]!r}")
open("/tmp/models.txt", "w").write(",".join(models))
print(f"installing models: {models}; dropped languages: {sorted(set(dropped))}")
PY

# --------------------------------------------------------------- builder ---
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Build tooling is needed only here; the runtime stage never sees it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=deps /tmp/requirements.txt /tmp/models.txt /tmp/

# A venv rather than --prefix, so the target environment starts empty and
# nothing can be skipped as "already satisfied".
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install --requirement /tmp/requirements.txt

# Fail the build rather than the container if the environment cannot import
# spacy: this is the check that would have caught the missing httpx.
RUN /opt/venv/bin/python -c "import spacy, httpx; print('spacy', spacy.__version__, 'ok')"

# ---------------------------------------------------------------- runtime ---
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# curl is only for the HEALTHCHECK below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code
RUN adduser -u 5678 --disabled-password --gecos "" appuser

COPY --from=builder /opt/venv /opt/venv
COPY --from=deps /tmp/models.txt /code/models.txt

COPY ./app /code/app
COPY ./training_data /code/training_data
COPY ./docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# The editor script for the /textarea page, only when asked for: the page is
# off by default (TEXTAREA_ENABLED), and an image without it carries nothing of
# it. Downloads the release pinned in bin/fetch_editor.py and checks its hash.
ARG TEXTAREA=false
COPY ./bin/fetch_editor.py /tmp/fetch_editor.py
RUN if [ "$TEXTAREA" = "true" ]; then python /tmp/fetch_editor.py --dest /code/app/static; fi \
    && rm /tmp/fetch_editor.py

RUN chmod +x /usr/local/bin/docker-entrypoint.sh && chown -R appuser /code

USER appuser

# Baked in rather than read from .git so /version reports the revision the
# image actually contains, not whatever the build context happened to be.
ARG GIT_REVISION=""
ENV GIT_REVISION=${GIT_REVISION}

ENV WORKERS=1 \
    PORT=8081

# Loading the models takes ~10-20 s per worker, so start-period has to cover a
# cold start or the container is killed while it is still coming up.
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

EXPOSE 8081

ENTRYPOINT ["docker-entrypoint.sh"]
