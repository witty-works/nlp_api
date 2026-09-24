# The /textarea page

A page for checking and rewriting text by hand against this API, authenticated with an API key typed into the page. It embeds Witty's editor component, the same highlighting and popover as the browser extension, and adds a prompt modelled on the dashboard's Witty GPT.

It is **off by default**. A deployment that does not turn it on serves no page (`/textarea` answers `404`, or `401` behind `REQUIRE_API_KEY` like any unknown path), opens no public path, and carries none of the editor's code: the editor script is not part of this repository and is only installed when asked for.

## What it does

The page explains itself to a first-time visitor: what Witty checks, how the key is handled, what the page can be used for, and whom to ask for a key. That contact is `TEXTAREA_CONTACT`, `api@witty.works` by default; a deployment that hands out its own keys sets its own address, or an empty value to leave the section out. A deployment that has to show legal information sets `TEXTAREA_IMPRINT_URL` (e.g. `https://www.witty.works/impressum`), linked as "Imprint" in the footer; it is empty, and the link absent, by default.

- **Checks as you type.** The editor sends the text to `/v2.4/check` and underlines what comes back. A click on an underline, or `Alt+Shift+W`, opens the extension's popover with the explanation and alternatives, and LLM rewrites of the sentence from `/v1.0/rephrase` where the key's user may use the LLM.
- **Rewrites by prompt.** The prompt field sends the editor's text and the prompt to [`/v1.0/write`](./api.md#core-endpoints): the LLM writes a draft, the draft is checked, and the LLM applies Witty's alternatives to what was flagged. The editor gets the result as one change, so one undo brings the previous text back, and it is read-only while a prompt runs so nothing typed meanwhile is lost. The draft is checked with the settings chosen in the editor's toolbar, the same ones its underlines use. Below the editor the page lists the issues found in the draft, linked to their explanations, and the edits the review made.
- **Switching the gender format.** The editor's Witty menu (the W icon) has "Switch gender format…": it rewrites every gendered form into one of the eight German separator formats in one undoable step, using the check's `bulk: "gender_format"` alerts; see [Switching a text's gender format](./request-configuration.md#switching-a-texts-gender-format) for what is converted.
- **Length.** The API checks up to `TEXT_MAX_LENGTH` characters per request (1000 by default). The editor checks longer texts sentence by sentence in requests of that size (the page passes the deployment's value as `maxRequestLength`), up to 20000 characters, and says so under the text when part of it stayed unchecked. A prompt's draft is reviewed in one request, so the model is asked to keep it within `TEXT_MAX_LENGTH`, and the page says when a draft was longer and only its start was reviewed; the editor then still underlines the rest. A prompt can rewrite a text of up to `TEXT_MAX_LENGTH` characters, since its result has to fit what Witty checks at once.

The editor itself is built and tested in the [browser-extension](https://github.com/witty-works/browser-extension) repository (`packages/editor`); this repository hosts the page around it.

## Setup

### 1. Install the editor script

```bash
python bin/fetch_editor.py
```

This downloads the version of [@witty-works/editor](https://www.npmjs.com/package/@witty-works/editor) pinned in [bin/fetch_editor.py](../bin/fetch_editor.py) from the npm registry, checks the tarball against the `sha512` integrity the registry published for that version, and installs the editor script (`witty-editor.js`) and its licence (`witty-editor.js.LICENSE.txt`) into `app/static/`. Both are ignored by git. It needs only the Python standard library, not npm or Node.js. The package is published with npm provenance: its page on npmjs.com links each version to the browser-extension commit and build it came from.

To build from a checkout of the browser-extension repository instead, for instance to try an unreleased change (needs Node.js and `npm install` done there):

```bash
python bin/fetch_editor.py --build ~/path/to/browser-extension
```

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

and `TEXTAREA_ENABLED=true` in `.env`. A script installed locally is not copied into the image (`.dockerignore`), so what an image serves is always the pinned npm release.

## Security

- The key typed into the page stays in the page's memory. It goes out only as the `x-key` header of the page's own requests, and is never written to an attribute, a cookie or storage. The editor's language setting (`i18nextLng`) is the only thing it stores.
- The page is public, its checks are not: without a valid key `/v2.4/check` and `/v1.0/write` answer `401`.
- The Content-Security-Policy allows scripts and styles from the API's own origin and inline, and images from the origin, inline `data:` images and `www.witty.works` (the popover's pictures). The page's requests go only to its own origin.

## Accessibility

The page's own markup (landmark, labels, live regions for the check and prompt status, the issue list and the edits, with the struck-through and inserted words read out as "removed" and "added") is checked with axe (WCAG 2.2 AA and best practice). With editor 2.5.0 there are no findings, including with its Witty menu or its gender format panel open, with the popover open, or after a prompt run. The editor, its toolbar and popover are the component's, and are tested in its repository.

## Updating the editor

Moving to a new version of `@witty-works/editor` is the one step that uses npm, and only on the maintainer's machine:

```bash
python bin/fetch_editor.py --pin 2.0.2
python bin/fetch_editor.py
```

`--pin` installs that version into a throwaway npm project (with `--ignore-scripts`, so nothing from the package runs) and has `npm audit signatures` verify its registry signature and its provenance. It then requires the provenance to name the browser-extension repository's `.github/workflows/publish-editor.yaml`, run from the tag named after the version, and only then writes the version and the integrity npm verified into `bin/fetch_editor.py`. A version published any other way, for instance from a leaked token, is refused. The second command installs it; check the page against it before committing the new pin.

The pin is what protects every later install: the download is checked against the integrity in the script, which changes only through a reviewed commit. That is why installs need no npm.

The page uses the component's `mount()` handle (`setApiKey`, `getSettings`, `getText`, `editor`) and its `describedBy` and `maxRequestLength` options and its `onStatus` callback; a release that changes those needs the page changed with it.
