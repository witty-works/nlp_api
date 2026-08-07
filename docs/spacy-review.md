# spaCy Usage Review and Refactoring Plan

Written 2026-08-07, after the `feature/tweaks` merge (#1229) added another
determiner-list workaround for noun number. This records a fundamental review of
how the code uses spaCy, the evidence behind it, and a staged plan for using
spaCy's own machinery instead of compensating for it. It is a plan, not a
change; each phase is independently shippable.

All probe results below were produced against the pinned models
(`de_core_news_lg` 3.7.0, spaCy 3.7.5) — rerun them before acting on this doc
if the pins have moved.

## The diagnosis in one paragraph

The code treats spaCy as an unreliable token labeler and compensates with
lookups and heuristics. Those compensation layers — not spaCy — are now the main
source of complexity: six places overwrite `token.lemma_`, three separate lemma
override tables, an expectation-biased word-type cascade mixing three tagsets, a
hand-rolled pattern matcher, and number detection that consults a word list
before the morphologizer. Meanwhile the parts of the `lg` models that would
answer these questions natively — the morphologizer, the dependency parser, the
trainable lemmatizer — are demoted, unused, or removed at load time. The stated
reason (model-swap stability: "a fixed list behaves the same on every model") is
legitimate, but the codebase has no instrument that measures per-model behavior,
so the workaround cannot be retired even where the model is now right. The plan
is therefore: build the measurement first, then move each compensation layer
onto spaCy's native mechanism behind that measurement.

## What spaCy provides vs. what we rebuilt

| Fact needed | spaCy's mechanism | What the code does instead |
|---|---|---|
| word type | `pos_` (UPOS, normalized by `attribute_ruler`) | `_fetch_word_type` cascade over mixed UPOS/STTS/PTB sets, biased by the caller's expected type ([app/model.py:141-252](../app/model.py#L141-L252)) |
| noun number | `morph.get("Number")` | word list first, static determiner lists second, morph third ([app/model.py:425-480](../app/model.py#L425-L480)) |
| determiner→noun binding | parser `det` edge / `token.lefts` | manual ≤3-token walk-back over ADJ/ADV ([app/model.py:411-423](../app/model.py#L411-L423)) |
| lemma | trainable edit-tree lemmatizer (removed at load) | lookup lemmatizer + `lookup.json` pipe + `rules_lemmatization` rewrites inside a getter + `german_lemmatization` per token + two more ad-hoc writes ([app/model.py:375-381](../app/model.py#L375-L381), [app/model.py:127-137](../app/model.py#L127-L137), [app/rule_processors.py:225](../app/rule_processors.py#L225), [app/db.py:342](../app/db.py#L342)) |
| phrase/pattern matching | `Matcher`/`PhraseMatcher` with `LEMMA`/`LOWER`/`OP` | hand-rolled `is_phrase_match`/`check_pattern`/`is_word_match` with a `|`-DSL ([app/rule_engine/matchers/pattern.py](../app/rule_engine/matchers/pattern.py)); the one real `Matcher` is rebuilt per request ([app/rule_processors.py:208](../app/rule_processors.py#L208)) |
| word vectors | the reason `lg` models are large | entirely unused — no `.similarity`/`.vector` anywhere |

German gender comes from suffix statistics ([app/rules.py:841-917](../app/rules.py#L841-L917)) while French reads `morph.get("Gender")` — the same fact, two philosophies.

## Probe evidence (2026-08-07, pinned models)

**Number on ambiguous weak nouns.** The exact problem the tweaks merge solved
with determiner lists: `Kunden` is singular oblique and plural. The
morphologizer got all seven probe cases right, including bare *"Anfragen von
Kunden"* where the determiner walk-back has nothing to walk back to and returns
None:

| sentence (abbrev.) | morph Number | correct |
|---|---|---|
| mit unserem Kunden | Sing | ✓ |
| mit unseren Kunden | Plur | ✓ |
| berät den Kunden | Sing | ✓ |
| berät die Kunden | Plur | ✓ |
| dem Kunden zur Seite | Sing | ✓ |
| Anfragen von Kunden | Plur | ✓ (list+determiner both fail here) |
| Zufriedenheit unserer Kunden | Plur | ✓ |

Also: *"Viele"* — the documented reason for distrusting the tagger
([app/rules.py:780-785](../app/rules.py#L780-L785)) — tagged `Plur` correctly in
all probes. The claim may date to an older model; without a corpus we cannot
tell, which is the point of Phase 0.

**Determiner binding.** On the sentence the walk-back's own comment cites
(*"eine Arbeitskraft für unsere Kunden"*), `token.lefts` yields `Eine` for
*Arbeitskraft* and `unsere` for *Kunden* — the parser already scopes the
determiner to its noun phrase.

**Lemmatizers.** `de_core_news_lg` ships a *trainable* edit-tree lemmatizer;
`load_nlp_model` discards it. Comparison on domain vocabulary:

| token | trained lemmatizer | lookup lemmatizer (prod) |
|---|---|---|
| Geschäftsführerinnen | Geschäftsführerin ✓ | Geschäftsführerinnen ✗ (unchanged) |
| Ärztinnen | Ärztin ✓ | Ärztin ✓ |
| Kund:innen | Kund:inn ✗ | Kund:innen (unchanged) |

The trained one generalizes to unseen feminine compounds — the vocabulary this
product is about — but mangles gender-colon forms. The lookup one is safe on
colon forms and silently wrong on any compound not in its tables. That failure
is exactly what the DB reverse-index over every declension column
([app/db.py:486-503](../app/db.py#L486-L503)) and the three lemma override
layers exist to paper over.

## The measurement gap

The snapshot corpus (181 cases) captures only end-to-end results (`text`,
`category`, `alternatives`, …) — `grep -rl word_type tests --include=output.json`
matches nothing. POS/lemma/number decisions are invisible except through whether
a rule fired. The direct instrument already exists —
`GET /debug/spacy?detailed=true` ([app/routes/debug.py:139-217](../app/routes/debug.py#L139-L217))
returns per-token `word_type`, `lemma`, `is_singular`, `morph`, `tag`, `pos`,
`dep` — but only two hand-written tests use it. So today:

- a spaCy model swap (`MODELS` env var) can only be evaluated as "how many of
  181 snapshots changed", with no view of *why*;
- a workaround can never be retired, because there is no way to show the model
  now handles the case;
- the anti-morph docstrings cannot be confirmed or refuted.

## Plan

### Phase 0 — build the instrument (small; unblocks everything else)

Add a snapshot test group that POSTs a sentence corpus to
`/debug/spacy?detailed=true` and snapshots the per-token analysis. Seed the
corpus from the existing 181 `input.json` texts plus targeted sets: ambiguous
weak nouns, gender-colon/star forms, feminine compounds, the `viele`-class
determiners. This reuses `get_dirs`/`pytest-snapshot` exactly as
[tests/test_api.py:240-265](../tests/test_api.py#L240-L265) does. While there,
pass `ids=` to `parametrize` so case IDs are directory names instead of
positional indices.

This yields, per proposed change: a token-level diff (what re-tagged, what
re-lemmatized) alongside the end-to-end diff (which rules changed). A/B recipe
for any model or pipeline change: scratch worktree → change → `pdm run pytest
--snapshot-update` → `git diff --stat tests/`. Requires the pinned local
LanguageTool 6.8 for the end-to-end groups; the new `/debug/spacy` group needs
no external service.

Optionally grow a small adjudicated gold subset (expected `word_type`/`Number`
for the tokens rules care about — the DB's `person_words` gives the inventory).
Snapshots say *what changed*; only gold says *what is right*.

### Phase 1 — one lemma authority

Today lemmas are written in six places across four layers, including inside a
getter (`fetch_word_type` rewrites `token.lemma_` as a side effect,
[app/model.py:127-137](../app/model.py#L127-L137)), so the lemma a rule sees
depends on which checks ran before it. Target state:

- One pipeline component owns lemmas: base lemmatizer, then a single override
  table merged at startup from `training_data/lookup.json` +
  `rules_lemmatization` (+ the word-type-conditional entries keyed properly).
- Evaluate trained vs. lookup base lemmatizer with the Phase 0 corpus. The
  probe suggests: trained lemmatizer + a guard that exempts tokens matching the
  gender-symbol pattern (`:`/`*`/`·` infix) gets compound generalization without
  the `Kund:inn` failure. If the diff says otherwise, keep lookup — the point is
  the decision becomes measurable.
- `fetch_word_type` stops mutating; `german_lemmatization` inside the token loop
  ([app/rule_processors.py:225](../app/rule_processors.py#L225)) becomes part of
  the same component or an explicit, documented step.

### Phase 2 — word type as a pure mapping, fixes as data

`_fetch_word_type` conflates three roles; separate them:

1. **Mapping**: UPOS (+ `morph` where UPOS is too coarse) → `WordType`, as one
   pure table-driven function. The `attribute_ruler` already normalizes
   STTS/PTB to UPOS, so the mixed tag sets ([app/model.py:66-94](../app/model.py#L66-L94))
   collapse; today `ADV` sits in `adj_tags`, so adverbs become adjectives by
   fall-through.
2. **Known tagger errors**: express as `AttributeRuler` patterns (data, applied
   once in the pipeline) instead of code branches — e.g. the FR `-ez` verb rule,
   the DE lowercase-verb-tagged-as-noun DB check. Each pattern cites a Phase 0
   corpus case, so it can be retired when a model handles it.
3. **Expectation bias**: today the caller's expected type changes the answer
   (PROPN returns the expectation verbatim, [app/model.py:249-250](../app/model.py#L249-L250)),
   which makes the classifier unfalsifiable. Move tolerance to the rule-match
   layer: a rule declares the set of word types it accepts.

Then `word_type` is computed once per token in the pipeline and cached
unconditionally — deleting the cache-only-when-unbiased subtlety and the
`strict`/`single_word` threading.

### Phase 3 — morphology first, word lists as fallback

Invert the priority in `is_token_singular`: `morph` (and the parser's `det`
edge, replacing the manual walk-back) decides; the word lists answer only when
morphology is absent or for failure classes the Phase 0 corpus demonstrates.
The `log_metrics` disagreement counter added in the tweaks merge
([app/model.py:449-463](../app/model.py#L449-L463)) is the right migration
tool: run it over the corpus, adjudicate the disagreements, then flip. Apply
the same policy to German gender (suffix statistics → `morph.get("Gender")`
first), which also unifies the DE/FR split.

This is the phase that directly answers the anti-morph docstrings: model-swap
stability becomes a *measured property per model* instead of a reason to avoid
the model on every model.

### Phase 4 — matching on spaCy's Matcher (larger, optional)

Compile rule patterns (`words` + per-word `lemmatize`/`lower_case` flags, the
`|`-DSL with `*`) into `Matcher` patterns (`LEMMA`/`LOWER`, `OP: "*"`) built
once at startup; keep the SQL `first_token` index for candidate narrowing or
replace it with one shared `PhraseMatcher`. Also: build the EN
false-positive `Matcher` once at startup instead of per request, and move the
FR `à/de + la` contraction special cases
([app/rule_engine/matchers/pattern.py:44-58](../app/rule_engine/matchers/pattern.py#L44-L58))
into tokenizer exceptions. High blast radius — do this only behind the full
snapshot suite, after Phases 1–2 have stabilized token facts.

### Phase 5 — model strategy (contingent on Phase 0 data)

Options, in order of cost:

1. **No training**: custom tokenizer (already keeps `Kund:in` whole) +
   `AttributeRuler` patterns + lemmatizer exceptions for gender-colon forms.
   Likely sufficient for the colon-form class; Phase 0 tells us.
2. **Finetune** the `lg` tagger/morphologizer/lemmatizer on domain sentences.
   Despite its name, `training_data/` contains no POS/lemma-annotated corpus
   and the repo has no `spacy train` config — this is greenfield: corpus from
   snapshot inputs + DB person nouns, annotations bootstrapped from the current
   pipeline and hand-corrected. Only worth it if Phase 0 shows systematic
   errors that data-level fixes can't absorb.
3. **Swap models** (`de_dep_news_trf`, or `_md` to halve memory since vectors
   are unused): evaluate with the A/B recipe. Constraints already documented in
   [technical-notes.md](./technical-notes.md#framework-and-models): trf lacks
   NER, which `is_entity_type_mismatch` and the LanguageTool name suppression
   depend on; and `Model.models` keys by language, so arms must run as separate
   processes.

## Defects found during review

All fixed on `feature/spacy-foundations` with unit tests in
[tests/test_unit.py](../tests/test_unit.py):

- `token.pos == "NOUN"` in `is_token_singular` compared the int hash to a
  string; the EN "ends with s ⇒ plural" fallback was dead code.
- `fetch_phrase_matcher` referenced an undefined `s[lang]` and had no callers;
  removed.
- `ADV` sat in `adj_tags`, so every plain adverb was classified as an
  adjective. Now: adjective-tagged tokens (ADJD/JJ/…) stay adjectives, an
  expected-adjective still matches adverbial position, and plain adverbs
  return `WordType.ADVERB` instead of `ADJECTIVE`.
- `standard_words` in the substring branch of `RuleCheck.handle` was used
  unconditionally but assigned only when `rule.false_positives is not None`
  (`UnboundLocalError` on rules without false positives); extracted to
  `substring_standard_words`.
- `is_gender_false_positive` shadowed its `token` parameter in the scan loop
  and reached the doc via a pointless `.sent.doc`; behavior (whole-doc scan)
  kept, code untangled.
- FR `-f` feminine adjectives produced `-vex` instead of `-ve`
  (`neuf → neuvex`).
- `Rule.dynamic` was a class-level `RuleDynamic()` — `Rule` is a plain class,
  so every rule in the process shared one mutable scratch object across
  requests; now created per instance.

Also checked and *not* a defect: the two `output.json` snapshots without an
`input.json` (`test_auth_2_0*`) are intentional — those tests build their
requests in code.
