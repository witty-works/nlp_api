import spacy
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

# Custom tokenizers
# English
def custom_tokenizer_en(nlp):
    infixes = (
        LIST_ELLIPSES
        + LIST_ICONS
        + [
            r"(?<=[0-9])[+\-\*^](?=[0-9-])",
            r"(?<=[{al}{q}])\.(?=[{au}{q}])".format(
                al=ALPHA_LOWER, au=ALPHA_UPPER, q=CONCAT_QUOTES
            ),
            r"(?<=[{a}]),(?=[{a}])".format(a=ALPHA),
            # hyphen excluded from separators
            # r"(?<=[{a}])(?:{h})(?=[{a}])".format(a=ALPHA, h=HYPHENS),
            r"(?<=[{a}0-9])[:<>=/](?=[{a}])".format(a=ALPHA),
        ]
    )

    infix_re = compile_infix_regex(infixes)

    return Tokenizer(
        nlp.vocab,
        prefix_search=nlp.tokenizer.prefix_search,
        suffix_search=nlp.tokenizer.suffix_search,
        infix_finditer=infix_re.finditer,
        token_match=nlp.tokenizer.token_match,
        rules=nlp.Defaults.tokenizer_exceptions,
    )


# German
def custom_tokenizer_de(nlp):
    _quotes = CONCAT_QUOTES.replace("'", "")
    infixes = (
        LIST_ELLIPSES
        + LIST_ICONS
        + [
            r"(?<=[{al}])\.(?=[{au}])".format(al=ALPHA_LOWER, au=ALPHA_UPPER),
            r"(?<=[{a}])[,!?](?=[{a}])".format(a=ALPHA),
            # removed : [:<>=]
            r"(?<=[{a}])[<>=](?=[{a}])".format(a=ALPHA),
            r"(?<=[{a}]),(?=[{a}])".format(a=ALPHA),
            r"(?<=[0-9{a}])\/(?=[0-9{a}])".format(a=ALPHA),
            r"(?<=[{a}])([{q}\)\]\(\[])(?=[{a}])".format(a=ALPHA, q=_quotes),
            r"(?<=[{a}])--(?=[{a}])".format(a=ALPHA),
            r"(?<=[0-9])-(?=[0-9])",
        ]
    )

    infix_re = compile_infix_regex(infixes)

    return Tokenizer(
        nlp.vocab,
        prefix_search=nlp.tokenizer.prefix_search,
        suffix_search=nlp.tokenizer.suffix_search,
        infix_finditer=infix_re.finditer,
        token_match=nlp.tokenizer.token_match,
        rules=nlp.Defaults.tokenizer_exceptions,
    )


# Model data
model = {"en": spacy.load("en_core_web_sm"), "de": spacy.load("de_core_news_sm")}

# custom tokenizer for English
model["en"].tokenizer = custom_tokenizer_en(model["en"])

# custom tokenizer for German
model["de"].tokenizer = custom_tokenizer_de(model["de"])

# custom lematizer to correct the lemmas in spacy library, to add to the curent spacy lematizer
dict_lemma_lookup = {
    "international": "international",
    "internationale": "international",
    "Meister": "Meister",
    "kämpfend": "kämpfend",
    "abgebrüht": "abgebrüht",
    "beherrschend": "beherrschend",
    "entscheidend": "entscheidend",
    "entschlossen": "entschlossen",
    "angewiesen": "angewiesen",
    "berührt": "berührt",
    "besonnen": "besonnen",
    "betreut": "betreut",
    "bewegt": "bewegt",
    "einfühlend": "einfühlend",
    "engagiert": "engagiert",
    "entgegenkommend": "entgegenkommend",
    "ergreifend": "ergreifend",
    "fördernd": "fördernd",
    "gerührt": "gerührt",
    "heiter": "heiter",
    "lieb": "lieb",
    "mitfühlend": "mitfühlend",
    "mitwirkend": "mitwirkend",
    "motiviert": "motiviert",
    "nährend": "nährend",
    "teilnehmend": "teilnehmend",
    "unterstützend": "unterstützend",
    "verbindend": "verbindend",
    "vermittelnd": "vermittelnd",
    "vertraut": "vertraut",
    "weich": "weich",
    "zusammenhängend": "zusammenhängend",
    "zusammenwirkend": "zusammenwirkend",
    "zustimmend": "zustimmend",
    "jünger": "jünger",
    "ausgeprägt": "ausgeprägt",
    "ausgezeichnet": "ausgezeichnet",
    "äußerst": "äußerst",
    "beeindruckend": "beeindruckend",
    "beste": "beste",
    "bester": "beste",
    "besten": "beste",
    "bestem": "beste",
    "bestes": "beste",
    "etabliert": "etabliert",
    "führend": "führend",
    "fundiert": "fundiert",
    "gewandt": "gewandt",
    "Götter": "Götter",
    "hervorragend": "hervorragend",
    "überzeugend": "überzeugend",
    "zwingend": "zwingend",
    "Alter": "Alter",
    "Bucklige": "Bucklige",
    "Grundsätze": "Grundsätze",
    "Herrschaften": "Herrschaften",
    "Jeder": "Jeder",
    "Kanus": "Kanus",
    "Spitzenunternehmen ": "Spitzenunternehmen",
    "Trampel": "Trampel",
    "Wettkämpfe": "Wettkämpfe",
    "Wilde": "Wilde",
    "Zusammenhänge": "Zusammenhänge",
    "andauernd": "andauernd",
    "angreifend": "angreifend",
    "anscheinend": "anscheinend",
    "auffallend": "auffallend",
    "aufstrebend": "aufstrebend",
    "ausgerechnet": "ausgerechnet",
    "bestimmend": "bestimmend",
    "bestimmt": "bestimmt",
    "einige": "einige",
    "entschieden": "entschieden",
    "entspannt": "entspannt",
    "erfüllend": "erfüllend",
    "ermutigend": "ermutigend",
    "erprobt": "erprobt",
    "etliche": "etliche",
    "fortwährend": "fortwährend",
    "führen": "führen",
    "gewagt": "gewagt",
    "herrschend": "herrschend",
    "o.Ä.": "o.Ä.",
    "offenbar": "offenbar",
    "schlicht": "schlicht",
    "sicher": "sicher",
    "stärker": "stärker",
    "treibend": "treibend",
    "u.Ä.": "u.Ä.",
    "u.ä.": "u.ä.",
    "zugegeben": "zugegeben",
    "überzeugt": "überzeugt",
}

lookup_table = model["de"].get_pipe("lemmatizer").lookups.get_table("lemma_lookup")
for key in dict_lemma_lookup:
    lookup_table.set(key, dict_lemma_lookup[key])
