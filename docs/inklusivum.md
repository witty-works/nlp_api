# Inklusivum (de-e)

Implementation notes and remaining work for the German [Inklusivum](https://geschlechtsneutral.net/inklusivum/), selected with `"german_gender_ending": "de-e"`.

## Table of Contents

- [Why it does not fit the other gender endings](#why-it-does-not-fit-the-other-gender-endings)
- [Where the code lives](#where-the-code-lives)
- [What is implemented](#what-is-implemented)
- [The refactor this is still waiting on](#the-refactor-this-is-still-waiting-on)
- [Remaining work](#remaining-work)
- [Forms the sources did not settle](#forms-the-sources-did-not-settle)

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

Where those pages are silent, the association's own tool is the second source: the [Inklusivomat](https://automat.geschlechtsneutral.net/) and its code at [LinusWemmer/gn_tool](https://github.com/LinusWemmer/gn_tool). It is a reference implementation rather than a ruling — it says what the system's authors built, not what the association has published — but its paradigm tables are explicit where the web pages leave cells empty. `lexicon.py` holds them at the top of the `Lexicon` class.

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

Ordered by impact. These are gaps rather than defects, with one exception: the address forms in §2, where the absence of a rule lets the generic path emit wrong suggestions.

### 1. The relative pronoun genitive

`dersen`, which differs from the article genitive `ders`. `Der Lehrer, dessen Buch fehlt` is in the `..._function_words` fixture and produces no finding on `dessen`. The reference implementation has a single-line rule for it (`neutralize_attributive_pronoun`), so the form is not in doubt; what is missing here is reaching it from a `dessen` or `deren` token.

The pronominal `einey` is done, so this entry is now only about the relative pronoun. Possessive agreement is also handled: rather than looking up the possessed noun, the gendered form being replaced already agrees with it, so only the stem is swapped. That does not extend to the relative pronoun, which has no such source form.

### 2. Address forms

`Sehr geehrte` → `Sehr geehrtey`, `Liebe`/`Lieber` → `Liebey`, `Herr`/`Frau` → `Person [Nachname]`, and `Sehr geehrte Damen und Herren` → `Sehr geehrtes Team von [Organisation]`. None are implemented.

This is the one gap that is worse than nothing. With no address rule the generic gendered-denomination path still fires on the salutation, and in the `..._function_words` fixture it offers `Herr` → `Erwachseney` and `Frau` → `Partnere`. Those are not address forms at all, and `Partnere` reads as a claim about the person. Suppressing the generic path on a salutation is worth doing even before the real forms land.

The reference implementation is a usable target: it marks a salutation by the adjective in front of the name (`PERSON_ADJECTIVES = ["lieb", "geehrt", "verehrt", "wert"]`), rewrites `Herr`/`Frau`/`Dame` to `Person`, and renders `Sehr geehrte Damen und Herren` as `Sehr geehrte Leute` rather than the `Team von …` the website suggests. Which of those two is the recommended form is now a question in [inklusivum-feedback.md](./inklusivum-feedback.md).

### 3. Exception lexicon breadth

`inklusivum_nouns.csv` is down to the pairs no rule can derive: unrelated roots, a stem taken from the feminine, the `-mann`/`-frau` compounds, and one entry that pins a recommended plural where the rules give the also accepted short form.

Prefer finding the rule over adding a row. Two classes that were listed word by word turned out to be systematic, and deriving them covers vocabulary the exception page does not mention at all. What remains there is worth reading with that in mind, and it is the page the association marks as least reviewed, so additions are lower confidence than the core system either way.

### 4. Derivations

`kaufmännisch` → `kaufleutisch`, `Studentenschaft` → `Studenterneschaft`. Both are confirmed: the reference implementation produces exactly these, so the forms are settled and only the derivation is missing here.

### 5. Pair formulas

`Kolleginnen und Kollegen` → `Kollegerne`, where the whole coordination collapses into one word. We report the two conjuncts separately, which leaves the reader to delete the rest of the phrase by hand.

[inklusivum-feedback.md](./inklusivum-feedback.md) records why this was left out: the replacement does not correspond to a single token, so it does not fit a suggestion anchored on one span. The reference implementation sidesteps that by rewriting whole text rather than offering findings, and marks the entire coordination as one selectable unit. Anything we do here needs a finding whose span covers both conjuncts and the conjunction.

### 6. A correct suggestion that changes nothing drops the whole finding

After an article, the Inklusivum form of `Vorgesetzte(r)` is `Vorgesetzte`, which is what the text already says. The suggestion is therefore registered as a false positive and the entire result disappears, taking the unrelated replacement suggestions (`Leitungsperson`, `Führungsperson`) with it.

Only the article actually needs changing here, and that is now reported separately, so what is left is the loss of the replacement suggestions rather than the missing article. Reporting nothing is at least better than the previous behaviour, which offered the article-less `Vorgesetztey` after an article.

## Forms the sources did not settle

These were inferred by analogy while the association's web pages were the only source, and the code depends on them. All of them are now confirmed against the reference implementation, so they are no longer assumptions — except where noted. [inklusivum-feedback.md](./inklusivum-feedback.md) keeps what is still worth putting to the association.

- **Genitive plural of nouns** — confirmed as identical to the nominative plural. `lexicon.py` gives the plural `-rne` for every case but the dative, which takes `-rnen`. Our `apply_case` does the same.
- **The article before a genitive plural** — we had this one wrong in prose. `neutralize_article` returns the input unchanged when the parse carries `Pl`, so it is *der Schülerne*, not *ders Schülerne*: in the plural the ordinary German article stays. The code was never wrong here, because the plural findings match the bare noun and prepend no article; only this document claimed otherwise. `test_api_gender_ending_inklusivum_plural` pins the behaviour.
- **Dative of `ens` before an Inklusivum noun** — confirmed as `enserm`. `ens` follows the `ein` paradigm, whose dative ending is `-erm`. Before an ordinary noun the possessive keeps the ending it already had (*ensem Geburtstag*), so both forms are real and the distinction is by design. We already produce both.
- **The reflexive pronoun** — confirmed unchanged. `sich` appears in the reference implementation only as a guard, never as something rewritten.
- **Genitive and dative singular of the exception nouns** — confirmed to follow the regular rule. The irregular nouns run through the same case branch as the derived ones, so the genitive singular is `+s`.
- **The n-declension** — confirmed dropped. There is no weak-declension branch; *den Studenten* becomes *de Studente*.
- **Genitive of the standalone article pronoun** — confirmed as `einers`. The empty cell on the Deklinationstabellen page is a gap in the table, not a missing form.
- **`deselben` in the nominative slot** — confirmed a typo on the website. The nominative is `deselbe`; every other case is the `der` article ending plus `selben`.

---

## Logo instead of the sad-face icon (done)

When the Inklusivum is the configured `german_gender_ending`, **all** gendered
findings carry the Inklusivum logo in place of the emoji icon — the logo
signals "this suggestion is in your chosen system", which holds for every
gendered suggestion under that config, not only for forms the Inklusivum
engine generated.

This is wired and visible in the snapshots: every `gender-orientation` finding
under `de-e` carries `explanation.icon_image` pointing at
`vgd-icon-bunt.svg`, and no finding in another category does. Older clients
still fall back to the emoji `icon`.

What remains is client-side QA rather than API work: that `icon_image` renders
in the extension's highlight UI, and that the CSP `img-src` allowlist covers
the assets domain.

## Dashboard readiness

What the dashboard must provide for the Inklusivum to reach users, stated
from this API's contract:

- **Settings UI**: offer the Inklusivum as a `german_gender_ending` option
  for user and organization configs, storing the value this API expects
  (see the option key in `training_data/config_options.json`). The option
  labels/translations flow through the existing dashboard→`config_options.json`
  sync, which already carries the Inklusivum label.
- **Logo asset + option metadata**: done — the SVG is hosted and reaches
  findings as `icon_image` (see the logo section above).
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
