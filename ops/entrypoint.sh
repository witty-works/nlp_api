#!/bin/bash
set -e

# start sshd
/usr/sbin/sshd

# start webservice as wittyuser
gosu wittyuser \
    gunicorn \
        app.main:app \
        -b 0.0.0.0:${PORT} \
        -w ${WORKERS} \
        -k uvicorn.workers.UvicornWorker \
        --forwarded-allow-ips="*"
