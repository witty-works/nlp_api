// The /textarea page: the editor, the API key, AI suggestions and the prompt.
// Served as a file (not inline) so the page runs under `script-src 'self'`.
// Its limits come from the page (a JSON block the server fills in).
const CONFIG = JSON.parse(document.getElementById("page-config").textContent);

const status = document.getElementById("status");
const apiKey = document.getElementById("api-key");
const aiSuggestions = document.getElementById("ai-suggestions");
const aiNote = document.getElementById("ai-suggestions-note");
const editor = WittyEditor.mount(document.getElementById("editor"), {
  // Long texts are checked in requests of this API's size.
  maxRequestLength: CONFIG.checkMax,
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
const TEXT_MAX = CONFIG.textMax;
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
  if (status === 403) return "This API key may not use the language model.";
  if (status === 502) {
    return "The language model's answer was cut off. Try a shorter text or prompt.";
  }
  if (status === 503) return "The language model is busy. Try again in a moment.";
  const detail = Array.isArray(body?.detail) ? body.detail[0] : null;
  // The route's own refusals say what is wrong; FastAPI's validation errors
  // have the same shape but a different type, and name the field instead.
  if (status === 422 && detail?.type === "value_error.not_supported") {
    return detail.msg + ".";
  }
  if (status === 422 && detail) {
    const field = detail.loc?.[1];
    return field === "text"
      ? "The text is too long to rewrite with a prompt."
      : field === "prompt"
        ? "The prompt is too long."
        : "The request was not accepted (422).";
  }
  return "The prompt failed (" + status + ").";
};

// Two language model calls and a check, each bounded on the server
// (LLM_TIMEOUT); past this the page stops waiting rather than stay read-only.
const WRITE_TIMEOUT_MS = 150000;

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
      signal: AbortSignal.timeout(WRITE_TIMEOUT_MS),
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
    writeStatus.textContent =
      error.name === "TimeoutError"
        ? "The prompt took too long. Try again, or with a shorter text."
        : "The prompt failed: " + error.message;
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
