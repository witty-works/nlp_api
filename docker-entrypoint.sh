#!/bin/sh
set -eu

# MODELS selects which of the *installed* models are loaded. Defaulting it to
# what the build actually installed keeps the two from drifting: asking for a
# model that is not in the image fails at startup, inside every worker, with a
# traceback that does not say which setting caused it.
if [ -z "${MODELS:-}" ] && [ -f /code/models.txt ]; then
    # app.settings reads this as a JSON list.
    MODELS="[\"$(sed 's/,/","/g' /code/models.txt)\"]"
    export MODELS
fi

# gunicorn --preload loads the models once in the parent and forks workers, so
# the model pages start out shared rather than copied per worker. Dropping it
# multiplies the resident set by WORKERS. See docs/deployment-sizing.md.
exec gunicorn app.main:app \
    --preload \
    --bind "0.0.0.0:${PORT:-8081}" \
    --workers "${WORKERS:-1}" \
    --worker-class uvicorn.workers.UvicornWorker \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-30}" \
    --forwarded-allow-ips "*" \
    "$@"
