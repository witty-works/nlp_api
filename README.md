# NLP API

NLP API for inclusive language: https://api.witty.works

## Resources

This project has two key dependencies:

| Dependency Name | Documentation                | Description                                                                            |
| --------------- | ---------------------------- | -------------------------------------------------------------------------------------- |
| spaCy           | https://spacy.io             | Industrial-strength Natural Language Processing (NLP) with Python and Cython           |
| FastAPI         | https://fastapi.tiangolo.com | FastAPI framework, high performance, easy to learn, fast to code, ready for production |

---

# Installation instructions (with python3.9)

## using Docker

1. Install Docker engine - https://docs.docker.com/engine/install/
2. Pull images from Github registry:

```
docker pull ghcr.io/witty-works/test-img:test
docker pull ghcr.io/witty-works/languagetool:v1

```

3. Run images:

```
docker run --rm -it -p 8010:8010 ghcr.io/witty-works/languagetool:v1
docker run  -p 8000:8000 --name nlp --network "bridge" --env languagetool_api=http://172.17.0.1:8010/v2 ghcr.io/test-img:test
```

## using pipenv

```
pipenv install --dev
pipenv run python3.9 -m spacy download en_core_web_sm
pipenv run python3.9 -m spacy download de_core_news_sm
```

## using virtual environment (venv)

```
python -m venv /path/to/new/virtual/environment
source /path/to/new/virtual/environment/bin/active
python3.9 -m pip install -r requirements.txt
python3.9 -m spacy download en_core_web_sm
python3.9 -m spacy download de_core_news_sm
```

Compile PO files (done automatically during deployment and above pot/po file generation)

```
pipenv run pybabel compile -d locales -l de_DE -f
pipenv run pybabel compile -d locales -l en_GB -f
```

Create directory for the Spacy models

```
mkdir files
```

Note to uninstall spacy models use

```
pipenv uninstall en_core_web_sm
pipenv uninstall de_core_news_sm
```

## Docker image

### Build Docker image:

After making change in the code or in the Dockerfile, build new image with the following command:

```
docker build -t DockerImageName:DockerImageRelease
```

## Install Platform.sh CLI

- Run `platform login`
- Run `platform project:set-remote`
- Run `platform list` to find out what commands are available
- Run `platform help [command]` to find out details about a command

see https://docs.platform.sh/development/cli.html for details

## Run Locally

---

Note for the Mac users. Set environment variables with the following snippet:

```
source .env.development.mac
```

You could alternatively set these variables in:

- when using venv: set variables in a `/path/to/new/virtual/environment/bin/activate` file. This way they will be set each time virtual environment is activated.
- when using conda: follow instructions in this article: https://guillaume-martin.github.io/saving-environment-variables-in-conda.html

---

```
pipenv run uvicorn app.main:app --reload
```

or

```
uvicorn app.main:app --reload
```

Open your browser to http://localhost:8000/docs to view the OpenAPI UI.

For an alternate view of the docs navigate to http://localhost:8000/redoc

## Production Deployment

Set an env variable `API_DOCS_AUTH_ENABLED` to `"true"` and for the username/password called `API_DOCS_USERNAME` and `API_DOCS_PASSWORD` for basic auth for the API docs.

Set am env variable `LANGUAGETOOL_API` to the URL endpoint of your LanguageTool server.
Default is `https://api.languagetool.org/v2`.

If the build fails due to "No space left on device" while installing the dependencies  run:

```
platform project:clear-build-cache
```

see:
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
## Cloud deployment
Test deployment(proof of concept) was done on Azure Kubernetes service with Docker images attached to this repository.
More about that: https://www.notion.so/witty-works/Cloud-Deployment-Approaches-a5320f3e1b854e1e817909d365118ee7#cd1d5b8f43d449088c59de1b816119fd

## Run tests

To run the entire test suite

```
pipenv run pytest -vv
```

To only run the last failing tests

```
pipenv run pytest -vv --lf
```

To update the fixtures with the current API responses run

```
pipenv run pytest --snapshot-update
```

Make sure to review the changes if they are indeed intended before commiting!

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

## Analyze Rules

Go to https://docs.google.com/spreadsheets/d/1G68x7SUGwolD5pFNG8ZCzvstVqRGz2ir/edit#gid=1195384709
CLick on "File" -> "Download" -> CSV

```
pipenv run python -m analyze_rules -i [CSV export]]
```

## Update the ignore.txt

```
pipenv run python -m add_alternatives_to_ignore
```

## Collect statistics

Run `./statistics.sh` to fetch statistics locally and remotely.
See `./statistics.sh -h` for instructions.