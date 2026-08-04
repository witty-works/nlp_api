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
| Tests | [tests/test_dee_generation.py](../tests/test_dee_generation.py) for the article data, [tests/test_inklusivum_nouns.py](../tests/test_inklusivum_nouns.py) for the paradigms, and the `tests/test_gender_ending/test_api_gender_ending_inklusivum*` fixtures end to end |

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
- **Adjectives**, `-e`/`-en` after any article and `-ey`/`-ers`/`-erm` without
  one. The Inklusivum does not split weak from mixed declension, so `de`, `ein`
  and `jedey` all take the same endings.
- **Adjectives used as nouns** (`Vorgesetzte(r)`, `Angestellte(r)`, the
  participles), which keep taking adjective endings rather than the noun ending.
  Recognised by shape: an adjective pair agrees by dropping the masculine's
  final `r`, where a noun pair derives the feminine with `-in`.
- **Pronouns** `en`/`ens`/`em`/`en`, with `enser` reserved for the rare true
  genitive.
- **Possessives**, where the gendered form already agrees with the noun it
  modifies, so only the stem changes: `ihrem` → `ensem`, `Ihre` → `Ense`.
- **Detection**, so text already written in the Inklusivum is neither reported by
  the gendered denomination rules nor by the spell checker. Nouns are confirmed
  against the lexicon; articles and possessives are closed sets; the
  article-less adjective endings `-ey` and `-erm` are distinctive enough to go
  by shape, where `-ers` is not ("anders", "besonders").

## Remaining work

Ordered by impact. None of these produce wrong output any more; they are gaps.

### 1. Already gender neutral words keep their gendered article

`Gast`, `Mitglied`, `Fan`, `Person` and every `-ling` word take no suffix at all,
which is already what happens: no rule fires on them, so nothing is suffixed.
What is missing is the other half, that their article still becomes `de`/`jedey`,
so `Der Gast` should be offered as `De Gast`.

Nothing anchors that today. The gendered denomination rules key on the noun being
gendered, and these nouns are not, so there is no match to hang the article
change on. It needs a check of its own, driven by the person words already loaded
into `Db.person_words` from the `ner` column, plus the neutral person word list
from
[Bereits geschlechtsneutrale Personenwörter](https://geschlechtsneutral.net/bereits-geschlechtsneutrale-personenworter/).

Worth weighing against noise: it would fire on every article before a person
word, which is a lot of suggestions for a small change each.

### 2. The remaining pronoun forms

The relative pronoun genitive `dersen`, which differs from the article genitive
`ders`, and the pronominal `einey` as distinct from the article `ein`.

Possessive agreement is handled: rather than looking up the possessed noun, the
gendered form being replaced already agrees with it, so only the stem is swapped.
That does not extend to the relative pronoun, which has no such source form.

### 3. Address forms

`Sehr geehrte` → `Sehr geehrtey`, `Liebe`/`Lieber` → `Liebey`, `Herr`/`Frau` →
`Person [Nachname]`, and `Sehr geehrte Damen und Herren` → `Sehr geehrtes Team
von [Organisation]`. None are implemented.

### 4. Exception lexicon breadth

`inklusivum_nouns.csv` holds the common cases. The association's exception page
lists more, and is the page they themselves mark as least reviewed, so additions
should be treated as lower confidence than the core system.

### 5. Derivations

`kaufmännisch` → `kaufleutisch`, `Studentenschaft` → `Studenterneschaft`.

### 6. A correct suggestion that changes nothing drops the whole finding

After an article, the Inklusivum form of `Vorgesetzte(r)` is `Vorgesetzte`, which
is what the text already says. The suggestion is therefore registered as a false
positive and the entire result disappears, taking the unrelated replacement
suggestions (`Leitungsperson`, `Führungsperson`) with it.

Only the article actually needs changing here, so this resolves with item 1
rather than on its own. Reporting nothing is at least better than the previous
behaviour, which offered the article-less `Vorgesetztey` after an article.

### 7. Attributive adjectives are not converted

`Als guter Arzt` gives `Arzte` for the noun but leaves `guter`, which should be
`gutey`. The adjective paradigm exists and is reachable for adjectives used as
nouns; ordinary attributive adjectives sit behind the tilde handler, and the
rules that reach it carry noun word types.

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
