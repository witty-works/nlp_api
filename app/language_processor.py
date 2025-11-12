"""Language processing functions for text analysis and rule application."""

from collections import defaultdict
import json

from spacy.tokens import Doc

from app.context import AppContext
from app.models import (
    Alternative,
    CheckRequestIn,
    Client,
    Config,
    Language,
    LangType,
    ResultOut,
    Rule,
    WordType,
)
from app.helper import utf16_offsets
from app.rule_processors import witty_rules


def fetch_text(
    check_request_in: CheckRequestIn,
    supported_langs: list,
    context: AppContext,
) -> tuple[str, Language | None, bool]:
    text = check_request_in.text
    limit_reached = len(text) > context.settings.text_max_length
    if limit_reached:
        text = text[0 : context.settings.text_max_length]
        text = text.rsplit(" ", 1)[0]

    locale = context.lang_detection.get_locale(
        supported_langs,
        text,
        check_request_in.lang,
        check_request_in.config.preferred_languages,
        check_request_in.config.preferred_variants,
    )

    language = None if locale is None else context.languages[locale]

    return text, language, limit_reached


async def apply_language_rules(
    client: Client,
    config: Config,
    configs: dict,
    language: Language,
    text: str,
    context: AppContext,
) -> list:
    tokens = context.model.fetch_tokens(language.lang, text)
    offsets = utf16_offsets(text)

    term_replacements = fetch_term_replacements(configs, language.lang, context)

    list_results = await witty_rules(
        config,
        term_replacements,
        client,
        tokens,
        offsets,
        language,
        text,
        context,
    )

    list_results = await context.languagetool.apply_languagetool_rules(
        config, client, language, text, tokens, offsets
    ) + await context_false_positives(language.lang, tokens, list_results, context)

    return apply_false_positives(list_results, configs)


def fetch_term_replacements(
    configs: dict,
    lang: LangType,
    context: AppContext,
) -> list[Rule]:
    if "term_replacements" not in configs:
        return []

    word_types = [WordType.VERB, WordType.NOUN, WordType.ADJECTIVE]
    term_replacement_rules = []
    for lemma in configs["term_replacements"]:
        if lemma[-3:] in context.term_replacement_langs:
            if not lemma.endswith(lang):
                continue

        term_replacement = configs["term_replacements"][lemma]

        alternatives = []
        for alternative in term_replacement["parsed_alternatives"]:
            alternatives.append(
                Alternative(
                    alternative["lemma"],
                    alternative["words"],
                    alternative["word_types"],
                )
            )

        rule = Rule(
            term_replacement["lemma"],
            lang,
            term_replacement["lemma"],
            term_replacement["words"],
            term_replacement["word_types"],
            "corporate_rules",
            alternatives,
        )

        if term_replacement["explanation"] is not None:
            rule.explanation = term_replacement["explanation"].get("text")
            rule.url = term_replacement["explanation"].get("url")
            rule.icon = term_replacement["explanation"].get("icon")

        if term_replacement["word_types"][0]["lower_case"]:
            rule.false_positives = term_replacement["false_positives"]
        else:
            rule.case_sensitive_false_positives = term_replacement["false_positives"]

        # If it is not a lemmatized rule
        rule.adapt_alternatives = (
            term_replacement["word_types"][0]["word_type"] in word_types
        )
        term_replacement_rules.append(rule)

    return term_replacement_rules


def apply_false_positives(
    list_results: list,
    configs: dict,
) -> list:
    if len(list_results) == 0:
        return list_results

    false_positives = []
    if "false_positives" in configs:
        false_positives = configs["false_positives"]

    if len(false_positives):
        for result in list_results.copy():
            if result.text in false_positives:
                list_results.remove(result)

    return list_results


async def context_false_positives(
    lang: LangType,
    tokens: Doc,
    list_results: list[ResultOut],
    context: AppContext,
) -> list[ResultOut]:
    # Return early if no results to check
    if len(list_results) == 0:
        return list_results

    # Return early if no context check rules exist for this language
    if len(context.static_rules[lang]["context_check"]) == 0:
        return list_results

    # Check if context checking is enabled for this language
    use_local = (
        context.settings.context_checker_local
        and context.context_checker.is_available(lang)
    )
    use_remote = lang in context.settings.context_checker

    if not use_local and not use_remote:
        return list_results

    sentences = {}
    sentences_to_check = defaultdict(list)
    for result_index in range(len(list_results)):
        result = list_results[result_index]
        if result.text_id in context.static_rules[lang]["context_check"]:
            if len(sentences) == 0:
                for sentence in tokens.sents:
                    sentences[sentence.end_char] = sentence.text

            sentence = None
            for end_char in sentences:
                if result.end <= end_char:
                    sentence = sentences[end_char]
                    break

            if sentence is None:
                continue

            sentences_to_check[sentence].append(result_index)

    if sentences_to_check == {}:
        return list_results

    sentences_list = list(sentences_to_check.keys())

    # Use local SetFit model if available, otherwise fall back to remote API
    if use_local:
        context_results = context.context_checker.predict(lang, sentences_list)
    else:
        # Remote API call
        headers = {
            "Content-Type": "application/json",
            "Authorization": (
                "Bearer " + context.settings.context_checker[lang]["api_key"]
            ),
        }

        payload = {
            "data": sentences_list,
        }

        api_results = await context.http.fetch_json_post(
            context.settings.context_checker[lang]["url"],
            json.dumps(payload),
            headers,
            "context checker",
        )
        # Convert API results to boolean (API returns "1" for genuine, "0" for false positive)
        context_results = [result == "1" for result in api_results]

    keys_to_remove = []
    for sentence_index in range(len(sentences_list)):
        sentence = sentences_list[sentence_index]
        # If result is True, it's a genuine issue; if False, it's a false positive
        if context_results[sentence_index]:
            continue

        for result_key in sentences_to_check[sentence]:
            if result_key in keys_to_remove:
                continue

            keys_to_remove.append(result_key)

    # Ensure we remove from the end so that the list indexes remain the same
    keys_to_remove.sort(reverse=True)
    for key_to_remove in keys_to_remove:
        list_results.pop(key_to_remove)

    return list_results
