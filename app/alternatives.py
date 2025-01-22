from app.models import (
    LangType,
    Rule,
    Alternative,
    WordType,
    Language,
    Config,
    BasicWordType,
    RuleType,
    GenderedRolesFormatType,
    Alternative,
    Config,
    Language,
    Rule,
    RuleType,
    BasicWordType,
    FrenchGenderSeparatorType,
)
from app.settings import Settings
from app.db import Db
from app.model import Model
from app.nouns import Nouns
from app.verbs import Verbs
from app.adjectives import Adjectives
from app.categories import is_sub_category_enabled, make_category_advanced
from app.helper import upperfirst, find_common_prefix
from app.query_definitions import declensions_config

from copy import deepcopy
from spacy.tokens import Doc
from logging import Logger
from pluralizefr import pluralize


class Alternatives:
    settings: Settings
    logger: Logger
    static_rules: dict
    db: Db
    model: Model
    nouns: Nouns
    verbs: Verbs
    adjectives: Adjectives

    def __init__(
        self,
        settings: Settings,
        logger: Logger,
        static_rules: dict,
        db: Db,
        model: Model,
        nouns: Nouns,
        verbs: Verbs,
        adjectives: Adjectives,
    ):
        self.settings = settings
        self.logger = logger
        self.static_rules = static_rules
        self.db = db
        self.model = model
        self.nouns = nouns
        self.verbs = verbs
        self.adjectives = adjectives

    def is_previous_token_article(self, token_index: int, tokens: Doc, lang: LangType):
        return (
            token_index > 0
            and tokens[token_index - 1].text.lower()
            in self.static_rules[lang]["articles"]
        )

    def get_previous_article(
        self,
        token_index: int,
        tokens: Doc,
        lang: LangType,
        text: str | None = None,
        start: int | None = None,
    ):
        if not self.is_previous_token_article(token_index, tokens, lang):
            return None, text, start

        article_index = token_index - 1
        gendered_article = tokens[article_index].text
        if text is not None:
            text = gendered_article + tokens[article_index].whitespace_ + text
            start = tokens[article_index].idx

        if lang != LangType.FR:
            return gendered_article, text, start

        article_index = article_index - 1

        # handle à la / de la
        if (
            article_index >= 0
            and gendered_article.lower() == "la"
            and tokens[article_index].lemma_ in ["de", "à"]
        ):
            prefix = tokens[article_index].text + tokens[article_index].whitespace_

            gendered_article = prefix + gendered_article
            if text is not None:
                text = prefix + text
                start = tokens[article_index].idx

        return gendered_article, text, start

    def fetch_article(
        self,
        lang: LangType,
        token_index: int,
        tokens: Doc,
        text: str,
        start: int,
    ):
        article = article_index = None

        if self.is_previous_token_article(token_index, tokens, lang):
            # Check if the article has not yet been included (f.e. via a pattern)
            article, text_, start_ = self.get_previous_article(
                token_index, tokens, lang, text, start
            )

            # If start == start_, the text was already expanded to include the article, f.e. via a pattern
            if start != start_:
                text = text_
                start = start_

            if "inclusive_articles" in self.static_rules[lang]:
                article_index = list(
                    self.static_rules[lang]["inclusive_articles"].keys()
                ).index(
                    self.static_rules[lang]["articles_inclusive_map"][article.lower()]
                )

        return text, start, article, article_index

    def alternatives_a_english(
        self,
        subcategory: str,
        token_index: int,
        tokens: Doc,
        alternatives: list[Alternative],
        text: str,
        start: int,
    ) -> tuple[str, int, list[Alternative]]:
        if subcategory.startswith("filler"):
            return text, start, alternatives

        text_, start_, article, _ = self.fetch_article(
            LangType.EN,
            token_index,
            tokens,
            text,
            start,
        )

        if article not in ["a", "an"]:
            return text, start, alternatives

        for alternative in alternatives:
            if (
                alternative.is_plural
                or alternative.is_remove
                or alternative.is_inspiration
                or alternative.lemma == "they"
                or alternative.lemma.startswith(
                    self.static_rules[LangType.EN]["a_not_startswith"]
                )
                or alternative.lemma.endswith(
                    self.static_rules[LangType.EN]["uncountables"]
                )
            ):
                continue

            alternative.lemma = (
                "an " + alternative.lemma
                if alternative.lemma[0].lower() in ["a", "e", "i", "o", "u"]
                else "a " + alternative.lemma
            )

        return text_, start_, alternatives

    async def alternative_declension(
        self,
        lang: LangType,
        target_form: str,
        source_text: str,
        source_lemma: str,
        word_type: str,
        rule: Rule,
        alternative: Alternative,
        is_singular: bool,
        prefix: str | None = None,
    ) -> Alternative:
        if (
            alternative.is_remove
            or alternative.is_inspiration
            or len(alternative.lemma) == 0
            or "~" in alternative.lemma
        ):
            return alternative

        if len(alternative.words) > 5:
            return alternative

        word_count = len(rule.words)

        alternative_tokens = self.model.fetch_tokens(lang, alternative.lemma)
        if word_count > 1:
            # TODO figure out how to modify phrases
            new_alternative_lemma = alternative.lemma
            is_plural_alternative = self.model.is_token_plural(
                lang, alternative_tokens[-1]
            )
        else:
            new_alternative_lemma = ""
            is_plural_alternative = False

            previous = False
            for alternative_index in reversed(range(len(alternative_tokens))):
                alternative_token = alternative_tokens[alternative_index]
                alternative_text = alternative_token.text
                if alternative_text != "," and self.model.token_is_conjunction(
                    alternative_token
                ):
                    previous = False
                else:
                    declension = (
                        not previous
                        and alternative.word_types[alternative_index]["lemmatize"]
                    )
                    if declension:
                        if alternative.word_types[alternative_index]["word_type"]:
                            alternative_word_type = alternative.word_types[
                                alternative_index
                            ]["word_type"]
                        elif len(alternative_tokens) == 1:
                            # in this case we just assume it is the same to avoid issues with word type detection
                            alternative_word_type = word_type
                        else:
                            alternative_word_type = await self.model.fetch_word_type(
                                lang, alternative_token, word_type, False
                            )

                        if WordType.VERB == word_type and (
                            (lang == LangType.EN and alternative_index == 0)
                            or WordType.VERB in alternative_word_type
                        ):
                            previous = True
                            alternative_text = await self.verbs.align_form_verb(
                                lang,
                                target_form,
                                source_text,
                                source_lemma,
                                alternative_token,
                            )
                        elif (
                            WordType.NOUN == word_type
                            and WordType.NOUN == alternative_word_type
                        ):
                            if self.model.is_token_plural(lang, alternative_token):
                                is_plural_alternative = True

                            previous = True
                            alternative_text = (
                                alternative_token.text
                                if alternative.is_collective_noun
                                or alternative.is_gendered_noun
                                else await self.nouns.align_form_noun(
                                    lang,
                                    target_form,
                                    alternative_token,
                                    prefix,
                                )
                            )
                        elif (
                            WordType.ADJECTIVE == word_type
                            and WordType.ADJECTIVE == alternative_word_type
                        ):
                            previous = True
                            alternative_text = (
                                await self.adjectives.align_form_adjective(
                                    lang,
                                    target_form,
                                    source_text,
                                    source_lemma,
                                    alternative_token,
                                )
                            )

                new_alternative_lemma = (
                    alternative_text
                    + alternative_token.whitespace_
                    + new_alternative_lemma
                )

        new_alternative = deepcopy(alternative)
        new_alternative.lemma = new_alternative_lemma
        new_alternative.is_plural = is_plural_alternative

        if (
            is_singular != False
            and is_plural_alternative
            and new_alternative.is_collective_noun
        ):
            new_alternative.is_inspiration = True

        return new_alternative

    async def alternatives_declension(
        self,
        lang: LangType,
        subcategory: str,
        text: str,
        start: int,
        token_index: int,
        tokens: Doc,
        target_form: str,
        rule: Rule,
        alternatives: list[Alternative],
        is_singular: bool,
    ) -> tuple[str, int, list[Alternative]]:
        if (
            len(rule.words) > 1
            or rule.is_pattern_match
            or subcategory.startswith("abbreviation")
            or alternatives == None
            or len(alternatives) == 0
            or (len(alternatives) == 1 and alternatives[0].is_remove)
        ):
            return text, tokens[token_index].idx, alternatives

        word_types = rule.get_word_types()
        word_type = (
            word_types[0]
            if (len(word_types) == 1 and word_types[0] != "")
            else await self.model.fetch_word_type(lang, tokens[token_index])
        )

        if tokens[token_index]._.start is not None:
            start = tokens[token_index]._.start
        if tokens[token_index]._.text is not None:
            text = tokens[token_index]._.text

        return (
            text,
            start,
            [
                await self.alternative_declension(
                    lang,
                    target_form,
                    text,
                    tokens[token_index].lemma_,
                    word_type,
                    rule,
                    alternative,
                    is_singular,
                )
                for alternative in alternatives
            ],
        )

    async def gendered_nouns(
        self,
        config: Config,
        language: Language,
        text: str,
        tokens: Doc,
        token_index: int,
        alternatives: list[Alternative],
        subcategory: str,
        is_singular: bool | None,
        rule: Rule,
        full_text: str,
        target_form: str,
    ) -> tuple[str | None, str | None, list[Alternative], None]:
        gendered_noun = False
        for alternative in alternatives:
            if alternative.lemma is not None and "~" in alternative.lemma:
                gendered_noun = True
                break

        if not gendered_noun:
            return text, subcategory, alternatives

        if (
            rule.type == RuleType.SUFFIX
            and not tokens[token_index].lemma_.endswith("frau")
            and not tokens[token_index].lemma_.endswith("mann")
            and tokens[token_index].lemma_.lower().endswith(rule.lemma.lower())
        ):
            lemma_lower = rule.lemma.lower().replace("ä", "a")
            # strip of last two chars to handle "Beauftragter" vs. "Beauftragten"
            if lemma_lower.endswith("er") or lemma_lower.endswith("e"):
                lemma_lower = lemma_lower[0:-2]

            prefix_end = text.lower().replace("ä", "a").find(lemma_lower)
            prefix = text[0:prefix_end]
        else:
            prefix = ""

        binary_case = False
        inclusive = Config.gendered_roles_format_inclusive(config.gendered_roles_format)
        binary = Config.gendered_roles_format_binary(config.gendered_roles_format)
        separator, noun_separator, separate_gender_plural = (
            config.get_gender_separators_from_config(language.lang)
        )
        additional_words = []
        is_singular = True if is_singular is None else is_singular
        if (
            target_form
            not in declensions_config[LangType.DE][BasicWordType.NOUN]["columns"]
        ):
            target_form = "sg_nom" if is_singular else "pl_nom"

        if prefix.endswith("-"):
            words = prefix[:-1].split("-")
            word_filter = ("?," * len(words)).removesuffix(",")

            query = f"SELECT base_form, male_form, female_form, collective_noun FROM rules_germannoun WHERE base_form IN ({word_filter})"
            rows = await self.db.fetch_rows(query, words.copy())

            male_noun_map = {}
            female_noun_map = {}
            for row in rows:
                if row[2] is not None:
                    male_noun_map[row[0]] = {
                        "female_form": row[2],
                        "collective_noun": row[3],
                    }
                elif row[1] is not None:
                    female_noun_map[row[0]] = {
                        "male_form": row[1],
                        "collective_noun": row[3],
                    }

            if len(male_noun_map) or len(female_noun_map):
                prefixes = []
                for word in words:
                    if word in male_noun_map:
                        male_form = word
                        female_form = male_noun_map[word]["female_form"]
                        collective_noun = male_noun_map[word]["collective_noun"]
                    elif word in female_noun_map:
                        female_form = word
                        male_form = female_noun_map[word]["male_form"]
                        collective_noun = female_noun_map[word]["collective_noun"]
                    else:
                        prefixes.append(word)
                        continue

                    prefix = ("-").join(prefixes) + "-" if len(prefixes) else ""
                    additional_words.append(
                        {
                            "word": word,
                            "male_form": prefix + male_form,
                            "female_form": prefix + female_form,
                            "collective_noun": (
                                prefix + collective_noun
                                if collective_noun is not None
                                else None
                            ),
                        }
                    )
                    prefixes = []

                prefix = ("-").join(prefixes)

        target_form = (
            "base_form"
            if target_form is None or target_form == "no_change"
            else target_form
        )

        new_alternatives = []
        for alternative in alternatives:
            if alternative.is_remove or alternative.is_inspiration:
                new_alternatives.append(alternative)
                continue

            if "~" in alternative.lemma:
                self.handle_single_tilde(alternative, prefix, is_singular)

            if not alternative.is_gendered_noun:
                alternative = await self.alternative_declension(
                    language.lang,
                    target_form,
                    text,
                    tokens[token_index].lemma_,
                    WordType.NOUN,
                    rule,
                    alternative,
                    is_singular,
                    prefix if alternative.lemma.startswith(prefix) else None,
                )

                if inclusive and separator != "/":
                    new_alternative = deepcopy(alternative)
                    new_alternative.lemma = new_alternative.lemma.replace(
                        "/", separator
                    )
                    new_alternatives.append(new_alternative)

                new_alternatives.append(alternative)
                continue

            alternative_variations, binary_case = await self.gendered_alternatives(
                alternative.lemma,
                inclusive,
                binary,
                separator,
                noun_separator,
                separate_gender_plural,
                additional_words,
                is_singular,
                target_form,
                token_index,
                tokens,
                full_text,
                prefix,
                binary_case,
            )

            # false positive
            if alternative_variations is None:
                return None, None, []

            if not is_sub_category_enabled(config.disabled_categories, subcategory):
                continue

            for alternative_variation in alternative_variations:
                new_alternative = deepcopy(alternative)
                new_alternative.lemma = alternative_variation
                new_alternative.is_collective_noun = alternative_variations[
                    alternative_variation
                ]
                new_alternative.is_gendered_noun = not alternative_variations[
                    alternative_variation
                ]
                if is_singular != False and new_alternative.is_collective_noun:
                    new_alternative.is_inspiration = True

                if (
                    "/" in alternative_variation and "/-" not in alternative_variation
                ) or self.static_rules[LangType.DE]["noun_conjunction"][
                    "plural"
                ] in alternative_variation:
                    for _ in range(text.count("-") + 1):
                        new_alternative.word_types.append(
                            {"word_type": "", "lower_case": True, "lemmatize": True}
                        )
                        new_alternative.word_types.append(
                            {
                                "word_type": WordType.NOUN,
                                "lower_case": True,
                                "lemmatize": True,
                            }
                        )

                new_alternatives.append(new_alternative)

        if binary_case:
            if binary:
                subcategory = "gendered_denominations_ending_advanced"
            else:
                subcategory = (
                    "function"
                    if "mann" in text.lower()
                    else "gendered_denominations_ending"
                )
                if rule.is_advanced:
                    subcategory = make_category_advanced(subcategory)

            if not is_sub_category_enabled(config.disabled_categories, subcategory):
                return None, None, []

            text += (
                tokens[token_index].whitespace_
                + tokens[token_index + 1].text
                + tokens[token_index + 1].whitespace_
                + tokens[token_index + 2].text
            )
        elif subcategory == "function":
            forms = await self.nouns.german_noun_lookup(tokens[token_index].text)
            if forms is not None and forms["male_form"] is not None:
                subcategory = "gender_identity"
                rule.text_id = forms["base_form"]

        return text, subcategory, new_alternatives

    async def gendered_alternatives(
        self,
        alternative: str,
        inclusive: bool,
        binary: bool,
        separator: str,
        noun_separator: str,
        separate_gender_plural: bool,
        additional_words: list = [],
        is_singular: bool = True,
        target_form: str = "base_form",
        token_index: int | None = None,
        tokens: Doc | None = None,
        full_text: str | None = None,
        prefix: str = "",
        binary_case: bool = False,
    ):
        alternatives = {}
        alternative_prefix = alternative_suffix = ""
        male_forms = None

        token_debug = (
            "" if token_index is None else f", idx: '{tokens[token_index].idx}'"
        )

        words = alternative.split(" ")
        for word in words:
            if not word.startswith("~") and "~" in word:
                male_form, female_form = word.split("~")
                male_forms = await self.nouns.german_noun_lookup(
                    male_form, None, prefix
                )
                if male_forms is None or target_form not in male_forms:
                    male_forms = None
                    self.logger.error(
                        f"Declension '{target_form}' missing for '{word}'{token_debug}"
                    )
                    break

                if female_form is None:
                    self.logger.error(
                        f"Declension data missing for other form in '{word}'{token_debug}"
                    )
                    return [], False

                female_forms = await self.nouns.german_noun_lookup(
                    female_form, None, prefix
                )
                if female_forms is None or target_form not in female_forms:
                    male_forms = True
                    self.logger.error(
                        f"Declension '{target_form}' missing for '{female_form}'{token_debug}"
                    )
                    return [], False

            elif male_forms is None:
                alternative_prefix += word + " "
            else:
                alternative_suffix += " " + word

        if male_forms is None:
            self.logger.error(
                f"Missing male_form '{word}' in '{alternative}'{token_debug}"
            )
            return [], binary_case

        female_form = female_forms[target_form]
        male_form = male_forms[target_form]

        if male_form == female_form:
            alternative = (
                alternative_prefix
                + self.add_german_prefix(male_form, prefix)
                + alternative_suffix
            )
            alternatives[alternative] = False
            return alternatives, binary_case

        if female_form is not None and male_form is not None:
            if inclusive:
                lemma = self.inclusive_alternative(
                    LangType.DE,
                    male_form,
                    female_form,
                    prefix,
                    separator,
                    noun_separator,
                    separate_gender_plural,
                )

                if self.model.is_false_positive(
                    full_text,
                    token_index,
                    tokens,
                    [lemma],
                    len(lemma),
                ):
                    return None, binary_case

                additional_prefix = ""
                for additional_word in additional_words:
                    additional_prefix += (
                        self.inclusive_alternative(
                            LangType.DE,
                            additional_word["male_form"],
                            additional_word["female_form"],
                            "",
                            separator,
                            noun_separator,
                            separate_gender_plural,
                        )
                        + "-"
                    )

                alternatives[
                    alternative_prefix.replace("/", separator)
                    + additional_prefix
                    + lemma
                    + alternative_suffix.replace("/", separator)
                ] = False

            female_form = self.add_german_prefix(female_form, prefix)
            male_form_without_prefix = male_form
            male_form = self.add_german_prefix(male_form, prefix)

            separator = (
                self.static_rules[LangType.DE]["noun_conjunction"]["singular"]
                if is_singular
                else self.static_rules[LangType.DE]["noun_conjunction"]["plural"]
            )
            lemma = female_form + separator + male_form
            false_positive_check = [
                lemma,
                male_form + separator + female_form,
            ]

            if not is_singular:
                # Arbeitskolleginnen und -kollegen
                false_positive_check.append(
                    female_form + separator + "-" + male_form_without_prefix.lower()
                )

            # case text = Mitarbeiterinnen: Mitarbeiterinnen und Mitarbeiter
            if self.model.is_false_positive(
                full_text,
                token_index,
                tokens,
                false_positive_check,
                0,
                len(lemma),
            ):
                # Suggest gender inclusive
                if binary and tokens[token_index].text == female_form:
                    return None, binary_case

                binary_case = True

            form_max = max(len(female_form), len(male_form))

            # case text = Mitarbeiter: Mitarbeiterinnen und Mitarbeiter
            if self.model.is_false_positive(
                full_text,
                token_index,
                tokens,
                false_positive_check,
                form_max + len(separator),
                form_max,
            ):
                return None, binary_case

            if binary:
                additional_prefix = ""
                for additional_word in additional_words:
                    additional_prefix += (
                        additional_word["female_form"]
                        + "/"
                        + additional_word["male_form"]
                        + "-"
                    )

                new_alternative = (
                    alternative_prefix + additional_prefix + lemma + alternative_suffix
                )
                alternatives[new_alternative] = False

            additional_prefix = ""
            for additional_word in additional_words:
                if additional_word["collective_noun"] is not None:
                    additional_prefix += additional_word["collective_noun"] + "-"

        for form in ["collective_noun", "collective_noun_2"]:
            if male_forms[form] is not None:
                new_alternative = (
                    alternative_prefix
                    + additional_prefix
                    + self.add_german_prefix(male_forms[form], prefix)
                    + alternative_suffix
                )
                alternatives[new_alternative] = True

        return alternatives, binary_case

    def add_german_prefix(self, word: str, prefix: str) -> str:
        if len(prefix) == 0 or word.startswith(prefix):
            return word

        if not word.startswith("-") and not prefix.endswith("-"):
            word = word[0].lower() + word[1:]

        return prefix + word

    def add_article(self, lang: LangType, text: str, article: str, separator: str):
        if (
            lang == LangType.FR
            and (article.endswith("le") or article == "la")
            and text[0] in ["a", "e", "i", "o", "u", "h"]
        ):
            return "l'" + text

        if separator != FrenchGenderSeparatorType.POINT_MEDIAN:
            article = article.replace(FrenchGenderSeparatorType.POINT_MEDIAN, separator)

        return article + " " + text

    def add_article_to_alternative(
        self,
        lang: LangType,
        alternative: Alternative,
        article_index: int,
        article: str,
        separator: str,
    ):
        alternative.lemma = self.add_article(
            lang, alternative.lemma, article, separator
        )

        if isinstance(alternative.male_form, str):
            alternative.male_form = self.add_article(
                lang,
                alternative.male_form,
                self.get_article_by_index(
                    lang,
                    "masculine_articles",
                    article_index,
                ),
                separator,
            )

        if isinstance(alternative.female_form, str):
            alternative.female_form = self.add_article(
                lang,
                alternative.female_form,
                self.get_article_by_index(
                    lang,
                    "feminine_articles",
                    article_index,
                ),
                separator,
            )

        return alternative

    async def noun_alternatives(
        self,
        lang: LangType,
        separator: str,
        noun_separator: str,
        separate_gender_plural: bool,
        male_form: str,
        female_form: str,
        article: str | None = None,
    ) -> dict[str]:
        sentence_male_tokens = self.model.fetch_tokens(lang, male_form)
        sentence_female_tokens = self.model.fetch_tokens(lang, female_form)
        if len(sentence_male_tokens) != len(sentence_female_tokens):
            return None, None, {}

        inclusive_form = ""
        binary_form = ""
        male_form_sub_sentence = ""
        female_form_sub_sentence = ""
        sub_sentence_contains_noun = False

        if article:
            article = article.lower()

        for token_index in range(len(sentence_male_tokens)):
            if (
                sentence_male_tokens[token_index].text
                != sentence_female_tokens[token_index].text
            ):
                inclusive_form += self.inclusive_alternative(
                    lang,
                    sentence_male_tokens[token_index].text,
                    sentence_female_tokens[token_index].text,
                    "",
                    separator,
                    noun_separator,
                    separate_gender_plural,
                )
                conjunction = (
                    self.static_rules[lang]["noun_conjunction"]["singular"]
                    if self.model.is_token_singular(
                        lang, sentence_male_tokens[token_index]
                    )
                    else self.static_rules[lang]["noun_conjunction"]["plural"]
                )
                if lang == LangType.FR:
                    if (
                        token_index > 0
                        and sentence_male_tokens[token_index - 1].lemma_
                        in self.static_rules[lang]["masculine_articles"]
                    ):
                        is_noun = True
                        sub_sentence_contains_noun = True
                    else:
                        is_noun = (
                            await self.model._fetch_word_type(
                                lang,
                                sentence_male_tokens[token_index],
                                WordType.NOUN,
                                True,
                                True,
                            )
                            == WordType.NOUN
                        )
                        if sub_sentence_contains_noun == True or is_noun:
                            sub_sentence_contains_noun = True

                    if male_form_sub_sentence != "":
                        male_form_sub_sentence += sentence_male_tokens[
                            token_index - 1
                        ].whitespace_
                        female_form_sub_sentence += sentence_female_tokens[
                            token_index - 1
                        ].whitespace_

                    male_form_sub_sentence += sentence_male_tokens[token_index].text
                    female_form_sub_sentence += (
                        sentence_female_tokens[token_index].text
                        if token_index > 0 or is_noun
                        else sentence_female_tokens[token_index].text.lower()
                    )
                else:
                    binary_form += (
                        sentence_female_tokens[token_index].text
                        + conjunction
                        + sentence_male_tokens[token_index].text
                    )
            else:
                inclusive_form += sentence_male_tokens[token_index].text
                if male_form_sub_sentence != "":
                    if sub_sentence_contains_noun:
                        binary_form += (
                            male_form_sub_sentence
                            + conjunction
                            + female_form_sub_sentence
                            + sentence_female_tokens[token_index - 1].whitespace_
                        )
                    else:
                        # TODO add user preference to choose male form over female form
                        binary_form += (
                            female_form_sub_sentence
                            + sentence_male_tokens[token_index - 1].whitespace_
                        )
                    male_form_sub_sentence = ""
                    female_form_sub_sentence = ""
                    sub_sentence_contains_noun = False

                binary_form += sentence_male_tokens[token_index].text

            inclusive_form += sentence_male_tokens[token_index].whitespace_

            if male_form_sub_sentence == "":
                binary_form += sentence_male_tokens[token_index].whitespace_

        if male_form_sub_sentence != "":
            if article:
                if article in self.static_rules[lang]["articles_inclusive_map"]:
                    male_article = article
                    female_article = article
                if article in self.static_rules[lang]["masculine_articles"]:
                    male_article = article
                    female_article = self.static_rules[lang]["articles_binary_map"][
                        article
                    ]
                else:
                    male_article = self.static_rules[lang]["articles_binary_map"][
                        article
                    ]
                    female_article = article

                male_form_sub_sentence = self.add_article(
                    lang, male_form_sub_sentence, male_article, separator
                )
                female_form_sub_sentence = self.add_article(
                    lang, female_form_sub_sentence, female_article, separator
                )

            binary_form += (
                male_form_sub_sentence + conjunction + female_form_sub_sentence
            )

        if article:
            inclusive_form = self.add_article(
                lang,
                inclusive_form,
                self.static_rules[lang]["articles_inclusive_map"][article],
                separator,
            )

        return (
            male_form_sub_sentence,
            female_form_sub_sentence,
            {
                GenderedRolesFormatType.INCLUSIVE_GENDER: inclusive_form,
                GenderedRolesFormatType.BINARY_GENDER: binary_form,
            },
        )

    def inclusive_alternative(
        self,
        lang: LangType,
        male_form: str,
        female_form: str,
        prefix_words: str,
        separator: str,
        noun_separator: str,
        separate_gender_plural: bool,
    ):
        if lang == LangType.DE:
            if male_form.lower() in self.static_rules[lang]["masculine_articles"]:
                return female_form + separator + male_form

            short_gender_star = True
            common_prefix = (
                ""
                if male_form.endswith("mann")
                else find_common_prefix(male_form, female_form, False, False)
            )
            if len(male_form) - len(common_prefix) > 2:
                common_prefix = female_form
                suffix = self.add_german_prefix(male_form, prefix_words)
                short_gender_star = False
            elif len(female_form) >= len(male_form):
                # Mitarbeiterin + Mitarbeiter = Mitarbeiter
                suffix = female_form[len(common_prefix) :]
            else:
                # Vorgesetze + Vorgesetzter = Vorgesetze
                suffix = male_form[len(common_prefix) :]

            temp_separator = noun_separator
            # In
            if separator != noun_separator:
                if short_gender_star:
                    suffix = upperfirst(suffix)
                else:
                    temp_separator = "/"

            return self.add_german_prefix(
                common_prefix + temp_separator + suffix, prefix_words
            )

        if lang == LangType.FR:
            male_form_lower = male_form.lower()
            if male_form_lower in self.static_rules[lang]["masculine_articles"]:
                inclusive_form = self.static_rules[lang]["masculine_articles"][
                    male_form_lower
                ]
                if male_form != male_form_lower:
                    inclusive_form = upperfirst(inclusive_form)
                return inclusive_form

            common_prefix = find_common_prefix(male_form, female_form, False, False)
            # Il est un poète
            if len(common_prefix) < 3:
                return prefix_words + male_form + separator + female_form.lower()

            if len(female_form) >= len(male_form):
                suffix = female_form[len(common_prefix) :]
                prefix = male_form
            else:
                suffix = male_form[len(common_prefix) :]
                prefix = female_form

            # expérimentés / expérimentées => expérimenté·es
            if prefix.endswith("s"):
                prefix = prefix[0:-1]

            if separate_gender_plural and suffix.endswith("s"):
                suffix = suffix[0:-1] + separator + "s"

            return prefix_words + prefix + separator + suffix

    def handle_single_tilde(
        self, alternative: Alternative, prefix: bool, is_singular: bool
    ):
        lemma = ""
        word_types = []
        # ideally we use alternative.words here but we strip out the "~" in the rule editor
        words = alternative.lemma.split()
        for word_index in range(len(words)):
            word = words[word_index]
            if word.count("~") == 1:
                slash = False
                if word.startswith("~"):
                    word = self.add_german_prefix(word[1:], prefix)
                else:
                    position = word.find("~")
                    if word[position + 1].islower():
                        # Trans~gender => Trans*gender, qualifiziert~e => qualifiziert*e, ihr~e => ihr*e
                        if position + 3 < len(word) or is_singular:
                            word = word.replace("~", "/")
                            slash = True
                        # ihr~e => ihre
                        elif word.endswith("e"):
                            word = word.replace("~", "")
                        # qualifizierte~r => qualifizierte
                        else:
                            word = word[0:position]

                        if slash:
                            word_types.append(alternative.word_types[word_index])
                            word_types.append(
                                {"word_type": "", "lower_case": True, "lemmatize": True}
                            )

            word_types.append(alternative.word_types[word_index])
            lemma += " " + word

        alternative.word_types = word_types
        alternative.lemma = lemma.strip()

    def nouns_with_articles(
        self,
        config: Config,
        lang: LangType,
        article: str | None,
        article_index: int | None,
        result: dict,
        is_plural: bool,
        alternative: Alternative,
        alternatives: list[Alternative],
        separator: str,
    ):
        if article:
            article = article.lower()

        alternative.lemma = result["base_form"]
        if is_plural:
            if result["plural"] is None:
                result["plural"] = pluralize(result["base_form"])

            alternative.lemma = result["plural"]
            if article:
                alternative = self.add_article_to_alternative(
                    lang,
                    alternative,
                    article_index,
                    article,
                    separator,
                )
            alternatives.append(alternative)

            return alternatives

        is_gender_neutral = self.nouns.is_gender_neutral(result)
        if result["female_form"] or is_gender_neutral:
            if config.gendered_roles_format == GenderedRolesFormatType.BOTH:
                new_alternative = deepcopy(alternative)
                if result["female_form"] or (article and is_gender_neutral):
                    new_alternative.male_form = result["base_form"]
                    new_alternative.female_form = result["base_form"]
                    new_alternative.is_gendered_noun = True
                    new_alternative.gender_role = (
                        GenderedRolesFormatType.INCLUSIVE_GENDER
                    )

                if article:
                    new_alternative = self.add_article_to_alternative(
                        lang,
                        new_alternative,
                        article_index,
                        self.static_rules[LangType.FR]["articles_inclusive_map"][
                            article
                        ],
                        separator,
                    )
                alternatives.append(new_alternative)

            if (
                # "la", "le", "la·le"
                article_index == 0
                and result["base_form"][0] not in ["a", "e", "i", "o", "u", "h"]
                and Config.gendered_roles_format_inclusive(config.gendered_roles_format)
            ):
                new_alternative = deepcopy(alternative)
                new_alternative.is_gendered_noun = False
                new_alternative.gender_role = None
                new_alternative.male_form = None
                new_alternative.female_form = None
                new_alternative.lemma = "les " + result["plural"]
                alternatives.append(new_alternative)

            if article:
                if (
                    config.gendered_roles_format
                    == GenderedRolesFormatType.INCLUSIVE_GENDER
                ):
                    alternative.male_form = alternative.lemma
                    alternative.female_form = alternative.lemma

                    alternative = self.add_article_to_alternative(
                        lang,
                        alternative,
                        article_index,
                        self.static_rules[LangType.FR]["articles_inclusive_map"][
                            article
                        ],
                        separator,
                    )
                    alternative.is_gendered_noun = True
                    alternative.gender_role = GenderedRolesFormatType.INCLUSIVE_GENDER
                else:
                    forms = {}
                    for form in ["masculine", "feminine"]:
                        forms[form] = self.add_article(
                            lang,
                            alternative.lemma,
                            self.get_article_by_index(
                                lang,
                                form + "_articles",
                                article_index,
                            ),
                            separator,
                        )
                    alternative.lemma = forms["masculine"]
                    if forms["masculine"] != forms["feminine"]:
                        alternative.lemma += (
                            self.static_rules[LangType.FR]["noun_conjunction"]["plural"]
                            if is_plural
                            else self.static_rules[LangType.FR]["noun_conjunction"][
                                "singular"
                            ]
                        ) + forms["feminine"]
                        alternative.male_form = forms["masculine"]
                        alternative.female_form = forms["feminine"]

                    alternative.gender_role = GenderedRolesFormatType.BINARY_GENDER
        elif article and result["gender_1"]:
            alternative = self.add_article_to_alternative(
                lang,
                alternative,
                article_index,
                self.get_article_by_index(
                    lang,
                    result["gender_1"] + "_articles",
                    article_index,
                ),
                separator,
            )

        alternatives.append(alternative)

        return alternatives

    def get_article_by_index(
        self, lang: LangType, articles_list: str, article_index: int
    ):
        return list(self.static_rules[lang][articles_list].keys())[article_index]

    def get_adjective_alternatives_french(self, male_form, female_form):
        lemma = male_form + "~" + female_form
        return [
            Alternative(
                lemma,
                [lemma],
                [
                    {
                        "word_type": "a",
                        "lower_case": True,
                        "lemmatize": True,
                    }
                ],
                False,
                False,
                False,
                False,
                False,
                True,
            )
        ]
