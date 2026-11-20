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
# See docs/deployment-sizing.md for what each costs. Nothing else is decided at
# build time: all configuration is environment at runtime, so the published
# image (.github/workflows/release-image.yaml) serves every deployment.

ARG PYTHON_VERSION=3.12

# ------------------------------------------------------------------ deps ---
# The lockfile export runs in its own stage, so nothing installed for it
# reaches the application's site-packages: a later `pip install --prefix`
# would take such packages as already satisfied and leave them out of the
# image.
FROM python:${PYTHON_VERSION}-slim-bookworm AS deps

ARG SPACY_LANGS="en,de,fr"
ARG SPACY_MODEL_SIZE="lg"

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# The same uv as CI (.github/workflows/main.yaml).
RUN pip install uv==0.13.9

WORKDIR /src
COPY pyproject.toml uv.lock ./
COPY bin/install_spacy_models.py bin/spacy-models.json ./bin/

# The dependency set is generated from the lockfile rather than kept as a
# second, hand-maintained requirements.txt that can drift from it, with the
# lockfile's hashes. --locked checks that uv.lock still matches pyproject.toml.
RUN uv export --locked --no-dev --no-emit-project --no-annotate \
        --no-header --format requirements-txt -o /tmp/requirements.hashed.txt

# torch comes from the PyTorch CPU index (pyproject.toml, [tool.uv.sources]),
# so it is installed on its own, from that index alone. Giving pip the index as
# an extra one for everything would let it take any package from there.
RUN set -eux; \
    python - <<'PY'
import re
lines = open("/tmp/requirements.hashed.txt").read().replace("\\\n", " ").splitlines()
torch = [l for l in lines if re.match(r"^torch==", l)]
if not torch:
    raise SystemExit("no torch in the lockfile export")
open("/tmp/torch.txt", "w").write("\n".join(torch) + "\n")
rest = [l for l in lines if l.strip() and not re.match(r"^torch==", l)]
open("/tmp/requirements.txt", "w").write("\n".join(rest) + "\n")
PY

# The spaCy models are not in the lock (Dependabot cannot resolve their GitHub
# release URLs): bin/spacy-models.json pins each wheel by hash. This picks the
# languages and the size, and records the names so the runtime default matches
# what was installed.
RUN python bin/install_spacy_models.py \
        --langs "$SPACY_LANGS" --size "$SPACY_MODEL_SIZE" \
        --requirements-out /tmp/models-requirements.txt --models-out /tmp/models.txt \
    && cat /tmp/models.txt

# --------------------------------------------------------------- builder ---
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Build tooling is needed only here; the runtime stage never sees it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=deps /tmp/requirements.txt /tmp/torch.txt /tmp/models.txt \
    /tmp/models-requirements.txt /tmp/

# A venv rather than --prefix, so the target environment starts empty and
# nothing can be skipped as "already satisfied". Every install is --no-deps and
# checked against hashes: the export already lists every dependency the lock
# resolved, and a package's own metadata must not add more (german-nouns
# declares wiktionary-de-parser, which pyproject.toml excludes, and with it an
# old lxml).
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install --no-deps --require-hashes \
        --index-url https://download.pytorch.org/whl/cpu --requirement /tmp/torch.txt \
    && /opt/venv/bin/pip install --no-deps --require-hashes \
        --requirement /tmp/requirements.txt \
    && /opt/venv/bin/pip install --no-deps --require-hashes \
        --requirement /tmp/models-requirements.txt

# Fail the build rather than the container if the environment cannot import
# spacy (this is the check that would have caught a missing httpx), or if
# torch is a CUDA build: the image runs on CPU.
RUN /opt/venv/bin/python -c "import importlib.util, spacy, httpx, torch; \
assert torch.version.cuda is None, 'torch is a CUDA build: ' + torch.version.cuda; \
models = open('/tmp/models.txt').read().split(','); \
missing = [m for m in models if importlib.util.find_spec(m) is None]; \
assert not missing, 'models not installed: ' + ', '.join(missing); \
assert importlib.util.find_spec('wiktionary_de_parser') is None, 'excluded package installed'; \
print('spacy', spacy.__version__, 'torch', torch.__version__, 'models', models, 'ok')"

# ----------------------------------------------------------------- editor ---
# The editor script for the /textarea page. Always in the image, so that one
# image serves every deployment: whether the page is served is TEXTAREA_ENABLED
# at runtime, off by default, and the script is under 1 MB. Downloads the npm
# release pinned in bin/editor-pin.json (no npm needed) and checks it against
# the integrity the registry published. A stage of its own, so a change to the
# app does not download it again.
FROM python:${PYTHON_VERSION}-slim-bookworm AS editor

COPY ./bin/fetch_editor.py ./bin/editor-pin.json /tmp/
RUN mkdir -p /editor && python /tmp/fetch_editor.py --dest /editor

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

# gitignored, so a build from a fresh checkout would otherwise ship an image
# that only fails once language detection is first used. Checked against a
# pinned hash, since it is downloaded unsigned.
RUN test -s /code/training_data/lid.176.bin \
    || { echo "training_data/lid.176.bin is missing, see docs/setup.md" >&2; exit 1; }
RUN echo "e613bda316ecb4f5e1924140eedf81b81c087d9a  /code/training_data/lid.176.bin" \
    | sha1sum -c -

# The release's rules. A file mounted over /code/database/dump.sql replaces
# them without a rebuild; the hash recorded beside it is how /version tells
# the two apart (see Db.rules_info).
COPY ./database/dump.sql /code/database/dump.sql
RUN sha256sum /code/database/dump.sql | cut -d' ' -f1 > /code/dump.sql.sha256

COPY --from=editor /editor/ /code/app/static/

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
