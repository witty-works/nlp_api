# 02 - Gender-inclusive forms mistagged (two comments for spaCy#3052)

**Venue:** two separate comments on
https://github.com/explosion/spaCy/issues/3052 (the pinned
model-predictions master thread) - thread style is short: versions,
snippet, expected/got.
**Status:** both posted 2026-08-10, see
https://github.com/explosion/spaCy/issues/3052#issuecomment-5236418061 and
https://github.com/explosion/spaCy/issues/3052#issuecomment-5236418960
(mapping A/B to URLs to be confirmed).

---

## Comment A: German gender-colon nouns (references #14010)

de_core_news_lg regression 3.7.0 to 3.8.0 on gender-inclusive colon forms
(kept whole via custom infixes, see #14010):

```python
# spaCy 3.8.14; colon forms kept whole per #14010
[(t.text, t.pos_, t.tag_) for t in nlp("Die Kund:innen sind zufrieden.")]
# 3.8.0: ('Kund:innen', 'ADJ', 'ADJA')
# 3.7.0: ('Kund:innen', 'NOUN', 'NN')
```

The star/interpunct variants, whole tokens in the *default* tokenizer,
stay NOUN/NN in the same 3.8.0 model (`Kolleg*innen`, `Expert·innen`), so
the model handles symbol-infixed nouns it has seen; colon forms don't
occur in TIGER-era training data and their reading flipped between
retrains. Until training data covers them, a shipped attribute_ruler
pattern pins the class (our production fix):

```python
ruler.add(patterns=[[{"TEXT": {"REGEX": r"^\w+[:*·](in|innen)$"}}]],
          attrs={"POS": "NOUN", "TAG": "NN"})
```

The original finding and solution were developed without AI assistance;
this comment was written with the help of Claude.

## Comment B: French point médian

fr_core_news_lg 3.8.0: écriture inclusive survives tokenization, but the
readings scatter:

```python
[(t.text, t.pos_) for t in nlp("Nous cherchons un·e développeur·se expérimenté·e.")]
# développeur·se → ADV    expérimenté·e → PRON    un·e → ADJ
# lemma: étudiant·e·s → 'étudiant·e·'
```

Documented in the literature:
[Grouin 2022](https://aclanthology.org/2022.jeptalnrecital-taln.12/)
measured POS error rates 3-7 points higher on Inclusive vs Standard
French (spaCy and TreeTagger), and
[INCLURE](https://aclanthology.org/2024.bucc-1.7/) (BUCC 2024) provides
69K aligned Standard↔Inclusive pairs if training exposure is an option.
Unlike the German colon case, a ruler override can't fix this: inclusive
marking hits determiners and adjectives too.

The original finding was developed without AI assistance; this comment
was written with the help of Claude.

---

## Our notes (not part of the comments)

- Disclosure lines follow the convention from #14010 ("I was unable to
  find an AI policy for this project" can be re-added if wanted).
- Pinned locally:
  [de_gender_colon](https://github.com/witty-works/nlp_api/tree/dev/tests/test_spacy_analysis/de_gender_colon),
  [fr_point_median](https://github.com/witty-works/nlp_api/tree/dev/tests/test_spacy_analysis/fr_point_median).
- The German attribute_ruler pattern is retirable when a future model
  passes the corpus case without it. No French mitigation on our side -
  a shape-blind override would mistag adjectives and determiners.
- Deeper background kept out of the comments: INCLUSIFY
  ([arXiv:2212.02564](https://arxiv.org/abs/2212.02564)) is German-only;
  INCLURE's proceedings are CC BY-NC 4.0 (license check before training
  use); the interpunct is even absent from BARThez's vocabulary; Grouin's
  hand-made IFC corpus at
  https://github.com/grouin/corpus-francais-inclusif is a good
  sanity-check set.
