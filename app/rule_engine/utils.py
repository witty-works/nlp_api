"""General rule engine utilities (token helpers, chunking, result helpers).

These helpers are pure and do not depend on class state.
"""

from typing import List, Optional
from spacy.tokens import Span, Token
from app.models import (
    ResultOut,
    Config,
    Client,
    Language,
    Alternative,
    ResultSource,
)


def fetch_sentence_noun_chunks(sent: Span) -> List[Span]:
    return [chunk for chunk in sent.noun_chunks]


def find_token_chunk(chunks: List[Span], token_index: int) -> Optional[Span]:
    for chunk in chunks:
        if chunk.start <= token_index < chunk.end:
            return chunk
        if chunk.start > token_index:
            break
    return None


def get_token_gender(token: Token) -> Optional[str]:
    gender = token.morph.get("Gender")
    if gender:
        return gender[0]
    return None


def is_target_noun(token: Token) -> bool:
    dep = token.dep_
    return dep.endswith("subj") or dep.endswith("obj") or dep.startswith("obl")


def append_result(
    out_list: list,
    *,
    config: Config,
    client: Client,
    language: Language,
    text: str,
    text_id: str,
    full_text: str,
    offsets: dict,
    subcategory: str,
    start: int,
    end: Optional[int] = None,
    alternatives: Optional[list[Alternative]] = None,
    label: Optional[str] = None,
    explanation: Optional[str] = None,
    url: Optional[str] = None,
    icon: Optional[str] = None,
    explanation_context: Optional[str] = None,
    source: Optional[ResultSource] = None,
    long_explanation: Optional[str] = None,
) -> None:
    out_list.append(
        ResultOut.factory(
            config,
            client,
            language,
            text,
            text_id,
            full_text,
            offsets,
            subcategory,
            start,
            end,
            alternatives,
            label,
            explanation,
            url,
            icon,
            explanation_context,
            source,
            long_explanation=long_explanation,
        )
    )
