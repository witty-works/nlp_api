# NLP API

NLP API for inclusive language

## Resources
This project has two key dependencies:

| Dependency Name | Documentation                | Description                                                                            |
|-----------------|------------------------------|----------------------------------------------------------------------------------------|
| spaCy           | https://spacy.io             | Industrial-strength Natural Language Processing (NLP) with Python and Cython           |
| FastAPI         | https://fastapi.tiangolo.com | FastAPI framework, high performance, easy to learn, fast to code, ready for production |
---

## Install

```
pipenv install --dev
pipenv shell
pipenv run python -m spacy download en_core_web_sm
pipenv run python -m spacy download de_core_news_sm
```

Note to uninstall spacy models use

```
pipenv uninstall ..
```

## Install Platform.sh CLI

  * Run `platform login`
  * Run `platform project:set-remote`
  * Run `platform list` to find out what commands are available
  * Run `platform help [command]` to find out details about a command

see https://docs.platform.sh/development/cli.html for details

## Run Locally

```
pipenv uvicorn app.main:app --reload
```

Open your browser to http://localhost:8000/docs to view the OpenAPI UI.

For an alternate view of the docs navigate to http://localhost:8000/redoc

## Production Deployment

Set an env variable `API_DOCS_AUTH_ENABLED` to `"true"` and for the username/password called `API_DOCS_USERNAME` and `API_DOCS_PASSWORD` for basic auth for the API docs.

If the build fails due to "No space left on device" while installing the dependencies see:
https://docs.platform.sh/development/troubleshoot.html#clear-the-build-cache

## Example

```
curl -X 'POST' \
  'http://127.0.0.1:8000/check' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "text": "Wer sind unsere Kunden?"
}'
```

## Run tests

To run the entire test suite

```
pipenv run pytest -vv
```

To only run the last failing tests

```
pipenv run pytest -vv --lf
```

## Profiling on Platform.sh

Install the Blackfire CLI:
https://blackfire.io/docs/up-and-running/installation

```
blackfire curl -X 'POST' https://[env subdomain].platformsh.site/check -H 'accept: application/json' -H 'Content-Type: application/json' -d '{"text": "Wer sind unsere Kunden?"}'
```

Then go to https://blackfire.io/ to view the profiler result.

## Benchmarking

Install the Apache HTTP server benchmarking tool:
https://httpd.apache.org/docs/2.4/programs/ab.html

```
ab -c 50 -n 100 -p tests/test_small.json -T application/json https://[env subdomain].platformsh.site/check
```

## Localization

Go to https://www.notion.so/witty-works/e68e073dd0a342fca2a6683c7a8b2341?v=b54da99f8a6b4e6e8f312a530f653eb0
Export to CSV

```
pipenv run python -m update_locales -i [CSV export]]
```

Compile po files (done automatically during deployment and above pot/po file generation)

```
pipenv run pybabel compile -d locales -l de_DE -f
pipenv run pybabel compile -d locales -l en_GB -f
```

## Update the browser extension

```
rsync -avz files/* "$(platform ssh -e main --pipe)":files/.
```
