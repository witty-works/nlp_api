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

  **Measured 2026-08-07** (`LEMMATIZER=trained`, see the setting added on
  `feature/spacy-foundations`): not a drop-in. Corpus verdict on the ~50
  changed lemmas: the trained lemmatizer wins on citation forms
  (`Eine → ein`, `neue → neu`, `erste → erster Dat`, `zum → zu`), loses on
  inclusive spellings (`Kund:innen → Kund:inn`, `Mitarbeiter*innen →
  Mitarbeiter*inne` — and the DB lemma repair keyed on the lemma no longer
  fires once it is mangled), loses on substantivized participles
  (`Studierende → studierend`), and swaps the pronoun convention the lookup
  tables use (`ich/mein` for all persons) for UD style (`wir/unser`). End to
  end it fails 4 of 181 rule-level cases (internal email demo, two
  gender-ending cases, one grammatical-alternatives case): the lemma
  *conventions* are load-bearing for rule keys. Conclusion: `lookup` stays
  the default; the trained lemmatizer is only worth revisiting together with
  a guard for gender-symbol tokens plus a convention-normalization pass, and
  this instrument makes that a reviewable diff when someone tries.
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

## Word-type branch metrics (2026-08-08, spaCy 3.8.14 / 3.8.0 models)

`_fetch_word_type` is now branch-traced, and `bin/word_type_metrics.py`
sweeps it over the test-corpus texts plus UD dev treebanks (de GSD, en EWT,
fr GSD; 4,276 sentences) in four strata: clean, partial (typing prefix),
typo (keyboard slips), grammar (dropped articles, lost capitalization,
swaps). Per branch it reports fire rate, divergence from a plain UPOS
table, and - where UD gold aligns - the model's own UPOS error rate at
those tokens. Verdicts:

**Earning their keep (compensating measured model error):**
- `adjective-tags` (de): fires on 3% of German tokens; where it fires the
  model's UPOS is wrong 44% of the time (gold ADJ read as ADV, the ADJD
  predicative class: "Es ist unbeschreiblich"). The single most load-bearing
  heuristic. On en/fr it never diverges from the plain table - live only in
  German.
- `propn-as-expected`: the en model still over-reads PROPN (23% of its
  PROPN calls disagree with UD gold) - the wildcard absorbs that.

**Product semantics, ready for the Phase 2 table (zero divergence or
intentional mapping):** `noun`, `verb`, `adverb`, `conjunction`, `emoji`,
`cardinal`/`number` (finer classes than UPOS by design), `pronoun` (the
DET-tag set PDAT/PPOSAT/... -> pron is an intentional mapping, 27% of its
German fires), `de-dash-noun` (compound ellipsis "Kunden- und ..."),
`invalid-text` (rejects stray single letters the table would call nouns).

**Narrowed on this evidence:**
- `de-lowercase-noun-is-verb`: fired once per ~800 clean German sentences,
  and the suite proved exactly one dependent ("Wir wollen das abzocken",
  the gender-verbs case). But on lowercase nouns - injected
  decapitalization and genuine informal German in UD ("Anlaß zur sorge") -
  it flipped nouns to verbs. Now guarded: the flip is skipped when the
  noun tables know the capitalized form. The guard is deliberately scoped
  to the rules DB, not the full german_nouns lexicon: substantivized
  infinitives ("Abzocken") are lexicalized there too, which would kill the
  legitimate flip. Residual miss, accepted: lowercase non-rule nouns like
  "auf kosten des..." still flip.
- `hyphen-split-first/-last` (en): in auto-detect mode the split misreads
  adjectival compounds ("self-driven" -> noun via "self"); the whole-token
  tag is right more often. The split is what lets "one-eyed"-class rules
  match, so it stays for expectation-driven calls.

**Strata findings:** branch distribution and model error rates stay stable
under partial and typo input (no catastrophic degradation for the
browser-extension case); the grammar stratum mildly raises pronoun/verb
confusions and is where the lowercase-noun misfires concentrated.

**Limitation:** the sweep runs the auto-detect path. Expectation-dependent
branches (`article-list`, `adverb-expected`, `hyphen-adjective`,
`de-verb-as-expected-adjective`, `pronoun-as-expected-noun`,
`fr-noun-expected`, `fr-ez-verb`) only fire during rule matching and are
covered by the e2e suite and their citation cases, not by these numbers.

## The right layer for our own tweaks (implemented 2026-08-08)

Which workarounds belong in spaCy's own extension points rather than app
code - the first four are done:

| Tweak | Layer it lives on now |
|---|---|
| Tokenizer infix/suffix patches | `tune_tokenizer` mutates the shipped tokenizer in place; the German colon default is proposed upstream (docs/spacy-upstream-feedback.md item 1) |
| Gender-symbol POS fix | `attribute_ruler` pattern - already spaCy's layer; upstreamable into the shipped model |
| Product lemma pins (`lookup.json`) | Merged into the lemmatizer's own `lemma_lookup` table for de/fr; the override pipe remains only for en (rule-mode lemmatizer has no surface table) and the trained toggle |
| Salutation surnames | `entity_ruler` before `ner` emits real PER spans, so entity suppression and the LanguageTool name check run on `ents` again instead of a side-channel heuristic |
| `_fetch_word_type` tag sets | App semantics; become data tables in Phase 2 |
| Word-type/number/article layers, DB lemma pins | App-side by design: product conventions the models must not own |

## Relation to the spaCy 3.8 update (upstream PR #1173)

The upstream 3.8 update stalled on "need to review all the test snapshot
changes": a retrained model shifts many end-to-end snapshots, and with only
rule-level output there is no way to separate benign re-taggings from real
regressions, so the review never converged. This plan attacks that directly:

- Phase 0 turns a model bump into a reviewable token-level diff — run the
  analysis corpus under the new models (`--snapshot-update` in a scratch
  worktree, `git diff`) and each changed end-to-end case can be traced to the
  tag/morph/lemma change that caused it.
- Phases 1–3 shrink the model-sensitive surface. The POS cascade is
  "optimized for spaCy large models" 3.7; a table-driven UPOS mapping and
  data-level exception patterns (each citing a corpus case) can be re-verified
  per model version and retired when a new model no longer needs them.
- The lemmatizer setting isolates one axis: lemma changes can be measured
  independently of tagger changes when models move.

### Language detection dependency (the numpy 2 blocker)

The fasttext/numpy2 conflict is packaging, not spaCy usage, but it gates the
upgrade, so the decision is recorded here. Meta archived fastText in March
2024, so every binding is community-maintained; the question is which fork,
or which replacement. Decision: **`fasttext-predict`** (SearXNG-maintained,
inference-only, no numpy dependency at all, same `fasttext` module name) with
the unchanged `lid.176.bin` — predictions stay identical, so the
language-detection snapshots verify the swap. Preferred over
`fasttext-numpy2` (individual-maintainer rebuild of the full library whose
purpose lapses once numpy 2 is adopted).

**Lingua was evaluated and rejected, twice.** The 2024 attempt
(pemistahl/lingua-py#242) hit short-text misclassifications; a re-check of
releases since (only 2.2.0, March 2025 — FST memory work, no short-text
quality changes, nothing released in the ~17 months to August 2026) shows no
movement on that failure mode. Low-accuracy mode is not an alternative: its
documented weakness is short text, which is this API's dominant input. And
restricting lingua to {en, de, fr} to lift accuracy would break
unsupported-language rejection — `get_locale` returns None when the detected
language is unsupported, which requires a detector that can confidently name
languages we do not process (lid.176 covers 176). If detector memory ever
matters, the lever is fastText's compressed `lid.176.ftz` (<1MB), not a
detector swap.

### The 3.8 upgrade, measured (2026-08-07, `feature/spacy-3.8`)

spacy 3.8.2 + the 3.8.0 model wheels + numpy 2 + `fasttext-predict`, in one
lock. fasttext-predict proved a drop-in (identical predictions on
`lid.176.bin`; language-detection snapshots unchanged). Raw model churn: 8 of
18 analysis-corpus cases, 17 end-to-end cases. Every change was traced to a
mechanism before deciding; the full evidence is in the branch history, the
summary:

**Model improvements taken as-is:** correct French parse structure the 3.7
model got wrong, `man-made`-style EN compounds tagged ADJ instead of PROPN,
German case corrections and coordination attachment, better French feminine
morphology (`curieuses` now carries `Gender=Fem`, which lets the
gendered-pair suppression fire across sentences).

**Regressions compensated in the analysis layer** (each with a unit test and
a corpus/e2e case citation, each retirable when a future model passes
without it):
- gender-symbol forms (`Kund:innen`) tagged ADJA → `attribute_ruler` pattern
  forces NOUN/NN;
- `pos=NOUN` with `tag=ADJD` conflicts (`Ehrgeiz`) → UPOS wins over the
  mixed-tagset adjective check;
- EN hyphen compounds (`state-of-the-art`): the whole-token adjective tag now
  answers an adjective expectation before the split (3.7 hid this behind
  PROPN-matches-anything);
- de NER no longer labels bare surnames (`Herr Müller`) → a PROPN attached
  to a salutation counts as name evidence for NON_PERSON/NON_NAME rules. A
  bare PROPN is not enough: standalone compounds (`Bäcker-Confiseur-Konditor`)
  are PROPN too.

**Accepted as model behavior:** number readings on ambiguous weak-noun
forms moved in both directions ("berät den Kunden" now reads dative plural —
wrong; other cases improved). Context-dependent, not pattern-fixable; the
`log_metrics` counter tracks the disagreement rate. LT typo findings shifted
with NER labels in both directions (`Abdichterinnen` surfaced,
`Einflußvermögen` suppressed) — if surfaced typos become noise, the
`languagetool/` ignore list is the lever.

**Rules-DB items, out of this repo's scope** — the 3.8 EN tagger reads these
in positions the rules' declared word types don't cover, so the findings are
lost until the rule data is relaxed (word type or lemma key): `ninja`
(ADJ as modifier), `ass` (predicative ADJ), `so` (CCONJ), `coloured people`
(VBN, lemma `colour` ≠ key `colored`), `intern` in signature-mangled text.

**Memory zones (implemented):** `Model.nlp_session(lang)` wraps the spaCy
span of each request in `Language.memory_zone()`, bounding per-worker
Vocab/StringStore growth so `--preload`'s copy-on-write sharing holds up
over a worker's lifetime. Zones are process-global on the vocab, and
requests interleave at await points inside one worker, so the session also
holds a per-language `asyncio.Lock`; that costs little because spaCy work
is GIL-serialized anyway and the slow awaits stay outside: LanguageTool's
name suppression and the context checker now receive plain-data views
(`ent_spans`, `(end_char, text)` sentence pairs) extracted before the zone
exits — a Doc must never outlive its zone. Kill switch: `MEMORY_ZONES=false`.
Debug endpoints run zoneless; they are not the volume path.

### Measuring without a deployment

The Phase 3/5 decisions were framed around production `log_metrics`
counters; without a deployment the same numbers come from corpora run
locally:

- **Gold morphology from UD treebanks.** UD_German-HDT (and GSD, plus the
  French/English UD sets) carry gold `Number`/`Case`/`POS` per token. Filter
  their sentences to tokens whose surface form is in
  `ambiguous_number_lookup` and score the loaded model against gold: that
  is the morph-vs-wordlist trust measurement per model, no traffic needed.
- **Counter sweeps over any text corpus.** A `bin/` runner feeding job-ad or
  business text through the pipeline with `LOG_METRICS=true` aggregates the
  same disagreement counters a deployment would emit.
- **Gold assertions in the analysis corpus.** The
  `tests/test_spacy_analysis` cases can carry expected `word_type`/`Number`
  for the tokens rules care about; snapshots say what changed, gold says
  what is right.

All of it stratified by input condition, because production is not clean
prose and the trust question may answer differently per stratum:

- **fully written text** - UD treebanks, job ads;
- **partially written text** (the browser extension checks while typing) -
  derived deterministically from the clean corpus: prefix cuts at token
  boundaries plus a mid-word cut for the final token; gold comes from the
  full sentence, restricted to the tokens that are complete in the prefix;
- **typos** - synthetic corruption of the clean corpus (QWERTZ
  adjacent-key substitution, transposition, deletion, doubling, ss/ß
  swaps); gold stays that of the clean source, measuring robustness per
  corruption type;
- **word creations** - German compounding is productive and head-inheriting,
  so novel compounds generated from the noun tables carry their own gold
  (gender/number/inflection follow the head noun); plus real coinages from
  job-ad vocabulary (Feelgood-Manager class).

Representative cases of each stratum live in `tests/test_spacy_analysis`
so CI sees degraded-input regressions; the bulk sweeps live in `bin/`.

**Principle for partial text: when in doubt, do not highlight.** False
positives cost more than false negatives while the user is still typing -
the finding may resolve itself with the next keystroke. Implications:

- **Scoring is asymmetric per stratum.** On the partial-text stratum a
  false positive counts against a change; a false negative is acceptable.
  Gold for partial cases should mainly assert "must not fire".
- **Proposed mechanism, not yet built**: a `partial` flag on the check
  request (the browser extension knows it is mid-keystroke; the API cannot
  reliably infer it). When set: suppress findings that touch the final
  token unless the text ends in a terminator, and let number/word-type
  checks that cannot be decided from the fragment fail closed (skip the
  rule) instead of guessing. Default off, so existing clients and
  snapshots are untouched.
- The same fail-closed bias applies wherever the analysis is low-context
  (the signature-mangled email class), independent of the flag.

### Rule-editor tooling for the rule-data issues

- **Per-model word-type lint**: run every rule's words through the loaded
  pipeline and report rules whose declared word type can no longer match
  (the ninja/ass/so class) and lemma keys the lemmatizer no longer produces
  (the coloured/colour class) - dead rules become a report instead of a
  silent product regression.
- **Category policy validation**: rules in categories where the term is
  problematic in any position (offensive language, slurs, exaggeration,
  fillers) should declare no word type; the editor can enforce that.
- **Example sentences as rule metadata**: a positive example per rule turns
  the whole rules DB into a generated contract-test corpus - after any
  model change, "does each rule still fire on its own example" replaces
  hand-adjudicating snapshot churn.

### LanguageTool typo noise without a custom ignore list

A managed/official LT deployment cannot take the `languagetool/` ignore
list, so suppression must live on our side of the API boundary:

- **Post-filter TYPOS matches morphologically**: before reporting an LT
  typo on a capitalized token, strip the feminine/gendered endings
  (`-in`, `-innen`, and the configured gender-symbol forms) and look the
  stem up in the noun tables (plus the compound splitter for
  `Abdichterinnen`-style derivations). Deterministic, model- and
  deployment-independent - unlike the current NER-overlap suppression,
  which moves with every model.
- **LT Premium personal dictionary** (`/words` API, the credentials
  settings already exist): syncable from the noun tables' generated forms
  if the hosted premium tier is used; a size-limited complement, not the
  primary mechanism.

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
