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
    ResultOut,
)
from app.helper import is_valid_text, check_word_case, is_addon_enabled, upperfirst
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

    def is_target_noun(self, token: Token):
        return (
            token.dep_.endswith("subj")
            or token.dep_.endswith("obj")
            or token.dep_.startswith("obl")
        )

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

    def is_entity_type_mismatch(self, rule: Rule, token: Token):
        if rule.entity_type == EntityType.DEFAULT:
            return False

        match rule.entity_type:
            case EntityType.NON_PERSON:
                if (
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
                if (
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

        if (
            len(rules) == 0
            and language.lang == LangType.FR
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
                        self.alternatives.get_adjective_alternatives_french(
                            male_form, female_form
                        ),
                    )
                    rule.false_positives = [
                        male_form + " et " + female_form,
                        female_form + " et " + male_form,
                    ]

                    rules.append(rule)
            elif (
                self.is_previous_token_article(token_index, tokens, language.lang)
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
                    self.alternatives.get_adjective_alternatives_french(
                        male_form, female_form
                    ),
                )

                rule.false_positives = [
                    male_form + " et " + female_form,
                    female_form + " et " + male_form,
                ]

                rules.append(rule)

        return rules

    async def check_not_for_people(
        self, rule: Rule, lang: LangType, token_index: int, tokens: Doc
    ):
        if rule.label_type != RuleLabelEnum.NOT_FOR_PEOPLE:
            return False

        chunks = self.fetch_sentence_noun_chunks(tokens[token_index].sent)
        token_chunk = self.find_token_chunk(chunks, token_index)
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

    async def fetch_rule_alternatives(
        self,
        rule: Rule,
        token_index: int,
        tokens: Doc,
        language: Language,
        client: Client,
        config: Config,
        is_singular: bool,
    ):
        word_types = rule.get_word_types()

        alternatives = await self.db.fetch_rule_alternatives(
            client,
            language,
            rule,
            is_singular,
            config.show_inspiration_alternatives,
        )

        if len(alternatives):
            form_token_i = token_index
            if rule.actual_word_types:
                word_type = rule.actual_word_types[0]
            else:
                expected_word_type = None
                if LangType.DE == language.lang and len(word_types) > 1:
                    form_token_offset = 0
                    for k in range(len(word_types)):
                        if word_types[k] == WordType.NOUN:
                            expected_word_type = WordType.NOUN
                            form_token_offset = k

                    form_token_i += form_token_offset

                if expected_word_type is None:
                    expected_word_type = word_types[0] if len(word_types) else None

                word_type = await self.model.fetch_word_type(
                    language.lang,
                    tokens[form_token_i],
                    expected_word_type,
                )

            target_form = await self.find_form(
                language.lang, word_type, form_token_i, tokens, is_singular
            )
        else:
            target_form = None

        return alternatives, word_types, target_form

    def is_french_adjecive_false_positive(
        self,
        token_index: int,
        tokens: Doc,
        rule: Rule,
        subcategory: str,
        alternatives: list[Alternative],
        text: str,
        skip_token: int,
    ):
        token = tokens[token_index]
        source_noun = None

        for a in token.ancestors:
            if self.is_target_noun(a):
                source_noun = a
                break

            for atok in a.children:
                if self.is_target_noun(atok):
                    source_noun = atok
                    break

        if source_noun is None:
            source_index = word_index = None
            for word in token.sent:
                if not self.is_target_noun(word):
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
            pass
        # Nous cherchons des stagiaires *curieux*
        elif (
            get_proficiency_level(subcategory) == "inclusive"
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
                    subcategory = "hidden_image"
                    alternatives = self.alternatives.get_adjective_alternatives_french(
                        male_form, female_form
                    )
                else:
                    if is_prev:
                        return True, None, None, None, None

                    if false_positive_check == token.text.lower():
                        subcategory = "hidden_image"
                        alternatives = [
                            Alternative(
                                male_form
                                if false_positive_check == female_form
                                else female_form
                            )
                        ]
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
        elif get_category_name(subcategory) == "hidden_image" and (
            source_noun is None
            or source_noun.text.lower()
            not in self.static_rules[LangType.FR]["gender_neutral_nouns"]
        ):
            return True, None, None, None, None

        return False, subcategory, alternatives, text, skip_token

    async def is_french_noun_false_positive(
        self,
        token_index: int,
        tokens: Doc,
        rule: Rule,
        config: Config,
        subcategory: str,
    ):
        token = tokens[token_index]
        category_name = get_category_name(subcategory)
        if (
            category_name == "gender_identity"
            or category_name in self.static_rules["male_specific_dimensions"]
        ):
            # false positive check
            gender = self.get_token_gender(token)
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
                return True, None

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
                        return True, None

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
                return True, None

            subcategory = is_sub_category_enabled(
                config.disabled_categories, subcategory
            )
            if not subcategory:
                return True, None

        return False, subcategory

    def fetch_french_article(
        self, rule: Rule, token_index: int, tokens: Doc, text: str, start: int
    ):
        article = article_index = None

        # when using pattern matching, the rule should explicitly state if the article should be included
        if not rule.pattern and self.is_previous_token_article(
            token_index, tokens, LangType.FR
        ):
            # Check if the article has not yet been included (f.e. via a pattern)
            article, text, start = self.get_previous_article(
                token_index, tokens, LangType.FR, text, start
            )

            article_index = list(
                self.static_rules[LangType.FR]["inclusive_articles"].keys()
            ).index(
                self.static_rules[LangType.FR]["articles_inclusive_map"][
                    article.lower()
                ]
            )

        return text, start, article, article_index

    async def generate_french_alternatives(
        self,
        token_index: int,
        tokens: Doc,
        rule: Rule,
        config: Config,
        subcategory: str,
        article: str,
        article_index: int,
        alternatives: list[Alternative],
        text: str,
        start: int,
    ):
        token = tokens[token_index]
        is_plural = self.model.is_token_plural(LangType.FR, token)

        separator, noun_separator, separate_gender_plural = (
            config.get_gender_separators_from_config(LangType.FR)
        )

        new_alternatives = []
        false_positives = []
        for alternative in alternatives:
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
                    subcategory,
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
                        new_alternatives = self.alternatives.nouns_with_articles(
                            config,
                            LangType.FR,
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

                    new_alternatives = self.alternatives.nouns_with_articles(
                        config,
                        LangType.FR,
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
                            subcategory,
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

                            collective_noun = self.alternatives.add_article(
                                LangType.FR,
                                collective_noun,
                                self.alternatives.get_article_by_index(
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
                    subcategory,
                    alternative.words[0],
                    token,
                    alternative,
                    alternative.words[1:],
                )

                alternative.gender_role = None
                if result is not None:
                    new_alternatives = self.alternatives.nouns_with_articles(
                        config,
                        LangType.FR,
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
                    gendered_article, _, _ = self.get_previous_article(
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
                            + " ou "
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
                                + " ou "
                                + male_article
                                + " "
                                + gender_neutral_noun
                            )
                        )

                new_alternatives.append(alternative)

        return new_alternatives, false_positives, text, start

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
    ) -> list:
        token = tokens[token_index]
        if not is_valid_text(language.lang, token.text):
            return token_index

        if token.lemma_ == "aber" and language.lang == LangType.DE:
            preceeding_text = full_text[max(0, token.idx - 5) : token.idx]
            if (
                re.search(r"^ *$", preceeding_text) is not None
                or re.search(r"[.!?:,]\s*$", preceeding_text, re.MULTILINE) is not None
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
            subcategory = is_sub_category_enabled(
                config.disabled_categories, rule.subcategories
            )
            if not subcategory:
                continue

            if self.is_entity_type_mismatch(rule, token):
                continue

            if rule.type == RuleType.SUBSTRING:
                text = token.text
                token_lower = text.lower()
                rule_lemma_lower = rule.lemma.lower()
                count = token_lower.count(rule_lemma_lower)
                if count == 0:
                    continue

                if rule.false_positives is not None:
                    standard_words = (
                        rule.false_positives
                        + self.static_rules[LangType.DE]["standard_words"].copy()
                    )

                for standard_word in standard_words:
                    if standard_word.lower() not in rule_lemma_lower:
                        token_lower = token_lower.replace(standard_word.lower(), "")

                count = token_lower.count(rule_lemma_lower)
                if count == 0:
                    continue

                skip_token = token_index + token._.token_index_offset
                start_token_index = token_index
            else:
                skip_token, start_token_index, text = await self.is_phrase_match(
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

            alternatives, word_types, target_form = await self.fetch_rule_alternatives(
                rule, token_index, tokens, language, client, config, is_singular
            )

            gendered_noun = False
            if LangType.DE == language.lang and len(alternatives):
                for alternative in alternatives:
                    if alternative.lemma is not None and "~" in alternative.lemma:
                        gendered_noun = True
                        break

                if gendered_noun:
                    (
                        text,
                        subcategory,
                        alternatives,
                    ) = await self.alternatives.gendered_nouns(
                        config,
                        language,
                        text,
                        tokens,
                        token_index,
                        alternatives,
                        subcategory,
                        is_singular,
                        rule,
                        full_text,
                        target_form,
                    )

                if text is None:
                    continue

            if text.endswith("-"):
                ending = "s-" if text.endswith("s-") else "-"

                for alternative in alternatives:
                    if (
                        alternative.lemma is not None
                        and alternative.lemma.endswith(ending) != ending
                    ):
                        alternative.lemma += ending

            start = tokens[start_token_index].idx

            if language.lang == LangType.FR:
                first_word_type = rule.get_first_word_type()
                match first_word_type:
                    case WordType.ADJECTIVE:
                        (
                            is_false_positive,
                            subcategory,
                            alternatives,
                            text,
                            skip_token,
                        ) = self.is_french_adjecive_false_positive(
                            token_index,
                            tokens,
                            rule,
                            subcategory,
                            alternatives,
                            text,
                            skip_token,
                        )

                        if is_false_positive:
                            continue

                    case WordType.NOUN:
                        is_false_positive, subcategory = (
                            await self.is_french_noun_false_positive(
                                token_index, tokens, rule, config, subcategory
                            )
                        )

                        if is_false_positive:
                            continue

                text, start, article, article_index = self.fetch_french_article(
                    rule, token_index, tokens, text, start
                )

                if len(alternatives):
                    alternatives, false_positives, text, start = (
                        await self.generate_french_alternatives(
                            token_index,
                            tokens,
                            rule,
                            config,
                            subcategory,
                            article,
                            article_index,
                            alternatives,
                            text,
                            start,
                        )
                    )

                    if len(alternatives) == 0:
                        # False positive due to a gender neutral noun without article while "advanced" is not enabled
                        continue

                    for alternative in alternatives:
                        if (
                            alternative.is_remove
                            or alternative.lemma.lower() == text.lower()
                        ):
                            continue

                        false_positives.append(alternative.lemma)

                    rule.false_positives = false_positives

                if await self.is_rule_false_positive(
                    full_text, token_index, tokens, rule
                ):
                    continue

            elif len(alternatives):
                # TODO make it possible to handle cases with multiple alternatives
                if len(alternatives) == 1 and alternatives[0].lemma == "they":
                    text, alternative = await self.pluralize_they(
                        text, tokens, token_index
                    )
                    alternatives = [Alternative(alternative)]
                elif not subcategory.startswith("abbreviation"):
                    text, start, alternatives = (
                        await self.alternatives.alternatives_declension(
                            language.lang,
                            text,
                            token_index,
                            tokens,
                            target_form,
                            rule,
                            alternatives,
                            is_singular,
                        )
                    )

                    if subcategory.startswith("filler"):
                        text, alternatives = self.detect_filler_words_at_sentence_start(
                            alternatives,
                            text,
                            full_text,
                            start + len(text),
                        )

                alternatives_with_article = await self.fetch_alternatives_with_article(
                    config,
                    language.lang,
                    tokens,
                    token_index,
                    is_singular,
                    word_types,
                    alternatives,
                )

                if alternatives_with_article is not None:
                    alternatives = alternatives_with_article
                    start = tokens[token_index - 1].idx
                    text = tokens[token_index - 1].text + " " + text

            label = token._.label if token._.label is not None else rule.label

            list_full.append(
                ResultOut.factory(
                    config,
                    client,
                    language,
                    text,
                    rule.text_id,
                    full_text,
                    offsets,
                    subcategory,
                    start,
                    None,
                    alternatives,
                    None,
                    rule.explanation,
                    rule.url,
                    rule.icon,
                    label,
                    rule.source,
                )
            )

            if token._.child_token:
                list_full.append(
                    ResultOut.factory(
                        config,
                        client,
                        language,
                        token._.child_token.text,
                        token.lemma_,
                        full_text,
                        offsets,
                        subcategory,
                        token._.child_token.idx,
                        None,
                        alternatives,
                        None,
                        rule.explanation,
                        rule.url,
                        rule.icon,
                        label,
                        rule.source,
                    )
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
        self, alternatives: list[Alternative], text: str, full_text: str, end: int
    ) -> tuple[str, list[Alternative]]:
        if alternatives == ["-"] and text[0].isupper():
            match = re.search(r"(\s*,\s*)(\S+)", full_text[end : end + 30])
            if isinstance(match, re.Match):
                text += match.group(0)
                alternatives = [upperfirst(match.group(2))]

        return text, alternatives

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
    def fetch_sentence_noun_chunks(self, sent: Span) -> list[Span]:
        chunks = []
        for chunk in sent.noun_chunks:
            chunks.append(chunk)

        return chunks

    def find_token_chunk(self, chunks: list[Span], token_index: int):
        for chunk in chunks:
            if chunk.start <= token_index < chunk.end:
                return chunk
            if chunk.start > token_index:
                break

        return None

    def fetch_article_for_flexion(
        self, flexion: str | None, gender: str, article_text: str
    ) -> tuple[str, str, str, str]:
        if flexion is None:
            return None, None, None, None

        form, _ = flexion.split()
        if (
            article_text not in self.static_rules[LangType.DE][gender + "_articles"]
            or form
            not in self.static_rules[LangType.DE][gender + "_articles"][article_text]
        ):
            return None, None, None, None

        article_forms = self.static_rules[LangType.DE][gender + "_articles"][
            article_text
        ][form]

        return article_forms[1], article_forms[2], article_forms[3], article_forms[5]

    async def fetch_alternatives_with_article(
        self,
        config: Config,
        lang: LangType,
        tokens: Doc,
        token_index: int,
        is_singular: bool,
        word_types: list,
        alternatives: list[Alternative],
    ) -> list[Alternative] | None:
        if alternatives is None:
            return []

        if (
            lang != LangType.DE
            or token_index == 0
            or len(word_types) != 1
            or word_types[0] != WordType.NOUN
        ):
            return None

        if not is_singular:
            return None

        token = tokens[token_index]
        text = token.text
        gender = await self.nouns.german_noun_gender_lookup(text)
        if gender is None:
            return None

        article_text = tokens[token_index - 1].text.lower()

        (
            match_masculine,
            match_feminine,
            match_neuter,
            match_alternative,
        ) = self.fetch_article_for_flexion(
            self.nouns.fetch_flexion(token), gender, article_text
        )

        if match_alternative is None:
            return None

        separator, _, _ = Config.get_gender_separators(config.german_gender_ending)

        alternatives_with_article = []
        for alternative in alternatives:
            if alternative.is_remove:
                alternatives_with_article.append(alternative)
                continue

            if alternative.is_gendered_noun:
                article_alternative = (
                    match_alternative if match_alternative else article_text
                )
                if alternative.is_collective_noun or separator in alternative.lemma:
                    # Mitarbeiter*in, Mitarbeitende
                    article_alternative = article_alternative.replace("~", separator)
                else:
                    # Mitarbeiterin/Mitarbeiter
                    article_alternative = article_alternative.replace("~", "/")
            else:
                alternative_tokens = self.model.fetch_tokens(
                    LangType.DE, alternative.words[-1]
                )
                if self.model.is_token_plural(LangType.DE, alternative_tokens[0]):
                    article_alternative = match_feminine
                else:
                    gender = await self.nouns.german_noun_gender_lookup(
                        alternative.words[-1]
                    )
                    if gender is None:
                        article_alternative = tokens[token_index - 1].text
                    else:
                        match gender:
                            case "masculine":
                                article_alternative = match_masculine
                            case "neuter":
                                article_alternative = match_neuter
                            case "feminine":
                                article_alternative = match_feminine
                            case _:
                                if alternative.lemma.endswith("in"):
                                    article_alternative = match_feminine

            if article_alternative != "":
                article_alternative += tokens[token_index - 1].whitespace_
                alternative.lemma = article_alternative + alternative.lemma

            alternatives_with_article.append(alternative)

        return alternatives_with_article

    def get_token_gender(self, token: Token):
        gender = token.morph.get("Gender")
        if len(gender):
            return gender[0]

        return None

    def is_gender_false_positive(self, token: Token) -> bool:
        gender = self.get_token_gender(token)
        if gender is None:
            return False

        lemma = token.lemma_.lower()
        male_form_found = True if gender == "Masc" else False
        female_form_found = True if gender == "Fem" else False

        doc = token.sent.doc
        for token in doc:
            if lemma != token.lemma_.lower():
                continue

            gender = self.get_token_gender(token)
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

    async def check_pattern(
        self,
        lang: LangType,
        tokens: Doc,
        pattern: list,
        i_pattern_start: int,
        offset: int,
    ) -> bool | int:
        count = 0
        for word_type in pattern:
            allow_skip = word_type.endswith("*")
            if i_pattern_start < 0:
                return False

            if i_pattern_start >= len(tokens):
                if allow_skip:
                    continue

                return False

            if allow_skip:
                word_type = word_type.removesuffix("*")
                while i_pattern_start >= 0 and await self.model.check_word_type(
                    lang, tokens[i_pattern_start], word_type, True, True
                ):
                    i_pattern_start -= 1
                    count += 1
                    if (
                        lang == LangType.FR
                        and i_pattern_start >= 0
                        and tokens[i_pattern_start + 1].lemma_ == "la"
                        and tokens[i_pattern_start].lemma_ in ["à", "de"]
                    ):
                        i_pattern_start -= 1
                        count += 1
            elif await self.model.check_word_type(
                lang, tokens[i_pattern_start], word_type, True
            ):
                if (
                    lang == LangType.FR
                    and i_pattern_start >= 1
                    and tokens[i_pattern_start].lemma_ == "la"
                    and tokens[i_pattern_start - 1].lemma_ in ["à", "de"]
                ):
                    i_pattern_start += 1
                    count += 1

                i_pattern_start += offset
                count += 1
            else:
                return False

        return count

    async def is_word_match(
        self,
        lang: LangType,
        token: Token,
        word: str,
        word_type: dict | None,
        suffix: str,
        lemma: str | None = None,
    ) -> bool:
        if word_type is None:
            word_type = {
                "word_type": "",
                "lemmatize": True,
                "lower_case": True,
            }

        lemma_ = token.lemma_ if lemma is None else lemma
        token_word = lemma_ if word_type["lemmatize"] else token.text

        # ignore differences between ’ and '
        token_word = token_word.replace("’", "'")
        word = word.replace("’", "'")

        if word_type["lower_case"]:
            token_word = token_word.lower()
            word = word.lower()

        if token_word != word and (
            not suffix or not token_word.lower().endswith(word.lower())
        ):
            if (
                lemma is None
                and word_type["lemmatize"]
                and lemma_ in self.db.male_to_female_normativ
            ):
                return await self.is_word_match(
                    lang,
                    token,
                    word,
                    word_type,
                    suffix,
                    self.db.male_to_female_normativ[lemma_],
                )
            return False

        return await self.model.check_word_type(
            lang, token, word_type["word_type"], True
        )

    async def is_phrase_match(
        self,
        lang: LangType,
        token_index: int,
        tokens: Doc,
        rule: Rule,
        false_positive_matcher: list | None = None,
    ) -> tuple[int | None, str | None]:
        suffix = rule.type == RuleType.SUFFIX

        word_count = len(rule.words)
        word_types_count = len(rule.word_types)
        if word_count > 1:
            suffix = False

        skip_token_index = token_index
        text = ""
        for word_index in range(word_count):
            if word_index > 0:
                text += word_token.whitespace_

            try:
                word_token = tokens[token_index + word_index]
            except IndexError:
                return None, None, None

            word_type = (
                rule.word_types[word_index] if word_index < word_types_count else None
            )

            if not await self.is_word_match(
                lang,
                word_token,
                rule.words[word_index],
                word_type,
                suffix,
            ):
                return None, None, None

            text += word_token.text

            skip_token_index += 1

        if false_positive_matcher is not None and self.model.is_false_positive_match(
            false_positive_matcher, token_index, tokens, rule.lemma
        ):
            return None, None, None

        start_token_index = token_index
        if rule.pattern is not None:
            pattern = rule.pattern.split("|")
            if pattern[0] == "*" or pattern[-1] == "*":
                self.logger.error(
                    "Rule pattern may not start or end with '*' but is '%s', rule id %i, idx: '%s'",
                    rule.pattern,
                    rule.id,
                    tokens[token_index].idx,
                )

                return None, None, None

            token_count = word_count
            prefix_tokens_match_count = 0
            lemma_position = pattern.index("l")

            if lemma_position > 0:
                prefix_pattern = pattern[0:lemma_position]
                prefix_pattern.reverse()
                tokens_match_count = await self.check_pattern(
                    lang, tokens, prefix_pattern, token_index - 1, -1
                )
                if tokens_match_count is False:
                    return None, None, None

                prefix_tokens_match_count += tokens_match_count

            suffix_pattern = pattern[lemma_position + 1 :]
            if len(suffix_pattern):
                tokens_match_count = await self.check_pattern(
                    lang, tokens, suffix_pattern, token_index + token_count, 1
                )
                if tokens_match_count is False:
                    return None, None, None

                token_count += tokens_match_count

            if rule.is_pattern_match:
                start_token_index -= prefix_tokens_match_count
                text = ""
                for k in range(prefix_tokens_match_count + token_count):
                    if k > 0:
                        text += tokens[start_token_index + k - 1].whitespace_

                    text += tokens[start_token_index + k].text

                skip_token_index = start_token_index + token_count + 1

        if (
            start_token_index + tokens[start_token_index]._.token_index_offset
            > skip_token_index
        ):
            skip_token_index = (
                start_token_index + tokens[start_token_index]._.token_index_offset
            )

        return skip_token_index, start_token_index, text

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
