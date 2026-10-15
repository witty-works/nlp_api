# 03 - de NER misses surnames after salutations (comment for spaCy#3052)

**Venue:** comment on https://github.com/explosion/spaCy/issues/3052.
**Status:** posted 2026-08-10:
https://github.com/explosion/spaCy/issues/3052#issuecomment-5236431157

---

## Comment

de_core_news_lg NER regression 3.7.0 → 3.8.0 on the correspondence
register:

```python
[(e.text, e.label_) for e in nlp("Hallo Herr Müller, wie geht es Ihnen?").ents]
# 3.7.0: [('Müller', 'PER')]    3.8.0: []   (tagger still says PROPN/NE)
```

Likely a register gap - WikiNER (encyclopedic text) barely contains
salutations, so name-after-salutation recognition is unstable across
retrains. Salutations are a closed class; an entity_ruler ahead of ner
composes cleanly as a workaround and could ship in the pipeline:

```python
ruler = nlp.add_pipe("entity_ruler", before="ner")
ruler.add_patterns([{"label": "PER", "pattern": [
    {"LOWER": {"IN": ["herr", "herrn", "frau", "dr", "dr."]}},
    {"POS": "PROPN"}]}])
```

The original finding was developed without AI assistance; this comment
was written with the help of Claude.

---

## Our notes (not part of the comment)

- Append the AI-disclosure line per our filing convention when posting.
- This is our production fix (full salutation list in `Model.load_nlp_model`);
  it restored entity-based suppression that broke on the 3.8 upgrade
  (case: tests/test_general_cases/test_api_entity_de).
