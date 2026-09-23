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
#
# --max-requests recycles a worker after roughly that many requests, which
# bounds the slow growth of a long-lived spaCy process (the memory_zones
# setting addresses the same thing from the other side). It is cheap here
# precisely because of --preload: the replacement is forked from the master,
# which still holds the loaded models, so nothing is re-read from disk. The
# jitter keeps workers from recycling in lockstep. The Upsun deployment ran
# with both set; 0 disables.
exec gunicorn app.main:app \
    --preload \
    --bind "0.0.0.0:${PORT:-8081}" \
    --workers "${WORKERS:-1}" \
    --worker-class uvicorn.workers.UvicornWorker \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-30}" \
    --max-requests "${MAX_REQUESTS:-2000}" \
    --max-requests-jitter "${MAX_REQUESTS_JITTER:-200}" \
    --forwarded-allow-ips "*" \
    "$@"
