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

from html import escape
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, Response

from app.context import AppContext
from app.dependencies import get_app_context
from app.models import WRITE_PROMPT_MAX_LENGTH, WRITE_TEXT_MAX_LENGTH
from app.settings import Settings


router = APIRouter()

EDITOR_BUNDLE = Path(__file__).resolve().parent.parent / "static" / "witty-editor.js"

PAGE = r"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Witty: check and write inclusive text</title>
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
      input,
      textarea {
        font: inherit;
        width: 100%;
        max-width: 24rem;
        padding: 0.25rem 0.5rem;
        box-sizing: border-box;
      }
      textarea {
        max-width: none;
        resize: vertical;
      }
      /* A checkbox and its label side by side, unlike the text fields. */
      .checkbox {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin-top: 1rem;
      }
      .checkbox input {
        width: auto;
        margin: 0;
      }
      .checkbox label {
        margin: 0;
      }
      button {
        font: inherit;
        margin-top: 0.5rem;
        padding: 0.25rem 1rem;
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
      .lead {
        font-size: 1.125rem;
      }
      /* Hard to miss: nothing on the page works without a key. */
      .notice {
        margin: 1rem 0 0;
        padding: 0.5rem 0.75rem;
        border-left: 4px solid #b54708;
        background: #fff4e5;
      }
      .help {
        display: block;
        color: #555;
        font-size: 0.875rem;
        margin: 0.25rem 0 0;
      }
      #write h2,
      #about h2 {
        font-size: 1.125rem;
        margin: 2rem 0 0.5rem;
      }
      footer {
        border-top: 1px solid #ddd;
        margin-top: 3rem;
        padding-top: 1rem;
        color: #555;
        font-size: 0.875rem;
      }
      #status,
      #write-status {
        color: #555;
        font-size: 0.875rem;
      }
      #write {
        margin-top: 2rem;
      }
      #review h2 {
        font-size: 1rem;
        margin: 1.5rem 0 0.5rem;
      }
      #edits {
        white-space: pre-wrap;
        border-left: 3px solid #ddd;
        padding-left: 0.75rem;
      }
      del {
        color: #a33;
      }
      #issues .witty-alert {
        cursor: auto;
      }
      .visually-hidden {
        position: absolute;
        width: 1px;
        height: 1px;
        overflow: hidden;
        clip-path: inset(50%);
        white-space: nowrap;
      }
      ins {
        color: #262;
        text-decoration: none;
        background: #e6f4e6;
      }
    </style>
  </head>
  <body>
    <main>
      <h1>Check and write inclusive text</h1>
      <p class="lead">
        Witty points out language that can exclude or put off readers, such as
        gendered job titles, stereotypes or jargon, and suggests what to write
        instead. Type or paste a text below and it is checked as you type.
        Using it needs an API key.
      </p>
      <p class="help">
        What you type in the editor is sent to this server to be checked, and
        for AI suggestions and prompts also to the language model it uses.
        Don't enter anything confidential.
      </p>
      <p>
        <label for="api-key">API key</label>
        <input
          id="api-key"
          type="password"
          autocomplete="off"
          spellcheck="false"
          aria-describedby="api-key-help"
        />
        <span id="api-key-help" class="help">
          Needed to check text. It stays in this page and is only sent with its
          requests to this server; it is not saved.
        </span>
      </p>
      <p id="key-required" class="notice" role="status">
        <span id="key-required-text">Enter your API key above to use this
        page.</span><!--key-request-->
      </p>
      <div id="editor"></div>
      <p id="editor-help" class="help">
        Underlined words have a suggestion. Click one, or move the cursor onto it
        and press Alt+Shift+W, to see why it was flagged and what to write
        instead.
      </p>
      <div>
        <span class="checkbox">
          <input
            id="ai-suggestions"
            type="checkbox"
            disabled
            aria-describedby="ai-suggestions-help"
          />
          <label for="ai-suggestions">AI suggestions</label>
        </span>
        <span id="ai-suggestions-help" class="help">
          A language model fits each alternative into your sentence, adjusting
          articles, endings and verbs so the result stays grammatically
          correct.
          <span id="ai-suggestions-note"></span>
        </span>
      </div>
      <p id="status" role="status" aria-live="polite"></p>
      <form id="write">
        <h2>Write or rewrite with a prompt</h2>
        <label for="prompt">Prompt</label>
        <textarea
          id="prompt"
          rows="3"
          maxlength="__PROMPT_MAX__"
          placeholder="Make it shorter, or: Write a job ad for a nurse"
          aria-describedby="prompt-help"
        ></textarea>
        <span id="prompt-help" class="help">
          Describe a new text, or how to change the one above. A language model
          writes a draft, Witty checks it, and the model revises what Witty
          flagged. The result replaces the text above; undo brings the previous
          one back.
        </span>
        <button type="submit">Run</button>
        <p id="write-status" role="status" aria-live="polite"></p>
      </form>
      <section id="review" hidden>
        <h2>Issues Witty found in the draft</h2>
        <ul id="issues"></ul>
        <div id="edits-block">
          <h2>Edits from the follow-up prompt</h2>
          <p id="edits"></p>
        </div>
      </section>
      <section id="about">
        <h2>What you can use it for</h2>
        <ul>
          <li>Checking job ads and role descriptions before they go out</li>
          <li>Reviewing website, marketing and product copy</li>
          <li>Writing internal communication such as announcements and newsletters</li>
          <li>Drafting new texts with the prompt, inclusive from the first version</li>
          <li>Trying Witty on your own texts before building on its API</li>
        </ul>
        <!--key-contact-->
      </section>
    </main>
    <footer>
      <p>
        Witty is made by <a href="https://witty.works">Witty Works</a>.
      </p>
      <!--imprint-->
    </footer>
    <script src="/textarea/witty-editor.js"></script>
    <script>
      const status = document.getElementById("status");
      const apiKey = document.getElementById("api-key");
      const aiSuggestions = document.getElementById("ai-suggestions");
      const aiNote = document.getElementById("ai-suggestions-note");
      const editor = WittyEditor.mount(document.getElementById("editor"), {
        // Long texts are checked in requests of this API's size.
        maxRequestLength: __CHECK_MAX__,
        // The visible help below the editor, after the editor's own hint.
        describedBy: "editor-help",
        // The popover's LLM rewrites (/v1.0/rephrase): each one is an LLM
        // request, so they are off until the "AI suggestions" box is ticked.
        llmAlternatives: false,
        // Long enough for a local model through Ollama, not only a hosted one.
        llmTimeoutMs: 30000,
        onStatus(next) {
          status.textContent =
            next.state === "idle"
              ? next.alerts + (next.alerts === 1 ? " alert" : " alerts")
              : next.state === "unauthorized"
                ? "Enter a valid API key to check the text."
                : "Checking failed: " + next.message;
        },
        // The editor's own settings panel has the same switch; both follow it.
        onSettingsChange(next) {
          aiSuggestions.checked = next.llmAlternatives;
        },
      });

      aiSuggestions.addEventListener("change", () => {
        editor.updateSettings({ llmAlternatives: aiSuggestions.checked });
      });

      // Nothing can be typed or run until the key is known to work; while a
      // prompt runs, the editor stays still because the answer replaces it.
      const keyRequired = document.getElementById("key-required");
      const keyRequiredText = document.getElementById("key-required-text");
      let keyValid = false;
      let llmAllowed = false;
      let running = false;
      function applyInputState() {
        editor.editor.setEditable(keyValid && !running);
        prompt.disabled = !keyValid;
        run.disabled = !keyValid || running;
        aiSuggestions.disabled = !(keyValid && llmAllowed);
        if (aiSuggestions.disabled && aiSuggestions.checked) {
          editor.updateSettings({ llmAlternatives: false });
        }
        keyRequired.hidden = keyValid;
        keyRequiredText.textContent = apiKey.value
          ? "This API key doesn't work. Check it for typos."
          : "Enter your API key above to use this page.";
        aiNote.textContent =
          keyValid && !llmAllowed ? "Not available with this API key." : "";
      }

      // Whether the key works, and whether it may use the language model:
      // /v2.0/auth reports llm_alternatives as forced off where the server
      // would refuse it.
      let keyCheck = 0;
      async function checkApiKey() {
        const current = ++keyCheck;
        let valid = false;
        let llm = false;
        if (apiKey.value) {
          try {
            const response = await fetch("/v2.0/auth", {
              method: "POST",
              headers: { "x-key": apiKey.value },
            });
            if (response.ok) {
              valid = true;
              const setting = (await response.json()).config?.llm_alternatives;
              llm = !(setting?.status === "force" && setting.value === false);
            }
          } catch {
            valid = false;
          }
        }
        if (current !== keyCheck) return;

        keyValid = valid;
        llmAllowed = llm;
        applyInputState();
      }

      let keyCheckTimer;
      function useApiKey(delay) {
        editor.setApiKey(apiKey.value);
        clearTimeout(keyCheckTimer);
        keyCheckTimer = setTimeout(checkApiKey, delay);
      }
      apiKey.addEventListener("input", () => useApiKey(500));
      // A browser restoring the field on reload, or a password manager filling
      // it, sets the value without an input event.
      apiKey.addEventListener("change", () => useApiKey(0));
      if (apiKey.value) useApiKey(0);

      const form = document.getElementById("write");
      const prompt = document.getElementById("prompt");
      const run = form.querySelector("button");
      const writeStatus = document.getElementById("write-status");
      const review = document.getElementById("review");
      const issues = document.getElementById("issues");
      const edits = document.getElementById("edits");
      const editsBlock = document.getElementById("edits-block");
      const PROMPT_MAX = __PROMPT_MAX__;
      const TEXT_MAX = __TEXT_MAX__;
      // Disabled until a key is checked and works.
      applyInputState();

      // The dashboard's getColor, onto the editor's own underline classes.
      const tone = (alert) =>
        alert.subcategory === "corporate_rules"
          ? "corporate"
          : !alert.gravity
            ? "inclusive"
            : alert.gravity < 1.5
              ? "severe"
              : alert.gravity > 2.5
                ? "style"
                : "bias";

      // Read out, not shown: what colour and strike-through say on screen.
      const hidden = (text) => {
        const span = document.createElement("span");
        span.className = "visually-hidden";
        span.textContent = text;
        return span;
      };

      // Only a web link becomes an href; anything else stays text.
      const webUrl = (url) => {
        try {
          const parsed = new URL(url);
          return /^https?:$/.test(parsed.protocol) ? parsed.href : null;
        } catch {
          return null;
        }
      };

      // As the dashboard lists them: the flagged words underlined in their
      // colour, the explanation, and a link named after the subcategory.
      const issue = (alert) => {
        const item = document.createElement("li");
        const flagged = document.createElement("span");
        flagged.className = "witty-alert witty-alert--" + tone(alert);
        flagged.textContent = alert.text;
        item.append(flagged);
        if (alert.explanation?.text) item.append(" – " + alert.explanation.text);

        const url = webUrl(alert.explanation?.url);
        if (url) {
          const link = document.createElement("a");
          link.href = url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.append(
            (alert.label || "").split(":").pop().trim() || "More",
            hidden(" (opens in a new tab)")
          );
          item.append(" (", link, ")");
        }
        return item;
      };

      // The word diff comes from the API; only its text is put on the page.
      const edit = ({ op, text }) => {
        if (op === "equal") return document.createTextNode(text);
        const node = document.createElement(op === "insert" ? "ins" : "del");
        node.append(hidden(op === "insert" ? "added: " : "removed: "), text);
        return node;
      };

      // Plain text to editor JSON rather than HTML, so nothing the model
      // writes is ever parsed as markup.
      const toDoc = (text) => ({
        type: "doc",
        content: text.split(/\n{2,}/).map((paragraph) => ({
          type: "paragraph",
          content: paragraph
            .split("\n")
            .flatMap((line, i) => [
              ...(i ? [{ type: "hardBreak" }] : []),
              ...(line ? [{ type: "text", text: line }] : []),
            ]),
        })),
      });

      const failure = (status, body) => {
        if (status === 401) return "Enter a valid API key to run a prompt.";
        if (status === 403) return "This API key may not use the LLM.";
        // FastAPI's validation errors are a list; the route's own 422 is not.
        if (status === 422 && Array.isArray(body?.detail)) {
          const field = body.detail[0]?.loc?.[1];
          return field === "text"
            ? "The text is too long to rewrite with a prompt."
            : field === "prompt"
              ? "The prompt is too long."
              : "The request was not accepted (" + status + ").";
        }
        if (status === 422) return "The language of the draft could not be determined.";
        return "The prompt failed (" + status + ").";
      };

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        // Also reached by Ctrl/Cmd+Enter, which a disabled button does not stop.
        if (run.disabled || !prompt.value.trim()) return;

        const text = editor.getText();
        if (text.length > TEXT_MAX) {
          writeStatus.textContent =
            "The text is " + text.length + " characters long; a prompt can " +
            "rewrite up to " + TEXT_MAX + ".";
          return;
        }

        // The last run's issues and edits no longer describe the text.
        review.hidden = true;
        issues.replaceChildren();
        edits.replaceChildren();
        // The answer replaces the whole text, so typing meanwhile would be lost.
        running = true;
        applyInputState();
        writeStatus.textContent = "Writing…";
        try {
          // The toolbar's settings, so the draft is checked the way the editor
          // checks the text.
          const config = editor.getSettings().config || {};
          const response = await fetch("/v1.0/write", {
            method: "POST",
            headers: { "content-type": "application/json", "x-key": apiKey.value },
            body: JSON.stringify({
              prompt: prompt.value,
              text,
              ...(Object.keys(config).length && { config }),
            }),
          });
          if (!response.ok) {
            const body = await response.json().catch(() => null);
            writeStatus.textContent = failure(response.status, body);
            return;
          }

          const result = await response.json();
          const replacement = result.reviewed_response || result.initial_response || "";
          running = false;
          applyInputState();
          // One transaction, so a single undo brings the previous text back.
          editor.editor.commands.setContent(toDoc(replacement));

          // What Witty found and what the revision changed stay beside the
          // editor, so the editor itself only ever holds the text.
          const found = result.check_results;
          const revisable = found.filter((alert) => alert.alternatives?.length).length;
          issues.replaceChildren(...found.map(issue));
          edits.replaceChildren(...(result.edits || []).map(edit));
          editsBlock.hidden = !result.edits?.length;
          review.hidden = !found.length;

          const parts = ["Replaced the text."];
          if (found.length) {
            parts.push(
              "Witty flagged " + found.length + " issue(s) in the draft" +
                (result.reviewed_response
                  ? "; the " + revisable + " with alternatives were revised."
                  : "; none had alternatives to revise with.")
            );
          }
          if (result.limit_reached) {
            parts.push(
              "The draft is longer than Witty checks at once, so only its " +
                "beginning was checked."
            );
          }
          parts.push("Undo with Ctrl+Z / ⌘Z.");
          writeStatus.textContent = parts.join(" ");
        } catch (error) {
          writeStatus.textContent = "The prompt failed: " + error.message;
        } finally {
          running = false;
          applyInputState();
        }
      });

      prompt.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
          form.requestSubmit();
        }
      });
    </script>
  </body>
</html>"""


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
    and to its imprint where it has one."""
    contact = settings.textarea_contact
    page = (
        PAGE.replace("__PROMPT_MAX__", str(WRITE_PROMPT_MAX_LENGTH))
        .replace("__TEXT_MAX__", str(WRITE_TEXT_MAX_LENGTH))
        .replace("__CHECK_MAX__", str(settings.text_max_length))
    )

    # Only a web address becomes a link, so a mistyped setting cannot put a
    # `javascript:` URL on the page.
    imprint = settings.textarea_imprint_url
    if imprint and urlparse(imprint).scheme in ("http", "https"):
        page = page.replace(
            "<!--imprint-->", f'<p><a href="{escape(imprint)}">Imprint</a></p>'
        )
    else:
        page = page.replace("<!--imprint-->", "")

    if not contact:
        return page.replace("<!--key-request-->", "").replace("<!--key-contact-->", "")

    address = escape(contact)
    mailto = escape(f"mailto:{contact}?subject={quote('API key request')}")
    return page.replace(
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
        )

    return HTMLResponse(content=render_page(context.settings))


@router.get(
    "/textarea/witty-editor.js",
    include_in_schema=False,
    dependencies=[Depends(textarea_enabled)],
)
def get_editor_bundle(request: Request) -> Response:
    """The editor script, revalidated rather than downloaded on every visit.

    no-cache keeps a reinstalled version from being served stale, and the ETag
    lets a browser that has the current one get a 304 instead of ~1 MB again;
    FileResponse sets an ETag but never answers a conditional request.
    """
    if not EDITOR_BUNDLE.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    stat = EDITOR_BUNDLE.stat()
    headers = {
        "ETag": f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"',
        # The security middleware keeps a Cache-Control the route set itself.
        "Cache-Control": "no-cache",
    }
    if request.headers.get("if-none-match") == headers["ETag"]:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    return FileResponse(EDITOR_BUNDLE, media_type="text/javascript", headers=headers)
