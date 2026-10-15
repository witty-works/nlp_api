# 01 - German tokenizer splits gender-colon words

**Venue:** explosion/spaCy issue, "Submit a Bug Report" template
("unexpected behaviour differing from the docs" covers deterministic
tokenizer rules - this is not a model-prediction report, so the #3052
master thread does not apply). Patch PR to follow.
**Status:** ready to file. No existing issue found (searched 2026-08-08).

**Title:** German tokenizer splits gender-inclusive colon forms (Kund:innen)

---

## How to reproduce the behaviour

The German infix rules split a colon between letters, which breaks
gender-inclusive forms, standard orthography in contemporary German
business and public-sector text, before tagging or NER ever see the word:

```python
import spacy

nlp = spacy.load("de_core_news_lg")  # tokenizer behavior; any de pipeline
print([t.text for t in nlp("Unsere Kund:innen und Mitarbeiter:innen sind zufrieden.")])
# ['Unsere', 'Kund', ':', 'innen', 'und', 'Mitarbeiter', ':', 'innen', 'sind', 'zufrieden', '.']
print([t.text for t in nlp("Wir suchen eine:n Ärzt:in für unser Team.")])
# ['Wir', 'suchen', 'eine', ':', 'n', 'Ärzt', ':', 'in', 'für', 'unser', 'Team', '.']
```

Expected: `Kund:innen`, `Mitarbeiter:innen`, `eine:n`, `Ärzt:in` as single
tokens. For comparison, the star and interpunct variants already stay
whole (`Kolleg*innen`, `Expert·innen`), only the colon splits, via this
infix in `spacy/lang/de/punctuation.py`:

```python
r"(?<=[{a}])[:<>=](?=[{a}])".format(a=ALPHA)
```

The gender colon is the most common separator in German inclusive writing
(the INCLUSIFY benchmark, [arXiv:2212.02564](https://arxiv.org/abs/2212.02564), documents frequency across sources). Every downstream component degrades on the split: the noun is tagged in pieces, NER never sees the name-like whole, and lemmas are
computed for the fragments. We created an [inclusive language text checker](https://github.com/witty-works/nlp_api) and patch this infix; we'd like to upstream the behavior.

Two possible fixes, happy to submit a PR for either:

1. Conservative: exempt the noun gender endings from the colon infix -
   `r"(?<=[{a}]):(?!in(nen)?\b)(?=[{a}])"` - which keeps `Kund:in` and
   `Kund:innen` whole. Article forms (`eine:n`, `jede:r`) would still
   split; covering them too means exempting short lowercase tails, e.g.
   `r"(?<=[{a}]):(?![a-zäöüß]{1,5}\b)(?=[{a}])"`, at the cost of no longer
   splitting all-lowercase typos like `wort:wort`.
2. A tokenizer config option, if changing the default is unwanted.

## Your Environment

* Operating System: macOS-26.6.1-arm64-arm-64bit
* Python Version Used: 3.12.9
* spaCy Version Used: 3.8.14
* Environment Information: de_core_news_lg 3.8.0 (behavior identical on
  3.7.x; long-standing default, not a regression)

## Notes

- The original solution was developed without AI assistance; however, this ticket was written with the help of Claude. I was unable to find an AI policy for this project.
- Our [production patch](https://github.com/witty-works/nlp_api/blob/dev/app/model.py#L350) keeps `<>=` splitting and drops only the colon.
- I have another ticket in the pipeline related to ADJA mistagging of colon forms, which is only observable once they survive tokenization.

---

## Our notes (not part of the issue)

- Our production patch keeps `<>=` splitting and drops only the colon: see
  `tune_tokenizer` in `app/model.py`.
- Ticket 02 depends on this one: the ADJA mistagging of colon forms is
  only observable once they survive tokenization.
- If maintainers prefer option 2 (config), our `tune_tokenizer` stays; if
  option 1 lands, it can be retired for German colons.
- Ticket URL: https://github.com/explosion/spaCy/issues/14010
