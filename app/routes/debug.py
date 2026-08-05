"""
Debug Routes
Debugging endpoints for testing rules, spacy analysis, and language features.
Only available in non-production environments.
"""

from typing import Union

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPBearer
from fastapi.security.api_key import APIKeyHeader
from spacy import displacy

from app.context import AppContext
from app.dependencies import fetch_current_username, get_app_context
from app.settings import get_settings
from app.models import (
    Alternative,
    Client,
    CheckRequestIn,
    Config,
    LangType,
    Result,
    ResultOut,
    ResultsOut,
    Rule,
    RuleIn,
)
from app.text_utils import german_lemmatization
from app.routes.check import check
from app.models import PrettyJSONResponse
from app.helper import utf16_offsets

router = APIRouter()


@router.post(
    "/debug/rule",
    include_in_schema=not get_settings().is_prod,
    response_model=list[ResultOut],
    response_model_exclude_none=True,
)
async def post_debug_rule(
    rule_data: RuleIn,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
):
    language = context.languages[rule_data.lang]
    config = Config()

    tokens = context.model.fetch_tokens(language.lang, rule_data.text)
    for token in tokens:
        word_type = await context.model.fetch_word_type(language.lang, token)
        for lemmatization in rule_data.lemmatizations:
            if token.text.lower() == lemmatization.text.lower() and (
                word_type == lemmatization.word_type or lemmatization.word_type == ""
            ):
                token.lemma_ = lemmatization.text
                break

    offsets = utf16_offsets(rule_data.text)
    false_positive_matcher = context.model.fetch_false_positive_matchers(
        language.lang, tokens
    )

    if rule_data.alternatives is not None:
        alternative_list = []
        for alternative_in in rule_data.alternatives:
            alternative = Alternative(
                alternative_in.lemma,
                context.model.tokenize(alternative_in.lemma, rule_data.lang),
                alternative_in.word_types,
                alternative_in.is_remove,
                alternative_in.is_inspiration,
                alternative_in.is_placeholder,
                alternative_in.is_advanced,
                alternative_in.is_collective_noun,
                alternative_in.is_gendered_noun,
                alternative_in.label,
            )

            alternative_list.append(alternative)
    else:
        alternative_list = None

    rule = Rule(
        "test",
        rule_data.lang,
        rule_data.lemma,
        context.model.tokenize(rule_data.lemma, rule_data.lang),
        rule_data.word_types,
        rule_data.subcategories,
        None,
        rule_data.actual_word_types,
    )

    rule.dynamic.alternatives = alternative_list
    rule.pattern = rule_data.pattern
    rule.is_pattern_match = rule_data.is_pattern_match
    rule.false_positives = rule_data.false_positives
    rule.label = rule_data.label
    rule.type = rule_data.type
    rule.entity_type = rule_data.entity_type
    rule.pluralization = rule_data.pluralization
    rule.adapt_alternatives = bool(len(alternative_list))

    rules = [rule]

    list_full = []
    client = Client.parse("debug:" + context.version)

    token_index = 0
    token_count = len(tokens)
    while token_index < token_count:
        if rule_data.lang == LangType.DE:
            tokens[token_index].lemma_ = await german_lemmatization(
                tokens, token_index, context
            )

        for rule in rules:
            await context.rule_check.handle(
                config,
                client,
                language,
                rule_data.text,
                token_index,
                tokens,
                offsets,
                list_full,
                [rule],
                false_positive_matcher,
            )

        token_index += 1

    return list_full


@router.get(
    "/debug/spacy",
    include_in_schema=not get_settings().is_prod,
    response_class=PrettyJSONResponse,
)
async def get_debug_spacy(
    text: str,
    lang: LangType,
    detailed: bool = False,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
):
    results = []
    tokens = context.model.fetch_tokens(lang, text)

    word_type_parts = []
    for token_index in range(len(tokens)):
        token = tokens[token_index]

        if lang == LangType.DE:
            token.lemma_ = await german_lemmatization(tokens, token_index, context)
        word_type = await context.model.fetch_word_type(lang, token)

        # Get string value for word_type, prefix with '~' if text != lemma
        word_type_str = getattr(word_type, "value", word_type)
        if token.text != token.lemma_:
            word_type_str = f"~{word_type_str}"
        word_type_parts.append(word_type_str)

        token_info = {
            "text": token.text,
            "lemma": token.lemma_,
            "word_type": word_type,
            "is_singular": context.model.is_token_singular(lang, token),
            "ner": token.ent_type_,
        }

        if detailed:
            token_info["start"] = token.idx
            token_info["whitespace"] = token.whitespace_
            token_info["emoji_desc"] = token._.emoji_desc
            token_info["is_emoji"] = token._.is_emoji
            token_info["morph"] = token.morph.to_dict()
            token_info["tag"] = token.tag_
            token_info["pos"] = token.pos_
            token_info["dep"] = token.dep_
            token_info["head"] = token.head.text

            dependent = None
            children = []
            for a in token.ancestors:
                for atok in a.children:
                    children.append(
                        {"dep": atok.dep_, "token": atok.text, "ner": atok.ent_type_}
                    )
                    if dependent is None and atok.dep_ in ["pobj", "dobj"]:
                        dependent = atok.text

            token_info["dependent"] = dependent
            token_info["children"] = children

        results.append(token_info)

    if detailed:
        noun_chunks = []
        for chunk in tokens.noun_chunks:
            noun_chunks.append(
                {
                    "text": chunk.text,
                    "start": chunk.start,
                    "end": chunk.end,
                }
            )

        results = [{"noun chunks": noun_chunks}] + results

    # Build the word type rule string
    word_type_rule = "|".join(word_type_parts)
    return [{"auto-detected word type": word_type_rule}] + results


@router.get(
    "/debug/displacy",
    include_in_schema=not get_settings().is_prod,
)
async def get_debug_displacy(
    text: str,
    lang: LangType,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
):
    tokens = context.model.fetch_tokens(lang, text)

    sentence_spans = list(tokens.sents)
    data = displacy.render(sentence_spans, style="dep")
    return Response(content=data, media_type="image/svg+xml")


@router.get(
    "/debug/german_noun",
    include_in_schema=not get_settings().is_prod,
    response_class=PrettyJSONResponse,
)
async def get_debug_german_noun(
    word: str,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
):
    return await context.nouns.german_noun_lookup(word)


@router.post(
    "/debug/check",
    response_model=Union[ResultsOut, Result],
    response_model_exclude_none=True,
    dependencies=[
        Depends(HTTPBearer(auto_error=False)),
        Depends(APIKeyHeader(name="x-key", auto_error=False)),
    ],
    include_in_schema=not get_settings().is_prod,
)
async def post_debug_check(
    request: Request,
    response: Response,
    check_request_in: CheckRequestIn,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
):
    return await check(request, response, check_request_in, None, context)
