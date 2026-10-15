// The /textarea page: the editor, the API key, AI suggestions and the prompt.
// Served as a file (not inline) so the page runs under `script-src 'self'`.
// Its limits come from the page (a JSON block the server fills in).
const CONFIG = JSON.parse(document.getElementById("page-config").textContent);

const checkStatus = document.getElementById("status");

function checkMessage(next) {
  if (next.state === "idle") {
    return next.alerts + (next.alerts === 1 ? " alert" : " alerts");
  }
  if (next.state === "unauthorized") {
    return "Enter a valid API key to check the text.";
  }
  return "Checking failed: " + next.message;
}
const apiKey = document.getElementById("api-key");
const aiSuggestions = document.getElementById("ai-suggestions");
const aiNote = document.getElementById("ai-suggestions-note");
const promptNote = document.getElementById("prompt-note");

// What the language model is for the key in the field, as /v2.0/auth
// reports it: whether the server has one, and whether this key may use it.
let llm = { available: false, allowed: false };

// Why the key may not use it, with where to ask for access. Only where the
// server has a model: otherwise there is nothing to grant.
function llmRefusal(element) {
  element.replaceChildren(
    llm.available
      ? "Not available with this API key."
      : "Not available on this server."
  );
  if (llm.available && CONFIG.llmAccessRequest) {
    const link = document.createElement("a");
    link.href = CONFIG.llmAccessRequest;
    link.textContent = "Ask for access";
    element.append(" ", link, ".");
  }
}
const editorElement = document.getElementById("editor");
const langSelect = document.getElementById("lang");
const exampleButton = document.getElementById("example");

// The editor takes the text's language when it is mounted, so choosing
// another one mounts it again (see below).
const mountEditor = (lang, content) =>
  WittyEditor.mount(editorElement, {
    lang,
    content,
    // A remounted editor checks its text straight away, so it needs the key
    // from the start rather than from a setApiKey afterwards.
    ...(apiKey.value && { apiKey: apiKey.value }),
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
      checkStatus.textContent = checkMessage(next);
    },
    // The editor's own settings panel has the same switch; both follow it.
    onSettingsChange(next) {
      aiSuggestions.checked = next.llmAlternatives;
    },
  });
let editor = mountEditor(langSelect.value);

// What this server offers, the same for everyone (asked without a key), as
// a list of everything this page can do, each available or not: every
// language the menu offers, spelling and grammar, the language model. What
// is missing is listed too, so nobody looks for it. Left out if the server
// does not say.
const serverFeatures = document.getElementById("server-features");
fetch("/v2.0/features")
  .then((response) => (response.ok ? response.json() : null))
  .then((body) => {
    const features = body?.features;
    if (!features) return;
    const loaded = features.languages?.values ?? [];
    const items = [...langSelect.options]
      .filter((option) => option.value !== "auto")
      .map((option) => [option.textContent, loaded.includes(option.value)]);
    if (features.spelling_grammar) {
      items.push(["Spelling and grammar", features.spelling_grammar.available]);
    }
    // Available on the server, but not to every key: marked, with the
    // footnote saying so (the note beside the checkbox says it per key).
    if (features.llm) {
      items.push(["AI suggestions and prompts", features.llm.available, "*"]);
    }
    serverFeatures.querySelector("ul").replaceChildren(
      ...items.map(([name, available, mark = ""]) => {
        const item = document.createElement("li");
        item.textContent =
          name + ": " + (available ? "available" + mark : "not available");
        if (!available) item.className = "missing";
        return item;
      })
    );
    document.getElementById("server-features-note").hidden = !features.llm?.available;
    serverFeatures.hidden = false;
  })
  .catch(() => {});

aiSuggestions.addEventListener("change", () => {
  editor.updateSettings({ llmAlternatives: aiSuggestions.checked });
});

// The example texts of the dashboard's former Witty Editor. Detect shows
// the English one. `shownExample` is the editor's text right after one was
// put in, so a language change can tell an untouched example from a text
// someone wrote.
const EXAMPLES = CONFIG.examples || {};
let shownExample = null;
function showExample() {
  const text = EXAMPLES[langSelect.value] || EXAMPLES.en;
  if (!text) return;
  // One transaction, so undo brings the previous text back.
  editor.editor.commands.setContent(toDoc(text));
  shownExample = editor.getText();
}
exampleButton.addEventListener("click", showExample);

langSelect.addEventListener("change", () => {
  const untouched = shownExample !== null && editor.getText() === shownExample;
  // The editor's own HTML, so nothing from outside it is parsed as markup.
  const content = editor.editor.getHTML();
  const { config, ...settings } = editor.getSettings();
  editor.destroy();
  editor = mountEditor(langSelect.value, content);
  editor.updateSettings(config ? { config, ...settings } : settings);
  applyInputState();
  // An example nobody changed follows the language; a text someone wrote
  // stays and is checked in the new language.
  if (untouched) showExample();
});

// Nothing can be typed or run until the key is known to work; while a
// prompt runs, the editor stays still because the answer replaces it.
const keyRequired = document.getElementById("key-required");
const keyRequiredText = document.getElementById("key-required-text");
let keyValid = false;
let running = false;
function applyInputState() {
  const llmUsable = keyValid && llm.allowed;
  editor.editor.setEditable(keyValid && !running);
  // The prompt is a language model request, so it is refused up front
  // rather than after it was written.
  prompt.disabled = !llmUsable;
  run.disabled = !llmUsable || running;
  aiSuggestions.disabled = !llmUsable;
  if (aiSuggestions.disabled && aiSuggestions.checked) {
    editor.updateSettings({ llmAlternatives: false });
  }
  keyRequired.hidden = keyValid;
  keyRequiredText.textContent = apiKey.value
    ? "This API key doesn't work. Check it for typos."
    : "Enter your API key above to use this page.";
  // Beside each control's label, so the reason is where the control is.
  for (const note of [aiNote, promptNote]) {
    if (keyValid && !llm.allowed) {
      llmRefusal(note);
    } else {
      note.replaceChildren();
    }
  }
}

// Whether the key works (/v2.0/auth: it also needs a config), and what the
// language model is for it (/v2.0/features), asked at the same time.
let keyCheck = 0;
async function checkApiKey() {
  const current = ++keyCheck;
  let valid = false;
  let capability = { available: false, allowed: false };
  if (apiKey.value) {
    const headers = { "x-key": apiKey.value };
    try {
      const [auth, features] = await Promise.all([
        fetch("/v2.0/auth", { method: "POST", headers }),
        fetch("/v2.0/features", { headers }),
      ]);
      valid = auth.ok;
      if (valid && features.ok) {
        capability = (await features.json()).features?.llm ?? capability;
      }
    } catch {
      valid = false;
    }
  }
  if (current !== keyCheck) return;

  keyValid = valid;
  llm = capability;
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
const tone = (alert) => {
  if (alert.subcategory === "corporate_rules") return "corporate";
  if (!alert.gravity) return "inclusive";
  if (alert.gravity < 1.5) return "severe";
  if (alert.gravity > 2.5) return "style";
  return "bias";
};

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
    if (field === "text") return "The text is too long to rewrite with a prompt.";
    if (field === "prompt") return "The prompt is too long.";
    return "The request was not accepted (422).";
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
        lang: langSelect.value,
        ...(Object.keys(config).length && { config }),
      }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      writeStatus.textContent = failure(response.status, body);
      // Refused although the key check allowed it: access changed since.
      // Asking again shows the refusal with where to ask for access.
      if (response.status === 403) checkApiKey();
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

// The page opens with the example, as the dashboard's editor did (after
// toDoc above is defined).
showExample();
