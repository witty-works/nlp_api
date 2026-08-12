# External benchmarks: diversifix (de) and INCLURE (fr)

First measured 2026-08-12 against dev (spaCy 3.8.14, 3.8.0 models, LanguageTool disabled - the gold covers inclusive language, not spelling). Harness: `bin/external_eval.py`; datasets live in `.cache/external-eval/` (gitignored - the geschicktgendern subset of diversifix is CC BY-NC-SA and must not enter the repo; INCLURE is MIT/CC0, Grouin's IFC is BSD-2).

Run:

    TESTING=True MANAGEMENT_AUTH_ENABLED=False LANGUAGETOOL_API="" \
        pdm run python -m bin.external_eval --pairs .cache/external-eval/french/oscar_inclure_test.csv --lang fr --limit 800
    TESTING=True MANAGEMENT_AUTH_ENABLED=False LANGUAGETOOL_API="" \
        pdm run python -m bin.external_eval --dict .cache/external-eval/german/unified.csv --lang de --limit 500

## French - INCLURE test split, 800 pairs (BUCC 2024)

| measure | result |
|---|---|
| in-scope targets (role nouns) detected | **75/108 (69%)** |
| gold rewrite re-flagged on inclusive side (true FP) | **9/800 (1.1%)** |
| suggestions where target detected: exact / same-lemma / neither | 39 / 8 / 30 of 77 |
| any finding on the exclusive side | 53% |
| residual masculines we flag on their "inclusive" side | 29% |

Readings:

- **Scope, quantified:** 86% of INCLURE's annotated rewrites target pronouns, participles and adjectives (`ceux -> celles et ceux`, `accusés -> accusé.e.s`) - deliberately outside this product's role-noun task. On the shared task (role nouns) recall is 69%.
- **The médian tagging chaos does not leak into behavior:** despite the fr model reading `développeur·se` as ADV etc., only 1.1% of their gold rewrites get re-flagged. The residual 29% are *their* corpus's leftover generic masculines (minimal pairs fix one span), which we correctly find - a point in our favor, not a false-positive rate.
- Suggestion "neither" cases are mostly philosophy (their flexion of the same word vs our neutralization) plus an article-prefix artifact (`les agent·es` vs `agent·es`), so 51% exact is a floor.

## German - diversifix unified.csv, 500 sampled terms

| measure | result |
|---|---|
| terms in our noun tables, detected | **36/48 (75%)**, misses ~= `Behinderter` |
| all terms detected | 176/500 (35%) |
| their *neutral* rewrites flagged (should-not-flag) | **0/167** |
| suggestion overlap with their alternatives | 8/176 |

Readings:

- diversifix's vocabulary is much broader than person nouns (`Abbrecherquote`-style derived compounds and rare professions from dereko/geschicktgendern); 90% of sampled terms are outside our noun tables, yet 140 of those still get detected through lemma rules.
- The perfect 0/167 on neutral rewrites is the German counterpart of the 1.1% French figure: already-inclusive language stays quiet.
- Low suggestion overlap is expected: their type-0 alternatives are bare feminine forms; ours are pair forms or curated neutralizations.
- **Rule-editor mining material:** the 324 undetected terms are coverage candidates. License care: dereko and diversifix rows are CC0 and can be imported; geschicktgendern rows (CC BY-NC-SA) can guide what to cover but their alternative texts must not be copied into the rules DB.

## Relation to their published numbers

diversifix's P=0.82/R=0.89 were computed on an annotated GC4 sample that is not published, so no direct comparison is possible; the dictionary recall above measures something adjacent (vocabulary coverage), not the same statistic. INCLURE publishes corpus statistics, not checker metrics.

## What the results mean for the approach

The core trade - precision over coverage - is validated. The should-not-flag results (0/167 neutral German rewrites, 1.1% French true false positives) are the numbers that decide whether a tool that interrupts writers is tolerable, and they held even where the underlying French model misreads médian forms token by token: the deterministic layers deliver the precision regardless of the statistical substrate. On the shared task the detection and suggestion numbers are in the same league as the published academic system, while the suggestions themselves are declined, convention-aware product alternatives rather than dictionary rows.

The binding constraint is coverage economics, not correctness: 35% overall detection on diversifix's broad vocabulary and the 324-term gap list quantify the tail. Coverage grows linearly with editorial hours through the rule editor's evaluation/import loop, which now has license-clean input (the CC0 subsets). The measured boundary of the algorithm is context-dependent rewriting - INCLURE's pronoun/participle/agreement class (86% of their gold) and pair formulas - which rule-per-lemma cannot reach; if that class becomes commercially relevant, the paths are seq2seq fine-tuning on INCLURE's MIT/CC0 pairs or the product's existing LLM-alternatives channel, as an additive layer whose output the deterministic core can check before display.

## Beyond detection: operational comparison

Dimensions that decide shippability, against the realistic alternatives (diversifix's dictionary+heuristics system, an INCLURE-style fine-tuned seq2seq, LLM-based checking):

| dimension | this product | dict+heuristics (diversifix) | fine-tuned seq2seq | LLM API |
|---|---|---|---|---|
| inference | CPU-only, ~1.5GB shared via `--preload`, memory-zone-bounded; tens of ms core latency, ~2 checks/s/worker measured incl. harness overhead | comparable (architectural sibling) | GPU serving or ~10x CPU latency per generated sentence | 1-5s round trips, per-token cost |
| output conventions | runtime request parameter: 9 German endings incl. Inklusivum, fr separators, org term replacements - no redeploy | single convention set | baked into weights; N conventions ~= N models | promptable, but slow/costly/inconsistent |
| maintenance unit | a rule: data edit + versioned evaluation + DB sync, minutes, non-engineers | same class | retraining cycle: data, GPU, eval infra, regression risk | prompt tuning + vendor drift |
| testability | 600+ deterministic snapshot/analysis tests; every change is an adjudicable diff | similar in principle | statistical eval only | statistical, vendor-dependent |
| failure mode | silent miss | silent miss | wrong text generated into the user's document (inherits the measured lemma/tagging instabilities) | hallucinated rewrites |
| explainability | rule id, category, explanation, literature source per finding | partial | none | none |
| privacy / hosting | self-hostable, text stays in deployment | self-hostable | self-hostable, GPU cost | text transits third party |

Where the model approaches genuinely win: generalization without editorial effort (the coverage tail), the context-dependent rewrite classes above, robustness to creative misspellings. Those strengths slot into the hybrid architecture as additive layers; on cost, configurability, maintenance, failure safety and auditability - the dimensions a competitor cannot close by fine-tuning - the deterministic core is the moat.

## Follow-ups

- Feed the 324-term gap list through the rule editor's sentence/import loop (CC0 subsets importable as alternatives, NC subset as inspiration).
- The pronoun/participle rewrite class INCLURE covers is the measured French roadmap gap, now with 692 gold examples to design against.
- Fold leading articles in the harness normalizer to un-floor the exact suggestion rate.
