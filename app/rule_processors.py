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
    GenderedRolesFormatType,
    GermanGenderEndingType,
    Language,
    LangType,
    ResultOut,
    Rule,
    WordType,
)
from app.categories import is_sub_category_enabled
from app.helper import is_valid_text
from app.gender_format import (
    COMPOUND_PATTERNS,
    convert_french,
    french_doublet,
    gendered_form_end,
)
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


async def french_gender_endings(
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
    """French inclusive forms written in another `french_gender_separator`
    format: `enseignant.e.s` under `·` gets `enseignant·es`. Marked as part of
    the gender format switch, like the German mismatches."""
    subcategory = "gendered_denominations_ending_advanced"
    if not (
        is_sub_category_enabled(config.disabled_categories, subcategory)
        and Config.gendered_roles_format_inclusive(config.gendered_roles_format)
    ):
        return token_index

    token = tokens[token_index]
    form, last = token.text, token_index
    if not re.search("[·./]", form):
        # `enseignant / e / s`: a slash splits the form into tokens.
        # At a sentence end the tokenizer keeps the full stop on the last part
        # (`s.`); it is not part of the form.
        while (
            last + 2 < len(tokens)
            and not tokens[last].whitespace_
            and tokens[last].text[-1:] != "."
            and tokens[last + 1].text == "/"
            and not tokens[last + 1].whitespace_
            and tokens[last + 2].text.removesuffix(".").isalpha()
        ):
            last += 2
        if last == token_index:
            return token_index
        end = tokens[last].idx + len(tokens[last].text.removesuffix("."))
        form = text[token.idx : end]

    french = context.static_rules[LangType.FR]
    converted = convert_french(
        form,
        config.french_gender_separator,
        set(french["masculine_articles"]),
        set(french["feminine_articles"]),
        lambda word: not tokens.vocab[word].is_oov,
    )
    if converted is None:
        return token_index
    if converted == form:
        # Already in the configured format: nothing to report, and nothing
        # for the other rules either (a gendered form, not a masculine).
        return last + 1

    result = ResultOut.factory(
        config,
        client,
        language,
        form,
        f"{config.french_gender_separator}french",
        text,
        offsets,
        subcategory,
        token.idx,
        None,
        [Alternative(converted)],
    )
    result.bulk = "gender_format"
    result.bulk_alternative = 0
    list_full.append(result)

    return last + 1


async def french_doublet_genders(
    context: AppContext, one: str, other: str
) -> bool | None:
    """Whether `one` is the masculine of the doublet `one`/`other`, False when
    it is the feminine, None when the two are not one role's two genders."""
    for masculine, feminine, first_is_masculine in (
        (one, other, True),
        (other, one, False),
    ):
        feminine_forms = await context.db.fetch_declensions(
            LangType.FR, WordType.NOUN, feminine
        )
        if not feminine_forms or not feminine_forms["male_form"]:
            continue
        masculine_forms = await context.db.fetch_declensions(
            LangType.FR, WordType.NOUN, feminine_forms["male_form"]
        )
        if not masculine_forms:
            continue
        plural = feminine.lower() != feminine_forms["base_form"].lower()
        expected = masculine_forms["plural" if plural else "base_form"] or ""
        if masculine.lower() == expected.lower():
            return first_is_masculine

    return None


async def french_doublets(
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
    """`les enseignantes et les enseignants` gets `les enseignant·es`, the
    French counterpart of a German pair formula (`Schüler und Schülerinnen`):
    `gendered_denominations_ending`, or its advanced form when binary forms are
    also suggested, so the gender format switch applies it too. Left alone when
    only binary forms are wanted, as a doublet is one."""
    if not Config.gendered_roles_format_inclusive(config.gendered_roles_format):
        return token_index
    subcategory = "gendered_denominations_ending"
    if Config.gendered_roles_format_binary(config.gendered_roles_format):
        subcategory += "_advanced"
    if not is_sub_category_enabled(config.disabled_categories, subcategory):
        return token_index

    french = context.static_rules[LangType.FR]
    found = french_doublet(
        tokens,
        token_index,
        {conjunction.strip() for conjunction in french["noun_conjunction"].values()},
        french["articles_map"],
    )
    if found is None:
        return token_index
    first_article, first, second_article, second = found

    first_is_masculine = await french_doublet_genders(
        context, tokens[first].text, tokens[second].text
    )
    if first_is_masculine is None:
        return token_index

    masculine, feminine = (first, second) if first_is_masculine else (second, first)
    masculine_article = (
        first_article
        if second_article is None or masculine == first
        else second_article
    )
    article = (
        tokens[masculine_article].text.lower().replace("’", "'")
        if masculine_article is not None
        else None
    )
    # The article goes in separately, so the builder writes its inclusive
    # form in the configured format (`la/le`); `l'` is `le` before a vowel.
    # `aux` and `des` have no gendered forms and stay in front of the nouns.
    article = "le" if article == "l'" else article
    inline = ""
    if article is not None and article not in french["articles_inclusive_map"]:
        inline, article = article + " ", None
    _, _, variants = await context.alternatives.noun_alternatives(
        LangType.FR,
        *config.get_gender_separators_from_config(LangType.FR),
        inline + tokens[masculine].text.lower(),
        inline + tokens[feminine].text.lower(),
        article,
    )
    inclusive = variants.get(GenderedRolesFormatType.INCLUSIVE_GENDER)
    if not inclusive:
        return token_index

    start = tokens[first if first_article is None else first_article].idx
    end = tokens[second].idx + len(tokens[second].text)
    alternative = Alternative(inclusive)
    alternative.gender_role = GenderedRolesFormatType.INCLUSIVE_GENDER
    list_full.append(
        ResultOut.factory(
            config,
            client,
            language,
            text[start:end],
            "french_doublet",
            text,
            offsets,
            subcategory,
            start,
            None,
            [alternative],
        )
    )

    return second + 1


def on_gendered_form(
    list_full: list,
    found: int,
    tokens: Doc,
    token_index: int,
    form_end: int,
    text: str,
    new_token_index: int,
) -> int:
    """What the rules found on the start of a split gendered form.

    `Lehrer` in `Lehrer/innen` is not masculine, so alerts offering to gender
    it are dropped. Anything else (`Chef/in` as leadership language) still
    applies, widened to the whole form so accepting `Leitungsperson` replaces
    `Chef/in` and not only `Chef`. The loop goes on at the next token either
    way, so the form's own ending is still checked.
    """
    end = tokens[form_end].idx + len(tokens[form_end].text)
    kept = []
    for result in list_full[found:]:
        if any(alternative.gender_role for alternative in result.alternatives or []):
            continue
        if result.start == tokens[token_index].idx or result.end == tokens[
            token_index
        ].idx + len(tokens[token_index].text):
            result.end = end
            result.text = text[result.start : end]
        kept.append(result)
    list_full[found:] = kept

    return new_token_index if kept else token_index


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

            # Compounds with the marker inside: `Mitarbeiter*innengespräch`,
            # `Lehrer*innen-Team`. Only the infix formats keep them in one
            # token, so only they are read; every format can be written.
            if key in COMPOUND_PATTERNS:
                endings.append(
                    Rule(
                        key + "compound",
                        LangType.DE,
                        COMPOUND_PATTERNS[key],
                        None,
                        config._gendereddenom_ending_word_type[key],
                        subcategory,
                    )
                )

            # Articles and pronouns in every format, `jede/-r` and `jede(r)`
            # too: a bulk switch has to convert them along with the nouns.
            if key in config._gendereddenom_ending_article:
                # Tokenised like the nouns in the same format, except that a
                # plain slash splits a pair into three tokens (`die / der`)
                # while `jede/-r` stays one.
                if key.startswith("("):
                    word_types = config._gendereddenom_ending_word_type[key]
                elif key == GermanGenderEndingType.SLASH_DASH:
                    word_types = (None, None, "/")
                elif key.startswith("/"):
                    word_types = (-1, 2, "/")
                else:
                    word_types = (None, None, key[0])

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

        # First, so the rules below never read `enseignant` in
        # `enseignant/e/s` as a masculine noun of its own.
        if language.lang == LangType.FR:
            new_token_index = await french_gender_endings(
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

            new_token_index = await french_doublets(
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
        # `Lehrer` in `Lehrer/innen` is the start of a gendered form: what the
        # rules say about it is filtered and widened to the whole form.
        form_end = (
            gendered_form_end(tokens, token_index)
            if language.lang == LangType.DE
            else None
        )
        if valid_text:
            found = len(list_full)
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
            if form_end is not None:
                new_token_index = on_gendered_form(
                    list_full,
                    found,
                    tokens,
                    token_index,
                    form_end,
                    text,
                    new_token_index,
                )

            if check_continue(
                list_full, token_index, new_token_index, tokens, "rule_check", context
            ):
                continue

            if language.lang == LangType.DE:
                found = len(list_full)
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
                if form_end is not None:
                    new_token_index = on_gendered_form(
                        list_full,
                        found,
                        tokens,
                        token_index,
                        form_end,
                        text,
                        new_token_index,
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

    await context.rule_check.inklusivum_articles(
        config, client, language, text, tokens, offsets, list_full
    )
    await context.rule_check.inklusivum_adjectives(
        config, client, language, text, tokens, offsets, list_full
    )

    return list_full
