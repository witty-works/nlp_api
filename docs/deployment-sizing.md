# Deployment sizing

What the NLP API needs to run on Proxmox/Docker, and which knobs change it. Written for whoever requests and sizes the VM.

The short version: the resident memory is almost entirely spaCy word vectors, so **which languages you load is the dominant cost**, workers are much cheaper than they look because the vectors stay shared, and LanguageTool wants roughly as much again as the API itself.

## What runs

| Container | Image | Why it is there |
| --- | --- | --- |
| `nlpapi` | built from this repo | the API itself |
| `redis` | `redis:7-alpine` | API keys, user and organization config |
| `languagetool` | built from [languagetool/](../languagetool/) | spell and grammar checking; **not started by default**, see below |

Plus two mounts into `nlpapi`:

- `./database` (read-only) — the rule database, ~8 MB as `dump.sql`, read into an in-memory SQLite at startup.
- `./models` (read-only) — SetFit context-checker weights, ~1.5 GB, only read when the context checker is on.

**Redis is not optional.** With no `REDIS_HOST` the app falls back to an in-process `FakeStrictRedis`, which is empty. Nothing errors: the API answers `200` with `{"results": []}` for every request, because no user has a config. This is easy to mistake for "the rules are broken" — it cost time while writing this document. The compose file wires it up so a fresh `docker compose up` does not land in that state.

## LanguageTool: prepared, off for now

LanguageTool is a second engine alongside the product's own rules. It is wired into `compose.yml` behind a profile so it is one command away, but nothing starts it and `LANGUAGETOOL_API` is empty.

**The setting's default is a third-party service, not "off".** `languagetool_api` defaults to `https://api.languagetoolplus.com/v2` in [app/settings.py](../app/settings.py), so a deployment that simply never mentions LanguageTool sends the text being checked to LanguageTool's hosted API. That is the wrong default for an on-premise install and the reason `compose.yml` sets the variable to empty explicitly rather than leaving it unset. Empty is the only value that means no spell checking *and* no outbound call.

**The hosted service is also wrong on correctness grounds, not only privacy.** It cannot carry this project's ignore lists, so it reports spelling errors on vocabulary the product uses deliberately, and it does not apply the `disabledRuleIds` in [languagetool/config.properties](../languagetool/config.properties) — several of which (`GLEICHBEHANDLUNG`, `ERSTSEMESTERIN`, `MAEDCHENNAME`, `PUTZFRAU`) are LanguageTool's own gendered-language rules, which overlap with the product's. Measured against the stock 6.8 image with a word taken from `de_ignore.txt`:

| | `"Die ARIA-Initiative ist wichtig."` |
| --- | --- |
| stock image | 1 typo match, `GERMAN_SPELLER_RULE` |
| image built from `languagetool/` | none |

So the container must be **built**, not pulled. `compose.yml` does that; the ignore lists are appended to LanguageTool's own (245,266 lines for German afterwards, of which 1,082 are ours), so both survive.

**Updating LanguageTool is one variable.** `LT_VERSION` in `.env` is the base image tag that [languagetool/Dockerfile](../languagetool/Dockerfile) builds on, so an update keeps the ignore lists and config:

    LT_VERSION=6.9
    docker compose --profile languagetool build

6.8 is the newest published tag as of 2026-09 and is what the Dockerfile now defaults to. It previously hardcoded 6.2 (2023-12-07), so enabling LanguageTool means a six-release jump: run the test suite and adjudicate the snapshot diff before trusting it, because LanguageTool retunes rules between releases and this project filters its output by rule and category id.

**One discrepancy with the Upsun deployment,** worth knowing if the two are ever compared: the Upsun build hook *overwrites* `ignore.txt` with ours (`cp`), where the Dockerfile *appends* (`>>`). Overwriting discards LanguageTool's own ~244,000 German entries, so Upsun will report far more spelling errors than this deployment does. Upsun also pins 6.3 where the Dockerfile pinned 6.2. Appending is the behaviour to keep.

**What you lose while it is off.** The whole `orthography` category — typos and punctuation — plus the style, plain-language and anglicism subcategories that are derived from LanguageTool's own rule categories. On the fixture `"Ich gehe noch schnell ueber die Strasse!!!"` those are the three findings `ueber → über`, `Strasse → Straße` and `!!! → !`. The gendered-language rules, which are the product, come from this repo and are unaffected: a check of `"Der Lehrer gibt dem Schüler den Stift."` returns the same two findings either way — verified by running it with the variable set and empty.

Degradation is clean rather than an error: `apply_languagetool_rules` returns an empty list when the variable is empty, so requests succeed with fewer findings.

**What it costs when you turn it on.**

| | |
| --- | --- |
| Memory | ~1.5 GiB resident at `Java_Xmx=2g`, measured while running the test suite |
| `LT_MEM_LIMIT` | `3g` — the container limit has to clear the heap plus JVM overhead |
| Disk | ~1 GB image |
| VM | **add 3 GB** to the figures below |

The JVM grows to fill whatever heap it is given, so `Java_Xmx` is the real knob and the container limit follows it. An earlier `4g` setting here was over-provisioned: `2g` runs the full suite.

To turn it on:

    docker compose --profile languagetool build
    docker compose --profile languagetool up -d

and set `LANGUAGETOOL_API=http://languagetool:8010/v2` in `.env`. The API side needs no rebuild; the LanguageTool image does, because it is built from this repo rather than pulled.

One caveat for later: LanguageTool serves 60 languages and loads them lazily, so the resident figure above reflects the languages actually exercised. Serving a lot of English and French traffic as well as German may push it higher; re-measure before trusting `3g` under real load.

## The four dimensions

Two are build-time and change the image; two are runtime and change the footprint of a running container.

### 1. spaCy model size — build time

`SPACY_MODEL_SIZE=sm|md|lg`, default `lg`.

This is the biggest lever on both disk and memory, because `lg` models carry word vectors and `sm` models carry none at all. Of `de_core_news_lg`'s 610 MB on disk, 596 MB is the `vocab` directory; for `en_core_web_lg` it is 411 MB of 425 MB. The pipeline components — tagger, parser, NER — are about 7 MB each.

It is also the only dimension that changes **output**. The product is tuned and snapshot-tested against `lg`; `sm` would change findings across the board. Treat `sm`/`md` as a way to fit a test or demo box, not as a production saving, and re-run the suite before believing anything measured on them.

### 2. Languages — build time and runtime

`SPACY_LANGS=en,de,fr` at build time decides which model wheels go into the image at all. `MODELS` at runtime decides which of those get loaded; it defaults to everything the build installed, so it only needs setting to load *fewer* languages than the image contains.

Splitting it this way means one image can serve a German-only instance and a three-language instance, while a German-only image is also available if disk matters more than flexibility.

### 3. Workers — runtime

`WORKERS`, default 1. gunicorn runs with `--preload`, so the models load once in the parent and workers are forked from it. The vectors are large contiguous arrays that nothing writes to, so they stay shared copy-on-write; what each worker adds is its own heap, request buffers, and the Python objects whose refcounts get touched.

Measured on `en_core_web_sm` (see below), four workers cost 1.93 GiB against a 897 MiB single-worker baseline — about 344 MiB per extra worker rather than another full copy. The saving is larger with `lg` models, because the shared portion is bigger.

**Do not remove `--preload`.** Without it each worker loads its own copy and the memory genuinely multiplies.

### 4. Context checker — runtime

`CONTEXT_CHECKER_LOCAL`, default `false`. When on, the SetFit models under `/code/models` load into each worker's parent process. On disk they are ~1.5 GB for two languages (`de` 1078 MB, `en` 419 MB; there is no French model in the repo), and they add roughly as much resident memory again as the spaCy models do.

The loader calls `share_memory()` on the model body, so it is fork-friendly in the same way the spaCy models are.

Note that torch is in the image whether or not you enable this: spaCy's own backend, thinc, imports torch when it is installed, so it loads at startup regardless. That is ~408 MB of the image and a fixed part of the baseline. Removing it would mean dropping SetFit from the dependency set entirely, which is a code change, not a deployment one.

## Measured numbers

**Method.** Built from this repo and run under Docker, memory read from `docker stats` (cgroup accounting, so shared pages are counted once for the whole container). Each case was booted until `/health` returned 200, then left to settle before reading.

**Two caveats that matter for a procurement number.** These were taken on `linux/aarch64` under Docker Desktop on macOS; a Proxmox host will be `x86_64`, where the figures will be close but not identical. And they are idle-after-boot figures — they do not include per-request working memory under load. Size with headroom and confirm on the real host.

**Image on disk.** 3.91 GB for the default build (three languages, `lg`). 2.20 GB for a single-language `sm` build — so torch and the rest of the Python environment, not the models, are most of a small image.

**Container memory, one worker unless stated, context checker off:**

| Configuration | Memory | Boot to healthy |
| --- | --- | --- |
| `en` only | 1.49 GiB | 12 s |
| `de` only | 1.83 GiB | 10 s |
| `fr` only | 1.90 GiB | 11 s |
| `de` + `en` | 2.44 GiB | 11 s |
| all three | 3.46 GiB | 13 s |
| all three, 2 workers | 3.94 GiB | 13 s |
| all three, 4 workers | 4.81 GiB | 12 s |
| `de` only, context checker on | 3.92 GiB | 14 s |
| all three, context checker on | 5.31 GiB | 18 s |

What the table says, in three numbers:

- **A language costs 0.9–1.4 GiB.** Going from one language to three roughly doubles the container. There is a fixed baseline of about 0.5 GiB before any model loads, which is why three languages cost less than three times one.
- **An extra worker costs ~460 MiB**, against a 3.46 GiB single-worker baseline for three languages. Four workers are 4.81 GiB rather than the 13.8 GiB they would be without `--preload`.
- **The context checker costs ~1.9 GiB** and is close to flat across languages, because it always loads its `en` and `de` models regardless of `MODELS`. Up to 1.5 GiB of that is the shared-memory segment rather than the heap.

For the rest of the stack: LanguageTool sits at about 1.5 GiB with `Java_Xmx=2g` and wants a container limit above that, and Redis is negligible at this data volume.

## Recommended configurations

Three points on the curve, all **without LanguageTool** — add 3 GB to any of them to run it. "VM" is what to ask for, including room for the host, page cache and the usual headroom over the measured idle figures.

| | German only | All three languages | All three + context checker |
| --- | --- | --- | --- |
| `SPACY_LANGS` | `de` | `en,de,fr` | `en,de,fr` |
| `WORKERS` | 2 | 2 | 4 |
| `API_MEM_LIMIT` | `4g` | `6g` | `10g` |
| measured API idle | ~2.3 GiB | 3.94 GiB | ~6.7 GiB |
| **VM memory** | **6 GB** | **8 GB** | **12 GB** |
| **with LanguageTool** | 9 GB | 11 GB | 15 GB |
| VM disk | 25 GB | 30 GB | 35 GB |

Disk is image plus room for a second image during upgrades, the ~8 MB rule database, the 126 MB language-detection model, and 1.5 GB of SetFit weights in the last column.

**CPU.** Not measured here, and it is the axis this document is weakest on. spaCy inference is CPU-bound and single-threaded per request, so throughput scales with workers until memory or cores run out; start at 4 vCPU for the middle column and measure against real traffic before committing. Budget one core per worker as a first approximation.

### What we are deploying

The middle column, with room to move: **three languages, `lg` models, 2 workers to start and up to 4, context checker off, LanguageTool prepared but not running.** [.env.example](../.env.example) pins it; copy it to `.env` next to `compose.yml`.

**Ask for 16 GB.** What is being deployed needs about 8, and even with LanguageTool running it is 11. The larger number is for what happens next: every option deliberately left off here — LanguageTool, the context checker, more workers — costs memory, and all three are runtime switches that need no rebuild. 16 GB means turning any of them on is a restart rather than a change request. Growing a Proxmox VM's memory needs a reboot and a ticket; asking for the larger number once does not.

| | value |
| --- | --- |
| VM memory | **16 GB** (8 GB is the working set; the rest is headroom for the switches below) |
| VM disk | **30 GB** |
| vCPU | **4 to start**, 6 if running 4 workers |
| `API_MEM_LIMIT` | `8g` |
| `REDIS_MEM_LIMIT` | `512m` |
| `LANGUAGETOOL_API` | empty — the profile is not started |
| `LT_MEM_LIMIT` | `3g` (`LT_HEAP_MAX=2g`), when it is |

What can be changed later with only a restart: `WORKERS`, `CONTEXT_CHECKER_LOCAL`, `REQUIRE_API_KEY`, and starting the LanguageTool profile. What needs a rebuild: `SPACY_LANGS` and `SPACY_MODEL_SIZE` — which is the argument for building all three languages now even if only German is served at first.

## Running without the dashboard

The dashboard normally mints API keys and syncs user config into Redis. Without it the API can do both itself, and the path is already built in — `Redis.factory` writes the configured key on every start precisely because "a deployment that runs for one person has no dashboard to mint a key".

Set these and nothing else is needed:

    REDIS_HOST=redis
    REDIS_PORT=6379
    DEFAULT_API_KEY=<the key clients will send>
    DEFAULT_USER_EMAIL=<any identifier; it keys the config and the metrics hash>
    DEFAULT_USER_CONFIG_ENABLED=True
    DEFAULT_CONFIG={"german_gender_ending":"de-e"}

Verified end to end: with only this, Redis holds a single `api_key:<key>` entry and

    curl -X POST http://host:8080/v2.4/check \
        -H 'Content-Type: application/json' -H 'x-key: <the key>' \
        -d '{"text":"Der Lehrer gibt dem Schüler den Stift."}'

returns `Der Lehrer → De Lehrere` and `dem Schüler → derm Schülere`.

### Refusing anonymous requests

By default an unauthenticated request is answered with `200` and an empty result set rather than refused — deliberate, so that a signed-out client keeps working instead of erroring. For a deployment where nothing should be free, set:

    REQUIRE_API_KEY=True
    PUBLIC_PATHS=["/health","/v2.0/categories"]

Every other route then answers `401` without a credential, including `/version`, `/docs` and paths that do not exist — so the gate cannot be probed for which routes are there. `/health` stays open for monitoring and `/v2.0/categories` because a client needs it to render its UI before a key has been issued.

Two things it deliberately does not refuse: CORS preflight, which carries no credentials by definition and would break browser clients, and any path named in `PUBLIC_PATHS`. Add `/slack/commands` there if Slack is enabled — it authenticates by signature and cannot send an API key.

An SSO bearer token satisfies the gate as well as an `x-key` API key, so the browser extension and Word plugin keep working against a deployment that also has SSO configured.

Four things that cost time to find, all of which fail quietly:

- **The auth header is `x-key`**, not `Authorization` or `X-API-KEY`. A request with the wrong header name, or no key at all, still returns `200` — as an anonymous user with no config, so every response is `{"results": []}`. An empty result set is what a misauthenticated request looks like.
- **`REDIS_PORT` has no usable default.** It is `""`, and setting `REDIS_HOST` without it crashes at startup on `int("")`. Set both or neither.
- **`DEFAULT_CONFIG` applies to the request, not to the user.** It fills in request fields such as the gender ending. It does not enable categories; `DEFAULT_USER_CONFIG_ENABLED` is what gives the caller a usable config at all.
- **The management endpoints deliberately 404** for a default user. `GET /user/configs` answers "User configs not found" even when `/v2.4/check` works, because only the request path substitutes defaults — that is intentional, so "nothing stored" stays distinguishable from "the stored config happens to equal the default". Do not read that 404 as a broken setup.

`POST /user/configs` and `POST /organization/configs` are there for anything beyond one user, gated by `MANAGEMENT_AUTH_ENABLED` — leave that on. Configs created that way live only in Redis, which is why the compose file persists it (`--appendonly yes` and a named volume). `DEFAULT_API_KEY` is rewritten at every start and so survives losing the volume; anything posted to those endpoints does not.

## Operational notes

**The context checker needs a bigger `/dev/shm`.** Torch's `share_memory()` moves the model into shared memory, and Docker's default `/dev/shm` is 64 MB — a ~1 GB SetFit model overruns it and the process dies of SIGBUS. What you see is exit code 135, no log line, and `OOMKilled=false`, which looks like anything but a full `/dev/shm`. `compose.yml` sets `shm_size: 2gb`; a plain `docker run` needs `--shm-size=2g`. Harmless when the context checker is off, which is why it does not show up until the day you enable it.

**Two files are gitignored and must be provisioned separately.** `training_data/lid.176.bin` (126 MB, fastText language detection) and the rule database under `database/`. The Dockerfile copies the first from the build context, so the image is only correct if that file is present at build time; the second is mounted at runtime. Neither is in the repository.

**Startup is slow and that is normal.** Loading the models takes roughly 10–20 s per container before the first request can be served, longer with the context checker on. The `HEALTHCHECK` in the Dockerfile has `--start-period=120s` for that reason; shortening it makes Docker kill containers that are still coming up. The same applies to any load balancer in front: give it a slow-start or readiness delay, or a rolling restart will take the service down.

**Logging.** The app logs its full settings object at `DEBUG`, including secrets (Slack bot token, AWS secret key). Do not run production at `DEBUG`.

## The LLM side

Deliberately not sized here. The API already speaks to LLMs through litellm and has the settings for it — `LLM_MODEL`, `LLM_API_BASE`, `LLM_API_KEY`, plus `LLM_ACCESS` and `LLM_ALLOWED_USERS` to gate who gets it — so pointing it at a model already running in the network is configuration rather than code.

The resource cost of that model lands on whatever hosts it, not on this API; what changes here is only request latency and concurrency, since LLM calls are slow and hold a worker's async context while they wait. If Witty GPT arrives as an optional checkbox in the F13 deployment, the thing to size then is the LLM host and the worker count needed to absorb the added request duration, not the memory of this container.

## Re-measuring

The matrix above is reproducible. Build the image, then run each case and read `docker stats` after `/health` returns 200:

    docker build --build-arg SPACY_LANGS=en,de,fr --build-arg SPACY_MODEL_SIZE=lg -t nlpapi:all-lg .
    docker run -d --name m -e MODELS='["de_core_news_lg"]' -e WORKERS=1 \
        -e LANGUAGETOOL_API="" -p 8096:8081 -v "$PWD/database:/code/database:ro" nlpapi:all-lg
    curl -s localhost:8096/health && docker stats m --no-stream --format '{{.MemUsage}}'

Worth redoing on the target host once it exists, and after any spaCy or model version bump.
