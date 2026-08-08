import spacy
from spacy.lang.en import English
from spacy.lang.de import German
from spacy.lang.fr import French

from spacy.lang.char_classes import (
    ALPHA,
    HYPHENS,
)

from spacy.util import compile_infix_regex, compile_suffix_regex
from spacy.lookups import Lookups
from spacy.tokens import Token, Doc
from spacy.matcher import Matcher

import asyncio
import re
from contextlib import asynccontextmanager
from logging import Logger
import json


from app.models import LangType, WordType
from app.helper import is_valid_text
from app.db import Db
from app.settings import Settings

Token.set_extension("word_type", default=None)
Token.set_extension("text", default=None)
Token.set_extension("start", default=None)
Token.set_extension("label", default=None)
Token.set_extension("form", default=None)
Token.set_extension("forms", default=None)
Token.set_extension("token_index_offset", default=1)
Token.set_extension("child_token", default=None)
Token.set_extension("connected_token", default=None)

with open("./training_data/lookup.json", "r") as fp:
    lemma_lookup = json.load(fp)


class Model:
    settings: Settings
    loggger: Logger
    static_rules: dict
    lemma_plural_lookup: set
    # Filled in at startup once the database is available.
    ambiguous_number_lookup: dict
    db: Db

    def __init__(
        self,
        settings: Settings,
        logger: Logger,
        static_rules: dict,
        lemma_plural_lookup: set,
    ):
        self.settings = settings
        self.logger = logger
        self.static_rules = static_rules
        self.lemma_plural_lookup = lemma_plural_lookup
        self.ambiguous_number_lookup = {}

        for model_name in self.settings.models:
            lang = model_name[0:2]
            self.load_nlp_model(lang, model_name)

    adj_tags = {
        "AFX",
        "ADJA",
        "ADJD",
        "ADJ",
        "JJ",
        "JJR",
        "JJS",
    }

    pronoun_tags = [
        "PDAT",
        "PDS",
        "PIAT",
        "PIDAT",
        "PIS",
        "PPER",
        "PPOSAT",
        "PPOSS",
        "PRELAT",
        "PRELS",
        "PRF",
        "PRP$",
        "PRON",
        "PDT",
        "WP$",
        "WDT",
    ]

    models = {}
    locks = {}

    @asynccontextmanager
    async def nlp_session(self, lang: LangType):
        """Bounds per-request Vocab/StringStore growth via memory zones.

        Serialized per language: zones are process-global on the vocab, so a
        zone exiting while another request's Doc is alive would evict strings
        that Doc still references. spaCy work is GIL-bound anyway; the slow
        awaits (LanguageTool, LLM) belong outside this block. Docs created
        inside must not be used after it - extract plain data before leaving.
        """
        if not self.settings.memory_zones:
            yield
            return

        async with self.locks[lang]:
            with self.models[lang].memory_zone():
                yield

    def token_is_conjunction(self, token: Token) -> bool:
        return token.text == "," or token.pos_ == "CCONJ"

    async def fetch_word_type(
        self,
        lang: LangType,
        token: Token,
        word_type: str | None = None,
        single_word: bool = False,
        strict: bool = False,
    ) -> str:
        if word_type is None and single_word == False and strict == False:
            cache = True
            if token._.word_type is not None:
                return token._.word_type
        else:
            cache = False

        word_type = await self._fetch_word_type(
            lang,
            token,
            word_type,
            single_word,
            strict,
        )

        if cache:
            token._.word_type = word_type

        if (
            word_type in self.db.word_type_lemmas[lang]
            and token.lemma_ in self.db.word_type_lemmas[lang][word_type]
        ):
            token.lemma_ = self.db.word_type_lemmas[lang][word_type][token.lemma_]
        elif (
            lang == LangType.FR
            and word_type == WordType.ADJECTIVE
            and token.lemma_.endswith("er")
        ):
            token.lemma_ = token.lemma_[0:-2] + "é"

        return word_type

    @staticmethod
    def _traced(trace: list | None, tag: str, word_type: str) -> str:
        """Record which branch decided, for the word-type metrics runner."""
        if trace is not None:
            trace.append(tag)
        return word_type

    async def _fetch_word_type(
        self,
        lang: LangType,
        token: Token,
        expected_word_type: str | None = None,
        single_word: bool = False,
        strict: bool = False,
        trace: list | None = None,
    ) -> str:
        """Hacky approach to fix some issues in spaCy POS detection.
        It was optimized for spaCy large models for the current rule set.
        Fine tuning the spaCy models is probably the cleaner approach.

        Every return is tagged via _traced so bin/word_type_metrics.py can
        measure which branches still earn their keep per model version."""
        # https://machinelearningknowledge.ai/tutorial-on-spacy-part-of-speech-pos-tagging/
        # https://github.com/explosion/spaCy/blob/master/spacy/glossary.py

        if token._.is_emoji:
            return self._traced(trace, "emoji", WordType.EMOJI)

        if token.pos_ == "NUM":
            if WordType.NUMBER != expected_word_type and (
                token.tag_ in ["CARD", "CD"] or "Card" in token.morph.get("NumType")
            ):
                return self._traced(trace, "cardinal", WordType.CARDINAL)

            return self._traced(trace, "number", WordType.NUMBER)

        if not is_valid_text(lang, token.text):
            return self._traced(trace, "invalid-text", "")

        if expected_word_type is None:
            expected_word_type = ""
        elif (
            expected_word_type == WordType.ARTICLE
            and token.text.lower() in self.static_rules[lang]["articles"]
        ):
            return self._traced(trace, "article-list", WordType.ARTICLE)

        if token.pos_ == "ADV":
            if WordType.ADVERB == expected_word_type:
                return self._traced(trace, "adverb-expected", WordType.ADVERB)

            if WordType.ADJECTIVE == expected_word_type:
                if lang == LangType.FR and token.text.lower().endswith("ez"):
                    # Vous l’incarnez et l’**animez** auprès de notre clientèle.
                    return self._traced(trace, "fr-ez-verb", WordType.VERB)

                return self._traced(
                    trace, "adv-as-expected-adjective", WordType.ADJECTIVE
                )

        if (
            lang == LangType.EN
            and expected_word_type
            and "-" in token.text
            and not token.text.startswith("-")
            and not token.text.endswith("-")
        ):
            # Splitting exists so "one-eyed"-class rules can match their
            # parts, which only makes sense against an expectation. In
            # auto-detect the whole-token tag is the better reading: the
            # split turns "self-driven" into a noun via "self" (measured in
            # docs/spacy-review.md, word-type branch metrics).
            # The tagger's reading of the whole compound answers the
            # expectation directly; splitting loses it. en 3.7.1 hid this by
            # tagging compounds PROPN, which matched any expectation (case:
            # 'state-of-the-art' in tests/test_lemmatizers/test_english_lemmatizer).
            if expected_word_type == WordType.ADJECTIVE and (
                token.tag_ in self.adj_tags or token.pos_ in self.adj_tags
            ):
                return self._traced(trace, "hyphen-adjective", WordType.ADJECTIVE)

            tokens = self.fetch_tokens(lang, token.text.replace("-", " "))
            word_type = await self.fetch_word_type(
                lang, tokens[0], expected_word_type, single_word
            )
            # Case: "one-eyed" => "one eyed"
            if word_type in [
                WordType.CARDINAL,
                WordType.NUMBER,
            ] and expected_word_type not in [WordType.CARDINAL, WordType.NUMBER]:
                return self._traced(
                    trace,
                    "hyphen-split-last",
                    await self.fetch_word_type(
                        lang, tokens[-1], expected_word_type, single_word
                    ),
                )

            return self._traced(trace, "hyphen-split-first", word_type)

        # UPOS wins when the two taggers disagree: the de 3.8.0 pipeline
        # emits pos=NOUN with tag=ADJD for nouns like 'Ehrgeiz' (case:
        # tests/test_general_cases/test_api_capitalize_alternatives).
        if (
            token.tag_ in self.adj_tags or token.pos_ in self.adj_tags
        ) and token.pos_ not in ("NOUN", "PROPN"):
            if lang == LangType.FR and token.text.lower().endswith("ez"):
                # Vous l’incarnez et l’**animez** auprès de notre clientèle.
                return self._traced(trace, "fr-ez-verb", WordType.VERB)

            return self._traced(trace, "adjective-tags", WordType.ADJECTIVE)

        # Predicative/adverbial adjectives carry an adjective tag (ADJD, JJ)
        # and are handled above; what reaches this point is a plain adverb.
        if token.pos_ == "ADV":
            return self._traced(trace, "adverb", WordType.ADVERB)

        if lang == LangType.FR and expected_word_type == WordType.NOUN:
            if token.pos_ == "NOUN" or token.tag_ == "NN":
                return self._traced(trace, "fr-noun-expected", WordType.NOUN)

        if token.pos_ == "VERB":
            if (
                not strict
                and lang == LangType.DE
                and WordType.ADJECTIVE in expected_word_type
            ):
                return self._traced(
                    trace, "de-verb-as-expected-adjective", WordType.ADJECTIVE
                )

            return self._traced(trace, "verb", WordType.VERB)

        if token.pos_ in self.pronoun_tags or token.tag_ in self.pronoun_tags:
            if expected_word_type == WordType.NOUN:
                return self._traced(trace, "pronoun-as-expected-noun", WordType.NOUN)

            return self._traced(trace, "pronoun", WordType.PRONOUN)

        if token.pos_ == "NOUN" or token.tag_ == "NN":
            if lang == LangType.DE:
                # A lowercase "noun" that the verb table knows is usually a
                # misread infinitive ("Wir wollen das abzocken"). But only
                # when the capitalized form is not itself a known noun:
                # informal lowercase German ("Anlaß zur sorge", "auf kosten
                # des...") must stay a noun (measured in
                # docs/spacy-review.md, word-type branch metrics).
                if token.text[0].islower() and self.db:
                    result = await self.db.fetch_declensions(
                        lang, WordType.VERB, token.text, token
                    )
                    # No token here: the call above cached the verb forms on
                    # it, and this lookup must not read or overwrite that.
                    if result is not None and not await self.db.fetch_declensions(
                        lang, WordType.NOUN, token.text
                    ):
                        return self._traced(
                            trace, "de-lowercase-noun-is-verb", WordType.VERB
                        )

            return self._traced(trace, "noun", WordType.NOUN)

        if lang == LangType.DE and token.text[0].isupper() and token.text.endswith("-"):
            return self._traced(trace, "de-dash-noun", WordType.NOUN)

        if token.tag_ == "KON" or token.pos_ == "CCONJ":
            return self._traced(trace, "conjunction", WordType.CONJUNCTION)

        if token.pos_ == "PROPN":
            return self._traced(trace, "propn-as-expected", expected_word_type)

        return self._traced(trace, "no-match", "")

    async def check_word_type(
        self,
        lang: LangType,
        token: Token,
        word_type: str = "",
        single_word: bool | None = None,
        strict: bool = False,
    ) -> bool:
        if len(word_type) == 0:
            return True

        return word_type == await self.fetch_word_type(
            lang, token, word_type, single_word, strict
        )

    def tokenize(self, text: str, lang: LangType) -> tuple:
        return tuple([i.text for i in self.models[lang].tokenizer(text)])

    # matcher to false positives
    def is_false_positive_match(
        self, false_positive_matcher: list, token_index: int, tokens: Doc, lemma: str
    ) -> bool:
        index = tokens[token_index].idx
        for _, start, end in false_positive_matcher:
            span_false = tokens[start:end]
            if tokens[start:end].lemma_ != lemma and index in range(
                span_false.start_char, span_false.end_char
            ):
                return True

        return False

    def fetch_tokens(self, lang: LangType, text: str) -> Doc:
        return self.models[lang](text.rstrip())

    # create false positives patterns based on false positives column
    def fetch_false_positive_matcher(
        self, lang: LangType, tokens: Doc, false_positives: list
    ) -> list:
        if len(false_positives) == 0:
            return []

        matcher = Matcher(self.models[lang].vocab)

        for false_positive in false_positives:
            matcher.add("FalsePositivesList", false_positive)

        return matcher(tokens)

    def tune_tokenizer(self, lang, nlp):
        """Adjust the shipped tokenizer in place rather than rebuilding it.

        de: keep gender-colon words ('Kund:in') whole; en/fr: keep hyphen
        compounds whole; all: always split a trailing period
        (https://github.com/explosion/spaCy/discussions/12930)."""
        if lang == LangType.DE:
            infixes = [
                # handle 'Kund:in' as one word
                r"(?<=[{a}])[<>=](?=[{a}])".format(a=ALPHA) if ":<>=" in infix else infix
                for infix in German.Defaults.infixes
            ]
            suffixes = German.Defaults.suffixes
        elif lang == LangType.EN:
            # https://spacy.io/usage/linguistic-features#tokenization
            infixes = [i for i in English.Defaults.infixes if HYPHENS not in i]
            suffixes = English.Defaults.suffixes
        elif lang == LangType.FR:
            infixes = [i for i in French.Defaults.infixes if HYPHENS not in i]
            suffixes = French.Defaults.suffixes
        else:
            return

        nlp.tokenizer.infix_finditer = compile_infix_regex(infixes).finditer
        nlp.tokenizer.suffix_search = compile_suffix_regex(
            list(suffixes) + [r"\."]
        ).search

    salutation_titles = [
        "herr",
        "herrn",
        "frau",
        "hr",
        "hr.",
        "fr",
        "fr.",
        "mr",
        "mr.",
        "mrs",
        "mrs.",
        "ms",
        "ms.",
        "miss",
        "dr",
        "dr.",
        "monsieur",
        "madame",
        "mme",
        "mme.",
    ]

    def load_nlp_model(self, lang, spacy_model):
        model = spacy.load(spacy_model, disable=["textcat"])
        model.add_pipe("emoji", first=True)
        self.tune_tokenizer(lang, model)

        if self.settings.lemmatizer == "lookup":
            # Switch to the non-trainable lemmatizer with its tables from
            # spacy-lookups-data.
            model.remove_pipe("lemmatizer")
            lemmatizer = model.add_pipe("lemmatizer")
            lemmatizer.initialize()

        if (
            self.settings.lemmatizer == "lookup"
            and model.get_pipe("lemmatizer").mode == "lookup"
        ):
            # Merge the product lemma pins into the lemmatizer's own lookup
            # table (de/fr) - last write wins, so the pins override shipped
            # entries.
            model.get_pipe("lemmatizer").lookups.get_table("lemma_lookup").update(
                lemma_lookup[lang]
            )
        else:
            # The rule-mode lemmatizer (en) and the trained one have no
            # surface-keyed table to merge into, so the pins run as a pipe.
            model.add_pipe("custom_lemmatizer_factory", after="lemmatizer")

        # A salutation followed by a PROPN is a person reference even where
        # the statistical NER stays silent - the de 3.8.0 model dropped bare
        # surnames like 'Herr Müller' (case:
        # tests/test_general_cases/test_api_entity_de). The entity_ruler is
        # spaCy's layer for exactly this; the ner keeps every span the ruler
        # already claimed.
        entity_ruler = model.add_pipe("entity_ruler", before="ner")
        entity_ruler.add_patterns(
            [
                {
                    "label": "PERSON" if lang == LangType.EN else "PER",
                    "pattern": [
                        {"LOWER": {"IN": self.salutation_titles}},
                        {"POS": "PROPN"},
                    ],
                }
            ]
        )

        if lang == LangType.DE:
            # Gender-symbol forms (Kund:innen, Kolleg*in) are nouns wherever
            # they appear, but the de 3.8.0 tagger reads some as adjectives
            # (case: tests/test_spacy_analysis/de_gender_colon). Retire this
            # pattern when a future model passes that case without it.
            ruler = model.get_pipe("attribute_ruler")
            ruler.add(
                patterns=[[{"TEXT": {"REGEX": r"^\w+[:*·](in|innen)$"}}]],
                attrs={"POS": "NOUN", "TAG": "NN"},
            )

        self.models[lang] = model
        self.locks[lang] = asyncio.Lock()

    def is_number_ambiguous(self, lang: LangType, token: Token) -> bool:
        """Whether the word list cannot decide this token's number.

        True for forms that are both a singular and a plural of the same lemma,
        where the list can only ever answer plural.
        """
        return token.text in self.ambiguous_number_lookup.get(lang, ())

    def number_from_determiner(self, lang: LangType, token: Token) -> bool | None:
        """Read the number off the determiner introducing this noun.

        Preferred over the tagger for ambiguous forms because it is a fixed
        lookup: it gives the same answer whichever model is loaded, which the
        morphology does not. Returns None when no determiner settles it.
        """
        rules = self.static_rules.get(lang, {})
        plural_only = rules.get("plural_only_determiners")
        singular_only = rules.get("singular_only_determiners")

        if not plural_only and not singular_only:
            return None

        # A determiner binds only the noun phrase it opens, so walk back over
        # adjectives and stop at the first word that is not one. Running past
        # that would pick up the determiner of an earlier phrase, reading
        # "eine Arbeitskraft für unsere Kunden" as a singular Kunden.
        for index in range(token.i - 1, max(token.i - 4, token.sent.start) - 1, -1):
            previous = token.doc[index]

            word = previous.text.lower()
            if word in plural_only:
                return False
            if word in singular_only:
                return True

            if previous.pos_ not in ("ADJ", "ADV"):
                return None

        return None

    def is_token_singular(self, lang: LangType, token: Token) -> bool | None:
        plural_lookup_first = (
            False if token.text.endswith("e") and token.lemma_.endswith("er") else True
        )
        # An ambiguous form is genuinely both, so the list is not evidence and
        # must not pre-empt the reading from the surrounding sentence.
        ambiguous = self.is_number_ambiguous(lang, token)

        if (
            not ambiguous
            and plural_lookup_first
            and token.text in self.lemma_plural_lookup[lang]
        ):
            return False

        if ambiguous:
            from_determiner = self.number_from_determiner(lang, token)
            if from_determiner is not None:
                return from_determiner

        number = token.morph.get("Number")
        if number:
            is_singular = "Sing" in number

            if (
                self.settings.log_metrics
                and ambiguous
                and is_singular
                and token.text in self.lemma_plural_lookup[lang]
            ):
                # Where the two sources disagree the model decides, so record it:
                # this is the only place a different spaCy model can change the
                # number, and without a count the trade-off is invisible.
                self.logger.info(
                    "Number from morphology over word list for '%s' (%s), model '%s'",
                    token.text,
                    lang,
                    self.models[lang].meta.get("name", "unknown"),
                )

            return is_singular

        # Nothing decided it, so fall back to the list even when ambiguous:
        # a guess from the lexicon beats no answer, and this keeps the previous
        # behaviour wherever the model has no morphological reading at all.
        if token.text in self.lemma_plural_lookup[lang]:
            return False

        if lang == LangType.EN and token.pos_ == "NOUN" and token.text.endswith("s"):
            return False

        if token.text.endswith("-"):
            return False

        # Likely to happen with nouns that are anglicisms, f.e. 'Store Manager Watch"
        return None

    def is_token_plural(self, lang: LangType, token: Token) -> bool | None:
        is_singular = self.is_token_singular(lang, token)
        if is_singular is None:
            return None

        return not is_singular

    def is_false_positive(
        self,
        full_text: str | None,
        token_index: int | None,
        tokens: Doc | None,
        false_positives: list,
        window_left: int | None = None,
        window_right: int | None = None,
        case_sensitive: bool = False,
    ) -> bool:
        if len(false_positives) == 0 or full_text is None:
            return False

        if window_left is None:
            # previous 5 tokens
            i_window_min = max(0, token_index - 5)
            window_left = tokens[i_window_min].idx
        else:
            window_left = max(tokens[token_index].idx - window_left, 0)

        if window_right is None:
            # following 5 tokens
            i_window_max = min(len(tokens) - 1, token_index + 5)
            window_right = tokens[i_window_max].idx + len(tokens[i_window_max].text)
        else:
            window_right += tokens[token_index].idx

        partial_text = full_text[window_left:window_right]
        if not case_sensitive:
            partial_text = partial_text.lower()
            false_positives = list(
                map(lambda false_positive: false_positive.lower(), false_positives)
            )

        start = tokens[token_index].idx - window_left
        end = start + len(tokens[token_index].text)

        for false_positive in false_positives:
            for m in re.finditer(re.escape(false_positive), partial_text):
                if m.start() <= start and m.end() >= end:
                    return True

        return False

    def fetch_false_positive_matchers(self, lang: LangType, tokens: Doc) -> list | None:
        if "pattern_false_positives" not in self.static_rules[lang]:
            return None

        return self.fetch_false_positive_matcher(
            lang, tokens, self.static_rules[lang]["pattern_false_positives"]
        )


def custom_lemmatizer(lang):
    lemmatizer = TokenLemmatizer(lemma_lookup[lang])

    lookups = Lookups()
    lookups.add_table("lemma_lookup", lemma_lookup[lang])
    lemmatizer.lookups = lookups

    return lemmatizer


@German.factory("custom_lemmatizer_factory")
@English.factory("custom_lemmatizer_factory")
@French.factory("custom_lemmatizer_factory")
def custom_lemmatizer_factory(nlp, name):
    return custom_lemmatizer(nlp.lang)


class TokenLemmatizer:
    def __init__(self, lemma_table):
        self.lemma_table = lemma_table

    def __call__(self, doc):
        for token in doc:
            # Overwrite the token.lemma_ if there's an entry in the data
            if token.text in self.lemma_table:
                token.lemma_ = self.lemma_table.get(token.text, token.lemma_)

        return doc
