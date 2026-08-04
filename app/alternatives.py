from app.models import (
    LangType,
    Rule,
    Alternative,
    WordType,
    Config,
    RuleType,
    GenderedRolesFormatType,
    Article,
    BasicWordType,
    INKLUSIVUM_SEPARATOR,
)
from app.settings import Settings
from app.db import Db
from app.model import Model
from app.nouns import Nouns
from app.verbs import Verbs
from app.adjectives import Adjectives
from app.categories import is_sub_category_enabled, make_category_advanced
from app.helper import check_word_case
from app.query_definitions import declensions_config

from copy import deepcopy
from spacy.tokens import Doc
from logging import Logger
from pluralizefr import pluralize
from app.alternatives_engine import utils
from app.alternatives_engine import formatting
from app.alternatives_engine import inklusivum
from app.alternatives_engine import sentences


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

    def has_attached_article(
        self, token_index: int, tokens: Doc, lang: LangType
    ) -> bool:
        """Whether an article introduces this noun phrase.

        Takes the determiner from the parse rather than from the token to the
        immediate left, so an adjective in between does not hide it: "Der nette
        Lehrer" has an article just as much as "Der Lehrer" does. Only the
        attachment comes from the parse; whether a word is an article is still
        decided by the article table, so a weaker model degrades to the
        adjacency check rather than to guesswork.
        """
        articles = self.static_rules[lang]["articles"]

        for child in tokens[token_index].lefts:
            if child.text.lower() in articles:
                return True

        return self.is_previous_token_article(token_index, tokens, lang)

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

            if lang == LangType.FR:
                article_index = list(
                    self.static_rules[lang]["inclusive_articles"].keys()
                ).index(
                    self.static_rules[lang]["articles_inclusive_map"][article.lower()]
                )

        return text, start, article, article_index

    def alternatives_a_english(
        self,
        rule: Rule,
        token_index: int,
        tokens: Doc,
        text: str,
        start: int,
    ) -> tuple[str, int]:
        if rule.dynamic.subcategory.startswith("filler"):
            return text, start

        text_, start_, article, _ = self.fetch_article(
            LangType.EN,
            token_index,
            tokens,
            text,
            start,
        )

        if article not in ["a", "an"]:
            return text, start

        for alternative in rule.alternatives:
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

        return text_, start_

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
        parts: list[str] | None = None
        if word_count > 1:
            # TODO figure out how to modify phrases
            new_alternative_lemma = alternative.lemma
            is_plural_alternative = self.model.is_token_plural(
                lang, alternative_tokens[-1]
            )
        else:
            parts = []
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

                parts.append(alternative_text + alternative_token.whitespace_)

        new_alternative = deepcopy(alternative)
        if parts is None:
            new_alternative.lemma = new_alternative_lemma
        else:
            new_alternative.lemma = "".join(reversed(parts)) if parts else ""
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
        text: str,
        start: int,
        token_index: int,
        tokens: Doc,
        target_form: str,
        rule: Rule,
        is_singular: bool,
    ) -> tuple[str, int]:
        if (
            len(rule.words) > 1
            or rule.is_pattern_match
            or rule.dynamic.subcategory.startswith("abbreviation")
        ):
            return text, start

        word_types = rule.get_word_types()
        word_type = (
            word_types[0]
            if (len(word_types) == 1 and word_types[0] != "")
            else await self.model.fetch_word_type(lang, tokens[token_index])
        )

        rule.alternatives = [
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
            for alternative in rule.alternatives
        ]

        return text, start

    async def add_german_article_to_alternative(
        self,
        tokens: Doc,
        token_index: int,
        rule: Rule,
        alternative: Alternative,
        separator: str,
    ) -> Alternative:
        if rule.dynamic.article is None:
            return alternative

        # helper to prepend an article and insert ARTICLE token(s)
        def _prepend_article(article_str: str) -> None:
            alternative.lemma = (
                article_str + tokens[token_index - 1].whitespace_ + alternative.lemma
            )
            alternative.word_types.insert(
                0,
                {"word_type": WordType.ARTICLE, "lower_case": True, "lemmatize": True},
            )

        is_dee = (
            separator == INKLUSIVUM_SEPARATOR
            and alternative.gender_role == GenderedRolesFormatType.INCLUSIVE_GENDER
        )
        article = None

        if is_dee:
            article = rule.dynamic.article.inklusivum or (
                rule.dynamic.article.inclusive or rule.dynamic.article.fallback
            )
            if isinstance(article, str):
                article = article.replace("~", "")

            if not alternative.is_gendered_noun:
                if article:
                    _prepend_article(article)
                return alternative
        else:
            if alternative.is_gendered_noun:
                article = (
                    rule.dynamic.article.inclusive or rule.dynamic.article.fallback
                )
                sep = (
                    separator
                    if alternative.gender_role
                    == GenderedRolesFormatType.INCLUSIVE_GENDER
                    else "/"
                )
                if isinstance(article, str):
                    article = article.replace("~", sep)
            else:
                alternative_tokens = self.model.fetch_tokens(
                    LangType.DE, alternative.words[-1]
                )
                if self.model.is_token_plural(LangType.DE, alternative_tokens[0]):
                    article = rule.dynamic.article.plural
                else:
                    gender = await self.nouns.german_noun_gender_lookup(
                        alternative.words[-1]
                    )
                    article = rule.dynamic.article.get_article(
                        gender, alternative.lemma
                    )

        if article:
            _prepend_article(article)

            if "/" in article:
                alternative.word_types.insert(
                    0, {"word_type": "", "lower_case": True, "lemmatize": True}
                )
                alternative.word_types.insert(
                    0,
                    {
                        "word_type": WordType.ARTICLE,
                        "lower_case": True,
                        "lemmatize": True,
                    },
                )

            if alternative.is_gendered_noun:
                alternative.male_form = (
                    rule.dynamic.article.masculine
                    + tokens[token_index - 1].whitespace_
                    + alternative.male_form
                )
                alternative.female_form = (
                    rule.dynamic.article.feminine
                    + tokens[token_index - 1].whitespace_
                    + alternative.female_form
                )

        return alternative

    def add_article_to_alternative(
        self,
        lang: LangType,
        alternative: Alternative,
        article: str,
        separator: str,
    ) -> Alternative:
        if not article:
            return alternative

        # Compose lemma with article using language-specific adjustments
        new_lemma = utils.add_article(lang, alternative.lemma, article, separator)
        alternative.lemma = new_lemma

        # Update word_types to include an ARTICLE at the beginning
        alternative.word_types.insert(
            0,
            {
                "word_type": WordType.ARTICLE,
                "lower_case": True,
                "lemmatize": True,
            },
        )

        # If the article contains a gender separator (e.g., la·le), mirror the German handling
        # by inserting an extra empty token and a second ARTICLE marker to keep alignment.
        if separator and separator in article:
            alternative.word_types.insert(
                1,
                {
                    "word_type": "",
                    "lower_case": True,
                    "lemmatize": True,
                },
            )
            alternative.word_types.insert(
                2,
                {
                    "word_type": WordType.ARTICLE,
                    "lower_case": True,
                    "lemmatize": True,
                },
            )

        # If male/female forms are provided, compose them with corresponding
        # masculine/feminine articles as well. Do not rely on is_gendered_noun
        # being set before this call (some call sites set it afterwards).
        if alternative.male_form is not None and alternative.female_form is not None:
            male_article, female_article = utils.article_binary_pair(
                self.static_rules, lang, article
            )

            alternative.male_form = utils.add_article(
                lang, alternative.male_form, male_article, separator
            )
            alternative.female_form = utils.add_article(
                lang, alternative.female_form, female_article, separator
            )

        return alternative

    def fetch_german_article_for_flexion(
        self, flexion: str | None, gender: str, article: str
    ) -> Article | None:
        if flexion is None:
            return None

        parts = flexion.split(maxsplit=1)
        if not parts:
            return None
        form = parts[0]
        if (
            article not in self.static_rules[LangType.DE][gender + "_articles"]
            or form not in self.static_rules[LangType.DE][gender + "_articles"][article]
        ):
            return None

        article_forms = self.static_rules[LangType.DE][gender + "_articles"][article][
            form
        ]
        if isinstance(article_forms, Article):
            article_forms.fallback = article

        return article_forms

    async def find_form(
        self,
        lang: LangType,
        word_type: WordType,
        token_index: int,
        tokens: Doc,
        is_singular: bool | None = None,
    ):
        if lang == LangType.FR:
            return tokens[token_index].text

        token = tokens[token_index]
        match word_type:
            case WordType.VERB:
                if lang == LangType.DE:
                    return await self.verbs.find_form_verb_german(token_index, tokens)

                return await self.verbs.find_form_verb_english(token_index, tokens)
            case WordType.ADJECTIVE | WordType.ADVERB:
                if lang == LangType.DE:
                    return await self.adjectives.find_form_adjective_german(
                        token_index, tokens
                    )

                return await self.adjectives.find_form_adjective_english(
                    token_index, tokens
                )

            case WordType.NOUN | WordType.PRONOUN:
                if lang == LangType.DE:
                    if token.text.endswith("-") and is_singular:
                        return "no_change"

                    return await self.nouns.find_form_noun_german(
                        token_index, tokens, is_singular
                    )

                return await self.nouns.find_form_noun_english(is_singular)

        if (
            self.settings.log_missing_declension
            and len(word_type)
            and len(token.text) > 3
            and check_word_case(token.text)
        ):
            word_type = await self.model.fetch_word_type(lang, token)
            if word_type in [WordType.NOUN, WordType.VERB, WordType.ADJECTIVE]:
                self.logger.error(
                    f"Declension in '{lang}' not found for '{token.text}' (lemma: '{token.lemma_}', tag: '{token.tag_}, pos: '{token.pos_}', idx: '{token.idx}')"
                )

        return None

    async def fetch_target_form(
        self,
        rule: Rule,
        token_index: int,
        tokens: Doc,
        lang: LangType,
        is_singular: bool,
    ):
        form_token_i = token_index
        if rule.actual_word_types:
            word_type = rule.actual_word_types[0]
        else:
            word_types = rule.get_word_types()
            expected_word_type = None
            if LangType.DE == lang and len(word_types) > 1:
                form_token_offset = 0
                for k in range(len(word_types)):
                    if word_types[k] == WordType.NOUN:
                        expected_word_type = WordType.NOUN
                        form_token_offset = k

                form_token_i += form_token_offset

            if expected_word_type is None:
                expected_word_type = word_types[0] if len(word_types) else None

            word_type = await self.model.fetch_word_type(
                lang,
                tokens[form_token_i],
                expected_word_type,
            )

        return await self.find_form(lang, word_type, form_token_i, tokens, is_singular)

    def german_target_form(
        self,
        target_form: str,
        is_singular: bool,
    ):
        if target_form is None or target_form == "no_change":
            target_form = "base_form"
        elif (
            target_form
            not in declensions_config[LangType.DE][BasicWordType.NOUN]["columns"]
        ):
            target_form = "sg_nom" if is_singular else "pl_nom"

        return target_form

    async def german_gendered_noun_prefix(
        self, rule: Rule, token_index: int, tokens: Doc, text: str, is_singular: bool
    ):
        prefix = ""

        if (
            rule.type == RuleType.SUFFIX
            and tokens[token_index].lemma_.lower() != rule.lemma.lower()
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

        additional_words = []
        is_singular = True if is_singular is None else is_singular

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

        return prefix, additional_words

    async def german_gendered_nouns(
        self,
        config: Config,
        text: str,
        start: int,
        tokens: Doc,
        token_index: int,
        is_singular: bool | None,
        rule: Rule,
        full_text: str,
        prefix: str,
        additional_words: list,
        target_form: str,
    ) -> tuple[str | None, int | None]:
        separator, noun_separator, separate_gender_plural = (
            config.get_gender_separators_from_config(LangType.DE)
        )

        binary_case = False
        inclusive = Config.gendered_roles_format_inclusive(config.gendered_roles_format)
        binary = Config.gendered_roles_format_binary(config.gendered_roles_format)

        new_alternatives = []
        for alternative in rule.alternatives:
            if alternative.is_remove or alternative.is_inspiration:
                new_alternatives.append(alternative)
                continue

            if "~" in alternative.lemma:
                self.handle_single_tilde(
                    alternative,
                    prefix,
                    is_singular,
                    separator,
                    rule.dynamic.article,
                    text,
                )

            if not alternative.is_gendered_noun:
                declined = (
                    separator == INKLUSIVUM_SEPARATOR
                    and await self.inklusivum_adjective(
                        alternative,
                        target_form,
                        self.has_attached_article(token_index, tokens, LangType.DE),
                    )
                )

                if not declined:
                    alternative = await self.alternative_declension(
                        LangType.DE,
                        target_form,
                        text,
                        tokens[token_index].lemma_,
                        rule.get_first_word_type(),
                        rule,
                        alternative,
                        is_singular,
                        prefix if alternative.lemma.startswith(prefix) else None,
                    )

                if rule.dynamic.article:
                    alternative = await self.add_german_article_to_alternative(
                        tokens, token_index, rule, alternative, separator
                    )

                # The Inklusivum has no separator to splice in, so this would
                # write the sentinel into the suggestion itself.
                if inclusive and separator not in ("/", INKLUSIVUM_SEPARATOR):
                    new_alternative = deepcopy(alternative)
                    new_alternative.lemma = new_alternative.lemma.replace(
                        "/", separator
                    )
                    new_alternatives.append(new_alternative)

                new_alternatives.append(alternative)
                continue

            alternative_variations, binary_case = (
                await self.german_gendered_alternatives(
                    rule,
                    alternative,
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
                    text,
                    prefix,
                    binary_case,
                )
            )

            # false positive
            if alternative_variations is None:
                return None, None

            if not is_sub_category_enabled(
                config.disabled_categories, rule.dynamic.subcategory
            ):
                continue

            new_alternatives.extend(alternative_variations)

        if binary_case:
            if binary:
                rule.dynamic.subcategory = "gendered_denominations_ending_advanced"
            else:
                rule.dynamic.subcategory = (
                    "function"
                    if "mann" in text.lower()
                    else "gendered_denominations_ending"
                )
                if rule.is_advanced:
                    rule.dynamic.subcategory = make_category_advanced(
                        rule.dynamic.subcategory
                    )

            if not is_sub_category_enabled(
                config.disabled_categories, rule.dynamic.subcategory
            ):
                return None, None

            text += (
                tokens[token_index].whitespace_
                + tokens[token_index + 1].text
                + tokens[token_index + 1].whitespace_
                + tokens[token_index + 2].text
            )
        elif rule.dynamic.subcategory == "function":
            forms = await self.nouns.german_noun_lookup(tokens[token_index].text)
            if forms is not None and forms["male_form"] is not None:
                rule.dynamic.subcategory = "gender_identity"
                rule.text_id = forms["base_form"]

        rule.alternatives = new_alternatives

        return text, start

    async def clone_alternative(
        self,
        tokens: Doc,
        token_index: int,
        separator: str,
        rule: Rule,
        alternative: Alternative,
        text: str | None,
        lemma: str,
        is_singular: bool,
        is_collective_noun: bool = False,
        male_form: str | None = None,
        female_form: str | None = None,
        gender_role: GenderedRolesFormatType | None = None,
    ):
        new_alternative = deepcopy(alternative)
        new_alternative.lemma = lemma
        new_alternative.is_collective_noun = is_collective_noun
        new_alternative.is_gendered_noun = not is_collective_noun
        new_alternative.male_form = male_form
        new_alternative.female_form = female_form
        new_alternative.gender_role = gender_role

        if is_singular != False and is_collective_noun:
            new_alternative.is_inspiration = True

        if text is not None and (
            ("/" in lemma and "/-" not in lemma)
            or self.static_rules[LangType.DE]["noun_conjunction"]["plural"] in lemma
        ):
            count = text.count("-") + 1
            pair = [
                {"word_type": "", "lower_case": True, "lemmatize": True},
                {"word_type": WordType.NOUN, "lower_case": True, "lemmatize": True},
            ]
            new_alternative.word_types.extend(pair * count)

        if rule.dynamic.article:
            new_alternative = await self.add_german_article_to_alternative(
                tokens, token_index, rule, new_alternative, separator
            )

        return new_alternative

    async def german_gendered_alternatives(
        self,
        rule: Rule,
        alternative: Alternative,
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
        text: str = "",
        prefix: str = "",
        binary_case: bool = False,
    ) -> tuple[list[Alternative], bool]:
        alternatives = []
        alternative_prefix = alternative_suffix = ""
        male_forms = None

        token_debug = (
            "" if token_index is None else f", idx: '{tokens[token_index].idx}'"
        )

        words = alternative.lemma.split(" ")
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

        male_form = male_forms[target_form]
        male_form_with_prefix = utils.add_german_prefix(male_form, prefix)
        female_form = female_forms[target_form]
        female_form_with_prefix = utils.add_german_prefix(female_form, prefix)

        if (
            rule.dynamic.article is None or not is_singular
        ) and male_form == female_form:
            alternatives.append(
                await self.clone_alternative(
                    tokens,
                    token_index,
                    separator,
                    rule,
                    alternative,
                    text,
                    male_form_with_prefix + alternative_suffix,
                    is_singular,
                )
            )
            return alternatives, binary_case

        if female_form is not None and male_form is not None:
            if inclusive:
                # A word is only already gender neutral when the two genders
                # share a base form. Comparing the declined forms instead would
                # catch every case where they merely happen to coincide, and
                # adjectives used as nouns do coincide in the dative, leaving
                # "Geflüchtetem" where the Inklusivum wants "Geflüchteten".
                is_neutral = (
                    male_forms.get("base_form") == female_forms.get("base_form")
                    if separator == INKLUSIVUM_SEPARATOR
                    else male_form == female_form
                )

                if is_neutral:
                    lemma = prefix + male_form
                elif separator == INKLUSIVUM_SEPARATOR:
                    lemma = self.inklusivum_noun(
                        male_forms,
                        female_forms,
                        target_form,
                        prefix,
                        self.has_attached_article(token_index, tokens, LangType.DE),
                    )
                    rule.dynamic.false_positives.append(lemma)
                else:
                    lemma = formatting.inclusive_alternative(
                        self.static_rules,
                        LangType.DE,
                        male_form,
                        female_form,
                        prefix,
                        separator,
                        noun_separator,
                        separate_gender_plural,
                    )

                    rule.dynamic.false_positives.append(lemma)

                parts = [
                    (
                        inklusivum.noun(
                            aw["male_form"],
                            aw["female_form"],
                            None,
                            "",
                            self.static_rules[LangType.DE]["inklusivum_nouns"],
                            True,
                            self.static_rules[LangType.DE]["inklusivum_neutral_nouns"],
                        )
                        if separator == INKLUSIVUM_SEPARATOR
                        else formatting.inclusive_alternative(
                            self.static_rules,
                            LangType.DE,
                            aw["male_form"],
                            aw["female_form"],
                            "",
                            separator,
                            noun_separator,
                            separate_gender_plural,
                        )
                    )
                    for aw in additional_words
                ]
                additional_prefix = ("".join(p + "-" for p in parts)) if parts else ""

                alternatives.append(
                    await self.clone_alternative(
                        tokens,
                        token_index,
                        separator,
                        rule,
                        alternative,
                        text,
                        utils.splice_separator(alternative_prefix, separator)
                        + additional_prefix
                        + lemma
                        + utils.splice_separator(alternative_suffix, separator),
                        is_singular,
                        False,
                        male_form_with_prefix,
                        female_form_with_prefix,
                        GenderedRolesFormatType.INCLUSIVE_GENDER,
                    )
                )

            lemma = male_form_with_prefix
            if male_form != female_form:
                conjunction = utils.get_noun_conjunction(
                    self.static_rules, LangType.DE, is_singular
                )
                lemma = female_form_with_prefix + conjunction + lemma

                false_positive_check = [
                    lemma,
                    male_form_with_prefix + conjunction + female_form_with_prefix,
                ]

                if not is_singular:
                    # Arbeitskolleginnen und -kollegen
                    false_positive_check.append(
                        female_form_with_prefix + conjunction + "-" + male_form.lower()
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
                    if binary and tokens[token_index].text == female_form_with_prefix:
                        return None, binary_case

                    binary_case = True
                else:
                    rule.dynamic.false_positives.extend(false_positive_check)

            if binary:
                additional_prefix = ""
                additional_prefix = "".join(
                    aw["female_form"] + "/" + aw["male_form"] + "-"
                    for aw in additional_words
                )

                alternatives.append(
                    await self.clone_alternative(
                        tokens,
                        token_index,
                        separator,
                        rule,
                        alternative,
                        text,
                        utils.splice_separator(alternative_prefix, separator)
                        + additional_prefix
                        + lemma
                        + utils.splice_separator(alternative_suffix, separator),
                        is_singular,
                        False,
                        male_form_with_prefix,
                        female_form_with_prefix,
                        GenderedRolesFormatType.BINARY_GENDER,
                    )
                )

            additional_prefix = ""
            additional_prefix = "".join(
                aw["collective_noun"] + "-"
                for aw in additional_words
                if aw["collective_noun"] is not None
            )

        for form in ["collective_noun", "collective_noun_2"]:
            if male_forms[form] is not None:
                alternatives.append(
                    await self.clone_alternative(
                        tokens,
                        token_index,
                        separator,
                        rule,
                        alternative,
                        text,
                        alternative_prefix
                        + additional_prefix
                        + utils.add_german_prefix(male_forms[form], prefix)
                        + alternative_suffix,
                        is_singular,
                        True,
                    )
                )

        return alternatives, binary_case

    async def noun_alternatives(
        self,
        lang: LangType,
        separator: str,
        noun_separator: str,
        separate_gender_plural: bool,
        male_form: str,
        female_form: str,
        article: str | None = None,
    ) -> tuple[str, str, dict]:
        """Build inclusive and binary noun alternatives for a pair of male/female forms.

        Returns a tuple of possibly adjusted male_form, female_form and a dict mapping
        GenderedRolesFormatType to the constructed string.
        """
        sentence_male_tokens = self.model.fetch_tokens(lang, male_form)
        sentence_female_tokens = self.model.fetch_tokens(lang, female_form)

        male_sub, female_sub, variants = await sentences.build_sentence_gendered_forms(
            self.model,
            self.static_rules,
            lang,
            sentence_male_tokens,
            sentence_female_tokens,
            separator,
            noun_separator,
            separate_gender_plural,
            article,
        )

        return male_sub or male_form, female_sub or female_form, variants

    def inklusivum_noun(
        self,
        male_forms: dict,
        female_forms: dict,
        target_form: str | None,
        prefix: str,
        has_article: bool = True,
    ) -> str | None:
        """Build an Inklusivum noun from the nominative singular pair.

        The Inklusivum declines its own stem rather than reusing a declined
        masculine, so the base forms are used here and ``target_form`` only
        selects number and case. ``has_article`` picks the adjective ending set
        for pairs that are adjectives rather than nouns.
        """
        return inklusivum.noun(
            male_forms.get("base_form") or male_forms.get("sg_nom"),
            female_forms.get("base_form") or female_forms.get("sg_nom"),
            target_form,
            prefix,
            self.static_rules[LangType.DE]["inklusivum_nouns"],
            has_article,
            self.static_rules[LangType.DE]["inklusivum_neutral_nouns"],
        )

    async def inklusivum_adjective(
        self,
        alternative: Alternative,
        target_form: str | None,
        has_article: bool,
    ) -> bool:
        """Decline a replacement that is an adjective used as a noun.

        Suggestions like "Geflüchtete" or "Vertriebene" arrive here undeclined
        and would otherwise be declined as ordinary German, giving
        "Geflüchtetem" in the dative where the Inklusivum wants "Geflüchteten".
        Returns whether it applied.
        """
        words = alternative.lemma.split()
        if not words:
            return False

        forms = await self.nouns.german_noun_lookup(words[-1])
        if not forms:
            return False

        masculine = forms.get("male_form") or forms.get("base_form")
        feminine = forms.get("female_form") or forms.get("base_form")

        if not inklusivum.is_substantivized_adjective(masculine, feminine):
            return False

        words[-1] = inklusivum.substantivized_adjective(
            masculine, target_form, "", has_article
        )

        alternative.lemma = " ".join(words)
        if alternative.words:
            alternative.words[-1] = words[-1]

        return True

    def is_adjective_word_type(self, alternative: Alternative, word_index: int) -> bool:
        if word_index >= len(alternative.word_types):
            return False

        return alternative.word_types[word_index].get("word_type") == WordType.ADJECTIVE

    def handle_single_tilde(
        self,
        alternative: Alternative,
        prefix: bool,
        is_singular: bool,
        separator: str,
        article: Article | None = None,
        source_text: str = "",
    ):
        lemma = ""
        word_types = []
        # ideally we use alternative.words here but we strip out the "~" in the rule editor
        words = alternative.lemma.split()
        for word_index in range(len(words)):
            word = words[word_index]
            if word.count("~") == 1:
                pre = []
                slash = False

                if word.startswith("~"):
                    word, pre = utils.add_german_prefix(word[1:], prefix), []
                elif (
                    separator == INKLUSIVUM_SEPARATOR
                    and word in self.static_rules[LangType.DE]["inclusive_articles"]
                ):
                    replacement = utils.inklusivum_article(
                        self.static_rules[LangType.DE]["inclusive_articles"][word],
                        article.form if article else None,
                    )

                    # The article table holds one form per case, but a
                    # possessive also agrees with the noun it modifies. The
                    # word being replaced already carries that agreement, so
                    # take it from there instead: "Ihre" -> "ense", not "ens".
                    # Only when the match is the possessive itself. A wider
                    # span, expanded over an article or matched by a pattern,
                    # would be spliced into the replacement word.
                    if (
                        replacement
                        and replacement.startswith(inklusivum.POSSESSIVE)
                        and source_text
                        and " " not in source_text.strip()
                    ):
                        agreed = inklusivum.possessive(source_text.strip())
                        if agreed:
                            replacement = agreed

                    word, pre = replacement, []
                elif separator == INKLUSIVUM_SEPARATOR and inklusivum.possessive_pair(
                    word
                ):
                    word, pre = inklusivum.possessive_pair(word), []
                elif (
                    separator == INKLUSIVUM_SEPARATOR
                    and is_singular
                    and self.is_adjective_word_type(alternative, word_index)
                ):
                    word, pre = (
                        inklusivum.adjective(
                            inklusivum.adjective_stem(word),
                            article.form if article else None,
                            article is not None,
                        ),
                        [],
                    )
                else:
                    position = word.find("~")
                    if (
                        position != -1
                        and position + 1 < len(word)
                        and word[position + 1].islower()
                    ):
                        if position + 3 < len(word) or is_singular:
                            slash = True
                            new_w = word.replace("~", "/")
                        elif word.endswith("e"):
                            new_w = word.replace("~", "")
                        else:
                            new_w = word[0:position]

                        pre_types = []
                        if slash:
                            pre_types = [
                                alternative.word_types[word_index],
                                {
                                    "word_type": "",
                                    "lower_case": True,
                                    "lemmatize": True,
                                },
                            ]
                        word, pre = new_w, pre_types
                    else:
                        pre = []

                if pre:
                    word_types.extend(pre)

            word_types.append(alternative.word_types[word_index])
            lemma += " " + word

        alternative.word_types = word_types
        alternative.lemma = lemma.strip()

    def french_nouns_with_articles(
        self,
        config: Config,
        article: str | None,
        article_index: int | None,
        result: dict,
        is_plural: bool,
        alternative: Alternative,
        alternatives: list[Alternative],
        separator: str,
    ) -> list[Alternative]:
        if article:
            article = article.lower()

        alternative.lemma = result["base_form"]
        if is_plural:
            if result["plural"] is None:
                result["plural"] = pluralize(result["base_form"])

            alternative.lemma = result["plural"]
            if article:
                alternative = self.add_article_to_alternative(
                    LangType.FR,
                    alternative,
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
                        LangType.FR,
                        new_alternative,
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
                        LangType.FR,
                        alternative,
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
                        forms[form] = utils.add_article(
                            LangType.FR,
                            alternative.lemma,
                            utils.get_article_by_index(
                                self.static_rules,
                                LangType.FR,
                                form + "_articles",
                                article_index,
                            ),
                            separator,
                        )
                    alternative.lemma = forms["masculine"]
                    if forms["masculine"] != forms["feminine"]:
                        conjunction = utils.get_noun_conjunction(
                            self.static_rules, LangType.FR, not is_plural
                        )
                        alternative.lemma += conjunction + forms["feminine"]
                        alternative.male_form = forms["masculine"]
                        alternative.female_form = forms["feminine"]

                    alternative.gender_role = GenderedRolesFormatType.BINARY_GENDER
        elif article and result["gender_1"]:
            alternative = self.add_article_to_alternative(
                LangType.FR,
                alternative,
                utils.get_article_by_index(
                    self.static_rules,
                    LangType.FR,
                    result["gender_1"] + "_articles",
                    article_index,
                ),
                separator,
            )

        alternatives.append(alternative)

        return alternatives
