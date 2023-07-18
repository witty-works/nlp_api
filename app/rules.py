import pandas as pd
import ast
from collections import namedtuple
from german_nouns.lookup import Nouns
from app.models import LangWithAutoType
import re


def build_rules(
    model,
    df,
    plural=False,
    postfix=False,
    secondary_subcategory=False,
    false_positives=False,
    filter_base=None,
):
    df_rules = [] if filter_base is True else {}

    for i, lemma in enumerate(df["Lemma"]):
        words = [i.text for i in model.tokenizer(lemma)]
        word_types = df["Word_Type"][i].split("|")

        rule = [
            lemma,
            words,
            word_types,
        ]

        if "Primary_subcategory" in df:
            if filter_base is False and "_base" in df["Primary_subcategory"][i]:
                continue

            rule.append(df["Primary_subcategory"][i])

        singular_key = "Sg_all_split" if plural else "Alt_split"
        if singular_key in df:
            rule.append(ast.literal_eval(df[singular_key][i]))

        if plural:
            rule.append(ast.literal_eval(df["Pl_all_split"][i]))

        if secondary_subcategory:
            rule.append(df["Secondary_subcategory"][i])

        if false_positives:
            rule.append(ast.literal_eval(df["False_Positives"][i]))

        if filter_base is True:
            df_rules.append(rule)
            continue

        key = words[0].lower()
        if postfix and "_base" in df["Primary_subcategory"][i]:
            # shortest base word, "Arzt"
            key = key[-4:]

        if key in df_rules:
            df_rules[key].append(rule)
        else:
            df_rules[key] = [rule]

    return df_rules


def fetch_rules(model):
    files = {
        "de": {
            # load Gender (nouns, not nouns) and sentences de
            "df_gender_ct": "gendered_noun_words.csv",
            "df_gender_no_noun_word": "gendered_no_noun_words.csv",
            # load articles for gendered denom
            "df_articles": "articles.csv",
            # load style words
            "df_style_word": "style_words.csv",
            # load openly discriminating words de
            "df_open_dis_word": "open_dis_words.csv",
            # load unconscious_bias word (nouns with plurals and nouns, adj, verbs without plural) and sentences de
            "df_ub_plur_word": "ub_plur_words.csv",
            "df_ub_no_plur_word": "ub_no_plur_words.csv",
            # load inslusive words
            "df_d_and_i_words": "d_and_i_words.csv",
            # load communal coded terms
            "df_communal_words": "communal.csv",
            # load gender false positive
            "df_gender_false_positive": "gender_false_positive.csv",
            # load abbreviations
            "df_abbreviation": "abbreviations.csv",
            # verbs
            "verbs": "verbs.csv",
        },
        "en": {
            # load openly discriminating words
            "df_open_dis_word": "open_dis_words.csv",
            "df_open_dis_sentence": "open_dis_sentences.csv",
            # load inclusive language
            "df_inclusive_word": "inclusive_words.csv",
            "df_inclusive_sentence": "inclusive_sentences.csv",
            # load style words
            "df_style_no_noun_word": "style_no_noun_words.csv",
            "df_style_noun_word": "style_noun_words.csv",
            "df_style_sentence": "style_sentences.csv",
            # load gendered language
            "df_gendered_no_noun_word": "gendered_no_noun_words.csv",
            "df_gendered_sentence": "gendered_sentences.csv",
            "df_gendered_noun_word": "gendered_noun_words.csv",
            # load unconscious_bias word (nouns with sing/plural, other words (nouns without sing/plur, verb, adj, adv)) and sentences en
            "df_ub_plur_word": "ub_plur_words.csv",
            "df_ub_no_plur_word": "ub_no_plur_words.csv",
            "df_ub_sentence": "ub_sentences.csv",
            "df_ub_singular_they": "ub_singular_they.csv",
            # load homonyms
            "df_homonyms_words": "homonyms_words.csv",
            # load abbreviations
            "df_abbreviation": "abbreviations.csv",
        },
    }

    rules = {
        "m_f_regexes": [
            # (m/f..)
            [
                re.compile(r"^m/(f|w)(\/[*a-z])*(\))?$", re.IGNORECASE),
                "0,7,/",
                "gender_specific_abbreviation",
            ],
            # (f/m..)
            [
                re.compile(r"^(f|w)/m(\/[*a-z])*(\))?$", re.IGNORECASE),
                "0,7,/",
                "gender_specific_abbreviation",
            ],
        ],
        # (d/f/m/v)
        "d_f_m_regexes": [
            [
                re.compile(r"^(d|x|\*)(/v)?/f(/v)?/m(/v)?$", re.IGNORECASE),
                "0,7,/",
                "d_and_i",
            ],
        ],
        "skin_tones": {
            "all": [
                "",
                "_dark_skin_tone",
                "_medium_skin_tone",
                "_medium-dark_skin_tone",
                "_medium-light_skin_tone",
            ],
            "full": [
                "_dark_skin_tone",
                "_medium_skin_tone",
                "_medium-dark_skin_tone",
                "_medium-light_skin_tone",
            ],
            "minimal": [
                "_dark_skin_tone",
                "_medium_skin_tone",
            ],
        },
        "emoji": {
            "group_gender_and": {
                "skin_tone": True,
                "subcategory": {
                    "sexual_orientation": [
                        "people",
                        "women",
                        "men",
                    ],
                },
                "rules": [
                    "woman_and_man",
                    "man_and_woman",
                ],
            },
            "group_gender": {
                "skin_tone": True,
                "subcategory": {
                    "sexual_orientation": [
                        "woman_woman",
                        "man_man",
                    ],
                },
                "rules": [
                    "woman_man",
                    "man_woman",
                ],
            },
            "person_gender": {
                "skin_tone": True,
                "subcategory": {
                    "gender_identity": [
                        "person",
                    ],
                },
                "rules": [
                    "woman",
                    "man",
                ],
            },
            "child_gender": {
                "skin_tone": True,
                "subcategory": {
                    "gender_identity": [
                        "child",
                    ]
                },
                "rules": [
                    "boy",
                    "girl",
                ],
            },
            "culture_food": {
                "skin_tone": False,
                "subcategory": {
                    "culture": [
                        "green_salad",
                        "falafel",
                        "dumpling",
                        "bento",
                        "curry",
                        "taco",
                        "stuffed_flatbread",
                    ],
                },
                "rules": [
                    "french_fries",
                    "hamburger",
                    "bacon",
                    "meat_on_bone",
                    "hotdog",
                    "cut_of_meat",
                ],
            },
            "culture_cutlery": {
                "skin_tone": False,
                "subcategory": {
                    "culture": [
                        "chopsticks",
                    ],
                },
                "rules": [
                    "fork_and_knife",
                    "spoon",
                ],
            },
            "culture_hotdrink": {
                "skin_tone": False,
                "subcategory": {
                    "culture": [
                        "teapot",
                        "tea",
                    ],
                },
                "rules": [
                    "coffee",
                ],
            },
            "culture_softdrink": {
                "skin_tone": False,
                "subcategory": {
                    "culture": [
                        "bubble_tea",
                        "beverage_box",
                        "glass_of_milk",
                    ],
                },
                "rules": [
                    "cup_with_straw",
                    "tropical_drink",
                    "beer",
                    "beers",
                    "wine_glass",
                ],
            },
            "culture_sport": {
                "skin_tone": False,
                "subcategory": {
                    "sports_terms": [
                        "cricket_game",
                        "boomerang",
                        "ping_pong",
                        "rugby_football",
                        "rugby_football",
                        "lacrosse",
                        "flying_disc",
                    ],
                },
                "rules": [
                    "american_football",
                    "soccer",
                    "baseball",
                    "basketball",
                    "tennis",
                    "volleyball",
                    "field_hockey",
                    "ice_hockey",
                    "ice_skate",
                ],
            },
            "religion_symbols": {
                "skin_tone": False,
                "subcategory": {
                    "belief": [
                        "place_of_worship",
                        "menorah",
                        "om",
                        "orthodox_cross",
                        "star_and_crescent",
                        "star_of_david",
                        "wheel_of_dharma",
                    ],
                },
                "rules": [
                    "latin_cross",
                ],
            },
            "religion_buildings": {
                "skin_tone": False,
                "subcategory": {
                    "belief": [
                        "synagogue",
                        "mosque",
                        "hindu_temple",
                    ],
                },
                "rules": [
                    "church",
                ],
            },
            "parent_feeding": {
                "skin_tone": True,
                "subcategory": {
                    "sexual_orientation": [
                        "person_feeding_baby",
                        "man_feeding_baby",
                    ],
                },
                "rules": [
                    "feeding_baby",
                ],
            },
            "parent_pregnant": {
                "skin_tone": True,
                "subcategory": {
                    "sexual_orientation": [
                        "pregnant_person",
                        "pregnant_man",
                    ],
                },
                "rules": [
                    "pregnant_woman",
                ],
            },
            "advanced_person": {
                "skin_tone": True,
                "subcategory": {
                    "advanced_hearing": [
                        "deaf_person",
                    ],
                    "advanced_belief": [
                        "woman_with_headscarf",
                        "man_with_turban",
                    ],
                    "advanced_vision": [
                        "person_with_white_cane",
                    ],
                    "advanced_ability": [
                        "person_in_manual_wheelchair",
                    ],
                    "advanced_age_old": [
                        "older_person",
                    ],
                    "advanced_age_young": [
                        "child",
                    ],
                },
                "rules": [
                    "person",
                ],
            },
        },
    }

    locales = {
        "de": [LangWithAutoType.DE],
        "en": [LangWithAutoType.enUS, LangWithAutoType.enGB],
    }

    langs = model.keys()

    data = {}
    for lang in langs:
        rules[lang] = {}
        for locale in locales[lang]:
            rules[locale] = data[locale] = {}
            for csv in files[lang]:
                data[locale][csv] = pd.read_csv(
                    "training_data/" + locale + "/" + files[lang][csv],
                    keep_default_na=False,
                )

    if "de" in langs:
        lang = "de"

        rules["de"]["hashtags"] = [
            # "#foobar"
            [
                re.compile(r"^#(?!.*[A-Z])\w\w\w\w\w+$"),
                "1,2,#",
                "style",
                [],
                {
                    "text": "Wenn du Wörter großschreibst, wissen alle gleich, was du meinst. #ZumBeispiel"
                },
            ],
        ]

        rules["de"]["context_check"] = []

        rules["de"]["verbs"] = {
            data["de"]["verbs"]["infinitiv"][i]: {
                "past_participle": data["de"]["verbs"]["past_participle"][i],
                "infinitiv_zu": data["de"]["verbs"]["infinitiv_zu"][i],
                "present_ich": data["de"]["verbs"]["present_ich"][i],
            }
            for i in range(len(data["de"]["verbs"]["infinitiv"]))
        }
        # list of "df_communal_words" words
        rules["de"]["communal_words"] = build_rules(
            model[lang], data["de"]["df_communal_words"]
        )

        # list of "df_d_and_i_words" words
        rules["de"]["d_and_i_words"] = build_rules(
            model[lang], data["de"]["df_d_and_i_words"]
        )

        # dictionaries to handle false positives
        false_positive = namedtuple("FalsePositive", "gender style")
        rules["de"]["false_positives"] = false_positive(
            data["de"]["df_gender_false_positive"]["False_positives"],
            ["international"],
        )

        rules["de"]["exceptions"] = [
            "Unternehmen",
            "Firma",
            "Gruppe",
            "Gesellschaft",
            "Kollektivgesellschaft",
            "Team",
            "Organization",
            "Gliederung",
        ]

        ### de-DE:
        rules["de"]["gender_words_data"] = build_rules(
            model[lang], data["de"]["df_gender_ct"], plural=True, postfix=True
        )

        # df gendered no noun
        # gendered: words + alternatives split + subcategory
        rules["de"]["gender_words_data_no_noun"] = build_rules(
            model[lang], data["de"]["df_gender_no_noun_word"]
        )

        # articles
        rules["de"]["articles"] = list(
            zip(
                data["de"]["df_articles"]["Form"],
                data["de"]["df_articles"]["Masculine"],
                data["de"]["df_articles"]["Feminine"],
                data["de"]["df_articles"]["Neuter"],
                data["de"]["df_articles"]["Plural"],
                data["de"]["df_articles"]["Alternative"],
            )
        )
        rules["de"]["male_articles"] = list(data["de"]["df_articles"]["Masculine"])
        rules["de"]["female_articles"] = list(data["de"]["df_articles"]["Feminine"])

        # df unconscious bias nouns with plural
        # unconscious bias: words + singular alternatives split + plural alternatives split + subcategory
        rules["de"]["bias_words_data_noun"] = build_rules(
            model[lang], data["de"]["df_ub_plur_word"], plural=True
        )

        # df unconscious bias words without plurals
        rules["de"]["bias_words_data_no_plur"] = build_rules(
            model[lang], data["de"]["df_ub_no_plur_word"]
        )

        # df style
        # style: words + alternatives + subcategory
        rules["de"]["style_words_data"] = build_rules(
            model[lang], data["de"]["df_style_word"]
        )
        # df open discrimination words
        # open discrimination: words + alternative_split + subcategory
        rules["de"]["open_disc_words_data"] = build_rules(
            model[lang],
            data["de"]["df_open_dis_word"],
            false_positives=True,
            filter_base=False,
        )
        rules["de"]["open_disc_words_data_base"] = build_rules(
            model[lang],
            data["de"]["df_open_dis_word"],
            false_positives=True,
            filter_base=True,
        )

        # df abbreviation
        rules["de"]["abbreviation"] = build_rules(
            model[lang], data["de"]["df_abbreviation"]
        )

        rules["de"]["primary_german_genus_endings"] = {
            "n": [
                "chen",
                "ett",
                "eau",
                "lein",
                "icht",
                "il",
                "ium",
                "it",
                "ma",
                "ment",
                "tel",
                "tum",
                "um",
            ],
            "f": [
                "in",
                "a",
                "ade",
                "age",
                "anz",
                "elle",
                "ette",
                "ere",
                "enz",
                "ei",
                "ine",
                "isse",
                "itis",
                "ive",
                "ie",
                "heit",
                "keit",
                "ik",
                "sion",
                "se",
                "sis",
                "tät",
                "ung",
                "ur",
                "schaft",
            ],
            "m": [
                "ant",
                "ast",
                "ich",
                "ist",
                "ig",
                "ling",
                "or",
                "us",
                "ismus",
                "är",
                "eur",
                "iker",
                "ps",
            ],
        }

        rules["de"]["secondary_german_genus_endings"] = {
            # 3 out of four words ending with -nis and -sal are neuter nouns
            "n": [
                "nis",
                "sal",
            ],
            # There are exceptions such as Postillion, which is masculine while the oberwhelming majority of -ion words in German is feminine.
            "f": [
                "ion",
            ],
            # More than half of  words ending with -er, -en, -el are masculine
            "m": [
                "er",
                "en",
                "el",
            ],
        }

        rules["de"]["german_nouns"] = Nouns()

        rules["de"]["pattern_false_positives"] = []

        rules["de"]["gender_neutral_nouns"] = {
            "Ierende": {
                "flexion": {
                    "nominativ singular": "Ierende",
                    "nominativ plural": "Ierende",
                    "genitiv singular": "Ierender",
                    "genitiv plural": "Ierender",
                    "dativ singular": "Ierender",
                    "dativ plural": "Ierenden",
                    "akkusativ singular": "Ierende",
                    "akkusativ plural": "Ierende",
                },
                "lemma": "Ierende",
                "pos": ["Substantiv", "adjektivische Deklination"],
                "genus": "f",
            },
            "Gebende": {
                "flexion": {
                    "nominativ singular": "Gebende",
                    "nominativ plural": "Gebende",
                    "genitiv singular": "Gebender",
                    "genitiv plural": "Gebender",
                    "dativ singular": "Gebender",
                    "dativ plural": "Gebenden",
                    "akkusativ singular": "Gebende",
                    "akkusativ plural": "Gebende",
                },
                "lemma": "Gebende",
                "pos": ["Substantiv", "adjektivische Deklination"],
                "genus": "f",
            },
        }

        # https://de.wikipedia.org/wiki/Anrede
        # https://karrierebibel.de/namenstitel/
        rules["de"]["salutations"] = (
            "Herr",
            "Herrn",
            "Frau",
            "Fräulein",
            "Sehr geehrter",
            "Sehr geehrte",
            "Hallo",
            "Hello",
            "Hi",
            "Hey",
            "Guten Morgen",
            "Guten Tag",
            "Guten Abend",
            "Wie gehts",
            "Wie geht's",
            "Liebe",
            "Sehr verehrte Frau",
            "Sehr verehrter Herr",
            "Liebste",
            "Liebster",
            "Prof.",
            "Dr.",
            "Ing.",
            "Inf.",
            "Dr. med.",
            "Dr. med. dent.",
            "Dr. med. vet.",
            "Dr. phil.",
            "Dr. rer. nat.",
            "Dr. iur.",
            "Dr. oec.",
            "Dr. oec. publ.",
            "Dr. h.c.",
            "Dr. e.h.",
            "Dr. mult.",
            "Dr. des.",
            "Dr. habil.",
            "Dres.",
            "Prof. med.",
            "Prof. med. dent.",
            "Prof. med. vet.",
            "Prof. phil.",
            "Prof. rer. nat.",
            "Prof. iur.",
            "Prof. oec.",
            "Prof. oec. publ.",
            "Prof. h.c.",
            "Prof. e.h.",
            "Prof. mult.",
            "Prof. des.",
            "Prof. habil.",
            "Heiligkeit",
            "Seligkeit",
            "Heiliger Vater",
            "Eminenz",
            "Exzellenz",
            "Bischof",
            "Hochwürden",
            "Hochwürdiger",
            "Hochehrwürdiger",
            "Wohlehrwürden",
            "Hochwürdige",
            "Mutter Oberin",
            "Ehrwürdige Mutter",
            "Ehrwürdigste  Mutter",
            "Hochehrwürdige Mutter",
            "Hochwürdiger Pater",
            "Hochwürdiger Bruder",
            "Ehrwürdige Schwester",
            "Ehrwürdiger Bruder",
            "Ehrwürdiger Herr",
            "Ehrwürden",
            "Allheiligkeit",
            "Heiligkeit",
            "Fürst",
            "Fürstin",
            "Prinzessin",
            "Prinz",
            "Herzog",
            "Herzogin",
            "Graf",
            "Gräfin",
            "Comtesse",
            "Freiherr",
            "Freifrau",
            "Freiin",
            "Baron",
            "Baronin",
            "Baronesse",
            "Majestät",
            "König",
            "Königin",
            "Kaiser",
            "Kaiserin",
            "Großherzog",
            "Grossherzog",
            "Großherzogin",
            "Grossherzogin",
            "Erzherzog",
            "Erzherzogin",
            "Großfürst",
            "Grossfürst",
            "Großfürstin",
            "Grossfürstin",
        )

        rules["de"]["splittable_words"] = {
            "durch": [
                "durchbeißen",
                "durchbeissen",
                "durchblasen",
                "durchblättern",
                "durchbrausen",
                "durchdringen",
                "durchfahren",
                "durchfallen",
                "durchfeiern",
                "durchgehen",
                "durchglühen",
                "durchkämpfen",
                "durchklettern",
                "durchkramen",
                "durchkriechen",
                "durchradeln",
                "durchrauschen",
                "durchrennen",
                "durchrieseln",
                "durchrinnen",
                "durchschallen",
                "durchscheinen",
                "durchschlafen",
                "durchschleichen",
                "durchschnüffeln",
                "durchschwitzen",
                "durchsetzen",
                "durchspringen",
                "durchsteigen",
                "durchstreichen",
                "durchwachen",
                "durchwachsen",
                "durchwärmen",
                "durchwaten",
                "durchziehen",
            ],
            "fremd": [
                "fremdschämen",
            ],
            "über": [
                "überbeanspruchen",
                "überbehüten",
                "überbeißen",
                "überbeissen",
                "überbekommen",
                "überbelasten",
                "überbelegen",
                "überbelichten",
                "überbetonen",
                "überbewerten",
                "überbezahlen",
                "überbleiben",
                "überdramatisieren",
                "übererfüllen",
                "überessen",
                "überfließen",
                "überfliessen",
                "übergehen",
                "überhandnehmen",
                "überhängen",
                "überkippen",
                "überkippen",
                "überkochen",
                "überlaufen",
                "überleiten",
                "überpflanzen",
                "überschießen",
                "überschiessen",
                "überschlagen",
                "übersprudeln",
                "übersprühen",
                "überstechen",
                "übertreten",
                "übertun",
                "überversichern",
                "überversorgen",
                "überwallen",
                "überwerfen",
                "übrigbehalten",
                "übrigbleiben",
                "übrighaben",
                "übriglassen",
            ],
            "offen": [
                "offenbleiben",
                "offenhalten",
                "offenlassen",
                "offenlegen",
                "offenliegen",
                "offenstehen",
            ],
            "um": [
                "umackern",
                "umadressieren",
                "umändern",
                "umarbeiten",
                "umbauen",
                "umbehalten",
                "umbenennen",
                "umbeschreiben",
                "umbesinnen",
                "umbestellen",
                "umbetten",
                "umbiegen",
                "umbilden",
                "umbinden",
                "umblasen",
                "umblättern",
                "umblicken",
                "umbranden",
                "umbrausen",
                "umbrechen",
                "umbringen",
                "umbuchen",
                "umdatieren",
                "umdecken",
                "umdefinieren",
                "umdeklarieren",
                "umdekorieren",
                "umdenken",
                "umdeuten",
                "umdichten",
                "umdirigieren",
                "umdisponieren",
                "umdrehen",
                "umdrucken",
                "umdrücken",
                "umentscheiden",
                "umerziehen",
                "umetikettieren",
                "umfallen",
                "umfälschen",
                "umfärben",
                "umfinanzieren",
                "umfirmieren",
                "umflaggen",
                "umformatieren",
                "umformulieren",
                "umfragen",
                "umfrisieren",
                "umfüllen",
                "umfunktionieren",
                "umgehen",
                "umgestalten",
                "umgewöhnen",
                "umgießen",
                "umgiessen",
                "umgraben",
                "umgründen",
                "umgruppieren",
                "umgucken",
                "umhaben",
                "umhacken",
                "umhängen",
                "umhauen",
                "umheben",
                "umherblicken",
                "umhinkönnen",
                "umhören",
                "uminterpretieren",
                "umkehren",
                "umkippen",
                "umklappen",
                "umknicken",
                "umkommen",
                "umkonstruieren",
                "umkopieren",
                "umkrempeln",
                "umladen",
                "umlagern",
                "umlassen",
                "umlauten",
                "umlegen",
                "umleiten",
                "umlenken",
                "umlernen",
                "ummachen",
                "ummelden",
                "ummodeln",
                "ummünzen",
                "umnehmen",
                "umnehmen",
                "umnutzen",
                "umoperieren",
                "umordnen",
                "umorganisieren",
                "umorientieren",
                "umpacken",
                "umparken",
                "umpflügen",
                "umplanen",
                "umpolen",
                "umprägen",
                "umprogrammieren",
                "umpumpen",
                "umpusten",
                "umquartieren",
                "umrangieren",
                "umräumen",
                "umrechnen",
                "umrennen",
                "umrubeln",
                "umrühren",
                "umrüsten",
                "umsäbeln",
                "umsacken",
                "umsägen",
                "umsatteln",
                "umschaffen",
                "umschalten",
                "umschauen",
                "umschichten",
                "umschlagen",
                "umschmeißen",
                "umschmeissen",
                "umschmelzen",
                "umschmieden",
                "umschminken",
                "umschnallen",
                "umschubsen",
                "umschulden",
                "umschulen",
                "umschütten",
                "umschwenken",
                "umsehen",
                "umsetzen",
                "umsiedeln",
                "umsinken",
                "umsortieren",
                "umspeichern",
                "umspringen",
                "umspritzen",
                "umspulen",
                "umstechen",
                "umstecken",
                "umsteigen",
                "umstellen",
                "umstempeln",
                "umsteuern",
                "umstilisieren",
                "umstimmen",
                "umstoßen",
                "umstossen",
                "umstrukturieren",
                "umstufen",
                "umstülpen",
                "umstürzen",
                "umtaufen",
                "umtauschen",
                "umteilen",
                "umtopfen",
                "umtragen",
                "umtreiben",
                "umtreten",
                "umtun",
                "umverteilen",
                "umwälzen",
                "umwandeln",
                "umwechseln",
                "umwehen",
                "umwenden",
                "umwerfen",
                "umwerten",
                "umwidmen",
                "umwühlen",
                "umzeichnen",
                "umziehen",
            ],
            "unter": [
                "unterbelegen",
                "unterbelichten",
                "unterbewerten",
                "unterbezahlen",
                "unterbringen",
                "unterbügeln",
                "unterbuttern",
                "unterducken",
                "untereinanderliegen",
                "untereinanderstehen",
                "unterfassen",
                "untergehen",
                "unterhaken",
                "unterheben",
                "unterjubeln",
                "unterkommen",
                "unterkriechen",
                "unterkriegen",
                "untermengen",
                "unterordnen",
                "unterpflügen",
                "unterrühren",
                "unterschieben",
                "unterschlupfen",
                "unterschlüpfen",
                "unterschnallen",
                "untersinken",
                "untertauchen",
                "untervermieten",
                "unterversichern",
                "unterversorgen",
                "unterwühlen",
                "uraufführen",
                "unterspannen",
            ],
        }

    if "en" in langs:
        lang = "en"

        ### en-US & en-GB:
        for locale in locales["en"]:
            ## words:
            # df open discrimination words
            # open discrimination: lemma + alternatives split + subcategory
            rules[locale]["open_disc_words_data"] = build_rules(
                model[lang], data[locale]["df_open_dis_word"]
            )

            # df open discrimination words gender no noun
            # gender no noun: lemma + alternatives split + subcategory
            rules[locale]["gender_words_data"] = build_rules(
                model[lang], data[locale]["df_gendered_no_noun_word"]
            )

            # df style
            # style: lemma + alternatives split + subcategory
            rules[locale]["style_words_data"] = build_rules(
                model[lang], data[locale]["df_style_no_noun_word"]
            )

            # df unconscious bias
            # unconscious bias: lemma + alternatives split + subcategory
            rules[locale]["bias_words_data"] = build_rules(
                model[lang], data[locale]["df_ub_no_plur_word"]
            )

            # df inclusive
            # inclusive: lemma + subcategory)
            rules[locale]["inclusive_words_data"] = build_rules(
                model[lang], data[locale]["df_inclusive_word"]
            )

            # df homonyms words
            rules[locale]["homonyms_word"] = build_rules(
                model[lang], data[locale]["df_homonyms_words"]
            )

            # df abbreviation english
            rules[locale]["abbreviation"] = build_rules(
                model[lang], data[locale]["df_abbreviation"]
            )

            # df gendered noun
            # gendered noun: lemma + singular alternatives split + plural alternatives split + primary subcategory + secondary subcategory
            rules[locale]["gender_noun_words_data"] = build_rules(
                model[lang],
                data[locale]["df_gendered_noun_word"],
                plural=True,
                secondary_subcategory=True,
            )

            # df gendered unconscious bias plural
            # gendered unconscious bias plural: lemma + singular alternatives split + plural alternatives split + subcategory
            rules[locale]["gender_bias_words_data"] = build_rules(
                model[lang], data[locale]["df_ub_plur_word"], plural=True
            )

            # df style noun
            # style noun: lemma + singular alternatives split + plural alternatives split + primary subcategory + secondary subcategory
            rules[locale]["style_noun_words_data"] = build_rules(
                model[lang], data[locale]["df_style_noun_word"], plural=True
            )

            ##sentences
            # df inclusive sentences
            df_inclusive_sentences = data[locale]["df_inclusive_sentence"]
            # inclusive sentences: lemma + subcategory
            rules[locale]["inclusive_sentences_data"] = list(
                zip(
                    df_inclusive_sentences["Lemma"],
                    df_inclusive_sentences["Primary_subcategory"],
                )
            )
            data[locale]["df_inclusive_sentence"] = list(
                data[locale]["df_inclusive_sentence"]["Lemma"]
            )

            # df open discrimination sentences
            df_open_dis_sentences = data[locale]["df_open_dis_sentence"]
            # open discrimination sentences: lemma + alternatives split + subcategory
            rules[locale]["open_dis_sentences"] = list(
                zip(
                    df_open_dis_sentences["Lemma"],
                    df_open_dis_sentences["Primary_subcategory"],
                    map(ast.literal_eval, df_open_dis_sentences["Alt_split"]),
                )
            )
            data[locale]["df_open_dis_sentence"] = list(
                data[locale]["df_open_dis_sentence"]["Lemma"]
            )

            # df gendered sentences
            df_gendered_sentences = data[locale]["df_gendered_sentence"]
            # gendered sentences: lemma + alternatives split + primary subcategory
            rules[locale]["gender_sentences_data"] = list(
                zip(
                    df_gendered_sentences["Lemma"],
                    df_gendered_sentences["Primary_subcategory"],
                    map(ast.literal_eval, df_gendered_sentences["Alt_split"]),
                )
            )
            data[locale]["df_gendered_sentence"] = list(
                data[locale]["df_gendered_sentence"]["Lemma"]
            )

            # df style sentences
            df_style_sentences = data[locale]["df_style_sentence"]
            # style sentences: lemma + alternatives split + subcategory
            rules[locale]["style_sentences_data"] = list(
                zip(
                    df_style_sentences["Lemma"],
                    df_style_sentences["Primary_subcategory"],
                    map(ast.literal_eval, df_style_sentences["Alt_split"]),
                )
            )
            data[locale]["df_style_sentence"] = list(
                data[locale]["df_style_sentence"]["Lemma"]
            )

            # df unconscious bias sentences
            df_bias_sentences = data[locale]["df_ub_sentence"]
            # unconscious bias sentences: lemma + alternatives split + subcategory
            rules[locale]["bias_sentences_data"] = list(
                zip(
                    df_bias_sentences["Lemma"],
                    df_bias_sentences["Primary_subcategory"],
                    map(ast.literal_eval, df_bias_sentences["Alt_split"]),
                )
            )
            data[locale]["df_ub_sentence"] = list(
                data[locale]["df_ub_sentence"]["Lemma"]
            )

            # unconscious bias singular they: lemma + alternatives split + subcategory
            rules[locale]["bias_singular_they_alternatives"] = build_rules(
                model[lang], data[locale]["df_ub_singular_they"]
            )

        rules["en"]["context_check"] = [
            "fossil",
            "flexible",
            "impact",
            "dynamic",
            "best",
            "alone",
            "retarded",
            "brilliant",
            "retard",
        ]

        rules["en"]["hashtags"] = [
            # "#foobar"
            [
                re.compile(r"^#(?!.*[A-Z])\w\w\w\w\w+$"),
                "1,2,#",
                "style",
                [],
                {
                    "text": "When you capitalize words, everyone knows right away what you mean. #ForExample"
                },
            ],
        ]

        rules["en"]["list_false_column"] = [
            "Air Force",
            "Armed forces",
            "Indian Act",
            "Indian status",
            "Minority Ethnic",
            "Musqueam Indian Band",
            "Nazi camp",
            "POW camp",
            "PhD student",
            "PhD students",
            "a little forced",
            "all the best",
            "alpha read",
            "alpha reader",
            "alpha reading",
            "analyses",
            "analysis team",
            "anything of the kind",
            "armed forces",
            "assign female",
            "assign male",
            "assigned female",
            "assigned male",
            "assigning female",
            "assigning male",
            "assigns female",
            "assigns male",
            "authority figure",
            "autism spectrum disorder",
            "award-winning type",
            "baby boomer",
            "back problem",
            "back problems",
            "bear fruit",
            "best available",
            "best effort",
            "best practice",
            "best practices",
            "best regards",
            "best wishes",
            "best-practice",
            "best-practices",
            "biological father",
            "biological son",
            "bipolar disorder",
            "birth father",
            "birth mother",
            "boot camp",
            "by force",
            "camp counselor",
            "camp counselors",
            "camp mother",
            "certificate of authority",
            "common problem",
            "communal leader",
            "communal leadership",
            "communal leaderships",
            "competitive advantage",
            "competitive analysis",
            "competitive cyclist",
            "competitive environment",
            "competitive intelligence",
            "competitive landscape",
            "competitive market",
            "competitive pricing",
            "competitive strategy",
            "concentration camp",
            "concussive force",
            "data analysis",
            "data analytics",
            "death camp",
            "decision process",
            "decision-making",
            "decisive moment",
            "detention camp",
            "direct message",
            "direct public offering",
            "directed",
            "dirty trick",
            "dirty tricks",
            "do best",
            "do the best",
            "do the trick",
            "dwarf satellite",
            "dwarf star",
            "each other",
            "epileptic episode",
            "epileptic episodes",
            "epileptic seizure",
            "epileptic seizures",
            "ethical hacker",
            "ethical hackers",
            "ethical security hacker",
            "ethical security hackers",
            "exceptional achievement",
            "exceptional viable product",
            "exceptionally good",
            "exceptionally well",
            "excessive force",
            "extreme mood",
            "extremely well",
            "feel good",
            "fierce competition",
            "first-mover advantage",
            "fit like a glove",
            "follow a lead",
            "for the best",
            "forbidden fruit",
            "forbidden fruits",
            "force close",
            "force for good",
            "force in",
            "force of arms",
            "force of habit",
            "force out",
            "force quit",
            "force to be reckoned",
            "force to reckon",
            "fossil group",
            "fruit and vegetable",
            "fruit juice",
            "fruit loops",
            "fruit of",
            "fruit preserve",
            "fruit preserves",
            "fruit salad",
            "fuzzy logic",
            "gas up",
            "generally accepted",
            "generate a lead",
            "generate leads",
            "genetic father",
            "genetic mother",
            "genetic son",
            "global majority",
            "going gets tough",
            "good at",
            "good enough",
            "good faith",
            "good fit",
            "good food",
            "good friends",
            "good hacker",
            "good hackers",
            "good impression",
            "good job",
            "good offer",
            "good relations",
            "good result",
            "good results",
            "good-looking",
            "goods",
            "great at",
            "great day",
            "great deal",
            "great effort",
            "great enthusiasm",
            "great importance",
            "great job",
            "great lengths",
            "great time",
            "great-hearted",
            "greater",
            "grow fruit",
            "growth hacker",
            "growth hackers",
            "has a problem with",
            "has autism",
            "have a great",
            "have a problem with",
            "health problems",
            "her best",
            "his best",
            "histrionic personality disorder",
            "holiday camp",
            "holiday camps",
            "how many",
            "How many",
            "as many as",
            "as many",
            "the many",
            "so many",
            "many times",
            "too many",
            "many ways",
            "not many",
            "many a",
            "many another",
            "many happy returns",
            "draft once reuse many",
            "one many",
            "a good many",
            "many sided",
            "a man of many parts",
            "many moons ago",
            "one too many",
            "countably many",
            "many coloured",
            "many colored",
            "many sidedness",
            "many valued",
            "a great many",
            "many strings to bow",
            "how many beans make five",
            "many an",
            "many irons in the fire",
            "one too many",
            "many chambered",
            "many tailed bandage",
            "many valued logic",
            "too many chiefs and not enough indians",
            "many a time",
            "many hands make light work",
            "many lobed",
            "many worlds interpretation",
            "with many interruptions",
            "many minded",
            "many words",
            "write once read many",
            "identifies as female",
            "identifies as male",
            "identify as female",
            "identify as male",
            "in full force",
            "in the minority",
            "internment camp",
            "know best",
            "know every trick",
            "knows best",
            "labor camp",
            "labor force",
            "lead astray",
            "lead bank",
            "lead exposure",
            "lead generation",
            "lead life",
            "lead manager",
            "lead pipe",
            "lead piping",
            "lead service line",
            "lead the way",
            "lead-foot",
            "lead-in",
            "letter of athority",
            "look for leads",
            "master class",
            "master mechanism",
            "master of ceremonies",
            "master plan",
            "master student",
            "master students",
            "master's",
            "master's degree",
            "master-chemical-mechanism",
            "math camp",
            "math camps",
            "medical analysis",
            "minority enterprise",
            "minority enterprises",
            "minority interest",
            "minority interests",
            "minority shareholder",
            "minority shareholders",
            "nature of authority",
            "no problem",
            "not a problem",
            "nothing of the kind",
            "nurture leads",
            "objectives and key results",
            "on-time performance",
            "one-trick pony",
            "only as strong as",
            "opinion shaper",
            "opinion shapers",
            "opioid addiction",
            "optical trick",
            "our best",
            "own decisions",
            "paper waste",
            "passion fruit",
            "payment in kind",
            "perform a trick",
            "performance indicator",
            "performance indicators",
            "performance marketing",
            "performance of",
            "performance review",
            "performance test",
            "play a trick",
            "poison fruit",
            "police force",
            "position of authority",
            "positions of authority",
            "present as female",
            "present as male",
            "presented as female",
            "presented as male",
            "presenting as female",
            "presenting as male",
            "presents as female",
            "presents as male",
            "prison camp",
            "prisoner-of-war camp",
            "problem-solve",
            "problem-solver",
            "problem-solves",
            "problem-solving",
            "profit and loss",
            "proof of authority",
            "push the boundaries",
            "queer communities",
            "queer community",
            "really simple syndication",
            "residential camp",
            "residential camps",
            "self-driven car",
            "self-driven cars",
            "self-driven minibus",
            "self-driven train",
            "self-driven trains",
            "self-important",
            "sending you the best",
            "servant leader",
            "servant leadership",
            "servant leaderships",
            "sleepaway camp",
            "sleepaway camps",
            "some kind of",
            "sound forced",
            "sounded forced",
            "statement of authority",
            "stong hunch",
            "strong as an ox",
            "strong desire",
            "strong emotions",
            "strong feelings",
            "strong interest",
            "strong response",
            "sub-camp",
            "substance user",
            "summer camp",
            "surpass expectations",
            "surpassed expectations",
            "task force",
            "the authorities",
            "the force be with you",
            "their best",
            "tough question",
            "tough questions",
            "tough situation",
            "tough situations",
            "toughen up",
            "tour de force",
            "trick of the trade",
            "trick of ther light",
            "trick or treat",
            "trick up",
            "uncoerced decision",
            "uncoerced decisions",
            "undergrad student",
            "undergrad students",
            "unique selling point",
            "unique selling proposition",
            "unique selling propositions",
            "unique sellings points",
            "unique visitor",
            "unique visitors",
            "user experience",
            "vaccination drive",
            "vaccination drives",
            "very good",
            "waste away",
            "waste collection",
            "waste collector",
            "waste collectors",
            "waste effort",
            "waste energy",
            "waste feelings",
            "waste money",
            "waste my life",
            "waste of",
            "waste of breath",
            "waste of feelings",
            "waste of money",
            "waste of time",
            "waste our lives",
            "waste receptacle",
            "waste their lives",
            "waste time",
            "waste your life",
            "wheelchair-user",
            "white paper",
            "whitebox testing",
            "whitepaper",
            "whitespace",
            "wild fruit",
            "win an advantage",
            "win over",
            "win the advantage",
            "work best",
            "work camp",
            "works best",
            "would be great",
            "your best",
        ]

        rules["en"]["a_not_startswith"] = (
            "a ",
            "an ",
            "someone",
            "something",
            "anything",
            "anyone",
            "everything",
            "everyone",
        )

        rules["en"]["uncountables"] = (
            " ethics",
            " accommodation",
            " information",
            " advice",
            " grass",
            " flour",
            " baggage",
            " meat",
            " carpentry",
            " ground",
            " help",
            " work",
            " engineering",
            " shopping",
            " ice",
            " coffee",
            " tea",
            " fuel",
            " silence",
            " honesty",
            " anger",
            " depression",
            " salt",
            " machinery",
            " wood",
            " sorrow",
            " snow",
            " noise",
            " sadness",
            " gold",
            " silver",
            " platinum",
            " beef",
            " honey",
            " sauce",
            " art",
            " weather",
            " money",
            " love",
            " oil",
            " physics",
            " butter",
            " silk",
            " fun",
            " alcohol",
            " satisfaction",
            " blood",
            " water",
            " milk",
            " assistance",
            " plastic",
            " paper",
            " nature",
            " fog",
            " beauty",
            " english",
            " furniture",
            " cheese",
            " failure",
            " faith",
            " jewelry",
            " science",
            " rice",
            " soup",
            " jam",
            " heat",
            " electricity",
            " news",
            " biology",
            " knowledge",
            " rain",
            " sugar",
            " behavior",
            " patience",
            " food",
            " darkness",
            " algebra",
            " humour",
            " humor",
            " leather",
            " hope",
            " luggage",
            " bread",
            " metal",
            " confidence",
            " finance",
            " laughter",
            " understanding",
            " travel",
            " youth",
            " bravery",
            " perfume",
            " yoga",
            " entertainment",
            " dust",
            " space",
            " warmth",
            " french",
            " data",
            " wealth",
            " spaghetti",
            " confusion",
            " sunshine",
            " content",
            " delight",
            " cash",
            " traffic",
            " chalk",
            " software",
            " evidence",
            " time",
            " confession",
            " fresh air",
            " transportation",
            " smoke",
            " history",
            " chewing gum",
            " smog",
            " motivation",
            " calm",
            " seafood",
            " dignity",
            " evil",
            " cake",
            " energy",
            " joy",
            " golf",
            " research",
            " music",
            " commerce",
            " air",
            " gasoline",
            " danger",
            " clothing",
            " progress",
            " chaos",
            " aggression",
            " grief",
            " harm",
            " peace",
            " education",
            " toast",
            " gymnastics",
            " chocolate",
            " driving",
            " unemployment",
            " environment",
            " thunder",
            " fruit",
            " height",
            " publicity",
            " fiction",
            " experience",
            " coffee",
            " wisdom",
            " fame",
            " cotton",
            " guilt",
            " equipment",
            " homework",
            " pasta",
            " advertising",
            " aid",
            " business",
            " childhood",
            " corruption",
            " courage",
            " currency",
            " damage",
            " danger",
            " determination",
            " economics",
            " employment",
            " enthusiasm",
            " fire",
            " freedom",
            " friendhip",
            " genetics",
            " grammar",
            " hair",
            " happiness",
            " health",
            " hospitality",
            " housework",
            " imagination",
            " importance",
            " innocence",
            " intelligence",
            " jealousy",
            " juice",
            " justice",
            " kindness",
            " knowledge",
            " labor",
            " lack",
            " leisure",
            " literature",
            " litter",
            " logic",
            " luck",
            " magic",
            " management",
            " motherhood",
            " nutrition",
            " obesity",
            " old age",
            " oxygen",
            " permission",
            " pollution",
            " poverty",
            " power",
            " pride",
            " production",
            " pronounciation",
            " punctuation",
            " quality",
            " quantity",
            " racism",
            " relaxation",
            " respect",
            " room",
            " rubbish",
            " sand",
            " speeds",
            " spelling",
            " stress",
            " tennis",
            " tolerance",
            " trade",
            " trust",
            " usage",
            " violence",
            " vision",
            " weight",
            " welfare",
            " wheat",
            " width",
            " wildlife",
            " acrylic",
            " aluminum",
            " bamboo",
            " brass",
            " brick",
            " bronze",
            " calcium",
            " cement",
            " chalk",
            " charcoal",
            " coal",
            " copper",
            " corn",
            " cream",
            " diesel",
            " enamel",
            " gelatin",
            " gem",
            " glass",
            " honey",
            " ink",
            " jute",
            " kerosene",
            " leather",
            " marble",
            " meat",
            " paraffin",
            " plastic",
            " plywood",
            " polyester",
            " powder",
            " rexine",
            " rock",
            " rubber",
            " steel",
            " stone",
            " tar",
            " wool",
        )

        # master of + noun
        pattern_master = [
            [
                {"LOWER": "master"},
                {"LEMMA": "of"},
                {"POS": {"IN": ["PRON", "NOUN", "PROPN"]}},
            ],
            [
                {"LOWER": "masters"},
                {"LEMMA": "of"},
                {"POS": {"IN": ["PRON", "NOUN", "PROPN"]}},
            ],
        ]

        # lead+someone(optional)+prepostion(on, down, up, to, away, back, along, with, off, by, in, nowhere)
        pattern_lead_prepos = [
            [
                {
                    "LEMMA": "lead",
                    "POS": "VERB",
                },
                {"POS": {"IN": ["PRON", "NOUN", "PROPN"]}, "OP": "?"},
                {
                    "LEMMA": {
                        "IN": [
                            "on",
                            "down",
                            "up",
                            "to",
                            "away",
                            "back",
                            "along",
                            "with",
                            "off",
                            "by",
                            "in",
                            "nowhere",
                        ]
                    }
                },
            ]
        ]

        # lead a (charmed, busy, quiet, normal, ...) life','lead your (my, his, her, their, our, ...) life'
        pattern_lead_life = [
            [
                {"LEMMA": "lead", "POS": "VERB"},
                {"POS": "DET", "OP": "?"},
                {"POS": {"IN": ["ADJ", "PRON"]}, "OP": "?"},
                {"LOWER": "life"},
            ]
        ]

        # need to, need for
        pattern_need_to = [
            [{"LEMMA": "need", "POS": "VERB"}, {"LEMMA": {"IN": ["to", "for"]}}]
        ]

        # let alone
        pattern_let_alone = [
            [{"LEMMA": "let", "POS": "VERB"}, {"LEMMA": {"IN": ["alone"]}}]
        ]

        # of a kind 'of a kind', 'of her kind', 'of his kind', 'of its kind', 'of one kind or another', 'of their kind',
        pattern_of_kind = [
            [
                {"LOWER": "of"},
                {"POS": {"IN": ["DET", "PRON", "NUM"]}, "OP": "?"},
                {"LOWER": "kind"},
            ]
        ]

        # quick call', 'quick check', 'quick checks', 'quick exit', 'quick meeting',
        pattern_quick = [
            [
                {"LEMMA": "quick"},
                {"LEMMA": {"IN": ["call", "check", "exit", "meeting"]}},
            ]
        ]

        rules["en"]["pattern_false_positives"] = [
            pattern_master,
            pattern_lead_prepos,
            pattern_lead_life,
            pattern_need_to,
            pattern_let_alone,
            pattern_of_kind,
            pattern_quick,
        ]

        rules["en"]["salutations"] = (
            "Dear",
            "Mrs.",
            "Miss",
            "Madam",
            "Ms.",
            "Dr.",
            "Mr.",
            "Hola",
            "Prof.",
            "Rev.",
            "Lady",
            "Sir",
            "Capt.",
            "Major",
            "Lt.-Col.",
            "Col.",
            "Lady",
            "Lt.-Cmdr.",
            "The Hon.",
            "Cmdr.",
            "Flt. Lt.",
            "Brgdr.",
            "Judge",
            "Lord",
            "The Hon. Mrs",
            "Wng. Cmdr.",
            "Group Capt.",
            "Rt. Hon. Lord",
            "Revd. Father",
            "Revd Canon",
            "Maj.-Gen.",
            "Air Cdre.",
            "Viscount",
            "Dame",
            "Rear Admrl.",
            "Good afternoon",
            "Good evening",
            "Good morning",
            "Hi",
            "Hey",
            "Morning",
            "Howdy",
            "Hello",
            "Greetings",
            "Whats up",
            "Good news",
            "To",
            "Yo",
            "Sup",
            "Holler",
        )

    return rules
