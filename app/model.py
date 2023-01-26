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
from spacy.pipeline import Lemmatizer
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


def custom_lemmatizer(lemma_lookup):
    lemmatizer = TokenLemmatizer(lemma_lookup)

    lookups = Lookups()
    lookups.add_table("lemma_lookup", lemma_lookup)
    lemmatizer.lookups = lookups

    return lemmatizer


def custom_tokenizer(lang, nlp):
    if lang == "de":
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
                r"(?<=[{a}])([{q}\)\]\(\[])(?=[{a}])".format(
                    a=ALPHA, q=CONCAT_QUOTES.replace("'", "")
                ),
                r"(?<=[{a}])--(?=[{a}])".format(a=ALPHA),
                r"(?<=[0-9])-(?=[0-9])",
            ]
        )

        infix_re = compile_infix_regex(infixes)
    else:
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


@German.factory("custom_lemmatizer_de")
def custom_lemmatizer_de(nlp, name):
    lemma_lookup = {
        "international": "international",
        "internationale": "international",
        "Meister": "Meister",
        "abgebrüht": "abgebrüht",
        "beherrschend": "beherrschend",
        "entscheidend": "entscheidend",
        "entschlossen": "entschlossen",
        "angewiesen": "angewiesen",
        "besonnen": "besonnen",
        "betreut": "betreut",
        "bewegt": "bewegt",
        "einfühlend": "einfühlend",
        "engagiert": "engagiert",
        "entgegenkommend": "entgegenkommend",
        "ergreifend": "ergreifend",
        "gerührt": "gerührt",
        "heiter": "heiter",
        "lieb": "lieb",
        "liebe": "lieb",
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
        "ausgezeichnet": "ausgezeichnet",
        "beeindruckend": "beeindruckend",
        "beste": "beste",
        "bester": "beste",
        "besten": "beste",
        "bestem": "beste",
        "bestes": "beste",
        "etabliert": "etabliert",
        "fundiert": "fundiert",
        "gewandt": "gewandt",
        "Götter": "Götter",
        "hervorragend": "hervorragend",
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
        "gewagt": "gewagt",
        "herrschend": "herrschend",
        "o.Ä.": "o.Ä.",
        "offenbar": "offenbar",
        "schlicht": "schlicht",
        "sicher": "sicher",
        "treibend": "treibend",
        "u.Ä.": "u.Ä.",
        "u.ä.": "u.ä.",
        "zugegeben": "zugegeben",
        "(x)aaS": "(x)aaS",
        "AP/AR": "AP/AR",
        "Behinderte": "Behinderte",
        "Bisexuelle": "Bisexuelle",
        "Illegale": "Illegale",
        "P/E": "P/E",
        "Schädigungen": "Schädigungen",
        "behindert": "behindert",
        "versehrt": "versehrt",
        "aktive": "aktiv",
        "ambitionierte": "ambitioniert",
        "androsexuelle": "androsexuell",
        "angriffslustige": "angriffslustig",
        "anspruchsvolle": "anspruchsvoll",
        "asexuelle": "asexuell",
        "athletische": "athletisch",
        "aufstiegsorientierte": "aufstiegsorientiert",
        "augenscheinliche": "augenscheinlich",
        "augenöffnende": "augenöffnend",
        "autonome": "autonom",
        "autoritative": "autoritativ",
        "beeinträchtigte": "beeinträchtigt",
        "behinderte": "behindert",
        "behindertengerechte": "behindertengerecht",
        "berührte": "berührt",
        "bescheidene": "bescheiden",
        "bestimmte": "bestimmt",
        "betreute": "betreut",
        "bewegte": "bewegt",
        "bisexuelle": "bisexuell",
        "braune": "braun",
        "brillante": "brillant",
        "couragierte": "couragiert",
        "debile": "debil",
        "dienstleistungsorientierte": "dienstleistungsorientiert",
        "dumme": "dumm",
        "dunkelhäutige": "dunkelhäutig",
        "durchsetzungsfähige": "durchsetzungsfähig",
        "durchsetzungsstarke": "durchsetzungsstark",
        "ehrgeizige": "ehrgeizig",
        "eigensinnige": "eigensinnig",
        "eigenständige": "eigenständig",
        "eigenverantwortliche": "eigenverantwortlich",
        "eigenwillige": "eigenwillig",
        "emotionale": "emotional",
        "empathische": "empathisch",
        "engagierte": "engagiert",
        "enthusiastische": "enthusiastisch",
        "entscheidungsfreudige": "entscheidungsfreudig",
        "entschlussfreudige": "entschlussfreudig",
        "entspannte": "entspannt",
        "erfinderische": "erfinderisch",
        "erfindungsreiche": "erfindungsreich",
        "erfolgshungrige": "erfolgshungrig",
        "erprobte": "erprobt",
        "etablierte": "etabliert",
        "faire": "fair",
        "fantastische": "fantastisch",
        "feindselige": "feindselig",
        "flexibele": "flexibel",
        "freimütige": "freimütig",
        "freundliche": "freundlich",
        "fundierte": "fundiert",
        "fördernde": "fördernd",
        "fürsorgliche": "fürsorglich",
        "gefühlsbetonte": "gefühlsbetont",
        "gefühlsmässige": "gefühlsmässig",
        "gehandicapierte": "gehandicapiert",
        "gehandicapte": "gehandicapt",
        "gelbe": "gelb",
        "geldgierige": "geldgierig",
        "gemeinschaftliche": "gemeinschaftlich",
        "genderqueere": "genderqueer",
        "gestalterische": "gestalterisch",
        "gestresste": "gestresst",
        "glückliche": "glücklich",
        "grundsätzliche": "grundsätzlich",
        "handicapierte": "handicapiert",
        "hartnäckige": "hartnäckig",
        "herausfordernde": "herausfordernd",
        "herausgeforderte": "herausgefordert",
        "herausragende": "herausragend",
        "heteronormative": "heteronormativ",
        "heterosexistische": "heterosexistisch",
        "hoch-motivierte": "hoch-motiviert",
        "hochmotivierte": "hochmotiviert",
        "hochwertige": "hochwertig",
        "homofeindliche": "homofeindlich",
        "homonormative": "homonormativ",
        "hysterische": "hysterisch",
        "hörgeschädigte": "hörgeschädigt",
        "identifizierene": "identifizieren",
        "impulsive": "impulsiv",
        "individuelle": "individuell",
        "initiative": "initiativ",
        "inklusive": "inklusiv",
        "innovative": "innovativ",
        "integere": "integer",
        "intere": "inter",
        "intersektionale": "intersektional",
        "invalide": "invalid",
        "junge": "jung",
        "kollegiale": "kollegial",
        "kommunikative": "kommunikativ",
        "kompetitive": "kompetitiv",
        "konkurrenzbetonte": "konkurrenzbetont",
        "konkurrenzfähige": "konkurrenzfähig",
        "konstruktive": "konstruktiv",
        "kooperative": "kooperativ",
        "kreative": "kreativ",
        "kämpferische": "kämpferisch",
        "lahme": "lahm",
        "leistungsbereite": "leistungsbereit",
        "lesbische": "lesbisch",
        "liebliche": "lieblich",
        "logische": "logisch",
        "loyale": "loyal",
        "lösungsorientierte": "lösungsorientiert",
        "machthungrige": "machthungrig",
        "militante": "militant",
        "miteinandere": "miteinander",
        "mongoloide": "mongoloid",
        "motivierte": "motiviert",
        "männliche": "männlich",
        "nachgiebige": "nachgiebig",
        "nette": "nett",
        "neugierige": "neugierig",
        "neurodivergente": "neurodivergent",
        "neurotische": "neurotisch",
        "normale": "normal",
        "obligatorische": "obligatorisch",
        "offenherzige": "offenherzig",
        "pansexuelle": "pansexuell",
        "partnerschaftliche": "partnerschaftlich",
        "perfekte": "perfekt",
        "performante": "performant",
        "polyamore": "polyamor",
        "pro-aktive": "pro-aktiv",
        "proaktive": "proaktiv",
        "problematische": "problematisch",
        "queerfeministische": "queerfeministisch",
        "questioninge": "questioning",
        "resiliente": "resilient",
        "respektvolle": "respektvoll",
        "resultat-orientierte": "resultat-orientiert",
        "resultatorientierte": "resultatorientiert",
        "risikofreudige": "risikofreudig",
        "robuste": "robust",
        "rücksichtslose": "rücksichtslos",
        "sanfte": "sanft",
        "schwarze": "schwarz",
        "schwerbehinderte": "schwerbehindert",
        "schwerbeschädigte": "schwerbeschädigt",
        "schöpferische": "schöpferisch",
        "sehgeschädigte": "sehgeschädigt",
        "sehre": "sehr",
        "selbstbewusste": "selbstbewusst",
        "selbstsichere": "selbstsicher",
        "selbstständige": "selbstständig",
        "selbständige": "selbständig",
        "sensibele": "sensibel",
        "sportlerische": "sportlerisch",
        "sportliche": "sportlich",
        "starke": "stark",
        "stilsichere": "stilsicher",
        "straight-actinge": "straight-acting",
        "straightactinge": "straightacting",
        "streitene": "streiten",
        "streitlustige": "streitlustig",
        "streitsüchtige": "streitsüchtig",
        "sture": "stur",
        "stärkere": "stärker",
        "sympathische": "sympathisch",
        "taktvolle": "taktvoll",
        "taube": "taub",
        "teamfähige": "teamfähig",
        "teamorientierte": "teamorientiert",
        "transsexuelle": "transsexuell",
        "treue": "treu",
        "umoperierte": "umoperiert",
        "umsetzungsstarke": "umsetzungsstark",
        "umsichtige": "umsichtig",
        "unbeugsame": "unbeugsam",
        "unisexe": "unisex",
        "unnachgiebige": "unnachgiebig",
        "unternehmungsfreudige": "unternehmungsfreudig",
        "unwiderstehliche": "unwiderstehlich",
        "verlässliche": "verlässlich",
        "verrückte": "verrückt",
        "versehrte": "versehrt",
        "verständnisvolle": "verständnisvoll",
        "vertraute": "vertraut",
        "voneinandere": "voneinander",
        "vor-alleme": "vor-allem",
        "voralleme": "vorallem",
        "waghalsige": "waghalsig",
        "warme": "warm",
        "weibliche": "weiblich",
        "weltweite": "weltweit",
        "wettbewerbsfähige": "wettbewerbsfähig",
        "widerstandsfähige": "widerstandsfähig",
        "zarte": "zart",
        "zickige": "zickig",
        "zielorientierte": "zielorientiert",
        "zugetane": "zugetan",
        "zusammene": "zusammen",
        "zwingendermaßene": "zwingendermaßen",
        "zwischenmenschliche": "zwischenmenschlich",
        "äußerste": "äußerst",
        "Freundliche": "freundlich",
        "türken": "türken",
        "Höchstleistungen": "Höchstleistung",
        "Führungskräfte": "Führungskraft",
        "selbstständiger": "selbstständig",
        "Alter": "Alter",  # alt
        "Behinderte": "Behinderte",  # behindert
        "Bisexuelle": "Bisexuelle",  # Bisexueller
        "Bucklige": "Bucklige",  # bucklig
        "Illegale": "Illegale",  # illegal
        "Jeder": "Jeder",  # jed
        "Meister": "Meister",  # meist
        "Wilde": "Wilde",  # Wilder
        "andauernd": "andauernd",  # andauern
        "angreifend": "angreifend",  # angreifen
        "anscheinend": "anscheinend",  # anscheinen
        "auffallend": "auffallend",  # auffallen
        "aufstrebend": "aufstrebend",  # aufstreben
        "ausgeprägt": "ausgeprägt",  # ausprägen
        "ausgerechnet": "ausgerechnet",  # ausrechnen
        "ausgezeichnet": "ausgezeichnet",  # auszeichnen
        "beeindruckend": "beeindruckend",  # beeindrucken
        "beeinträchtigt": "beeinträchtigt",  # beeinträchtigen
        "beherrschend": "beherrschend",  # beherrschen
        "behindert": "behindert",  # behindern
        "beste": "beste",  # gut
        "bestimmend": "bestimmend",  # bestimmen
        "bestimmt": "bestimmt",  # bestimmen
        "einige": "einige",  # einig
        "entscheidend": "entscheidend",  # entscheiden
        "entschieden": "entschieden",  # entscheiden
        "entschlossen": "entschlossen",  # entschließen
        "erprobt": "erprobt",  # erproben
        "etabliert": "etabliert",  # etablieren
        "etliche": "etliche",  # etlich
        "fortwährend": "fortwährend",  # fortwähren
        "fundiert": "fundiert",  # fundieren
        "führen": "führen",  # fahren
        "führend": "führend",  # führen
        "geschädigt": "geschädigt",  # schädigen
        "gewagt": "gewagt",  # wagen
        "gewandt": "gewandt",  # wenden
        "herrschend": "herrschend",  # herrschen
        "hervorragend": "hervorragend",  # hervorragen
        "kämpfend": "kämpfend",  # kämpfen
        "offenbar": "offenbar",  # offenbaren
        "schlicht": "schlicht",  # schleichen
        "stärker": "stärker",  # stark
        "treibend": "treibend",  # treiben
        "verrückt": "verrückt",  # verrücken
        "versehrt": "versehrt",  # versehren
        "zugegeben": "zugegeben",  # zugeben
        "zwingend": "zwingend",  # zwingen
        "äußerst": "äußerst",  # äußern
        "überfordert": "überfordert",  # überfordern
        "überzeugend": "überzeugend",  # überzeugen
        "überzeugt": "überzeugt",  # überzeugen
    }

    return custom_lemmatizer(lemma_lookup)


@English.factory("custom_lemmatizer_en")
def custom_lemmatizer_en(nlp, name):
    lemma_lookup = {
        "Bin-Laden": "Bin-Laden",
        "Binladen": "Binladen",
        "Buckwheat": "Buckwheat",
        "Cervix-haver": "Cervix-haver",
        "Cervixhaver": "Cervixhaver",
        "Congressman": "Congressman",
        "Euro-weenies": "Euro-weenies",
        "Euroweenies": "Euroweenies",
        "Jewbacca": "Jewbacca",
        "Jewgene": "Jewgene",
        "Sincerely": "Sincerely",
        "able-bodied": "able-bodied",
        "ablebodied": "ablebodied",
        "afro-saxon": "afro-saxon",
        "ages": "ages",
        "attention-seeking": "attention-seeking",
        "attentionseeking": "attentionseeking",
        "battle-axe": "battle-axe",
        "bean-eater": "bean-eater",
        "bean-flicker": "bean-flicker",
        "bin-Laden": "bin-Laden",
        "bin-laden": "bin-laden",
        "blind-sided": "blind-sided",
        "brain-damaged": "brain-damaged",
        "braindamaged": "braindamaged",
        "bum-boy": "bum-boy",
        "bum-chum": "bum-chum",
        "bum-driller": "bum-driller",
        "bum-robber": "bum-robber",
        "bumhole-engineer": "bumhole-engineer",
        "butt-boy": "butt-boy",
        "butt-fruit": "butt-fruit",
        "butt-pilot": "butt-pilot",
        "butt-pirate": "butt-pirate",
        "butt-rider": "butt-rider",
        "butt-rustler": "butt-rustler",
        "bøsser": "bøsser",
        "chi-chi-man": "chi-chi-man",
        "cis-gender": "cis-gender",
        "cis-gendered": "cis-gendered",
        "cisgendered": "cisgendered",
        "code-switching": "code-switching",
        "codeswitching": "codeswitching",
        "conquest": "conquest",
        "crafty-butcher": "crafty-butcher",
        "crick-crick": "crick-crick",
        "cunt-boy": "cunt-boy",
        "deaf-mute": "deaf-mute",
        "deformed": "deformed",
        "deranged": "deranged",
        "determined": "determined",
        "disabled": "disabled",
        "disfigured": "disfigured",
        "donut-muncher": "donut-muncher",
        "donut-puncher": "donut-puncher",
        "enlightened": "enlightened",
        "every-man": "every-man",
        "extra-ordinary": "extra-ordinary",
        "eye-opener": "eye-opener",
        "feebleminded": "feebleminded",
        "first-class": "first-class",
        "first-mover": "first-mover",
        "flat-face": "flat-face",
        "flat-head": "flat-head",
        "flatter": "flatter",
        "flattering": "flattering",
        "fog-breather": "fog-breather",
        "front-runner": "front-runner",
        "fruit-loop": "fruit-loop",
        "fruit-packer": "fruit-packer",
        "fudge-packer": "fudge-packer",
        "fulfilling": "fulfilling",
        "go-getter": "go-getter",
        "goal-getter": "goal-getter",
        "gogetter": "gogetter",
        "grandfathered": "grandfathered",
        "greaser": "greaser",
        "gun-man": "gun-man",
        "gym-bunny": "gym-bunny",
        "gypped": "gypped",
        "half-breed": "half-breed",
        "half-caste": "half-caste",
        "head-strong": "head-strong",
        "hearing-impaired": "hearing-impaired",
        "hearingimpaired": "hearingimpaired",
        "herp-derp": "herp-derp",
        "high-flyer": "high-flyer",
        "hooch-cooch": "hooch-cooch",
        "hyper-active": "hyper-active",
        "hyper-sensitive": "hyper-sensitive",
        "inbred": "inbred",
        "incapacitated": "incapacitated",
        "indian-giver": "indian-giver",
        "inter-dependence": "inter-dependence",
        "inter-dependent": "inter-dependent",
        "inter-personal": "inter-personal",
        "job-sharing": "job-sharing",
        "jobsharing": "jobsharing",
        "kitty-puncher": "kitty-puncher",
        "knife-nose": "knife-nose",
        "les": "les",
        "limp-wristed": "limp-wristed",
        "limpwristed": "limpwristed",
        "man-bag": "man-bag",
        "man-bun": "man-bun",
        "man-day": "man-day",
        "man-hour": "man-hour",
        "man-hunt": "man-hunt",
        "man-kini": "man-kini",
        "man-made": "man-made",
        "man-power": "man-power",
        "man-scara": "man-scara",
        "man-sized": "man-sized",
        "man-to-man": "man-to-man",
        "man-trap": "man-trap",
        "mansized": "mansized",
        "market-leader": "market-leader",
        "mentoring": "mentoring",
        "micro-aggression": "micro-aggression",
        "middle-man": "middle-man",
        "must-have": "must-have",
        "opinionated": "opinionated",
        "over-the-hill": "over-the-hill",
        "pow-wow": "pow-wow",
        "pro-active": "pro-active",
        "pussy-puncher": "pussy-puncher",
        "result-oriented": "result-oriented",
        "resultoriented": "resultoriented",
        "results-oriented": "results-oriented",
        "resultsoriented": "resultsoriented",
        "risk-taker": "risk-taker",
        "self-confidence": "self-confidence",
        "self-confident": "self-confident",
        "self-reliance": "self-reliance",
        "self-reliant": "self-reliant",
        "self-sufficiency": "self-sufficiency",
        "self-sufficient": "self-sufficient",
        "sharing": "sharing",
        "slant-eye": "slant-eye",
        "spazzed": "spazzed",
        "state-of-the-art": "state-of-the-art",
        "switch-hitter": "switch-hitter",
        "taco-head": "taco-head",
        "team-player": "team-player",
        "thicklips": "thicklips",
        "top-performer": "top-performer",
        "top-performance": "top-performance",
        "top-performing": "top-performing",
        "trans-man": "trans-man",
        "trans-woman": "trans-woman",
        "under-represented": "under-represented",
        "uterus-havers": "uterus-havers",
        "well-established": "well-established",
        "wellestablished": "wellestablished",
        "wheelchair-bound": "wheelchair-bound",
        "world-wide": "world-wide",
        "greed": "greed",
        "surpass": "surpass",
        "best": "best",  # well
        "bonkers": "bonkers",  # bonker
        "challenging": "challenging",  # challenge
        "compelling": "compelling",  # compel
        "dim-witted": "dim-witted",  # dim-witte
        "dimwitted": "dimwitted",  # dimwitte
        "feeble-minded": "feeble-minded",  # feeble-minde
        "gals": "gals",  # gal
        "gramps": "gramps",  # gramp
        "grandfathering": "grandfathering",  # grandfathere
        "manwards": "manwards",  # manward
        "market-leading": "market-leading",  # market-leade
        "marketleading": "marketleading",  # marketleade
        "nuts": "nuts",  # nut
        "performance-based": "performance-based",  # performance-base
        "performancebased": "performancebased",  # performancebase
        "redlining": "redlining",  # redline
        "risk-taking": "risk-taking",  # risk-take
        "risktaking": "risktaking",  # risktake
        "scatterbrained": "scatterbrained",  # scatterbraine
        "self-motivated": "self-motivated",  # self-motivate
        "selfmotivated": "selfmotivated",  # selfmotivate
        "special-needs": "special-needs",  # special-need
        "specialneeds": "specialneeds",  # specialneed
        "strong-minded": "strong-minded",  # strong-minde
        "strongminded": "strongminded",  # strongminde
        "tongue-tied": "tongue-tied",  # tongue-tie
        "tonguetied": "tonguetied",  # tonguetie
        "top-performing": "top-performing",  # top-performe
        "topperforming": "topperforming",  # topperforme
        "uterushavers": "uterushavers",  # uterushaver
    }

    return custom_lemmatizer(lemma_lookup)


def fetch_nlp_model(lang, spacy_model):
    model = spacy.load(spacy_model)
    model.tokenizer = custom_tokenizer(lang, model)

    # Switch to non-trainable lemmatizer
    model.remove_pipe("lemmatizer")
    # Add non-trainable lemmatizer from language defaults
    # and load lemmatizer tables from spacy-lookups-data
    model.add_pipe("lemmatizer").initialize()

    model.add_pipe("custom_lemmatizer_" + lang, after="lemmatizer")

    return model
