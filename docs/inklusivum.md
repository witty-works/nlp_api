# Inklusivum (de-e)

Implementation notes and remaining work for the German
[Inklusivum](https://geschlechtsneutral.net/inklusivum/), selected with
`"german_gender_ending": "de-e"`.

## Table of Contents

- [Why it does not fit the other gender endings](#why-it-does-not-fit-the-other-gender-endings)
- [Where the code lives](#where-the-code-lives)
- [What is implemented](#what-is-implemented)
- [Remaining work](#remaining-work)
- [Forms the sources do not settle](#forms-the-sources-do-not-settle)

---

## Why it does not fit the other gender endings

The other eight values of `german_gender_ending` are typographic separators. The
configured value *is* the answer: find the split point in `Lehrerin`, insert the
character, done. The whole pipeline is built around that, which is why
`Config.get_gender_separators` returns a separator string and why
`inclusive_alternative()` takes a male form, a female form and a separator.

The Inklusivum is not a separator. It is a fourth grammatical gender with its own
articles, adjective endings, pronouns and noun declension. Its forms are derived
from the masculine stem and then declined; they are never assembled from a male
and a female surface form. Two consequences shape the code:

- Grammatical case matters. `Schülere` takes `-s` in the genitive singular and
  the plural takes `-n` in the dative, so the number and case have to reach the
  point where the word is built. That is what `target_form` (`sg_gen`, `pl_dat`,
  …) carries.
- Detection cannot work on shape. An Inklusivum noun looks like any other German
  noun ending in `-e`, so `Liebe`, `Sprache` and `Woche` are indistinguishable
  from it by pattern. Recognising it needs a lexicon lookup.

## Where the code lives

| Concern | Location |
| --- | --- |
| Noun and adjective forms, detection primitives | [app/alternatives_engine/inklusivum.py](../app/alternatives_engine/inklusivum.py) |
| Articles and pronouns | [training_data/de/articles.csv](../training_data/de/articles.csv), `Inklusivum` column |
| Nouns the rules cannot derive | [training_data/de/inklusivum_nouns.csv](../training_data/de/inklusivum_nouns.csv) |
| Routing nouns to the paradigm | `Alternatives.inklusivum_noun` in [app/alternatives.py](../app/alternatives.py) |
| Suppressing rules on Inklusivum text | `RuleCheck.is_written_in_inklusivum` in [app/rule_check.py](../app/rule_check.py) |
| Suppressing spell check on Inklusivum text | `LanguageTool.is_inklusivum_form` in [app/languagetool.py](../app/languagetool.py) |
| Tests | [tests/test_dee_generation.py](../tests/test_dee_generation.py), [tests/test_inklusivum_nouns.py](../tests/test_inklusivum_nouns.py), `tests/test_gender_ending/test_api_gender_ending_inklusivum*` |

Sources for every form are the association's own tables:
[Gesamtsystem](https://geschlechtsneutral.net/gesamtsystem/),
[Deklinationstabellen](https://geschlechtsneutral.net/deklinationstabellen/),
[Ausnahmeformen](https://geschlechtsneutral.net/ausnahmeformen/).

## What is implemented

- **Nouns.** `-e` on the masculine stem, `-re` when it already ends in `-e`
  (`Kollegere`), plural `-rne`, umlaut in the plural only (`Arzte` but
  `Ärzterne`), genitive singular `-s`, dative plural `-n`.
- **Word replacement** for `-mann`/`-frau` compounds (`Kaufmann` →
  `Kaufperson`, plural `Kaufleute`) and other pairs the rules cannot derive.
- **Articles and possessives** across all four cases, including the `unse`/`eue`
  special case and the `zurm` contraction.
- **Pronouns** `en`/`ens`/`em`/`en`, with `enser` reserved for the rare true
  genitive.
- **Detection**, so text already written in the Inklusivum is neither reported by
  the gendered denomination rules nor by the spell checker.

## Remaining work

Ordered by impact. The first two produce wrong output; the rest are gaps.

### 1. Substantivized adjectives take adjective endings, not noun endings

`Vorgesetzte(r)`, `Angestellte(r)`, `Verlobte(r)`, `Beamte(r)`, `Jugendliche(r)`
and participles such as `Studierende` and `Mitarbeitende` are adjectives. The
spec is explicit that they decline as adjectives in the Inklusivum too, so
`de Vorgesetzte` after an article and `Vorgesetztey` without one. Routing them
through the noun paradigm yields `Vorgesetztere`, and for `dem Flüchtling` three
alternatives with three different wrong endings, one of them masculine.

This class is common in workplace text, which makes it the most visible defect.

### 2. The adjective endings are not reachable

`inklusivum.adjective()` implements the paradigm and is unit tested, but nothing
routes to it in practice: it hangs off the tilde handler and the rules that reach
that path do not carry adjective word types. Fixing 1 requires making this
reachable, so the two are one piece of work.

### 3. Already gender neutral words need the article changed, nothing else

`Gast`, `Mitglied`, `Fan`, `Person` and every `-ling` word take no suffix at all;
only their article becomes `de`/`jedey`. Needs the neutral person word list from
[Bereits geschlechtsneutrale Personenwörter](https://geschlechtsneutral.net/bereits-geschlechtsneutrale-personenworter/),
without which they get suffixed like ordinary nouns.

### 4. Pronoun agreement and the remaining pronoun forms

`ens` agrees with the possessed noun (`ens Auto`, `ense Jacke`, `an ensem
Geburtstag`); we always emit the bare form. Also missing: the relative pronoun
genitive `dersen`, which differs from the article genitive `ders`, and the
pronominal `einey` as distinct from the article `ein`.

Needs the possessed noun, which is in the token stream rather than in the
alternative, so it is a different seam from the article handling.

### 5. Address forms

`Sehr geehrte` → `Sehr geehrtey`, `Liebe`/`Lieber` → `Liebey`, `Herr`/`Frau` →
`Person [Nachname]`, and `Sehr geehrte Damen und Herren` → `Sehr geehrtes Team
von [Organisation]`. None are implemented.

### 6. Exception lexicon breadth

`inklusivum_nouns.csv` holds the common cases. The association's exception page
lists more, and is the page they themselves mark as least reviewed, so additions
should be treated as lower confidence than the core system.

### 7. Derivations

`kaufmännisch` → `kaufleutisch`, `Studentenschaft` → `Studenterneschaft`.

### 8. Detection covers nouns and articles only

Adjectives and pronouns written in the Inklusivum are still reported.

## Forms the sources do not settle

Do not treat these as decided; they are inferred by analogy and should be
confirmed before anything depends on them.

- Genitive plural of nouns, assumed identical to the nominative plural by
  analogy with standard German syncretism.
- Dative of `ens` before an Inklusivum noun (`enserm`?). Only the genitive is
  attested in the association's examples.
- The reflexive pronoun. Never mentioned; `sich` is already gender invariant, so
  it is assumed unchanged.
- Genitive and dative singular of the exception nouns, assumed to follow the
  regular `+s` rule since no override is given.
- Whether the traditional n-declension is preserved (`Studente` vs
  `Studenten`). No exception is stated, so the uniform rule is assumed.
- `deselben` appears in the nominative slot of the `derselbe` table where
  `deselbe` is expected, which looks like a typo in the source.

---

## See Also

- [Request Configuration](./request-configuration.md#gender-inclusive-formatting)
- [Training Data & Lookups](./training-data.md)
