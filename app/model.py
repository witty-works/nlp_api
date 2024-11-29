import spacy
from spacy.lang.en import English
from spacy.lang.de import German
from spacy.lang.fr import French

from spacy.lang.char_classes import (
    ALPHA,
    HYPHENS,
)
from spacy.tokenizer import Tokenizer
from spacy.util import compile_infix_regex, compile_suffix_regex, compile_prefix_regex
from spacy.lookups import Lookups
from spacy.tokens import Token, Doc
from spacy.matcher import PhraseMatcher, Matcher

import re
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

        for model_name in self.settings.models:
            lang = model_name[0:2]
            self.load_nlp_model(lang, model_name)

    adj_tags = {
        "AFX",
        "ADJA",
        "ADJD",
        "ADV",
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

    async def _fetch_word_type(
        self,
        lang: LangType,
        token: Token,
        expected_word_type: str | None = None,
        single_word: bool = False,
        strict: bool = False,
    ) -> str:
        # https://machinelearningknowledge.ai/tutorial-on-spacy-part-of-speech-pos-tagging/
        # https://github.com/explosion/spaCy/blob/master/spacy/glossary.py

        if token._.is_emoji:
            return WordType.EMOJI

        if token.pos_ == "NUM":
            if WordType.NUMBER != expected_word_type and (
                token.tag_ in ["CARD", "CD"] or "Card" in token.morph.get("NumType")
            ):
                return WordType.CARDINAL

            return WordType.NUMBER

        if not is_valid_text(lang, token.text):
            return ""

        if expected_word_type is None:
            expected_word_type = ""
        elif expected_word_type == WordType.ARTICLE:
            match lang:
                case LangType.EN:
                    if token.text.lower() in ["the", "a", "an"]:
                        return WordType.ARTICLE
                case _:
                    if token.text.lower() in self.static_rules[lang]["articles"]:
                        return WordType.ARTICLE

        if token.pos_ == "ADV":
            if WordType.ADVERB == expected_word_type:
                return WordType.ADVERB

            if lang == LangType.FR and WordType.ADJECTIVE == expected_word_type:
                return WordType.ADJECTIVE

        if (
            lang == LangType.EN
            and "-" in token.text
            and not token.text.startswith("-")
            and not token.text.endswith("-")
        ):
            tokens = self.fetch_tokens(lang, token.text.replace("-", " "))
            word_type = await self.fetch_word_type(
                lang, tokens[0], expected_word_type, single_word
            )
            # Case: "one-eyed" => "one eyed"
            if word_type in [
                WordType.CARDINAL,
                WordType.NUMBER,
            ] and expected_word_type not in [WordType.CARDINAL, WordType.NUMBER]:
                return await self.fetch_word_type(
                    lang, tokens[-1], expected_word_type, single_word
                )

            return word_type

        if token.tag_ in self.adj_tags or token.pos_ in self.adj_tags:
            return WordType.ADJECTIVE

        if lang == LangType.FR and expected_word_type == WordType.NOUN:
            if token.pos_ == "NOUN" or token.tag_ == "NN":
                return WordType.NOUN

            result = await self.db.fetch_declensions(
                lang, WordType.NOUN, token.text, token
            )
            if result is not None:
                return WordType.NOUN

        if token.pos_ == "VERB":
            if (
                not strict
                and lang == LangType.DE
                and WordType.ADJECTIVE in expected_word_type
            ):
                return WordType.ADJECTIVE

            return WordType.VERB

        if token.pos_ in self.pronoun_tags or token.tag_ in self.pronoun_tags:
            if expected_word_type == WordType.NOUN:
                return WordType.NOUN

            return WordType.PRONOUN

        if token.pos_ == "NOUN" or token.tag_ == "NN":
            if lang == LangType.DE:
                if token.text[0].islower() and self.db:
                    result = await self.db.fetch_declensions(
                        lang, WordType.VERB, token.text, token
                    )
                    if result is not None:
                        return WordType.VERB

            return WordType.NOUN

        if lang == LangType.DE and token.text[0].isupper() and token.text.endswith("-"):
            return WordType.NOUN

        if token.tag_ == "KON" or token.pos_ == "CCONJ":
            return WordType.CONJUNCTION

        if token.pos_ == "PROPN":
            return expected_word_type

        return ""

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
        return self.models[lang](text.rstrip().replace("\n", " "))

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

    def fetch_phrase_matcher(self, lang: LangType, tokens: Doc, phrases: list) -> list:
        # Phrase matcher part to handle False positives with two words and special symbols
        matcher = PhraseMatcher(s[lang].vocab, attr="LOWER")

        # Only run model.make_doc to speed things up
        patterns = [self.models[lang].make_doc(text) for text in phrases]
        matcher.add("TerminologyList", patterns)

        return matcher(tokens)

    def custom_tokenizer(self, lang, nlp):
        if lang == LangType.DE:
            infixes = German.Defaults.infixes
            for i in range(0, len(infixes)):
                if ":<>=" in infixes[i]:
                    # handle 'Kund:in' as one word
                    infixes[i] = r"(?<=[{a}])[<>=](?=[{a}])".format(a=ALPHA)
                    break

            rules = German.Defaults.tokenizer_exceptions
            suffixes = German.Defaults.suffixes
            prefixes = German.Defaults.prefixes
            token_match = German.Defaults.token_match
        elif lang == LangType.EN:
            infixes = English.Defaults.infixes
            for i in range(0, len(infixes)):
                if HYPHENS in infixes[i]:
                    # https://spacy.io/usage/linguistic-features#tokenization
                    # r"(?<=[{a}])(?:{h})(?=[{a}])".format(a=ALPHA, h=HYPHENS)
                    infixes.pop(i)
                    break

            rules = English.Defaults.tokenizer_exceptions
            suffixes = English.Defaults.suffixes
            prefixes = English.Defaults.prefixes
            token_match = English.Defaults.token_match
        elif lang == LangType.FR:
            # return None
            infixes = French.Defaults.infixes
            for i in range(0, len(infixes)):
                if HYPHENS in infixes[i]:
                    # https://spacy.io/usage/linguistic-features#tokenization
                    # r"(?<=[{a}])(?:{h})(?=[{a}])".format(a=ALPHA, h=HYPHENS)
                    infixes.pop(i)
                    break

            rules = French.Defaults.tokenizer_exceptions
            suffixes = French.Defaults.suffixes
            prefixes = French.Defaults.prefixes
            token_match = French.Defaults.token_match
        else:
            return None

        # https://github.com/explosion/spaCy/discussions/12930
        suffixes += [r"\."]

        return Tokenizer(
            vocab=nlp.vocab,
            rules=rules,
            prefix_search=compile_prefix_regex(prefixes).search,
            suffix_search=compile_suffix_regex(suffixes).search,
            infix_finditer=compile_infix_regex(infixes).finditer,
            token_match=token_match,
        )

    def load_nlp_model(self, lang, spacy_model):
        model = spacy.load(spacy_model, disable=["textcat"])
        model.add_pipe("emoji", first=True)
        tokenizer = self.custom_tokenizer(lang, model)
        if tokenizer is not None:
            model.tokenizer = tokenizer

        # Switch to non-trainable lemmatizer
        model.remove_pipe("lemmatizer")
        # Add non-trainable lemmatizer from language defaults
        # and load lemmatizer tables from spacy-lookups-data
        model.add_pipe("lemmatizer").initialize()

        model.add_pipe("custom_lemmatizer_factory", after="lemmatizer")

        self.models[lang] = model

    def is_token_singular(self, lang: LangType, token: Token) -> bool | None:
        plural_lookup_first = (
            False if token.text.endswith("e") and token.lemma_.endswith("er") else True
        )
        if plural_lookup_first and token.text in self.lemma_plural_lookup[lang]:
            return False

        number = token.morph.get("Number")
        if number:
            return "Sing" in number

        if not plural_lookup_first and token.text in self.lemma_plural_lookup[lang]:
            return False

        if lang == LangType.EN and token.pos == "NOUN" and token.text.endswith("s"):
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
