"""Pattern and phrase matching helpers for RuleCheck.

These helpers encapsulate async matching logic and depend on the provided
model, db, and logger instead of a specific owning class.
"""

from typing import Tuple
from spacy.tokens import Doc, Token
from logging import Logger

from app.models import LangType, Rule, RuleType


async def check_pattern(
    model,
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
            while i_pattern_start >= 0 and await model.check_word_type(
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
        elif await model.check_word_type(
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
    model,
    db,
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
            and lemma_ in db.male_to_female_normativ
        ):
            return await is_word_match(
                model,
                db,
                lang,
                token,
                word,
                word_type,
                suffix,
                db.male_to_female_normativ[lemma_],
            )
        return False

    return await model.check_word_type(lang, token, word_type["word_type"], True)


async def is_phrase_match(
    model,
    db,
    logger: Logger,
    lang: LangType,
    token_index: int,
    tokens: Doc,
    rule: Rule,
    false_positive_matcher: list | None = None,
) -> Tuple[int | None, int | None, str | None]:
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

        if not await is_word_match(
            model,
            db,
            lang,
            word_token,
            rule.words[word_index],
            word_type,
            suffix,
        ):
            return None, None, None

        text += word_token.text

        skip_token_index += 1

    if false_positive_matcher is not None and model.is_false_positive_match(
        false_positive_matcher, token_index, tokens, rule.lemma
    ):
        return None, None, None

    start_token_index = token_index
    if rule.pattern is not None:
        pattern = rule.pattern.split("|")
        if pattern[0] == "*" or pattern[-1] == "*":
            logger.error(
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
            tokens_match_count = await check_pattern(
                model, lang, tokens, prefix_pattern, token_index - 1, -1
            )
            if tokens_match_count is False:
                return None, None, None

            prefix_tokens_match_count += tokens_match_count

        suffix_pattern = pattern[lemma_position + 1 :]
        if len(suffix_pattern):
            tokens_match_count = await check_pattern(
                model, lang, tokens, suffix_pattern, token_index + token_count, 1
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
