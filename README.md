# NLP API

NLP API for inclusive language

## Resources
This project has two key dependencies:

| Dependency Name | Documentation                | Description                                                                            |
|-----------------|------------------------------|----------------------------------------------------------------------------------------|
| spaCy           | https://spacy.io             | Industrial-strength Natural Language Processing (NLP) with Python and Cython           |
| FastAPI         | https://fastapi.tiangolo.com | FastAPI framework, high performance, easy to learn, fast to code, ready for production |
| HanTa           | https://github.com/wartaal/HanTa | The Hanover Tagger - A simple approach to lemmatization and POS-tagging based on heuristics and hidden markov models of German morphology.         |
---

## Install

```
pipenv install
pipenv shell
pipenv run python3 -m spacy download en_core_web_sm
pipenv run python3 -m spacy download de_core_news_sm
```

Note to uninstall spacy models use

```
pip uninstall ..
```

## Install Platform.sh CLI

  * Run `platform login`
  * Run `platform project:set-remote`
  * Run `platform list` to find out what commands are available
  * Run `platform help [command]` to find out details about a command

see https://docs.platform.sh/development/cli.html for details

## Run Locally

```
pipenv shell
uvicorn app.main:app --reload
```

Open your browser to http://localhost:8000/docs to view the OpenAPI UI.

For an alternate view of the docs navigate to http://localhost:8000/redoc

## Example

```
curl -X 'POST' \
  'http://127.0.0.1:8000/entities' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "text": "Is London a city in England?",
  "lang": "auto"
}'
```
