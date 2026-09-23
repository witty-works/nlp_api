"""Textarea route: a page for checking text by hand against this API.

The page embeds Witty's editor component, which checks as you type through
/v2.4/check and underlines what it flags. It authenticates with an API key
entered on the page; the key stays in the page's memory and goes out only as
the `x-key` header.

`app/static/witty-editor.js` is a vendored build of the component from the
browser-extension repository (`packages/editor`), see docs/api.md.
"""

from pathlib import Path

from fastapi import APIRouter
from starlette.responses import FileResponse, HTMLResponse

router = APIRouter()

EDITOR_BUNDLE = Path(__file__).resolve().parent.parent / "static" / "witty-editor.js"

PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Witty check</title>
    <style>
      body {
        font: 16px/1.5 system-ui, sans-serif;
        max-width: 48rem;
        margin: 2rem auto;
        padding: 0 1rem;
      }
      label {
        display: block;
        font-weight: 600;
        margin-bottom: 0.25rem;
      }
      input {
        font: inherit;
        width: 100%;
        max-width: 24rem;
        padding: 0.25rem 0.5rem;
      }
      #editor {
        border: 1px solid #bbb;
        border-radius: 4px;
        padding: 0 0.75rem;
        margin-top: 1rem;
      }
      #editor:focus-within {
        border-color: #4a7bd0;
      }
      #status {
        color: #555;
        font-size: 0.875rem;
      }
    </style>
  </head>
  <body>
    <h1>Check text</h1>
    <p>
      <label for="api-key">API key</label>
      <input id="api-key" type="password" autocomplete="off" spellcheck="false" />
    </p>
    <div id="editor"></div>
    <p id="status" role="status" aria-live="polite"></p>
    <script src="/textarea/witty-editor.js"></script>
    <script>
      const status = document.getElementById("status");
      const editor = WittyEditor.mount(document.getElementById("editor"), {
        onStatus(next) {
          status.textContent =
            next.state === "idle"
              ? next.alerts + (next.alerts === 1 ? " alert" : " alerts")
              : next.state === "unauthorized"
                ? "Enter a valid API key to check the text."
                : "Checking failed: " + next.message;
        },
      });
      document.getElementById("api-key").addEventListener("input", (event) => {
        editor.setApiKey(event.target.value);
      });
    </script>
  </body>
</html>"""


@router.get("/textarea", include_in_schema=False)
def get_textarea() -> HTMLResponse:
    return HTMLResponse(content=PAGE)


@router.get("/textarea/witty-editor.js", include_in_schema=False)
def get_editor_bundle() -> FileResponse:
    return FileResponse(EDITOR_BUNDLE, media_type="text/javascript")
