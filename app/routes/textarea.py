"""Textarea route returning a simple HTML form and simple handlers."""

from fastapi import APIRouter
from starlette.responses import HTMLResponse

router = APIRouter()


@router.get("/textarea", include_in_schema=False)
def get_textarea() -> HTMLResponse:  # pragma: no cover
    html = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Textarea</title>
  </head>
  <body>
    <h1>Submit Text</h1>
    <form method="post" action="/textarea">
      <textarea name="text" rows="10" cols="80"></textarea>
      <br />
      <button type="submit">Submit</button>
    </form>
  </body>
</html>"""
    return HTMLResponse(content=html)
