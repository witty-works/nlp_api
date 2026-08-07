# Inklusivum (de-e)

Implementation notes and remaining work for the German [Inklusivum](https://geschlechtsneutral.net/inklusivum/), selected with `"german_gender_ending": "de-e"`.

## Table of Contents

- [Why it does not fit the other gender endings](#why-it-does-not-fit-the-other-gender-endings)
- [Where the code lives](#where-the-code-lives)
- [What is implemented](#what-is-implemented)
- [The refactor this is still waiting on](#the-refactor-this-is-still-waiting-on)
- [Remaining work](#remaining-work)
- [Forms the sources do not settle](#forms-the-sources-do-not-settle)

---

## Why it does not fit the other gender endings

The other eight values of `german_gender_ending` are typographic separators. The configured value *is* the answer: find the split point in `Lehrerin`, insert the character, done. The whole pipeline is built around that, which is why `Config.get_gender_separators` returns a separator string and why `inclusive_alternative()` takes a male form, a female form and a separator.

The Inklusivum is not a separator. It is a fourth grammatical gender with its own articles, adjective endings, pronouns and noun declension. Its forms are derived from the masculine stem and then declined; they are never assembled from a male and a female surface form. Two consequences shape the code:

- Grammatical case matters. `Schülere` takes `-s` in the genitive singular and the plural takes `-n` in the dative, so the number and case have to reach the point where the word is built. That is what `target_form` (`sg_gen`, `pl_dat`, …) carries.
- Detection cannot work on shape. An Inklusivum noun looks like any other German noun ending in `-e`, so `Liebe`, `Sprache` and `Woche` are indistinguishable from it by pattern. Recognising it needs a lexicon lookup.

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

Sources for every form are the association's own tables: [Gesamtsystem](https://geschlechtsneutral.net/gesamtsystem/), [Deklinationstabellen](https://geschlechtsneutral.net/deklinationstabellen/), [Ausnahmeformen](https://geschlechtsneutral.net/ausnahmeformen/).

## What is implemented

- **Nouns.** `-e` on the masculine stem, `-re` when it already ends in `-e` (`Kollegere`), plural `-rne`, umlaut in the plural only (`Arzte` but `Ärzterne`), genitive singular `-s`, dative plural `-n`.
- **Nouns whose ending is replaced rather than suffixed**: Romance loans (`Alumnus`/`Alumna` → `Alumne`, `Ballerino` → `Ballerine`) and the few `-erer` nouns where `-in` replaces the second `-er` (`Wanderer`/`Wanderin` → `Wandere`). Both are rules, so they cover words the exception page never lists.
- **Words that take no ending at all**, such as `Gast`, `Mitglied`, `Person` and everything in `-ling`, which is a rule rather than a list. Some of these do have a feminine in the lexicon, `Gästin` for one, which is a real word but not a reason to derive a form the system does not use. The list therefore deliberately overrides the lexicon for these words, and is expected to stay that way; if it needs to be maintained alongside the rest of the language data it can move into the imported sqlite database, which changes where it lives but not what it decides.
- **Word replacement** for `-mann`/`-frau` compounds (`Kaufmann` → `Kaufperson`, plural `Kaufleute`) and the handful of genuinely irregular pairs, which are all that is left in the lexicon.
- **Articles and possessives** across all four cases, including the `unse`/`eue` special case and the `zurm` contraction.
- **Adjectives**, `-e`/`-en` after any article and `-ey`/`-ers`/`-erm` without one. The Inklusivum does not split weak from mixed declension, so `de`, `ein` and `jedey` all take the same endings.
- **Adjectives used as nouns** (`Vorgesetzte(r)`, `Angestellte(r)`, the participles), which keep taking adjective endings rather than the noun ending. Recognised by shape: an adjective pair agrees by dropping the masculine's final `r`, where a noun pair derives the feminine with `-in`.
- **Pronouns** `en`/`ens`/`em`/`en`, with `enser` reserved for the rare true genitive.
- **Possessives**, where the gendered form already agrees with the noun it modifies, so only the stem changes: `ihrem` → `ensem`, `Ihre` → `Ense`.
- **The article for words that take no ending**, so `Der Gast` is offered as `De Gast`. Nothing else reports these, since the noun is not gendered and no denomination rule matches it.
- **Attributive adjectives**, where the noun is being rewritten: `als guter Arzte` becomes `als gutey Arzte`. Most need no change even then, because after an article the endings are the ordinary German ones.
- **Explanations** naming the rule behind an article or adjective suggestion, linking into the association's page at the section that covers it.
- **Detection**, so text already written in the Inklusivum is neither reported by the gendered denomination rules nor by the spell checker. Nouns are confirmed against the lexicon; articles and possessives are closed sets; the article-less adjective endings `-ey` and `-erm` are distinctive enough to go by shape, where `-ers` is not ("anders", "besonders").

## The refactor this is still waiting on

Everything below is a feature gap. This one is not: it is the shape of the code, and it is what the defects in this branch have had in common.

`Config.get_gender_separators` has to return a separator string, because that is what the eight other endings are. The Inklusivum has none, so it returns the placeholder `INKLUSIVUM_SEPARATOR` and every consumer has to know not to splice it into a word. That knowledge is not in one place, and it has not held:

- the advanced ending conversion emitted the literal `de-e` as a suggestion, and its first character `d` as a separator
- the rephrase endpoint reached `inclusive_alternative`, which builds words a character at a time around whatever it is given
- a slash-to-separator rewrite shipped `ihremDEEseinem` to users
- the prefix and suffix of a gendered alternative were spliced unguarded
- `inclusive_alternative` was later given an Inklusivum branch that applied only the base noun ending, so the rephrase path produced `dere`, `Alumnuse` and `Vorgesetztere`

Five of those were fixed by adding a guard, which is why there were five. The same pattern produced the rest of the defects found reviewing this branch: `singular()` where `noun()` was meant, a suffix where the lexicon was meant, a matched span where a token was meant. Each is a shortcut past the shared path, and each was expressible because the shared path is a convention rather than a structure.

What removes the class rather than the instances is making the gender ending a collaborator with methods for noun, article, adjective and pronoun, of which the eight separator endings are one implementation and the Inklusivum another. Then there is no placeholder to leak and no lower-level call to reach past. The staging matters: thread the grammatical context through first, then introduce the collaborator with only the separator implementation and require every snapshot to be byte identical, and only then add the second implementation. The first two steps changing nothing is the evidence that the seam is in the right place.

It is not small. `alternatives.py` is around 1,400 lines shared by three languages, and snapshots are the only safety net, so this wants doing at the start of a session rather than the end of one.

## Remaining work

Ordered by impact. None of these produce wrong output any more; they are gaps.

### 1. The remaining pronoun forms

The relative pronoun genitive `dersen`, which differs from the article genitive `ders`, and the pronominal `einey` as distinct from the article `ein`.

Possessive agreement is handled: rather than looking up the possessed noun, the gendered form being replaced already agrees with it, so only the stem is swapped. That does not extend to the relative pronoun, which has no such source form.

### 2. Address forms

`Sehr geehrte` → `Sehr geehrtey`, `Liebe`/`Lieber` → `Liebey`, `Herr`/`Frau` → `Person [Nachname]`, and `Sehr geehrte Damen und Herren` → `Sehr geehrtes Team von [Organisation]`. None are implemented.

### 3. Exception lexicon breadth

`inklusivum_nouns.csv` is down to the pairs no rule can derive: unrelated roots, a stem taken from the feminine, the `-mann`/`-frau` compounds, and one entry that pins a recommended plural where the rules give the also accepted short form.

Prefer finding the rule over adding a row. Two classes that were listed word by word turned out to be systematic, and deriving them covers vocabulary the exception page does not mention at all. What remains there is worth reading with that in mind, and it is the page the association marks as least reviewed, so additions are lower confidence than the core system either way.

### 4. Derivations

`kaufmännisch` → `kaufleutisch`, `Studentenschaft` → `Studenterneschaft`.

### 5. A correct suggestion that changes nothing drops the whole finding

After an article, the Inklusivum form of `Vorgesetzte(r)` is `Vorgesetzte`, which is what the text already says. The suggestion is therefore registered as a false positive and the entire result disappears, taking the unrelated replacement suggestions (`Leitungsperson`, `Führungsperson`) with it.

Only the article actually needs changing here, and that is now reported separately, so what is left is the loss of the replacement suggestions rather than the missing article. Reporting nothing is at least better than the previous behaviour, which offered the article-less `Vorgesetztey` after an article.

## Forms the sources do not settle

Do not treat these as decided; they are inferred by analogy, and the code already depends on them. [inklusivum-feedback.md](./inklusivum-feedback.md) puts them to the association as questions, along with what would make the system easier to implement.

Two were checked again against every page the site links to and are genuinely absent rather than missed: the genitive plural of nouns, and the reflexive pronoun. The dative plural is attested (*den Schülernen*), the genitive plural is not.

- Genitive plural of nouns, assumed identical to the nominative plural by analogy with standard German syncretism.
- Dative of `ens` before an Inklusivum noun (`enserm`?). Only the genitive is attested in the association's examples.
- The reflexive pronoun. Never mentioned; `sich` is already gender invariant, so it is assumed unchanged.
- Genitive and dative singular of the exception nouns, assumed to follow the regular `+s` rule since no override is given.
- Whether the traditional n-declension is preserved (`Studente` vs `Studenten`). No exception is stated, so the uniform rule is assumed.
- `deselben` appears in the nominative slot of the `derselbe` table where `deselbe` is expected, which looks like a typo in the source.

---

## Logo instead of the sad-face icon (decided, not yet wired)

When the Inklusivum is the configured `german_gender_ending`, **all** gendered
findings carry the Inklusivum logo in place of the emoji icon — the logo
signals "this suggestion is in your chosen system", which holds for every
gendered suggestion under that config, not only for forms the Inklusivum
engine generated.

The plumbing already exists; the wiring is data plus one conditional:

- The `Result` schema has `icon_image`, and the explanation assembly emits it
  whenever category data carries `emoji_image` (the corporate-rules branding
  path) - clients that render corporate icons render this too, and older
  clients fall back to the emoji `icon`.
- Dashboard: host the SVG in the regular asset pipeline and attach it as
  `icon_image` to the *Inklusivum ending option* in the config-options data
  (not to a subcategory - the same subcategories serve every ending style).
- API: at result assembly, when the active config's ending is the Inklusivum
  and the finding is a gendered one, pass that `icon_image` through.
- Extension: QA that `icon_image` renders in the highlight UI and that the
  CSP `img-src` allowlist covers the assets domain; fall back to an inline
  `data:` SVG only if a rendering context forces it.

## Dashboard readiness

What the dashboard must provide for the Inklusivum to reach users, stated
from this API's contract:

- **Settings UI**: offer the Inklusivum as a `german_gender_ending` option
  for user and organization configs, storing the value this API expects
  (see the option key in `training_data/config_options.json`). The option
  labels/translations flow through the existing dashboard→`config_options.json`
  sync, which already carries the Inklusivum label.
- **Logo asset + option metadata**: host the SVG and attach it as
  `icon_image` to the ending option in that same synced data (see the logo
  section above).
- **Rendering of Inklusivum text**: anywhere the dashboard displays findings
  or alternatives (team analytics, demos), expect Inklusivum forms - `einey`,
  `ens` possessives, endings without a separator character - and the logo in
  `icon_image` where it renders finding icons.
- **Category/driver sync**: if the association's material adds an
  Inklusivum-specific explanation page, the drivers data (`hs_path`,
  translations) is the channel; no API change needed.

## See Also

- [Rückfragen zum Inklusivum](./inklusivum-feedback.md), open questions for the association
- [Request Configuration](./request-configuration.md#gender-inclusive-formatting)
- [Training Data & Lookups](./training-data.md)
