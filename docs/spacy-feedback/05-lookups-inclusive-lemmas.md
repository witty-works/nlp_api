# 05 - Gender-inclusive lemma table contribution

**Venue:** explosion/spacy-lookups-data PR (no CLA required).
**Status:** **gated** - do not file before the provenance and coverage
points below are resolved.

## Evidence

No current lemmatizer produces usable lemmas for inclusive forms:

- lookup mode: `Kund:innen` → `Kund:innen` (untouched);
- trained (default de pipeline): `Mitarbeiter*innen` → `Mitarbeiter*inn`,
  `Kund:innen` → `Kund:inn` (suffix-mangled).

## Offer

Our rules database generates every inclusive spelling with its base form
(`Kund:innen → Kunde`, `Kolleg*in → Kollege`, all separator variants) - a
finished `de_lemma_lookup` extension rather than a request.

## Gate 1: provenance

The declension data behind the pairs was filled per-noun from
verbformen.de - scraping otherwise disallowed; permission was granted to
Witty Works by Netzverb, info@netzverb.de
(https://www.netzverb.com/impressum.htm) - with a Wiktionary (CC BY-SA)
fallback, and rows do not record which source filled them. A public PR is
MIT-licensed redistribution: a larger grant than our permission, and EU
database sui-generis rights apply. Before filing:

- obtain publishable permission from Netzverb, quoted in the PR / NOTICE;
- add a `declension_source` field in the rule editor so future rows are
  row-level traceable (Wiktionary-fallback rows must be excludable);
- or regenerate from clean sources (see below).

## Gate 2: coverage

We only downloaded declensions for nouns that have rules (~3k person
nouns). A general-purpose upstream table wants broader coverage - which
means either more downloads under a broader permission, or the cleaner
route:

**Self-generation.** Our inclusive-form derivation code is authored
in-house; run over any freely licensed German person-noun list, it emits
`(inclusive surface, base lemma)` pairs with clean provenance *and*
arbitrary coverage. This sidesteps both gates and is the recommended path
if Netzverb's public grant is slow or narrow.

## Relation to training (INCLUSIFY)

Long-term the better fix is upstream training exposure, not lookup tables
(see ticket 02). For our own use, note: the same self-generation trick
produces *annotated training text* for free - apply the derivation to
already-annotated corpora and the labels carry over. This is exactly how
INCLURE built its 69K-pair French corpus (rule-based transformation with
labels carried; Lerner & Grouin, BUCC 2024) - independent validation of
the approach. INCLUSIFY ([arXiv:2212.02564](https://arxiv.org/abs/2212.02564), German) and INCLURE (French)
then serve best as independent evaluation sets - check artifact licenses
before any training or commercial use (INCLURE's proceedings are
CC BY-NC 4.0).
