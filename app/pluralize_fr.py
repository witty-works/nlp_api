# Code taken from https://github.com/sblondon/pluralizefr/blob/da2b525bfadde87b408d0a7f290c8892f1fc8726/pluralizefr/__init__.py License: BSD-3-Clause license

"""Pluralize word according French grammar rules

Special cases are based on:
http://fr.wiktionary.org/wiki/Annexe:Pluriels_irr%C3%A9guliers_en_fran%C3%A7ais
"""


def pluralize(word, is_masculine=True):
    if word.startswith("grand-") and is_masculine:
        word = "grands-" + word[6:]

    for GRAMMAR_RULE in (
        _ail_word,
        _al_word,
        _au_word,
        _eil_word,
        _eu_word,
        _ou_word,
        _s_word,
        _x_word,
        _z_word,
        _default,
    ):
        plural = GRAMMAR_RULE(word)
        if plural:
            return plural


def _ail_word(word):
    if word.endswith("ail"):
        if word == "ail":
            return "aulx"
        elif word in (
            "bail",
            "corail",
            "émail",
            "fermail",
            "soupirail",
            "travail",
            "vantail",
            "ventail",
            "vitrail",
        ):
            return word[:-3] + "aux"
        return word + "s"


def _al_word(word):
    if word.endswith("al"):
        if word in (
            "bal",
            "carnaval",
            "chacal",
            "festival",
            "récital",
            "régal",
            "bancal",
            "fatal",
            "fractal",
            "final",
            "morfal",
            "natal",
            "naval",
            "aéronaval",
            "anténatal",
            "néonatal",
            "périnatal",
            "postnatal",
            "prénatal",
            "tonal",
            "atonal",
            "bitonal",
            "polytonal",
            "corral",
            "deal",
            "goal",
            "autogoal",
            "revival",
            "serial",
            "spiritual",
            "trial",
            "caracal",
            "chacal",
            "gavial",
            "gayal",
            "narval",
            "quetzal",
            "rorqual",
            "serval",
            "metical",
            "rial",
            "riyal",
            "ryal",
            "cantal",
            "emmental",
            "emmenthal",
            "floréal",
            "germinal",
            "prairial",
        ):
            return word + "s"
        return word[:-2] + "aux"


def _au_word(word):
    if word.endswith("au"):
        if word in ("berimbau", "donau", "karbau", "landau", "pilau", "sarrau", "unau"):
            return word + "s"
        return word + "x"


def _eil_word(word):
    if word.endswith("eil"):
        return "vieux" if word == "vieil" else word + "s"


def _eu_word(word):
    if word.endswith("eu"):
        if word in ("bleu", "émeu", "enfeu", "pneu", "rebeu"):
            return word + "s"
        return word + "x"


def _ou_word(word):
    if word.endswith("ou"):
        if word in ("bijou", "caillou", "chou", "genou", "hibou", "joujou", "pou"):
            return word + "x"
        return word + "s"


def _s_word(word):
    if word[-1] == "s":
        return word


def _x_word(word):
    if word[-1] == "x":
        return word


def _z_word(word):
    if word[-1] == "z":
        return word


def _default(word):
    return word + "s"


def singularize(word):
    for GRAMMAR_RULE in (
        _eau_word_sing,
        _ail_word_sing,
        _eil_word_sing,
        _eu_word_sing,
        _ou_word_sing,
        _s_word_sing,
        _default_sing,
    ):
        singular = GRAMMAR_RULE(word)
        if singular:
            return singular


def _eau_word_sing(word):
    if word.endswith("eaux"):
        return word[:-1]


def _ail_word_sing(word):
    if word == "aulx":
        return "ail"
    if word.endswith("aux"):
        if word in (
            "baux",
            "coraux",
            "émaux",
            "fermaux",
            "soupiraux",
            "travaux",
            "vantaux",
            "ventaux",
            "vitraux",
        ):
            return word[:-3] + "ail"
        else:
            return word[:-3] + "al"


def _eil_word_sing(word):
    if word == "vieux":
        return "vieil"


def _eu_word_sing(word):
    if word.endswith("eus") or word.endswith("eux"):
        return word[:-1]


def _ou_word_sing(word):
    if word.endswith("oux"):
        if word in (
            "bijoux",
            "cailloux",
            "choux",
            "genoux",
            "hiboux",
            "joujoux",
            "poux",
        ):
            return word[:-1]
        else:
            return word


def _s_word_sing(word):
    if word.endswith("s"):
        if word in (
            "abcès",
            "accès",
            "abus",
            "albatros",
            "anchois",
            "anglais",
            "autobus",
            "brebis",
            "carquois",
            "cas",
            "chas",
            "colis",
            "concours",
            "corps",
            "cours",
            "cyprès",
            "décès",
            "devis",
            "discours",
            "dos",
            "embarras",
            "engrais",
            "entrelacs",
            "excès",
            "fois",
            "fonds",
            "gâchis",
            "gars",
            "glas",
            "guet-apens",
            "héros",
            "intrus",
            "jars",
            "jus",
            "kermès",
            "lacis",
            "legs",
            "lilas",
            "marais",
            "matelas",
            "mépris",
            "mets",
            "mois",
            "mors",
            "obus",
            "os",
            "palais",
            "paradis",
            "parcours",
            "pardessus",
            "pays",
            "plusieurs",
            "poids",
            "pois",
            "pouls",
            "printemps",
            "processus",
            "progrès",
            "puits",
            "pus",
            "rabais",
            "radis",
            "recors",
            "recours",
            "refus",
            "relais",
            "remords",
            "remous",
            "rhinocéros",
            "repas",
            "rubis",
            "sas",
            "secours",
            "souris",
            "succès",
            "talus",
            "tapis",
            "taudis",
            "temps",
            "tiers",
            "univers",
            "velours",
            "verglas",
            "vernis",
            "virus",
            "accordailles",
            "affres",
            "aguets",
            "alentours",
            "ambages",
            "annales",
            "appointements",
            "archives",
            "armoiries",
            "arrérages",
            "arrhes",
            "calendes",
            "cliques",
            "complies",
            "condoléances",
            "confins",
            "dépens",
            "ébats",
            "entrailles",
            "épousailles",
            "errements",
            "fiançailles",
            "frais",
            "funérailles",
            "gens",
            "honoraires",
            "matines",
            "mœurs",
            "obsèques",
            "pénates",
            "pierreries",
            "préparatifs",
            "relevailles",
            "rillettes",
            "sévices",
            "ténèbres",
            "thermes",
            "us",
            "vêpres",
            "victuailles",
        ):
            return word
        else:
            return word[:-1]


def _default_sing(word):
    return word
