from app.models import (
    Config,
    Client,
    LangType,
    Language,
    Rule,
    EntityType,
    RuleType,
    PluralizationType,
    WordType,
    RuleLabelEnum,
    Alternative,
    GenderedRolesFormatType,
    GermanGenderEndingType,
)
from app.helper import is_valid_text, is_addon_enabled, upperfirst
from app.categories import (
    is_sub_category_enabled,
    get_category_name,
    get_proficiency_level,
)
from app.model import Model
from app.db import Db
from app.nouns import Nouns
from app.verbs import Verbs
from app.adjectives import Adjectives
from app.alternatives import Alternatives
from app.settings import Settings
from pluralizefr import pluralize

import re
from copy import deepcopy
from spacy.tokens import Token, Doc, Span
from logging import Logger
from app.rule_engine.utils import append_result
from app.rule_engine.matchers.pattern import is_phrase_match
from app.alternatives_engine import inklusivum
from app.alternatives_engine import utils
from app.rule_engine import utils as rule_utils

# spaCy reports the case as a UD tag; the article table names them in German.
INKLUSIVUM_CASES = {
    "Nom": "nominativ",
    "Gen": "genitiv",
    "Dat": "dativ",
    "Acc": "akkusativ",
}


class RuleCheck:
    settings: Settings
    logger: Logger
    static_rules: dict
    model: Model
    db: Db
    nouns: Nouns
    verbs: Verbs
    adjectives: Adjectives
    alternatives: Alternatives

    def __init__(
        self,
        settings: Settings,
        logger: Logger,
        static_rules: dict,
        model: Model,
        db: Db,
        nouns: Nouns,
        verbs: Verbs,
        adjectives: Adjectives,
        alternatives: Alternatives,
    ):
        self.settings = settings
        self.logger = logger
        self.static_rules = static_rules
        self.model = model
        self.db = db
        self.nouns = nouns
        self.verbs = verbs
        self.adjectives = adjectives
        self.alternatives = alternatives

    def substring_standard_words(self, rule: Rule) -> list:
        standard_words = self.static_rules[LangType.DE]["standard_words"]
        if rule.false_positives is not None:
            standard_words = rule.false_positives + standard_words

        return standard_words

    salutations = {
        "herr",
        "herrn",
        "frau",
        "hr",
        "fr",
        "mr",
        "mrs",
        "ms",
        "miss",
        "dr",
        "monsieur",
        "madame",
        "mme",
    }

    def is_name_after_salutation(self, token: Token) -> bool:
        """A PROPN attached to a salutation reads as a person name even when
        the NER stays silent: the de 3.8.0 model no longer labels bare
        surnames like 'Herr Müller' PER (case:
        tests/test_general_cases/test_api_entity_de). A bare PROPN is not
        enough - standalone compounds like 'Bäcker-Confiseur-Konditor' are
        also tagged PROPN (case: tests/test_gender_ending/-dashed)."""
        if token.pos_ != "PROPN":
            return False

        if token.head.text.lower().rstrip(".") in self.salutations:
            return True

        return (
            token.i > 0
            and token.doc[token.i - 1].text.lower().rstrip(".") in self.salutations
        )

    def is_entity_type_mismatch(self, rule: Rule, token: Token):
        if rule.entity_type == EntityType.DEFAULT:
            return False

        match rule.entity_type:
            case EntityType.NON_PERSON:
                if self.is_name_after_salutation(token) or (
                    token.ent_type_
                    and token.ent_type_
                    in self.static_rules["named_entity_labels"][EntityType.PERSON]
                ):
                    return True
            case EntityType.PERSON:
                if (
                    token.ent_type_
                    not in self.static_rules["named_entity_labels"][EntityType.PERSON]
                ):
                    return True
            case EntityType.NON_NAME:
                if self.is_name_after_salutation(token) or (
                    token.ent_type_
                    and token.ent_type_
                    in self.static_rules["named_entity_labels"][EntityType.NAME]
                ):
                    return True
            case EntityType.NAME:
                if (
                    token.ent_type_
                    not in self.static_rules["named_entity_labels"][EntityType.NAME]
                ):
                    return True

        return False

    def inklusivum_article_for(self, article: str, case: str | None) -> str | None:
        """The Inklusivum form of a masculine article."""
        forms = self.static_rules[LangType.DE]["masculine_articles"].get(
            article.lower()
        )
        if not forms:
            return None

        entry = forms.get(case) if case else None
        if entry is None:
            if len(forms) != 1:
                return None
            entry = next(iter(forms.values()))

        return entry.inklusivum

    async def inklusivum_articles(
        self,
        config: Config,
        client: Client,
        language: Language,
        full_text: str,
        tokens: Doc,
        offsets: dict,
        list_full: list,
    ) -> None:
        """Offer the Inklusivum article for person words that take no ending.

        "Gast" carries no gender to remove, so no denomination rule matches it
        and only the article should change. Nothing else would report it.

        Runs once the other results are in, because whether to report an
        article depends on what else was found: a phrase rule that already
        covers "Jeder Lehrling" owns that article, and reporting it again says
        the same thing about part of the same words. That cannot be decided
        while the results are still being collected, since a rule anchored on
        the noun widens its span over the article afterwards.

        Every signal it needs has to be present. Where one is missing the token
        is passed over rather than guessed at: the noun is left untouched, so a
        wrong article is the whole of what the reader sees.
        """
        if (
            language.lang != LangType.DE
            or config.german_gender_ending != GermanGenderEndingType.INKLUSIVUM
        ):
            return

        subcategory = is_sub_category_enabled(
            config.disabled_categories, "hidden_image"
        )
        if not subcategory:
            return

        articles = self.static_rules[LangType.DE]["articles"]
        neutral = self.static_rules[LangType.DE]["inklusivum_neutral_nouns"]
        reported = [(result.start, result.end) for result in list_full]

        for token in tokens:
            if token.pos_ != "DET" or token.text.lower() not in articles:
                continue

            noun = token.head
            if noun.i == token.i or noun.pos_ not in ("NOUN", "PROPN"):
                continue

            if not inklusivum.is_already_neutral(noun.lemma_, neutral):
                continue

            # Plural articles are already neutral, so there is nothing to say.
            number = noun.morph.get("Number")
            if not number or "Plur" in number:
                continue

            forms = await self.nouns.german_noun_lookup(noun.lemma_)
            if not forms or forms.get("gender_1") != "masculine":
                continue

            end = token.idx + len(token.text)
            if any(start <= token.idx and end <= stop for start, stop in reported):
                continue

            case = INKLUSIVUM_CASES.get(next(iter(token.morph.get("Case")), None))
            replacement = self.inklusivum_article_for(token.text, case)
            if not replacement or replacement == token.text.lower():
                continue

            append_result(
                list_full,
                config=config,
                client=client,
                language=language,
                text=token.text,
                text_id=token.text.lower(),
                full_text=full_text,
                offsets=offsets,
                subcategory=subcategory,
                start=token.idx,
                alternatives=[
                    Alternative(
                        upperfirst(replacement)
                        if token.text[0].isupper()
                        else replacement
                    )
                ],
            )

    async def is_written_in_inklusivum(
        self, lang: LangType, config: Config, token: Token
    ) -> bool:
        """Whether the token already is the Inklusivum of a gendered pair.

        Shape alone cannot decide this, because an Inklusivum noun looks like
        any other noun ending in -e, and some of its forms collide with
        ordinary plurals ("Freunde"). So candidates are confirmed against the
        noun lexicon, and this only runs when the Inklusivum was asked for.
        """
        if (
            lang != LangType.DE
            or config.german_gender_ending != GermanGenderEndingType.INKLUSIVUM
        ):
            return False

        exceptions = self.static_rules[LangType.DE]["inklusivum_nouns"]

        for candidate in inklusivum.base_form_candidates(token.text):
            forms = await self.nouns.german_noun_lookup(candidate)
            if not forms:
                continue

            feminine = forms.get("female_form")
            if not feminine:
                continue

            if inklusivum.is_form_of(token.text, candidate, feminine, exceptions):
                return True

        return False

    async def fetch_rules(
        self,
        language: Language,
        token_index: int,
        tokens: Doc,
        config: Config,
        suffix_check: bool,
    ) -> list[Rule]:
        token = tokens[token_index]
        rules = await self.db.fetch_rules(
            language,
            token,
            token.text,
            token.lemma_,
            config.addons,
            suffix_check,
        )

        if rules and await self.is_written_in_inklusivum(language.lang, config, token):
            # Already gender neutral, so the gendered denomination rules would
            # only suggest rewriting it into the form it is already in.
            rules = [
                rule
                for rule in rules
                if not self.db.is_gendered_denom_rule(language.lang, rule.subcategories)
            ]

        if (
            language.lang == LangType.FR
            and len(rules) == 0
            and await self.model.check_word_type(
                language.lang, token, WordType.ADJECTIVE, True, True
            )
        ):
            if self.model.is_token_plural(LangType.FR, token):
                male_form = pluralize(token.lemma_)
                female_form = pluralize(
                    self.adjectives.get_feminine_form_french(token.lemma_)
                )

                if male_form != female_form:
                    rule = Rule(
                        "fr_adjective_rule",
                        LangType.FR,
                        token.lemma_,
                        [token.lemma_],
                        [{"word_type": "a", "lower_case": True, "lemmatize": True}],
                        ["hidden_image"],
                        utils.build_french_adjective_alternatives(
                            male_form, female_form
                        ),
                    )

                    rule.adapt_alternatives = True
                    rule.dynamic.false_positives = [
                        male_form
                        + self.static_rules[LangType.FR]["noun_conjunction"]["plural"]
                        + female_form,
                        female_form
                        + self.static_rules[LangType.FR]["noun_conjunction"]["plural"]
                        + male_form,
                    ]

                    rules.append(rule)
            elif (
                self.alternatives.is_previous_token_article(
                    token_index, tokens, language.lang
                )
                and (
                    token_index + 1 >= len(tokens)
                    or not await self.model.check_word_type(
                        language.lang,
                        tokens[token_index],
                        WordType.NOUN,
                        True,
                        True,
                    )
                )
                and not self.is_gender_false_positive(token)
            ):
                male_form = token.lemma_
                female_form = self.adjectives.get_feminine_form_french(token.lemma_)

                rule = Rule(
                    "fr_noun_adjective_rule",
                    LangType.FR,
                    token.lemma_,
                    [token.lemma_],
                    [{"word_type": "a", "lower_case": True, "lemmatize": True}],
                    ["hidden_image"],
                    utils.build_french_adjective_alternatives(male_form, female_form),
                )

                rule.adapt_alternatives = True
                rule.dynamic.false_positives = [
                    male_form
                    + self.static_rules[LangType.FR]["noun_conjunction"]["plural"]
                    + female_form,
                    female_form
                    + self.static_rules[LangType.FR]["noun_conjunction"]["plural"]
                    + male_form,
                ]

                rules.append(rule)

        return rules

    async def check_not_for_people(
        self, rule: Rule, lang: LangType, token_index: int, tokens: Doc
    ) -> bool:
        if rule.label_type != RuleLabelEnum.NOT_FOR_PEOPLE:
            return False

        chunks = rule_utils.fetch_sentence_noun_chunks(tokens[token_index].sent)
        token_chunk = rule_utils.find_token_chunk(chunks, token_index)
        if token_chunk is None:
            # No noun detected => assume false positive
            if len(chunks) == 0:
                return True

            # If there is only one noun: ie. *You* are flexible / *Mitarbeiter* sind flexibel
            token_chunk = chunks[0]

            if len(chunks) > 1:
                # Handle conjunctions
                # Competition is our daily life *and* we love to be >challenged<.

                sent_token_index = tokens[token_index].sent.start
                while sent_token_index < tokens[token_index].sent.end:
                    if sent_token_index > token_index:
                        break

                    if self.model.token_is_conjunction(tokens[sent_token_index]):
                        for chunk in chunks:
                            if chunk.start < sent_token_index:
                                token_chunk = chunk

                    sent_token_index += 1

        # TODO cache on the token
        return await self.check_person_noun(rule, lang, tokens, chunks, token_chunk)

    def is_french_adjective_false_positive(
        self,
        token_index: int,
        tokens: Doc,
        rule: Rule,
        text: str,
        skip_token: int,
    ):
        token = tokens[token_index]
        source_noun = None

        for a in token.ancestors:
            if rule_utils.is_target_noun(a):
                source_noun = a
                break

            for atok in a.children:
                if rule_utils.is_target_noun(atok):
                    source_noun = atok
                    break

        if source_noun is None:
            source_index = word_index = None
            for word in token.sent:
                if not rule_utils.is_target_noun(word):
                    continue

                if word.i < word.head.i:
                    word_index = word.head.i
                    source_index = word.i
                elif word.i > word.head.i:
                    word_index = word.i
                    source_index = word.head.i

                if word_index == token_index:
                    source_noun = tokens[source_index]
                    break

        if rule.id == "fr_noun_adjective_rule":
            return False, text, skip_token

        # Nous cherchons des stagiaires *curieux*
        if (
            get_proficiency_level(rule.dynamic.subcategory) == "inclusive"
            and source_noun is not None
            and self.model.is_token_plural(LangType.FR, source_noun)
            and source_noun.text.lower()
            in self.static_rules[LangType.FR]["gender_neutral_nouns"]
        ):
            male_form = pluralize(token.lemma_)
            female_form = pluralize(self.adjectives.get_feminine_form_french(male_form))

            # adjective is not gender neutral
            if male_form != female_form:
                false_positive_check = None
                is_prev = False
                if (
                    token_index - 1 > 0
                    and tokens[token_index - 1].lemma_ == "et"
                    and tokens[token_index - 2].text.lower() in [male_form, female_form]
                ):
                    false_positive_check = tokens[token_index - 2].text.lower()
                    is_prev = True
                elif (
                    token_index + 1 < len(tokens)
                    and tokens[token_index + 1].lemma_ == "et"
                    and tokens[token_index + 2].text.lower() in [male_form, female_form]
                ):
                    false_positive_check = tokens[token_index + 2].text.lower()

                if false_positive_check is None:
                    rule.dynamic.subcategory = "hidden_image"
                    rule.alternatives = utils.build_french_adjective_alternatives(
                        male_form, female_form
                    )
                    rule.adapt_alternatives = True
                else:
                    if is_prev:
                        return True, None, None

                    if false_positive_check == token.text.lower():
                        rule.dynamic.subcategory = "hidden_image"
                        rule.alternatives = [
                            Alternative(
                                male_form
                                if false_positive_check == female_form
                                else female_form
                            )
                        ]
                        rule.adapt_alternatives = True
                    else:
                        text += (
                            token.whitespace_
                            + tokens[token_index + 1].text
                            + tokens[token_index + 1].whitespace_
                            + tokens[token_index + 2].text
                        )
                        skip_token += 2

        # Nous cherchons des *stagiaires actifs*.
        # Les *volcans* sont *actifs*.
        elif get_category_name(rule.dynamic.subcategory) == "hidden_image" and (
            source_noun is None
            or source_noun.text.lower()
            not in self.static_rules[LangType.FR]["gender_neutral_nouns"]
        ):
            return True, None, None

        return False, text, skip_token

    async def is_french_noun_false_positive(
        self,
        token_index: int,
        tokens: Doc,
        rule: Rule,
        config: Config,
    ) -> bool:
        token = tokens[token_index]
        category_name = get_category_name(rule.dynamic.subcategory)
        if (
            category_name == "gender_identity"
            or category_name in self.static_rules["male_specific_dimensions"]
        ):
            # false positive check
            gender = rule_utils.get_token_gender(token)
            if gender is None:
                result = await self.db.fetch_declensions(
                    LangType.FR, WordType.NOUN, token.text, token
                )

                if result and (result["male_form"] or result["female_form"]):
                    gender = "Fem" if result["male_form"] else "Masc"
                elif token_index > 0:
                    gender = (
                        "Fem"
                        if tokens[token_index - 1].text.lower()
                        in self.static_rules[LangType.FR]["feminine_articles"]
                        else "Masc"
                    )
                else:
                    gender = "Masc"

            # false positive check
            if self.is_gender_false_positive(token):
                return True

            # TODO if BINARY_GENDER not enabled but inclusive is, then propose to switch the entire phrase to inclusive
            if (
                config.gendered_roles_format == GenderedRolesFormatType.BOTH
                or config.gendered_roles_format == GenderedRolesFormatType.BINARY_GENDER
            ):
                other_token = None
                # check false positive in front
                if (
                    token_index > 1
                    and tokens[token_index - 1].lemma_.lower()
                    in self.static_rules[LangType.FR]["noun_separator_options"]
                    and tokens[token_index - 2].lemma_.lower()
                    == tokens[token_index].lemma_.lower()
                ):
                    other_token = tokens[token_index - 2]
                elif (
                    token_index + 1 < len(tokens)
                    and tokens[token_index + 1].lemma_.lower()
                    in self.static_rules[LangType.FR]["noun_separator_options"]
                ):
                    # check false positive behind
                    if (
                        tokens[token_index + 2].lemma_.lower()
                        == tokens[token_index].lemma_.lower()
                    ):
                        other_token = tokens[token_index + 2]
                    # check false positive behind with article
                    elif (
                        token_index + 2 < len(tokens)
                        and tokens[token_index + 3].lemma_.lower()
                        == tokens[token_index].lemma_.lower()
                        and await self.model.check_word_type(
                            LangType.FR,
                            tokens[token_index + 2],
                            WordType.ARTICLE,
                        )
                    ):
                        other_token = tokens[token_index + 3]

                if other_token:
                    male_form, female_form = (
                        (
                            token.text.lower(),
                            other_token.text.lower(),
                        )
                        if gender == "Masc"
                        else (
                            other_token.text.lower(),
                            token.text.lower(),
                        )
                    )

                    if (
                        male_form != female_form
                        and female_form in self.db.french_feminine_nouns
                    ):
                        return True

            subcategory_to_find = (
                self.static_rules["male_specific_dimensions"]
                if "Masc" in gender
                else ["gender_identity"]
            )
            subcategory = None
            for search_subcategory in rule.subcategories:
                if get_category_name(search_subcategory) in subcategory_to_find:
                    subcategory = search_subcategory
                    break

            if subcategory is None:
                return True

            subcategory = is_sub_category_enabled(
                config.disabled_categories, subcategory
            )
            if not subcategory:
                return True
            rule.dynamic.subcategory = subcategory

        return False

    async def generate_alternatives(
        self,
        lang: LangType,
        token_index: int,
        tokens: Doc,
        rule: Rule,
        config: Config,
        is_singular: bool,
        text: str,
        start: int,
        full_text: str,
    ):
        match lang:
            case LangType.FR:
                text, start = await self.generate_french_alternatives(
                    token_index,
                    tokens,
                    rule,
                    config,
                    full_text,
                    text,
                    start,
                )
            case LangType.EN:
                text, start = await self.generate_english_alternatives(
                    token_index,
                    tokens,
                    rule,
                    config,
                    is_singular,
                    text,
                    start,
                )
            case LangType.DE:
                text, start = await self.generate_german_alternatives(
                    token_index,
                    tokens,
                    rule,
                    config,
                    is_singular,
                    text,
                    start,
                    full_text,
                )

        if rule.dynamic.subcategory.startswith("filler"):
            text = self.detect_filler_words_at_sentence_start(
                rule,
                text,
                full_text,
                start + len(text),
            )

        return text, start

    async def generate_german_alternatives(
        self,
        token_index: int,
        tokens: Doc,
        rule: Rule,
        config: Config,
        is_singular: bool,
        text: str,
        start: int,
        full_text: str,
    ) -> tuple[str, int]:
        token = tokens[token_index]
        gendered_noun = False
        for alternative in rule.alternatives:
            if alternative.lemma is not None and "~" in alternative.lemma:
                gendered_noun = True
                break

        target_form = await self.alternatives.fetch_target_form(
            rule,
            token_index,
            tokens,
            LangType.DE,
            is_singular,
        )

        if gendered_noun:
            prefix, additional_words = (
                await self.alternatives.german_gendered_noun_prefix(
                    rule, token_index, tokens, text, is_singular
                )
            )

            target_form = self.alternatives.german_target_form(
                target_form,
                is_singular,
            )
        else:
            prefix = ""
            additional_words = []

        if is_singular and rule.get_first_word_type() == WordType.NOUN:
            gender = await self.nouns.german_noun_gender_lookup(token.text)

            if gender:
                text_, start_, article, _ = self.alternatives.fetch_article(
                    LangType.DE,
                    token_index,
                    tokens,
                    text,
                    start,
                )

                rule.dynamic.article = (
                    self.alternatives.fetch_german_article_for_flexion(
                        self.nouns.fetch_german_flexion(token),
                        gender,
                        article.lower(),
                    )
                    if article
                    else None
                )

                if rule.dynamic.article:
                    text = text_
                    start = start_
        else:
            if tokens[token_index]._.start is not None:
                start = tokens[token_index]._.start
            if tokens[token_index]._.text is not None:
                text = tokens[token_index]._.text

        (
            text,
            start,
        ) = await self.alternatives.german_gendered_nouns(
            config,
            text,
            start,
            tokens,
            token_index,
            is_singular,
            rule,
            full_text,
            prefix,
            additional_words,
            target_form,
        )

        if not text or await self.is_rule_false_positive(
            full_text, token_index, tokens, rule
        ):
            return None, None

        if text.endswith("-"):
            ending = "s-" if text.endswith("s-") else "-"

            for alternative in rule.alternatives:
                if (
                    alternative.lemma is not None
                    and alternative.lemma.endswith(ending) != ending
                ):
                    alternative.lemma += ending

        return text, start

    async def generate_english_alternatives(
        self,
        token_index: int,
        tokens: Doc,
        rule: Rule,
        config: Config,
        is_singular: bool,
        text: str,
        start: int,
    ) -> tuple[str, int]:
        # TODO make it possible to handle cases with multiple alternatives
        if len(rule.alternatives) == 1 and rule.alternatives[0].lemma == "they":
            if not config.llm_alternatives:
                text, alternative = await self.pluralize_they(text, tokens, token_index)
                rule.alternatives = [Alternative(alternative)]
        else:
            target_form = await self.alternatives.fetch_target_form(
                rule,
                token_index,
                tokens,
                LangType.EN,
                is_singular,
            )

            text, start = await self.alternatives.alternatives_declension(
                LangType.EN,
                text,
                start,
                token_index,
                tokens,
                target_form,
                rule,
                is_singular,
            )

            if not config.llm_alternatives:
                text, start = self.alternatives.alternatives_a_english(
                    rule,
                    token_index,
                    tokens,
                    text,
                    start,
                )

        return text, start

    async def generate_french_alternatives(
        self,
        token_index: int,
        tokens: Doc,
        rule: Rule,
        config: Config,
        full_text: str,
        text: str,
        start: int,
    ) -> tuple[str, int, list[Alternative]]:
        text, start, article, article_index = self.alternatives.fetch_article(
            LangType.FR, token_index, tokens, text, start
        )

        token = tokens[token_index]
        is_plural = self.model.is_token_plural(LangType.FR, token)

        separator, noun_separator, separate_gender_plural = (
            config.get_gender_separators_from_config(LangType.FR)
        )

        new_alternatives = []
        false_positives = []
        for alternative in rule.alternatives:
            if alternative.is_remove:
                new_alternatives.append(alternative)
                continue

            result = None
            if alternative.is_gendered_noun:
                alternative.male_form, alternative.female_form = (
                    alternative.lemma.split("~")
                )

                result = await self.nouns.french_noun_lookup(
                    config.disabled_categories,
                    rule.dynamic.subcategory,
                    alternative.male_form,
                    token,
                    alternative,
                )

                # should only happen for non "official" female nouns when advanced is not enabled
                if result is not None and result["female_form"] is None:
                    alternative.is_gendered_noun = False
                    alternative.gender_role = None
                    if article:
                        alternative.lemma = alternative.male_form
                        new_alternatives = self.alternatives.french_nouns_with_articles(
                            config,
                            article,
                            article_index,
                            result,
                            is_plural,
                            alternative,
                            new_alternatives,
                            separator,
                        )

                    continue

            if alternative.is_gendered_noun:
                collective_nouns = []
                if result is not None:
                    if result["collective_noun"] is not None:
                        collective_nouns.append(result["collective_noun"])
                    if result["collective_noun_2"] is not None:
                        collective_nouns.append(result["collective_noun_2"])

                if is_plural:
                    alternative.male_form = (
                        pluralize(alternative.male_form)
                        if result is None or result["plural"] is None
                        else result["plural"]
                    )
                    alternative.female_form = pluralize(alternative.female_form)

                (
                    alternative.male_form,
                    alternative.female_form,
                    gendered_alternatives,
                ) = await self.alternatives.noun_alternatives(
                    LangType.FR,
                    separator,
                    noun_separator,
                    separate_gender_plural,
                    alternative.male_form,
                    alternative.female_form,
                    article,
                )

                for gendered_alternative in gendered_alternatives:
                    if (
                        config.gendered_roles_format == GenderedRolesFormatType.BOTH
                        or config.gendered_roles_format == gendered_alternative
                    ):
                        new_alternative = deepcopy(alternative)
                        new_alternative.lemma = gendered_alternatives[
                            gendered_alternative
                        ]
                        new_alternative.gender_role = gendered_alternative
                        new_alternatives.append(new_alternative)

                # add gender neutral option on top of the male/female variation
                if self.nouns.is_gender_neutral(result) and (
                    not is_plural or alternative.male_form != token.text.lower()
                ):
                    alternative.lemma = alternative.male_form
                    alternative.gender_role = None

                    new_alternatives = self.alternatives.french_nouns_with_articles(
                        config,
                        article,
                        article_index,
                        result,
                        is_plural,
                        alternative,
                        new_alternatives,
                        separator,
                    )

                for collective_noun in collective_nouns:
                    new_alternative = deepcopy(alternative)
                    new_alternative.is_gendered_noun = False
                    new_alternative.male_form = None
                    new_alternative.female_form = None
                    new_alternative.gender_role = None
                    new_alternative.is_collective_noun = True

                    if article:
                        result = await self.nouns.french_noun_lookup(
                            config.disabled_categories,
                            rule.dynamic.subcategory,
                            collective_noun,
                            token,
                            new_alternative,
                        )
                        if result is not None:
                            articles_list = (
                                "masculine_articles"
                                if result["gender_1"] == "masculine"
                                else "feminine_articles"
                            )

                            collective_article_index = (
                                0 if article.lower() == "les" else article_index
                            )

                            collective_noun = utils.add_article(
                                LangType.FR,
                                collective_noun,
                                utils.get_article_by_index(
                                    self.static_rules,
                                    LangType.FR,
                                    articles_list,
                                    collective_article_index,
                                ),
                                separator,
                            )
                    new_alternative.lemma = collective_noun
                    new_alternatives.append(new_alternative)
            elif article:
                result = await self.nouns.french_noun_lookup(
                    config.disabled_categories,
                    rule.dynamic.subcategory,
                    alternative.words[0],
                    token,
                    alternative,
                    alternative.words[1:],
                )

                alternative.gender_role = None
                if result is not None:
                    new_alternatives = self.alternatives.french_nouns_with_articles(
                        config,
                        article,
                        article_index,
                        result,
                        is_plural,
                        alternative,
                        new_alternatives,
                        separator,
                    )
                else:
                    new_alternatives.append(alternative)
            else:
                if (
                    alternative.lemma == token.lemma_
                    and rule.pattern is not None
                    and rule.pattern.startswith("article|l")
                    and not is_plural
                ):
                    gendered_article, _, _ = self.alternatives.get_previous_article(
                        token_index, tokens, LangType.FR
                    )
                    gendered_article = gendered_article.lower()

                    gender_neutral_noun = alternative.lemma
                    if Config.gendered_roles_format_inclusive(
                        config.gendered_roles_format
                    ):
                        alternative.lemma = (
                            self.static_rules[LangType.FR]["articles_inclusive_map"][
                                gendered_article
                            ]
                            + " "
                            + gender_neutral_noun
                        )

                        if config.gendered_roles_format == GenderedRolesFormatType.BOTH:
                            new_alternative = deepcopy(alternative)
                            new_alternatives.append(new_alternative)
                            new_alternative.gender_role = (
                                GenderedRolesFormatType.INCLUSIVE_GENDER
                            )

                    if Config.gendered_roles_format_binary(
                        config.gendered_roles_format
                    ):
                        gendered_article_lower = gendered_article.lower()
                        if (
                            gendered_article
                            in self.static_rules[LangType.FR]["masculine_articles"]
                        ):
                            male_article = gendered_article
                            female_article = self.static_rules[LangType.FR][
                                "articles_map"
                            ][gendered_article_lower]
                        else:
                            male_article = self.static_rules[LangType.FR][
                                "articles_map"
                            ][gendered_article_lower]
                            female_article = gendered_article

                        alternative.lemma = (
                            male_article
                            + " "
                            + gender_neutral_noun
                            + utils.get_noun_conjunction(
                                self.static_rules, LangType.FR, True
                            )
                            + female_article
                            + " "
                            + gender_neutral_noun
                        )
                        alternative.gender_role = GenderedRolesFormatType.BINARY_GENDER

                        false_positives.append(
                            (
                                female_article
                                + " "
                                + gender_neutral_noun
                                + utils.get_noun_conjunction(
                                    self.static_rules, LangType.FR, True
                                )
                                + male_article
                                + " "
                                + gender_neutral_noun
                            )
                        )

                new_alternatives.append(alternative)

        for alternative in rule.alternatives:
            if alternative.is_remove or alternative.lemma.lower() == text.lower():
                continue

            false_positives.append(alternative.lemma)

        if self.model.is_false_positive(
            full_text, token_index, tokens, false_positives
        ):
            return None, None

        rule.alternatives = new_alternatives

        return text, start

    async def handle(
        self,
        config: Config,
        client: Client,
        language: Language,
        full_text: str,
        token_index: int,
        tokens: Doc,
        offsets: dict,
        list_full: list,
        rules: list[Rule] | None = None,
        false_positive_matcher: list | None = None,
        suffix_check: bool = False,
    ) -> int:
        token = tokens[token_index]
        if not is_valid_text(language.lang, token.text):
            return token_index

        if token.lemma_ == "aber" and language.lang == LangType.DE:
            # Bounded to the 5 characters sliced above; see Result.isUpper.
            preceding_text = full_text[max(0, token.idx - 5) : token.idx]
            if (
                re.search(r"^ {0,5}$", preceding_text) is not None
                or re.search(r"[.!?:,]\s{0,5}$", preceding_text, re.MULTILINE)
                is not None
            ):
                return token_index

        if rules is None:
            rules = await self.fetch_rules(
                language,
                token_index,
                tokens,
                config,
                suffix_check,
            )

        for rule in rules:
            rule.reset()
            subcategory = is_sub_category_enabled(
                config.disabled_categories, rule.subcategories
            )
            if not subcategory:
                continue
            rule.dynamic.subcategory = subcategory

            if self.is_entity_type_mismatch(rule, token):
                continue

            if rule.type == RuleType.SUBSTRING:
                text = token.text
                token_lower = text.lower()
                rule_lemma_lower = rule.lemma.lower()
                count = token_lower.count(rule_lemma_lower)
                if count == 0:
                    continue

                for standard_word in self.substring_standard_words(rule):
                    if standard_word.lower() not in rule_lemma_lower:
                        token_lower = token_lower.replace(standard_word.lower(), "")

                count = token_lower.count(rule_lemma_lower)
                if count == 0:
                    continue

                skip_token = token_index + token._.token_index_offset
                start_token_index = token_index
            else:
                skip_token, start_token_index, text = await is_phrase_match(
                    self.model,
                    self.db,
                    self.logger,
                    language.lang,
                    token_index,
                    tokens,
                    rule,
                    false_positive_matcher,
                )

                if self.is_german_pronoun_check_required(language.lang, token):
                    subcategory = self.german_pronoun_check(config, rule, token)
                    if not subcategory:
                        continue
                    rule.dynamic.subcategory = subcategory

                if not text or await self.is_rule_false_positive(
                    full_text, token_index, tokens, rule
                ):
                    continue

            is_singular = None
            for k in range(len(rule.words)):
                is_singular = self.model.is_token_singular(
                    language.lang, tokens[token_index + k]
                )
                if is_singular is None:
                    continue

                break

            match rule.pluralization:
                case PluralizationType.PLURAL_ONLY:
                    if is_singular == True:
                        continue
                case PluralizationType.SINGULAR_ONLY:
                    if is_singular == False:
                        continue

            if await self.check_not_for_people(
                rule, language.lang, token_index, tokens
            ):
                continue

            rule.alternatives = await self.db.fetch_rule_alternatives(
                client,
                language,
                rule,
                is_singular,
                config.show_inspiration_alternatives,
            )

            start = tokens[start_token_index].idx

            # Check for false positives, find correct subcategory
            match language.lang:
                case LangType.FR:
                    match rule.get_first_word_type():
                        case WordType.ADJECTIVE:
                            (
                                is_false_positive,
                                text,
                                skip_token,
                            ) = self.is_french_adjective_false_positive(
                                token_index,
                                tokens,
                                rule,
                                text,
                                skip_token,
                            )

                            if is_false_positive:
                                continue

                        case WordType.NOUN:
                            is_false_positive = (
                                await self.is_french_noun_false_positive(
                                    token_index, tokens, rule, config
                                )
                            )

                            if is_false_positive:
                                continue

            # Adapt alternatives if necessary
            if rule.adapt_alternatives:
                text, start = await self.generate_alternatives(
                    language.lang,
                    token_index,
                    tokens,
                    rule,
                    config,
                    is_singular,
                    text,
                    start,
                    full_text,
                )

                if text is None:
                    continue

            label = token._.label if token._.label is not None else rule.label

            append_result(
                list_full,
                config=config,
                client=client,
                language=language,
                text=text,
                text_id=rule.text_id,
                full_text=full_text,
                offsets=offsets,
                subcategory=rule.dynamic.subcategory,
                start=start,
                alternatives=rule.alternatives,
                label=None,
                explanation=rule.explanation,
                url=rule.url,
                icon=rule.icon,
                explanation_context=label,
                source=rule.source,
            )

            if token._.child_token:
                append_result(
                    list_full,
                    config=config,
                    client=client,
                    language=language,
                    text=token._.child_token.text,
                    text_id=token.lemma_,
                    full_text=full_text,
                    offsets=offsets,
                    subcategory=rule.dynamic.subcategory,
                    start=token._.child_token.idx,
                    alternatives=rule.alternatives,
                    label=None,
                    explanation=rule.explanation,
                    url=rule.url,
                    icon=rule.icon,
                    explanation_context=label,
                    source=rule.source,
                )

            return skip_token

        return token_index

    async def pluralize_they(
        self, text: str, tokens: Doc, token_index: int
    ) -> tuple[str, str]:
        token = tokens[token_index]
        alternative = "they"

        next_i = token_index + 1
        if len(tokens) <= next_i:
            return text, alternative

        verb_map = {
            "is": "are",
            "has": "have",
        }

        if tokens[next_i].text in verb_map:
            text += token.whitespace_ + tokens[next_i].text
            alternative += token.whitespace_ + verb_map[tokens[next_i].text]
        else:
            # she/he builds, cleans and refurbishes houses => they build, clean and refurbish houses
            prev_token = token
            while (
                len(tokens) > next_i + 1
                and self.model.token_is_conjunction(tokens[next_i])
                and tokens[next_i + 1].text[-1] == "s"
            ) or (
                next_i == token_index + 1
                and tokens[next_i].text[-1] == "s"
                and WordType.VERB
                == await self.model.fetch_word_type(LangType.EN, tokens[next_i])
            ):
                if self.model.token_is_conjunction(tokens[next_i]):
                    text += prev_token.whitespace_ + tokens[next_i].text
                    alternative += prev_token.whitespace_ + tokens[next_i].text
                    prev_token = tokens[next_i]
                    next_i += 1
                    if len(tokens) <= next_i:
                        break

                text += prev_token.whitespace_ + tokens[next_i].text
                ending_length = -2 if tokens[next_i].text.endswith("hes") else -1
                alternative += (
                    prev_token.whitespace_ + tokens[next_i].text[0:ending_length]
                )

                prev_token = tokens[next_i]
                next_i += 1
                if len(tokens) <= next_i:
                    break

        return text, alternative

    def detect_filler_words_at_sentence_start(
        self, rule: Rule, text: str, full_text: str, end: int
    ) -> tuple[str, list[Alternative]]:
        if (
            len(rule.alternatives)
            and rule.alternatives[0].is_remove
            and text[0].isupper()
        ):
            match = re.search(r"(\s*,\s*)(\S+)", full_text[end : end + 30])
            if isinstance(match, re.Match):
                text += match.group(0)
                rule.alternatives = [Alternative(upperfirst(match.group(2)))]

        return text

    def is_german_pronoun_check_required(self, lang: LangType, token: Token):
        return (
            lang == LangType.DE
            and token.text.lower()
            in self.static_rules[LangType.DE]["formal_shallow_signal_words"]
        )

    def german_pronoun_check(self, config: Config, rule: Rule, token: Token):
        is_formal = self.is_formal_check(config, token)
        if is_formal is None:
            return False

        for subcategory in rule.subcategories:
            if not is_sub_category_enabled(config.disabled_categories, [subcategory]):
                continue

            if is_formal:
                if subcategory.startswith("formality"):
                    rule.text_id = rule.text_id.capitalize()
                    return subcategory
            elif subcategory.startswith("binary_pronouns"):
                return subcategory

        return None

    def is_formal_check(self, config: Config, token: Token):
        if not token.text[0].isupper():
            # "Er und sie"
            # "Sie, gehen sie nach Hause"
            #             ^^^
            # "Sagen Sie ihnen, dass sie nach Hause gehen sollen"
            #            ^^^
            # "Sagen Sie ihnen, dass sie nach Hause gehen sollen"
            #                        ^^^
            return False

        # "Sie, gehen sie nach Hause"
        #  ^^^
        if not token.is_sent_start or (
            len(token.sent) > 1 and token.sent[1].text == ","
        ):
            return True

        if self.model.is_token_singular(LangType.DE, token) != False:
            # "Sie geht nach Hause"
            return False

        if (
            is_addon_enabled("hr", config.addons)
            and len(token.sent) > 1
            and token.sent[1].lemma_ in self.static_rules[LangType.DE]["hilf_verben"]
        ):
            # "Sie haben einen Master in .."
            # "Sie sind Student*in .."
            # "Sie sind zu schnell"
            return True

        # Check for the presence of informal pronouns
        for sent_token in token.sent:
            # If we encounter a formal signal words
            if (
                sent_token.lemma_
                in self.static_rules[LangType.DE]["formal_signal_words"]["lemma"]
                or sent_token.text
                in self.static_rules[LangType.DE]["formal_signal_words"]["text"]
            ):
                # "Gehen Sie nach Hause"
                # "Sagen Sie ihnen, dass sie nach Hause gehen sollen"
                #        ^^^
                return True

        # "Sie sagen ihnen, dass sie nach Hause gehen sollen"
        #  ^^^
        # "Sie sind zu schnell"
        return None

    async def check_person_noun(
        self,
        rule: Rule,
        lang: LangType,
        tokens: Doc,
        chunks: list[str],
        token_chunk: Span,
    ):
        skip = True
        noun_count = 0
        chunk_token_index = token_chunk.end
        while chunk_token_index >= token_chunk.start:
            chunk_token_index -= 1

            chunk_token = tokens[chunk_token_index]
            chunk_word_type = await self.model.fetch_word_type(
                lang,
                chunk_token,
            )

            # ignore noun's that match the rule (ie. "The project has become a *vegetable*, showing no signs of progress.")
            if chunk_word_type == WordType.NOUN and (
                tokens[chunk_token_index].lemma_ == rule.lemma
                or tokens[chunk_token_index].text == rule.lemma
            ):
                continue

            chunk_token_lemma_lower = chunk_token.lemma_.lower()
            if (
                chunk_word_type == WordType.NOUN
                and chunk_token_lemma_lower in self.db.misc_words[lang]
            ):
                continue

            if chunk_word_type == WordType.NOUN or chunk_word_type == WordType.PRONOUN:
                noun_count += 1
                skip = (
                    chunk_word_type != WordType.PRONOUN
                    and chunk_token_lemma_lower not in self.db.person_words[lang]
                )
                break

        # *He* is *a vegetable*
        if noun_count == 0 and token_chunk != chunks[0]:
            return await self.check_person_noun(rule, lang, tokens, chunks, chunks[0])

        return skip

    # TODO cache on the sentence?

    def is_gender_false_positive(self, token: Token) -> bool:
        gender = rule_utils.get_token_gender(token)
        if gender is None:
            return False

        lemma = token.lemma_.lower()
        male_form_found = True if gender == "Masc" else False
        female_form_found = True if gender == "Fem" else False

        for other in token.doc:
            if lemma != other.lemma_.lower():
                continue

            gender = rule_utils.get_token_gender(other)
            if not male_form_found and gender == "Masc":
                male_form_found = True
            elif not female_form_found and gender == "Fem":
                female_form_found = True

            if male_form_found and female_form_found:
                break

        return male_form_found and female_form_found

    async def is_rule_false_positive(
        self, full_text: str, token_index: int, tokens: Doc, rule: Rule
    ) -> bool:
        false_positives = await self.db.fetch_false_positives(rule)
        result = self.model.is_false_positive(
            full_text, token_index, tokens, false_positives
        )
        if result is False and rule.case_sensitive_false_positives is not None:
            result = self.model.is_false_positive(
                full_text,
                token_index,
                tokens,
                rule.case_sensitive_false_positives,
                None,
                None,
                True,
            )

        return result
