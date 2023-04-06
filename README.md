# NLP API

NLP API for inclusive language: https://api.witty.works

## Resources

This project has two key dependencies:

| Dependency Name | Documentation                | Description                                                                            |
| --------------- | ---------------------------- | -------------------------------------------------------------------------------------- |
| spaCy           | https://spacy.io             | Industrial-strength Natural Language Processing (NLP) with Python and Cython           |
| FastAPI         | https://fastapi.tiangolo.com | FastAPI framework, high performance, easy to learn, fast to code, ready for production |

---

# Installation instructions (with python3.11)

- Install Platform.sh CLI https://docs.platform.sh/development/cli.html
  - Run `platform login`
  - Run `platform project:set-remote` (select `witty`)
  - Run `platform list` to find out what commands are available
  - Run `platform help [command]` to find out details about a command

## Using Docker

1. Install Docker engine - https://docs.docker.com/engine/install/
2. Pull images from Azure container registry:

```
az login
az acr login --name wittyworks
docker pull wittyworks.azurecr.io/nlpapi:main
docker pull wittyworks.azurecr.io/languagetool:main
```

3. Run images:

First run the LanguageTool image:

```
docker run --rm --name lt -p 8000:8000 wittyworks.azurecr.io/languagetool:main
```

Open another terminal tab and check LanguageTool container local address:

```
lt_api=`docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' lt`
```

As a last step run the NLP API image:

```
docker run --rm --name nlp_api -p 8080:8080 --network "bridge" --env languagetool_api="$lt_api/v2" wittyworks.azurecr.io/nlpapi:main
```

You should see application running under http://localhost:8000/docs

## Using pdm

```
pdm install --dev
wget -P training_data https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin
```

Compile PO files:

```
./compile-translations.sh
```

## Update dependencies locally

To update packages locally after pyproject.toml/pdm.lock was changed, run the
command:

```
pdm install --dev
```

## Add new package

When adding new package to the project, you need to updated existing
pyproject.toml. Following command will install the package and add it to the
`pyproject.toml/pdm.lock` and `pyproject.toml/pdm.lock`:

```
pdm add <package_name>
```

## Docker image

### Build Docker image:

After making changes in the code or in the Dockerfile, you can run the local
setup. Build new image with the following commands:

```
pdm export --prod -o requirements.txt
python3.11 -m pip install -r requirements.txt
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
cp .env.development.mac .env
```

---

```
pdm run uvicorn app.main:app --reload
```

or

```
uvicorn app.main:app --reload
```

Open your browser to http://localhost:8000/docs to view the OpenAPI UI.

For an alternate view of the docs navigate to http://localhost:8000/redoc

## Profiling locally

```
pdm run blackfire-python uvicorn app.main:app --reload
```

Make sure you have a `.blackfire.ini`, get the settings from
https://blackfire.io/docs/php/configuration

Make sure you to select "Witty Works > NLP API" (defaults to "Personal")

```
BLACKFIRE_SERVER_ID=""
BLACKFIRE_SERVER_TOKEN=""
```

## Production Deployment

Set an env variable `API_DOCS_AUTH_ENABLED` to `"true"` and for the
username/password called `API_DOCS_USERNAME` and `API_DOCS_PASSWORD` for basic
auth for the API docs.

If the build fails due to "No space left on device" while installing the
dependencies run:

```
platform project:clear-build-cache
```

see:
https://docs.platform.sh/development/troubleshoot.html#clear-the-build-cache

## Example API call

```
curl -X 'POST' \
  'http://127.0.0.1:8000/v1.1/check' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "text": "Wer sind unsere Kunden?"
}'
```

## Cloud deployment

Test deployment (proof of concept) was done on Azure Kubernetes service with
Docker images attached to this repository. More about that:
https://www.notion.so/witty-works/Cloud-Deployment-Approaches-a5320f3e1b854e1e817909d365118ee7#cd1d5b8f43d449088c59de1b816119fd

## Run tests

To run the entire test suite

```
pdm run pytest -vv
```

To only run the last failing tests

```
pdm run pytest -vv --lf
```

To update the fixtures with the current API responses run

```
pdm run pytest --snapshot-update
```

Make sure to review the changes if they are indeed intended before commiting!

## Benchmarking

Install the Apache HTTP server benchmarking tool:
https://httpd.apache.org/docs/2.4/programs/ab.html

```
ab -c 50 -n 100 -p tests/test_small.json -T application/json https://[env subdomain].platformsh.site/check
```

## Localization

Go to
https://www.notion.so/witty-works/e68e073dd0a342fca2a6683c7a8b2341?v=b54da99f8a6b4e6e8f312a530f653eb0
Export to CSV

```
pdm run python -m bin.update_locales -i [CSV export]
```

## Analyze Rules

```
pdm run python -m bin.analyze_rules -l en
```

## Update the ignore.txt

1. Download the current LanguageTool server

```
curl https://languagetool.org/download/LanguageTool-stable.zip
```

Unzip the file and move into the folder

2. Run the LanguageTool server

```
java -noverify -cp languagetool-server.jar org.languagetool.server.HTTPServer --public --allow-origin "*"
```

3. Run the script to generate ignore words for German:

```
pdm run python -m bin.analyze_rules -p <path_to_ignore_file>
```

for English:

```
pdm run python -m bin.analyze_rules -l en -p <path_to_ignore_file>
```

For example:

```
pdm run python -m bin.analyze_rules -l en -p ../languagetool/ignored_words/English/ignore.txt
pdm run python -m bin.analyze_rules -l de -p ../languagetool/ignored_words/German/ignore.txt
```

## Update the false positive list

1. Run server locally (or restart to re-read the training data), for example
   with pdm:

```
pdm run uvicorn app.main:app --reload
```

2. Run the generate_false_positive.py file

```
pdm run python -m bin.generate_false_positive
```

If you get an error here, please repeat steps 1-2 and run the script again.

## Collect statistics

Run `./statistics.sh` to fetch statistics locally and remotely. See
`./statistics.sh -h` for instructions.

## Incorrect German Noun Gender Detection

Missing word needs to be added to https://de.wiktionary.org/ and then update
https://github.com/gambolputty/german-nouns#compiling-the-list

## Incorrect/Missing German Articles

See https://www.verbformen.de/deklination/pronomen and update
./training_data/de-DE/articles.csv accordingly.
