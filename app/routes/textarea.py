"""Textarea route: a page for checking text by hand against this API.

The page embeds Witty's editor component, which checks as you type through
/v2.4/check and underlines what it flags. Below it a prompt, as in the
dashboard's Witty GPT, rewrites the text through /v1.0/write. Both authenticate
with an API key entered on the page; the key stays in the page's memory and
goes out only as the `x-key` header.

Off unless TEXTAREA_ENABLED is set. The editor script is not part of this
repository: `bin/fetch_editor.py` installs the pinned version of its npm package
(@witty-works/editor), or a local build, as `app/static/witty-editor.js`, see
docs/textarea.md.
"""

import json
import re
from functools import lru_cache
from html import escape
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, Response

from app.context import AppContext
from app.dependencies import get_app_context
from app.models import WRITE_PROMPT_MAX_LENGTH
from app.settings import Settings


router = APIRouter()

EDITOR_BUNDLE = Path(__file__).resolve().parent.parent / "static" / "witty-editor.js"

# Stricter than the rest of the API, whose policy the Swagger docs need: this
# is where people type their API key. No inline or third-party script (the
# page's own script is a file), requests only to this server, and not framed.
# The editor injects its styles, hence 'unsafe-inline' for styles only; its
# popover shows pictures from witty.works.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: https://www.witty.works",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)
CSP_HEADER = {"Content-Security-Policy": CONTENT_SECURITY_POLICY}

PAGE_DIR = Path(__file__).resolve().parent.parent / "textarea"
PAGE = (PAGE_DIR / "page.html").read_text(encoding="utf-8")
PAGE_SCRIPT = PAGE_DIR / "page.js"

MISSING_BUNDLE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Witty check</title>
  </head>
  <body>
    <main>
      <h1>The editor is not installed</h1>
      <p>
        TEXTAREA_ENABLED is on, but app/static/witty-editor.js is missing. Install
        it with <code>python bin/fetch_editor.py</code>, or build the image with
        <code>--build-arg TEXTAREA=true</code>. See docs/textarea.md.
      </p>
    </main>
  </body>
</html>"""


def render_page(settings: Settings) -> str:
    """The page, pointing people without a key to the deployment's contact,
    and to its imprint where it has one. It depends on nothing but these
    settings, so it is built once per combination of them."""
    return _render_page(
        settings.text_max_length,
        settings.textarea_contact or "",
        settings.textarea_imprint_url or "",
    )


@lru_cache(maxsize=8)
def _render_page(text_max_length: int, contact: str, imprint: str) -> str:
    # The limits the script needs, as data: a JSON block is not executed, so
    # it needs no inline script. `<` is escaped so the block cannot be closed.
    config = json.dumps(
        {"checkMax": text_max_length, "textMax": text_max_length}
    ).replace("<", "\\u003c")
    page = PAGE.replace("__PROMPT_MAX__", str(WRITE_PROMPT_MAX_LENGTH)).replace(
        "__CONFIG__", config
    )

    # Only a web address becomes a link, so a mistyped setting cannot put a
    # `javascript:` URL on the page.
    if imprint and urlparse(imprint).scheme in ("http", "https"):
        page = page.replace(
            "<!--imprint-->", f'<p><a href="{escape(imprint)}">Imprint</a></p>'
        )
    else:
        page = page.replace("<!--imprint-->", "")

    if not contact:
        page = page.replace("<!--key-request-->", "").replace("<!--key-contact-->", "")
    else:
        address = escape(contact)
        mailto = escape(
            f"mailto:{quote(contact, safe='@')}?subject={quote('API key request')}"
        )
        page = page.replace(
            "<!--key-request-->",
            ' No key yet? <a href="#get-a-key">Request one</a>.',
        ).replace(
            "<!--key-contact-->",
            f"""<h2 id="get-a-key">Getting an API key</h2>
        <p>
          Write to <a href="{mailto}">{address}</a> and tell us what you would
          like to use it for.
        </p>""",
        )

    # A placeholder left in would show as text, or as an empty limit.
    leftover = re.search(
        r"__[A-Z_]+__|<!--(?:key-request|key-contact|imprint)-->", page
    )
    if leftover:
        raise RuntimeError(f"textarea page: {leftover.group(0)} was not filled in")

    return page


def _revalidated(request: Request, path: Path, media_type: str) -> Response:
    """A script, revalidated rather than downloaded on every visit.

    no-cache keeps a reinstalled version from being served stale, and the ETag
    lets a browser that has the current one get a 304 instead of it again;
    FileResponse sets an ETag but never answers a conditional request.
    """
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    stat = path.stat()
    etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
    headers = {
        "ETag": etag,
        # The security middleware keeps a Cache-Control the route set itself.
        "Cache-Control": "no-cache",
    }
    # A list of ETags, weak ones included (a proxy may have weakened ours).
    sent = request.headers.get("if-none-match", "")
    if any(tag.strip().removeprefix("W/") == etag for tag in sent.split(",")):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    return FileResponse(path, media_type=media_type, headers=headers)


def textarea_enabled(context: AppContext = Depends(get_app_context)) -> None:
    """A 404 unless the deployment asked for the page, as for any other path."""
    if not context.settings.textarea_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get(
    "/textarea",
    include_in_schema=False,
    dependencies=[Depends(textarea_enabled)],
)
def get_textarea(context: AppContext = Depends(get_app_context)) -> HTMLResponse:
    if not EDITOR_BUNDLE.is_file():
        return HTMLResponse(
            content=MISSING_BUNDLE,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers=CSP_HEADER,
        )

    return HTMLResponse(content=render_page(context.settings), headers=CSP_HEADER)


@router.get(
    "/textarea/witty-editor.js",
    include_in_schema=False,
    dependencies=[Depends(textarea_enabled)],
)
def get_editor_bundle(request: Request) -> Response:
    return _revalidated(request, EDITOR_BUNDLE, "text/javascript")


@router.get(
    "/textarea/page.js",
    include_in_schema=False,
    dependencies=[Depends(textarea_enabled)],
)
def get_page_script(request: Request) -> Response:
    """The page's own script."""
    return _revalidated(request, PAGE_SCRIPT, "text/javascript")
