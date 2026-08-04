"""
Rule Processing Functions
Core functions for processing Witty language rules.
"""

import re
from inspect import currentframe

from spacy.tokens import Doc

from app.context import AppContext
from app.models import (
    Alternative,
    Client,
    Config,
    GermanGenderEndingType,
    Language,
    LangType,
    ResultOut,
    Rule,
)
from app.categories import is_sub_category_enabled
from app.helper import is_valid_text
from app.text_utils import german_lemmatization


def check_continue(
    list_full: list,
    token_index: int,
    new_token_index: int,
    tokens: Doc,
    func_name: str,
    context: AppContext,
) -> bool:
    if new_token_index == token_index:
        return False

    if new_token_index < token_index:
        cf = currentframe()

        text_id = list_full[-1].text_id if len(list_full) else ""

        context.logger.error(
            "Incorrect new_token_index on line %i using '%s': expected %i < %i for '%s' versus '%s' for text_id '%s'",
            cf.f_back.f_lineno,
            func_name,
            token_index,
            new_token_index,
            tokens[token_index].text,
            tokens[new_token_index].text,
            text_id,
        )

        return False

    return True


def is_bullet_point(line: str) -> bool:
    line = line.strip()
    if not line:
        return False

    # Check for bullet characters
    bullet_chars = {"-", "*", "•", "‣", "⁃", "⁌", "⁍", "◘", "◦", "⦾", "⦿"}
    if line[0] in bullet_chars:
        return True

    # Check for numbered list (e.g., "1.", "2)", "3:")
    return bool(re.match(r"^\d+[).:]", line))


async def german_gender_endings(
    config: Config,
    client: Client,
    tokens: Doc,
    offsets: dict,
    language: Language,
    text: str,
    token_index: int,
    list_full: list,
    context: AppContext,
) -> int:
    # shallow check to see if any of the delimiters is even contained
    if not re.search("[/):_*I]", text):
        return token_index

    # The Inklusivum is a declension system rather than an infix separator, so
    # the separator based rules below cannot express it. Until the paradigm is
    # implemented these paths are skipped rather than splicing "d" into words.
    is_inklusivum = config.german_gender_ending == GermanGenderEndingType.INKLUSIVUM

    subcategory = "d_and_i"
    if not is_inklusivum and is_sub_category_enabled(
        config.disabled_categories, subcategory
    ):
        word_types = (
            (-1, 1, config.german_gender_ending[0])
            if config.german_gender_ending.startswith("/")
            else (None, None, config.german_gender_ending[0])
        )

        endings = [
            Rule(
                config.german_gender_ending + "",
                LangType.DE,
                config._gendereddenom_ending[config.german_gender_ending],
                None,
                config._gendereddenom_ending_word_type[config.german_gender_ending],
                subcategory,
            ),
        ]

        if config.german_gender_ending in config._gendereddenom_ending_article:
            endings.append(
                Rule(
                    config.german_gender_ending + " article",
                    LangType.DE,
                    config._gendereddenom_ending_article[config.german_gender_ending],
                    None,
                    word_types,
                    subcategory,
                )
            )

        new_token_index = await context.regex_check.handle(
            config,
            client,
            language,
            text,
            token_index,
            tokens,
            offsets,
            list_full,
            endings,
        )

        if check_continue(
            list_full, token_index, new_token_index, tokens, "regex_match", context
        ):
            return new_token_index

    subcategory = "gendered_denominations_ending_advanced"
    if (
        not is_inklusivum
        and is_sub_category_enabled(config.disabled_categories, subcategory)
        and Config.gendered_roles_format_inclusive(config.gendered_roles_format)
    ):
        endings = []
        for key, regexp in config._gendereddenom_ending.items():
            if config.german_gender_ending == key:
                continue

            ending = Rule(
                key + "",
                LangType.DE,
                regexp,
                None,
                config._gendereddenom_ending_word_type[key],
                subcategory,
                [Alternative(config.german_gender_ending)],
            )

            endings.append(ending)

            if (
                # GermanGenderEndingType.SLASH_DASH is redundant to GermanGenderEndingType.SLASH
                key != GermanGenderEndingType.SLASH_DASH
                # only check if relevant regexp is defined
                and key in config._gendereddenom_ending_article
            ):
                word_types = (
                    (-1, 2, key[0]) if key.startswith("/") else (None, None, key[0])
                )

                ending = Rule(
                    key + "article",
                    LangType.DE,
                    config._gendereddenom_ending_article[key],
                    None,
                    word_types,
                    subcategory,
                )

                endings.append(ending)

        new_token_index = await context.regex_check.handle(
            config,
            client,
            language,
            text,
            token_index,
            tokens,
            offsets,
            list_full,
            endings,
        )

        if check_continue(
            list_full, token_index, new_token_index, tokens, "regex_match", context
        ):
            return new_token_index

    return token_index


async def witty_rules(
    config: Config,
    term_replacements: list[Rule],
    client: Client,
    tokens: Doc,
    offsets: dict,
    language: Language,
    text: str,
    context: AppContext,
) -> list:
    false_positive_matcher = context.model.fetch_false_positive_matchers(
        language.lang, tokens
    )

    list_full = []

    new_token_index = 0
    token_count = len(tokens)
    while new_token_index < token_count:
        token_index = new_token_index

        token = tokens[token_index]
        if token._.connected_token is not None:
            new_token_index += 1
            continue

        if language.lang == LangType.DE:
            token.lemma_ = await german_lemmatization(tokens, token_index, context)

        if len(term_replacements):
            new_token_index = await context.rule_check.handle(
                config,
                client,
                language,
                text,
                token_index,
                tokens,
                offsets,
                list_full,
                term_replacements,
            )

            if check_continue(
                list_full, token_index, new_token_index, tokens, "rule_check", context
            ):
                continue

        if is_sub_category_enabled(
            config.disabled_categories, "gender_specific_abbreviation"
        ):
            new_token_index = await context.regex_check.handle(
                config,
                client,
                language,
                text,
                token_index,
                tokens,
                offsets,
                list_full,
                context.static_rules["m_f_regexes"],
            )

            if check_continue(
                list_full, token_index, new_token_index, tokens, "regex_match", context
            ):
                continue

        new_token_index = context.emoji_check.handle(
            config,
            client,
            language,
            text,
            token_index,
            tokens,
            offsets,
            list_full,
        )

        if check_continue(
            list_full,
            token_index,
            new_token_index,
            tokens,
            "detect_non_inclusive_emoji",
            context,
        ):
            continue

        if token.text.startswith("#"):
            new_token_index = await context.regex_check.handle(
                config,
                client,
                language,
                text,
                token_index,
                tokens,
                offsets,
                list_full,
                context.static_rules[language.lang]["hashtags"],
            )

            if check_continue(
                list_full, token_index, new_token_index, tokens, "regex_match", context
            ):
                continue

        valid_text = is_valid_text(language.lang, token.text)
        if valid_text:
            new_token_index = await context.rule_check.handle(
                config,
                client,
                language,
                text,
                token_index,
                tokens,
                offsets,
                list_full,
                None,
                false_positive_matcher,
            )

            if check_continue(
                list_full, token_index, new_token_index, tokens, "rule_check", context
            ):
                continue

            if language.lang == LangType.DE:
                new_token_index = await context.rule_check.handle(
                    config,
                    client,
                    language,
                    text,
                    token_index,
                    tokens,
                    offsets,
                    list_full,
                    None,
                    false_positive_matcher,
                    True,
                )

                if check_continue(
                    list_full,
                    token_index,
                    new_token_index,
                    tokens,
                    "rule_check",
                    context,
                ):
                    continue

        if language.lang == LangType.DE:
            new_token_index = await german_gender_endings(
                config,
                client,
                tokens,
                offsets,
                language,
                text,
                token_index,
                list_full,
                context,
            )

            if check_continue(
                list_full, token_index, new_token_index, tokens, "rule_check", context
            ):
                continue

        if len(token.text) > 18 and is_sub_category_enabled(
            config.disabled_categories, "plain_language"
        ):
            subwords = (
                token.text.replace("/", "-")
                .replace("@", "-")
                .replace(":", "-")
                .replace(".", "-")
                .replace("_", "-")
                .split("-")
            )
            highlight = len(subwords) == 1
            for subword in subwords:
                if len(subword) > 12:
                    highlight = True
                    break

            if highlight:
                list_full.append(
                    ResultOut.factory(
                        config,
                        client,
                        language,
                        token.text,
                        token.text,
                        text,
                        offsets,
                        "plain_language",
                        token.idx,
                        explanation=language.translate("TOO_LONG_WORD"),
                    )
                )

        new_token_index += 1

    if is_sub_category_enabled(config.disabled_categories, "plain_language"):
        sentence_word_limit = 30

        for sent in tokens.sents:
            if len(sent) <= sentence_word_limit:
                continue

            sentences = {}
            sentence_parts = []
            start = sent[0].idx

            lines = sent.text.split("\n")
            for line in lines:
                if is_bullet_point(line):
                    sentence = "\n".join(sentence_parts)
                    if sentence and sentence.count(" ") > sentence_word_limit:
                        sentences[start] = sentence

                    start += len(sentence) + 1
                    sentence_parts = [line]
                else:
                    sentence_parts.append(line)

            sentence = "\n".join(sentence_parts)
            if sentence and sentence.count(" ") >= sentence_word_limit:
                sentences[start] = sentence

            for start in sentences:
                list_full.append(
                    ResultOut.factory(
                        config,
                        client,
                        language,
                        sentences[start],
                        sentences[start],
                        text,
                        offsets,
                        "plain_language",
                        start,
                        explanation=language.translate("TOO_LONG_SENTENCE"),
                    )
                )

    return list_full
