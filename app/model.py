import spacy
from spacy.lang.en import English
from spacy.lang.de import German

from spacy.lang.char_classes import (
    ALPHA,
    ALPHA_LOWER,
    ALPHA_UPPER,
    CONCAT_QUOTES,
    LIST_ELLIPSES,
    LIST_ICONS,
)
from spacy.tokenizer import Tokenizer
from spacy.util import compile_infix_regex
from spacy.lookups import Lookups


class TokenLemmatizer:
    def __init__(self, lemma_table):
        self.lemma_table = lemma_table

    def __call__(self, doc):
        for token in doc:
            # Overwrite the token.lemma_ if there's an entry in the data
            if token.text in self.lemma_table:
                token.lemma_ = self.lemma_table.get(token.text, token.lemma_)

        return doc


def custom_tokenizer(lang, nlp):
    if lang == "de":
        infixes = (
            LIST_ELLIPSES
            + LIST_ICONS
            + [
                r"(?<=[{al}])\\.(?=[{au}])".format(al=ALPHA_LOWER, au=ALPHA_UPPER),
                r"(?<=[{a}])[,!?](?=[{a}])".format(a=ALPHA),
                # removed : [:<>=]
                r"(?<=[{a}])[<>=](?=[{a}])".format(a=ALPHA),
                r"(?<=[{a}]),(?=[{a}])".format(a=ALPHA),
                r"(?<=[0-9{a}])\/(?=[0-9{a}])".format(a=ALPHA),
                r"(?<=[{a}])([{q}\)\]\(\[])(?=[{a}])".format(
                    a=ALPHA, q=CONCAT_QUOTES.replace("'", "")
                ),
                r"(?<=[{a}])--(?=[{a}])".format(a=ALPHA),
                r"(?<=[0-9])-(?=[0-9])",
            ]
        )
    else:
        # https://spacy.io/usage/linguistic-features#tokenization
        infixes = (
            LIST_ELLIPSES
            + LIST_ICONS
            + [
                r"(?<=[0-9])[+\\-\\*^](?=[0-9-])",
                r"(?<=[{al}{q}])\\.(?=[{au}{q}])".format(
                    al=ALPHA_LOWER, au=ALPHA_UPPER, q=CONCAT_QUOTES
                ),
                r"(?<=[{a}]),(?=[{a}])".format(a=ALPHA),
                # ✅ Commented out regex that splits on hyphens between letters:
                # r"(?<=[{a}])(?:{h})(?=[{a}])".format(a=ALPHA, h=HYPHENS),
                r"(?<=[{a}0-9])[:<>=/](?=[{a}])".format(a=ALPHA),
            ]
        )

    infix_re = compile_infix_regex(infixes)

    # https://github.com/explosion/spaCy/discussions/12930
    suffixes = nlp.Defaults.suffixes + [r"\."]
    suffix_regex = spacy.util.compile_suffix_regex(suffixes)
    nlp.tokenizer.suffix_search = suffix_regex.search

    return Tokenizer(
        nlp.vocab,
        prefix_search=nlp.tokenizer.prefix_search,
        suffix_search=nlp.tokenizer.suffix_search,
        infix_finditer=infix_re.finditer,
        token_match=nlp.tokenizer.token_match,
        rules=nlp.Defaults.tokenizer_exceptions,
    )

lemma_lookup = {}

def custom_lemmatizer(lang):
    lemmatizer = TokenLemmatizer(lemma_lookup[lang])

    lookups = Lookups()
    lookups.add_table("lemma_lookup", lemma_lookup[lang])
    lemmatizer.lookups = lookups

    return lemmatizer


@German.factory("custom_lemmatizer_factory")
@English.factory("custom_lemmatizer_factory")
def custom_lemmatizer_factory(nlp, name):
    return custom_lemmatizer(nlp.lang)


def fetch_nlp_model(lang, spacy_model, lookup):
    lemma_lookup[lang] = lookup

    model = spacy.load(spacy_model)
    model.add_pipe("emoji", first=True)
    model.tokenizer = custom_tokenizer(lang, model)

    # Switch to non-trainable lemmatizer
    model.remove_pipe("lemmatizer")
    # Add non-trainable lemmatizer from language defaults
    # and load lemmatizer tables from spacy-lookups-data
    model.add_pipe("lemmatizer").initialize()

    model.add_pipe("custom_lemmatizer_factory", after="lemmatizer")

    return model
