"""Unit tests for defects found in the spaCy usage review (docs/spacy-review.md).

These test app internals directly on blank spaCy pipelines, so they need
neither the large models nor LanguageTool.
"""

import asyncio
import logging

import pytest
import spacy
from spacy.tokens import Token

from app.adjectives import Adjectives
from app.model import Model
from app.models import LangType, Rule, WordType
from app.rule_check import RuleCheck
from app.settings import Settings

# Registered by the spacymoji pipe in production; register here so
# _fetch_word_type can run on blank pipelines.
if not Token.has_extension("is_emoji"):
    Token.set_extension("is_emoji", default=False)


def fetch_model(lemma_plural_lookup=None):
    model = Model(
        Settings(models=[]),
        logging.getLogger("test"),
        {},
        lemma_plural_lookup if lemma_plural_lookup is not None else {},
    )
    model.db = None
    return model


def fetch_rule_check(static_rules=None):
    return RuleCheck(
        Settings(models=[]),
        logging.getLogger("test"),
        static_rules if static_rules is not None else {},
        None,
        None,
        None,
        None,
        None,
        None,
    )


def test_english_plural_fallback_without_morphology():
    # token.pos was compared against the string "NOUN"; the fallback for
    # nouns the morphology cannot decide never fired.
    model = fetch_model({LangType.EN: set()})
    doc = spacy.blank("en")("cars")
    token = doc[0]
    token.pos_ = "NOUN"

    assert model.is_token_singular(LangType.EN, token) is False
    assert model.is_token_plural(LangType.EN, token) is True


@pytest.mark.asyncio
async def test_plain_adverb_is_not_an_adjective():
    # ADV sat in adj_tags, so every adverb was classified as an adjective.
    model = fetch_model()
    doc = spacy.blank("de")("oft")
    token = doc[0]
    token.pos_ = "ADV"
    token.tag_ = "ADV"

    assert await model._fetch_word_type(LangType.DE, token) == WordType.ADVERB


@pytest.mark.asyncio
async def test_adverb_still_matches_an_expected_adjective():
    # Rules may declare adjectives that appear in adverbial position; the
    # expectation keeps matching them.
    model = fetch_model()
    doc = spacy.blank("de")("oft")
    token = doc[0]
    token.pos_ = "ADV"
    token.tag_ = "ADV"

    word_type = await model._fetch_word_type(
        LangType.DE, token, WordType.ADJECTIVE
    )
    assert word_type == WordType.ADJECTIVE


@pytest.mark.asyncio
async def test_predicative_adjective_stays_an_adjective():
    # German tags predicative/adverbial adjectives ADJD with pos ADV.
    model = fetch_model()
    doc = spacy.blank("de")("agil")
    token = doc[0]
    token.pos_ = "ADV"
    token.tag_ = "ADJD"

    assert await model._fetch_word_type(LangType.DE, token) == WordType.ADJECTIVE


def test_substring_standard_words_without_false_positives():
    # standard_words was only assigned when the rule carried false positives,
    # leaving the loop below it to fail on rules without any.
    rule_check = fetch_rule_check(
        {LangType.DE: {"standard_words": ["arbeit"]}}
    )

    rule = Rule("1", "de", "beruf", None, None)
    assert rule_check.substring_standard_words(rule) == ["arbeit"]

    rule.false_positives = ["berufung"]
    assert rule_check.substring_standard_words(rule) == ["berufung", "arbeit"]


def test_gender_false_positive_finds_pair_across_doc():
    rule_check = fetch_rule_check()
    nlp = spacy.blank("de")

    doc = nlp("Kunden und Kundinnen")
    doc[0].lemma_ = "Kunde"
    doc[0].set_morph("Gender=Masc")
    doc[2].lemma_ = "Kunde"
    doc[2].set_morph("Gender=Fem")

    assert rule_check.is_gender_false_positive(doc[0]) is True
    # The probed token itself keeps its own reading.
    assert rule_check.is_gender_false_positive(doc[2]) is True


def test_gender_false_positive_single_form():
    rule_check = fetch_rule_check()
    doc = spacy.blank("de")("Kunden sind wichtig")
    doc[0].lemma_ = "Kunde"
    doc[0].set_morph("Gender=Masc")

    assert rule_check.is_gender_false_positive(doc[0]) is False


def test_french_feminine_form_of_f_adjectives():
    adjectives = Adjectives(None, None, None)

    assert adjectives.get_feminine_form_french("sportif") == "sportive"
    assert adjectives.get_feminine_form_french("neuf") == "neuve"
    assert adjectives.get_feminine_form_french("naïf") == "naïve"


@pytest.mark.asyncio
async def test_upos_noun_wins_over_adjective_tag():
    # de 3.8.0 emits pos=NOUN with tag=ADJD for nouns like 'Ehrgeiz'.
    model = fetch_model()
    doc = spacy.blank("de")("Ehrgeiz")
    token = doc[0]
    token.pos_ = "NOUN"
    token.tag_ = "ADJD"

    assert await model._fetch_word_type(LangType.DE, token) == WordType.NOUN


def test_person_entities_suppress_non_person_rules():
    # Name evidence comes from ent_type_ alone; the entity_ruler pipe in
    # Model.load_nlp_model labels salutation-attached surnames ('Herr
    # Müller') that the de 3.8.0 statistical NER misses.
    from app.models import EntityType

    rule_check = fetch_rule_check(
        {"named_entity_labels": {EntityType.PERSON: ["PER", "PERSON"]}}
    )
    rule = Rule("1", "de", "Müller", None, None)
    rule.entity_type = EntityType.NON_PERSON

    doc = spacy.blank("de")("Hallo Herr Müller")
    token = doc[2]
    token.ent_type_ = "PER"
    assert rule_check.is_entity_type_mismatch(rule, token) is True

    doc = spacy.blank("de")("Bäcker-Confiseur-Konditor gesucht")
    token = doc[0]
    token.pos_ = "PROPN"
    assert rule_check.is_entity_type_mismatch(rule, token) is False


@pytest.mark.asyncio
async def test_lowercase_verb_flip_guarded_by_noun_forms():
    # A lowercase "noun" the verb table knows flips to verb ("das
    # abzocken"), except when the form is also a known noun ("zur sorge") -
    # and the membership sets keep the decision off the token._.forms
    # cache, which once got poisoned with verb forms on noun tokens.
    model = fetch_model()
    model.de_verb_surface_forms = frozenset({"abzocken", "sorge"})
    model.de_noun_surface_forms = frozenset({"sorge"})

    doc = spacy.blank("de")("abzocken sorge")
    for token in doc:
        token.pos_ = "NOUN"

    trace = []
    assert (
        await model._fetch_word_type(LangType.DE, doc[0], None, trace=trace)
        == WordType.VERB
    )
    assert trace[-1] == "de-lowercase-noun-is-verb"
    assert (
        await model._fetch_word_type(LangType.DE, doc[1], None) == WordType.NOUN
    )


@pytest.mark.asyncio
async def test_en_hyphen_compound_trusts_tagger_without_expectation():
    # The split exists for expectation-driven matching ("one-eyed"); in
    # auto-detect it misread "self-driven" as a noun via "self" (measured
    # in docs/spacy-review.md, word-type branch metrics).
    model = fetch_model()
    # blank() would split the hyphen; the app's custom tokenizer keeps
    # compounds whole, so build the Doc explicitly.
    from spacy.tokens import Doc

    doc = Doc(spacy.blank("en").vocab, words=["self-driven"], spaces=[False])
    token = doc[0]
    token.pos_ = "ADJ"
    token.tag_ = "JJ"

    trace = []
    word_type = await model._fetch_word_type(LangType.EN, token, None, trace=trace)
    assert word_type == WordType.ADJECTIVE
    assert trace[-1] == "adjective-tags"

    # With an adjective expectation the compound answers it directly.
    trace = []
    word_type = await model._fetch_word_type(
        LangType.EN, token, WordType.ADJECTIVE, trace=trace
    )
    assert word_type == WordType.ADJECTIVE
    assert trace[-1] == "hyphen-adjective"


@pytest.mark.asyncio
async def test_nlp_session_evicts_transient_strings():
    model = fetch_model()
    nlp = spacy.blank("de")
    saved_model = Model.models.get(LangType.DE)
    saved_lock = Model.locks.get(LangType.DE)
    Model.models[LangType.DE] = nlp
    Model.locks[LangType.DE] = asyncio.Lock()

    try:
        baseline = len(nlp.vocab.strings)
        async with model.nlp_session(LangType.DE):
            model.fetch_tokens(LangType.DE, "Xylophonorchester quixotisch kzt9x")
            assert len(nlp.vocab.strings) > baseline

        # The request-transient entries are evicted at session exit.
        assert len(nlp.vocab.strings) == baseline
    finally:
        if saved_model is not None:
            Model.models[LangType.DE] = saved_model
            Model.locks[LangType.DE] = saved_lock
        else:
            Model.models.pop(LangType.DE, None)
            Model.locks.pop(LangType.DE, None)


def test_rule_dynamic_is_not_shared_between_rules():
    first = Rule("1", "de", "erste", None, None)
    second = Rule("2", "de", "zweite", None, None)

    assert first.dynamic is not second.dynamic

    first.dynamic.false_positives.append("x")
    first.dynamic.subcategory = "sub"

    assert second.dynamic.false_positives == []
    assert second.dynamic.subcategory is None
