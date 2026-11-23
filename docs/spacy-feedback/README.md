# Feedback to spaCy upstream

One file per ticket, each self-contained per spaCy's CONTRIBUTING.md.
Model-prediction reports go to the pinned master thread
explosion/spaCy#3052 ("Inaccurate pre-trained model predictions"), not
fresh issues - spacy-models takes no issues either. Evidence behind every claim is reproducible in this repo: the
analysis corpus (`tests/test_spacy_analysis/`), the adjudicated 3.7→3.8
model diff (`docs/spacy-review.md`), and the branch metrics over UD dev
treebanks (`bin/word_type_metrics.py`).

| # | Ticket | Venue | Status |
|---|---|---|---|
| 1 | [German tokenizer splits gender-colon words](01-de-tokenizer-gender-colon.md) | explosion/spaCy issue + PR | **filed: [#14010](https://github.com/explosion/spaCy/issues/14010)** |
| 2 | [de tagger reads whole gender-colon nouns as ADJA](02-de-tagger-gender-colon-adjective.md) | spaCy #3052 comments | **posted 2026-08-10** |
| 3 | [de NER misses surnames after salutations](03-de-ner-salutations.md) | spaCy #3052 comment | **posted 2026-08-10** |
| 4 | [ADJD vs UPOS convention mismatch](04-adjd-upos-convention.md) | explosion/spaCy discussion | draft |
| 5 | [Gender-inclusive lemma table contribution](05-lookups-inclusive-lemmas.md) | spacy-lookups-data PR | gated (provenance + coverage) |
| 6 | [memory_zone docs: async caveat](06-memory-zone-docs.md) | docs PR | draft |
| 7 | [requires-python ceiling vs lockers](07-packaging.md) | discussion | note |

Filing rules distilled from CONTRIBUTING.md:

- Self-contained repro snippets - never references to this repo.
- Environment block from `python -m spacy info --markdown`; both model
  versions for 3.7-vs-3.8 regressions.
- Model reports framed as *systematic classes with version instability*,
  not one-off mispredictions (their README explicitly expects statistical
  errors).
- Issue first, then PR against `master`; tests under `spacy/tests/lang/de/`
  marked `@pytest.mark.issue(N)`; `black` + `flake8`. No CLA.

Posted so far: issue [#14010](https://github.com/explosion/spaCy/issues/14010)
(ticket 01), and on #3052:
[comment-5236418061](https://github.com/explosion/spaCy/issues/3052#issuecomment-5236418061),
[comment-5236418960](https://github.com/explosion/spaCy/issues/3052#issuecomment-5236418960)
(ticket 02 A/B), and
[comment-5236431157](https://github.com/explosion/spaCy/issues/3052#issuecomment-5236431157)
(ticket 03).

Caveats we state in every filing: UD dev sets plausibly overlap the models'
training data (biasing toward flattering the models), and our percentages
are precision-at-fire on aligned tokens, not global accuracy.
