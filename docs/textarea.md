# The /textarea page

A page for checking and rewriting text by hand against this API, authenticated with an API key typed into the page. It embeds Witty's editor component, the same highlighting and popover as the browser extension, and adds a prompt modelled on the dashboard's Witty GPT.

It is **off by default**. A deployment that does not turn it on serves no page (`/textarea` answers `404`, or `401` behind `REQUIRE_API_KEY` like any unknown path), opens no public path, and carries none of the editor's code: the editor script is not part of this repository and is only installed when asked for.

## What it does

- **Checks as you type.** The editor sends the text to `/v2.4/check` and underlines what comes back. A click on an underline, or `Alt+Shift+W`, opens the extension's popover with the explanation and alternatives, and LLM rewrites of the sentence from `/v1.0/rephrase` where the key's user may use the LLM.
- **Rewrites by prompt.** The prompt field sends the editor's text and the prompt to [`/v1.0/write`](./api.md#core-endpoints): the LLM writes a draft, the draft is checked, and the LLM applies Witty's alternatives to what was flagged. The editor gets the result as one change, so one undo brings the previous text back. Below the editor the page lists the issues found in the draft, linked to their explanations, and the edits the review made.

The editor itself is built and tested in the [browser-extension](https://github.com/witty-works/browser-extension) repository (`packages/editor`); this repository hosts the page around it.

## Setup

### 1. Install the editor script

```bash
python bin/fetch_editor.py
```

This downloads the editor release pinned in [bin/fetch_editor.py](../bin/fetch_editor.py) from the browser-extension repository's GitHub releases, checks each file against its pinned SHA-256, and installs `witty-editor.js` and the licence notices of the code bundled into it (`witty-editor.js.LICENSE.txt`) into `app/static/`. Both are ignored by git. Only the Python standard library is needed.

To build from a checkout of the browser-extension repository instead, for instance to try an unreleased change (needs Node.js and `npm install` done there):

```bash
python bin/fetch_editor.py --build ~/path/to/browser-extension
```

Until the editor has its first release, no release is pinned and only `--build` works; the script says so.

### 2. Turn the page on

```bash
TEXTAREA_ENABLED=true
```

With the page on, `/textarea` and `/textarea/witty-editor.js` are reachable without a key even behind `REQUIRE_API_KEY`, without listing them in `PUBLIC_PATHS`: the page is static and asks for a key itself, and every check it makes is gated as usual. If the script is missing, `/textarea` answers `503` with instructions instead of a broken editor.

### 3. Give it a key that checks something

The page needs an API key whose user has a config, or every check comes back empty (`200` with no results, which shows as "0 alerts"). With the dashboard that is any synced user. Without it, see [Running without the dashboard](./configuration.md#running-without-the-dashboard):

```bash
DEFAULT_API_KEY=<the key you will type into the page>
DEFAULT_USER_EMAIL=<any identifier>
DEFAULT_USER_CONFIG_ENABLED=true
```

### 4. Optional: an LLM for the prompt and the rewrites

Both need an LLM, and a user allowed to spend it; see [LLM provider](./configuration.md#llm-provider-llm-assisted-alternatives-and-rephrasing) and [Who may spend the LLM budget](./configuration.md#who-may-spend-the-llm-budget). Without a dashboard:

```bash
LLM_MODEL=ollama_chat/mistral-small:24b
LLM_API_BASE=http://localhost:11434
DEFAULT_USER_LLM_ALTERNATIVES=true
```

Without an LLM the page still checks and highlights; the prompt answers "This API key may not use the LLM." and the popover shows no rewrites.

For a local model through Ollama, Mistral Small 24B handled the rephrase prompt on a hand-checked sample of German and English sentences (French was wrong for every model tried). Apertus 1.5 8B does not follow that prompt when the flagged words start the sentence, so its popover rewrites mostly come back empty. Mistral Small at its default 32k context takes about 19 GB of memory.

### Docker

The image contains the editor script only when built with the `TEXTAREA` build argument, which runs the same download during the build:

```bash
TEXTAREA=true docker compose build
```

and `TEXTAREA_ENABLED=true` in `.env`. A script installed locally is not copied into the image (`.dockerignore`), so what an image serves is always the pinned release.

## Security

- The key typed into the page stays in the page's memory. It goes out only as the `x-key` header of the page's own requests, and is never written to an attribute, a cookie or storage. The editor's language setting (`i18nextLng`) is the only thing it stores.
- The page is public, its checks are not: without a valid key `/v2.4/check` and `/v1.0/write` answer `401`.
- The Content-Security-Policy allows scripts and styles from the API's own origin and inline, and images from the origin, inline `data:` images and `www.witty.works` (the popover's pictures). The page's requests go only to its own origin.

## Accessibility

The page's own markup (landmark, labels, live regions for the check and prompt status, the issue list and the edits, with the struck-through and inserted words read out as "removed" and "added") is checked with axe and has no findings. The editor and its popover are the component's and are checked in its repository.

## Updating the editor

When the browser-extension repository publishes a new editor release, update `RELEASE` and the two SHA-256 values in `FILES` in [bin/fetch_editor.py](../bin/fetch_editor.py), from the release's assets, and check the page against it. The page uses the component's `mount()` handle (`setApiKey`, `getText`, `editor`) and its `onStatus` callback; a release that changes those needs the page changed with it.
