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
from app.logger import Logger
from app.helper import is_valid_text, check_word_case, is_addon_enabled, upperfirst
from app.categories import is_sub_category_enabled, get_category_name
from app.model import Model
from app.db import Db
from app.nouns import Nouns
from app.verbs import Verbs
from app.adjectives import Adjectives
from app.alternatives import Alternatives
from app.settings import Settings

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
        rules: list | None = None,
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
            rules = await self.db.fetch_rules(
                language,
                token,
                token.text,
                token.lemma_,
                config.addons,
                suffix_check,
            )

        for rule in rules:
            subcategory = is_sub_category_enabled(
                config.disabled_categories, rule.subcategories
            )
            if not subcategory:
                continue

            if rule.entity_type != EntityType.DEFAULT:
                match rule.entity_type:
                    case EntityType.NON_PERSON:
                        if (
                            token.ent_type_
                            and token.ent_type_
                            in self.static_rules["named_entity_labels"][
                                EntityType.PERSON
                            ]
                        ):
                            continue
                    case EntityType.PERSON:
                        if (
                            token.ent_type_
                            not in self.static_rules["named_entity_labels"][
                                EntityType.PERSON
                            ]
                        ):
                            continue
                    case EntityType.NON_NAME:
                        if (
                            token.ent_type_
                            and token.ent_type_
                            in self.static_rules["named_entity_labels"][EntityType.NAME]
                        ):
                            continue
                    case EntityType.NAME:
                        if (
                            token.ent_type_
                            not in self.static_rules["named_entity_labels"][
                                EntityType.NAME
                            ]
                        ):
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
            else:
                skip_token, text = await self.is_phrase_match(
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

            if is_singular == True:
                if rule.pluralization == PluralizationType.PLURAL_ONLY:
                    continue
            elif (
                is_singular == False
                and rule.pluralization == PluralizationType.SINGULAR_ONLY
            ):
                continue

            if rule.label_type == RuleLabelEnum.NOT_FOR_PEOPLE:
                chunks = self.fetch_sentence_noun_chunks(tokens[token_index].sent)
                token_chunk = self.find_token_chunk(chunks, token_index)
                if token_chunk is None:
                    # No noun detected => assume false positive
                    if len(chunks) == 0:
                        continue

                    # If there is only one noun: ie. *You* are flexible / *Mitarbeiter* sind flexibel
                    token_chunk = chunks[0]

                    if len(chunks) > 1:
                        # Handle conjunctions
                        # Competition is our daily life *and* we love to be >challenged<.

                        sent_token_index = tokens[token_index].sent.start
                        while sent_token_index < tokens[token_index].sent.end:
                            if sent_token_index > token_index:
                                break

                            if self.model.token_is_conjunction(
                                tokens[sent_token_index]
                            ):
                                for chunk in chunks:
                                    if chunk.start < sent_token_index:
                                        token_chunk = chunk

                            sent_token_index += 1

                skip = await self.check_person_noun(
                    rule, language.lang, tokens, chunks, token_chunk
                )

                # TODO cache on the token
                if skip:
                    continue

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

            start = token.idx
            if language.lang == LangType.FR:
                word_types = rule.get_word_types()
                first_word_type = word_types[0] if len(word_types) else ""
                match first_word_type:
                    case WordType.ADJECTIVE:
                        source_noun = None

                        for a in token.ancestors:
                            if a.dep_ == "nsubj":
                                source_noun = a.text
                                break

                            for atok in a.children:
                                if atok.dep_ == "nsubj":
                                    source_noun = atok.text
                                    break

                        if source_noun is None:
                            source_index = word_index = None
                            for word in token.sent:
                                if word.dep_ != "nsubj":
                                    continue

                                if word.i < word.head.i:
                                    word_index = word.head.i
                                    source_index = word.i
                                elif word.i > word.head.i:
                                    word_index = word.i
                                    source_index = word.head.i

                                if word_index == token_index:
                                    source_noun = tokens[source_index].text
                                    break

                        if (
                            source_noun is None
                            or source_noun.lower()
                            not in self.static_rules[LangType.FR][
                                "gender_neutral_nouns"
                            ]
                        ):
                            continue
                    case WordType.NOUN:
                        category_name = get_category_name(subcategory)
                        if (
                            category_name == "gender_identity"
                            or category_name
                            in self.static_rules["male_specific_dimensions"]
                        ):
                            gender = token.morph.get("Gender")
                            if gender is None:
                                gender = "Fem" if token_index > 0 and tokens[token_index - 1].lower() in ["une", "la"] else "Masc"

                            subcategory_to_find = (
                                self.static_rules["male_specific_dimensions"]
                                if "Masc" in gender
                                else ["gender_identity"]
                            )
                            subcategory = None
                            for search_subcategory in rule.subcategories:
                                if (
                                    get_category_name(search_subcategory)
                                    in subcategory_to_find
                                ):
                                    subcategory = search_subcategory
                                    break

                            if subcategory is None:
                                continue

                            subcategory = is_sub_category_enabled(
                                config.disabled_categories, subcategory
                            )
                            if not subcategory:
                                continue

                new_alternatives = []
                for alternative in alternatives:
                    if alternative.is_gendered_noun:
                        male_form, female_form = alternative.lemma.split("~")
                        gendered_alternatives = (
                            await self.alternatives.noun_alternatives(
                                language.lang, "·", "·", male_form, female_form
                            )
                        )
                        for gendered_alternative in gendered_alternatives:
                            if (
                                config.gendered_roles_format
                                == GenderedRolesFormatType.BOTH
                                or config.gendered_roles_format == gendered_alternative
                            ):
                                new_alternative = deepcopy(alternative)
                                new_alternative.lemma = gendered_alternatives[
                                    gendered_alternative
                                ]
                                new_alternatives.append(new_alternative)
                    else:
                        new_alternatives.append(alternative)

                alternatives = new_alternatives
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
            lang == LangType.EN
            or token_index == 0
            or len(word_types) != 1
            or word_types[0] != WordType.NOUN
        ):
            return None

        if lang == LangType.FR:
            article_text = tokens[token_index - 1].text.lower()
            if article_text == "les":
                alternatives_with_article = []
                for alternative in alternatives:
                    if alternative.is_remove:
                        continue

                    article_alternative = ""
                    if " le " not in alternative.lemma:
                        article_alternative = (
                            "l'" if alternative.lemma.startswith("é") else "les"
                        )

                    if article_alternative != "":
                        if not article_alternative.endswith("'"):
                            article_alternative += tokens[token_index - 1].whitespace_
                        alternative.lemma = article_alternative + alternative.lemma

                    alternatives_with_article.append(alternative)

                return alternatives_with_article

            return None

        if lang == LangType.DE and not is_singular:
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

        separator, _ = Config.get_german_noun_separator(config.german_gender_ending)

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
        pattern: str,
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
            elif await self.model.check_word_type(
                lang, tokens[i_pattern_start], word_type, True
            ):
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
                return None, None

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
                return None, None

            text += word_token.text

            skip_token_index += 1

        if false_positive_matcher is not None and self.model.is_false_positive_match(
            false_positive_matcher, token_index, tokens, rule.lemma
        ):
            return None, None

        if rule.pattern is not None:
            pattern = rule.pattern.split("|")
            if pattern[0] == "*" or pattern[-1] == "*":
                self.logger.error(
                    "Rule pattern may not start or end with '*' but is '%s', rule id %i, idx: '%s'",
                    rule.pattern,
                    rule.id,
                    tokens[token_index].idx,
                )

                return None, None

            token_count = word_count
            prefix_tokens_match_count = 0
            lemma_position = pattern.index("l")

            if lemma_position > 0:
                prefix_pattern = pattern[0:lemma_position]
                prefix_pattern.reverse()
                tokens_match_count = await self.check_pattern(
                    lang, tokens, prefix_pattern, token_index - 1, -1
                )
                if not tokens_match_count:
                    return None, None

                prefix_tokens_match_count += tokens_match_count

            suffix_pattern = pattern[lemma_position + 1 :]
            if len(suffix_pattern):
                tokens_match_count = await self.check_pattern(
                    lang, tokens, suffix_pattern, token_index + token_count, 1
                )
                if not tokens_match_count:
                    return None, None

                token_count += tokens_match_count

            if rule.is_pattern_match:
                token_index -= prefix_tokens_match_count
                text = ""
                for k in range(prefix_tokens_match_count + token_count):
                    if k > 0:
                        text += tokens[token_index + k - 1].whitespace_

                    text += tokens[token_index + k].text

                skip_token_index = token_index + token_count + 1

        if token_index + tokens[token_index]._.token_index_offset > skip_token_index:
            skip_token_index = token_index + tokens[token_index]._.token_index_offset

        return skip_token_index, text

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
