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
| Person words that take no ending | [training_data/de/inklusivum_neutral_nouns.csv](../training_data/de/inklusivum_neutral_nouns.csv) |
| Routing nouns to the paradigm | `Alternatives.inklusivum_noun` in [app/alternatives.py](../app/alternatives.py) |
| Articles for words that take no ending | `RuleCheck.inklusivum_articles` in [app/rule_check.py](../app/rule_check.py) |
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
- **Nouns whose ending is replaced rather than suffixed**: Romance loans
  (`Alumnus`/`Alumna` → `Alumne`, `Ballerino` → `Ballerine`) and the few `-erer`
  nouns where `-in` replaces the second `-er` (`Wanderer`/`Wanderin` →
  `Wandere`). Both are rules, so they cover words the exception page never
  lists.
- **Words that take no ending at all**, such as `Gast`, `Mitglied`, `Person` and
  everything in `-ling`, which is a rule rather than a list. Some of these do
  have a feminine in the lexicon, `Gästin` for one, which is a real word but not
  a reason to derive a form the system does not use. The list therefore
  deliberately overrides the lexicon for these words, and is expected to stay
  that way; if it needs to be maintained alongside the rest of the language data
  it can move into the imported sqlite database, which changes where it lives
  but not what it decides.
- **Word replacement** for `-mann`/`-frau` compounds (`Kaufmann` →
  `Kaufperson`, plural `Kaufleute`) and the handful of genuinely irregular
  pairs, which are all that is left in the lexicon.
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
- **The article for words that take no ending**, so `Der Gast` is offered as
  `De Gast`. Nothing else reports these, since the noun is not gendered and no
  denomination rule matches it.
- **Attributive adjectives**, where the noun is being rewritten: `als guter
  Arzte` becomes `als gutey Arzte`. Most need no change even then, because after
  an article the endings are the ordinary German ones.
- **Explanations** naming the rule behind an article or adjective suggestion,
  linking into the association's page at the section that covers it.
- **Detection**, so text already written in the Inklusivum is neither reported by
  the gendered denomination rules nor by the spell checker. Nouns are confirmed
  against the lexicon; articles and possessives are closed sets; the
  article-less adjective endings `-ey` and `-erm` are distinctive enough to go
  by shape, where `-ers` is not ("anders", "besonders").

## Remaining work

Ordered by impact. None of these produce wrong output any more; they are gaps.

### 1. The remaining pronoun forms

The relative pronoun genitive `dersen`, which differs from the article genitive
`ders`, and the pronominal `einey` as distinct from the article `ein`.

Possessive agreement is handled: rather than looking up the possessed noun, the
gendered form being replaced already agrees with it, so only the stem is swapped.
That does not extend to the relative pronoun, which has no such source form.

### 2. Address forms

`Sehr geehrte` → `Sehr geehrtey`, `Liebe`/`Lieber` → `Liebey`, `Herr`/`Frau` →
`Person [Nachname]`, and `Sehr geehrte Damen und Herren` → `Sehr geehrtes Team
von [Organisation]`. None are implemented.

### 3. Exception lexicon breadth

`inklusivum_nouns.csv` is down to the pairs no rule can derive: unrelated roots,
a stem taken from the feminine, the `-mann`/`-frau` compounds, and one entry that
pins a recommended plural where the rules give the also accepted short form.

Prefer finding the rule over adding a row. Two classes that were listed word by
word turned out to be systematic, and deriving them covers vocabulary the
exception page does not mention at all. What remains there is worth reading with
that in mind, and it is the page the association marks as least reviewed, so
additions are lower confidence than the core system either way.

### 4. Derivations

`kaufmännisch` → `kaufleutisch`, `Studentenschaft` → `Studenterneschaft`.

### 5. A correct suggestion that changes nothing drops the whole finding

After an article, the Inklusivum form of `Vorgesetzte(r)` is `Vorgesetzte`, which
is what the text already says. The suggestion is therefore registered as a false
positive and the entire result disappears, taking the unrelated replacement
suggestions (`Leitungsperson`, `Führungsperson`) with it.

Only the article actually needs changing here, and that is now reported
separately, so what is left is the loss of the replacement suggestions rather
than the missing article. Reporting nothing is at least better than the previous
behaviour, which offered the article-less `Vorgesetztey` after an article.

## Forms the sources do not settle

Do not treat these as decided; they are inferred by analogy, and the code
already depends on them. [inklusivum-feedback.md](./inklusivum-feedback.md) puts
them to the association as questions, along with what would make the system
easier to implement.

Two were checked again against every page the site links to and are genuinely
absent rather than missed: the genitive plural of nouns, and the reflexive
pronoun. The dative plural is attested (*den Schülernen*), the genitive plural is
not.

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

- [Rückfragen zum Inklusivum](./inklusivum-feedback.md), open questions for the association
- [Request Configuration](./request-configuration.md#gender-inclusive-formatting)
- [Training Data & Lookups](./training-data.md)
