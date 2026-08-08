FROM python:3.12.1

RUN pip install --upgrade pip

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

# Creates a non-root user
WORKDIR /code
RUN adduser -u 5678 --disabled-password --gecos "" appuser && chown -R appuser /code

# install deps
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check --requirement requirements.txt

# change user https://stackoverflow.com/questions/73174175/gunicorn-command-not-found
USER appuser

COPY ./app /code/app

COPY ./training_data /code/training_data

# Baked in rather than read from .git so /version reports the revision the
# image actually contains, not whatever the build context happened to be.
ARG GIT_REVISION=""
ENV GIT_REVISION=${GIT_REVISION}

ENV WORKERS=1
CMD gunicorn app.main:app --preload -b 0.0.0.0:8081 -w $WORKERS -k uvicorn.workers.UvicornWorker --forwarded-allow-ips "*"

EXPOSE 8081