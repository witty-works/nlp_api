# 04 - ADJD's UPOS is inconsistent with UD conventions and with the tagger

**Venue:** explosion/spaCy discussion (convention question, not a bug).
**Status:** draft.

## Evidence

Where de_core_news_lg 3.8.0 emits `tag=ADJD`, its UPOS says ADV while
UD-GSD gold says ADJ in ~44% of our aligned fires ("Es ist
unbeschreiblich" - gold ADJ, model ADV; measured over the UD German GSD
dev set, `bin/word_type_metrics.py` in our repo). The two heads can also
contradict each other within one token: `Ehrgeiz` as `pos=NOUN, tag=ADJD`.

Related, smaller: en_core_web_lg 3.8.0's PROPN precision measured ~77% on
our EWT-dev alignment - systematic over-PROPN'ing of unknown capitalized
tokens and compounds.

## Root cause

UPOS comes from the morphologizer, the STTS tag from the tagger - two
independently trained heads over a TIGER-derived conversion whose ADJD
mapping differs from UD's predicative-adjective convention. Nothing
reconciles them.

## Ask

Document which UPOS convention the German models follow for ADJD
(consumers reading `pos_` reasonably expect UD semantics), and consider an
attribute_ruler reconciliation for contradictory pos/tag combinations.

## Caveats to state

GSD dev plausibly overlaps training data; percentages are
precision-at-fire on aligned tokens, not global accuracy.
