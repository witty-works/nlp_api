import pandas as pd
import re
from app.models import LangWithAutoType, Rule, EntityType, LangType


def fetch_static_rules(langs: list[str]):
    files = {
        LangType.DE: {
            # load articles for gendered denom
            "df_articles": "articles.csv",
        },
        LangType.EN: {},
        LangType.FR: {},
    }

    static_rules = {
        "male_specific_dimensions": ["function", "titles", "male_stereotype"],
        "named_entity_labels": {
            EntityType.NAME: (
                "PER",  # Named person or family
                "ORG",  # Companies, agencies, institutions, etc.
                "PERSON",  # People, including fictional
                "GPE",  # Countries, cities, states
                "LOC",  # Non-GPE locations, mountain ranges, bodies of water
                "PRODUCT",  # Objects, vehicles, foods, etc. (not services)
                "EVENT",  # Named hurricanes, battles, wars, sports events, etc.
                "FAC",  # Buildings, airports, highways, bridges, etc.
                "LANGUAGE",  # Any named language
                "LAW",  # Named documents made into laws.
                "NORP",  # Nationalities or religious or political groups
                "WORK_OF_ART",  # Titles of books, songs, etc.
                "MISC",  # Miscellaneous entities, e.g., events, nationalities, products, or works of art.
            ),
            EntityType.PERSON: (
                "PER",  # Named person or family
                "PERSON",  # People, including fictional
            ),
            EntityType.NUMBER: (
                "MONEY",  # Monetary values, including unit
                "CARDINAL",  # Numerals that do not fall under another type
                "ORDINAL",  # "first", "second", etc.
                "QUANTITY",  # Measurements, as of weight or distance
                "PERCENT",  # Percentage, including "%"
            ),
            EntityType.DATETIME: (
                "DATE",  # Absolute or relative dates or periods
                "TIME",  # Times smaller than a day
            ),
        },
        "m_f_regexes": [
            Rule(
                "(m/f..)",
                None,
                re.compile(r"^m/(f|w)(\/[*a-z])*(\))?$", re.IGNORECASE),
                None,
                (0, 7, "/"),
                "gender_specific_abbreviation",
            ),
            Rule(
                "(f/m..)",
                None,
                re.compile(r"^(f|w)/m(\/[*a-z])*(\))?$", re.IGNORECASE),
                None,
                (0, 7, "/"),
                "gender_specific_abbreviation",
            ),
            Rule(
                "(d/f/m/v)",
                None,
                re.compile(r"^(d|x|\*)(/v)?/f(/v)?/m(/v)?$", re.IGNORECASE),
                None,
                (0, 7, "/"),
                "gender_specific_abbreviation_advanced",
            ),
        ],
        "skin_tones": {
            "all": [
                "",
                "_dark_skin_tone",
                "_medium_skin_tone",
                "_medium-dark_skin_tone",
                "_medium-light_skin_tone",
                "_light_skin_tone",
            ],
            "full": [
                "_dark_skin_tone",
                "_medium_skin_tone",
                "_medium-dark_skin_tone",
                "_light_skin_tone",
            ],
            "minimal": [
                "_dark_skin_tone",
                "_medium_skin_tone",
                "_light_skin_tone",
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
            "person_advanced": {
                "skin_tone": True,
                "subcategory": {
                    "hearing_advanced": [
                        "deaf_person",
                    ],
                    "belief_advanced": [
                        "woman_with_headscarf",
                        "man_with_turban",
                        "man_in_lotus_position",  # Representing meditation, often associated with Eastern religions
                        "man_with_skullcap",  # Representing a man wearing a skullcap, found in various religious traditions
                    ],
                    "vision_advanced": [
                        "person_with_white_cane",
                    ],
                    "ability_advanced": [
                        "person_in_manual_wheelchair",
                    ],
                    "age_old_advanced": [
                        "older_person",
                    ],
                    "age_young_advanced": [
                        "child",
                    ],
                    "culture_advanced": [
                        "man_with_chinese_cap",  # Representing a man wearing a traditional Chinese cap, linked to certain cultural practices
                    ],
                },
                "rules": [
                    "person",
                ],
            },
            "holiday_symbols": {
                "skin_tone": False,
                "subcategory": {
                    "belief": [
                        "gift",  # Universal gift-giving
                        "star",  # General festivity
                        "candle",  # Diwali, Hanukkah
                        "party_popper",  # Celebration
                        "palm_tree",  # Palm tree
                        "snowflake",  # Winter theme
                        "snowman",  # Winter theme
                        "menorah",  # Hanukkah
                        "dreidel",  # Hanukkah
                        "star_of_david",  # Judaism symbol
                    ],
                },
                "rules": [
                    "Christmas_tree",
                ],
            },
            "holiday_santa": {
                "skin_tone": True,
                "subcategory": {
                    "belief": [
                        "Mrs._Claus",
                        "Santa_Claus",
                    ],
                },
                "rules": [
                    "Santa_Claus",
                    "Mrs._Claus",
                ],
            },
            "military_terms": {
                "skin_tone": False,
                "subcategory": {
                    "military_source": [
                        "dove",
                        "peace_symbol",
                        "white_flag",
                        "handshake",
                    ],
                },
                "rules": [
                    "military_helmet",
                    "crossed_swords",
                    "shield",
                    "bomb",
                    "dagger",
                ],
            },
            "military_medal": {
                "skin_tone": False,
                "subcategory": {
                    "military_source": [
                        "sports_medal",
                        "3rd_place_medal",
                        "2nd_place_medal",
                        "1st_place_medal",
                    ],
                },
                "rules": [
                    "military_medal",
                ],
            },
            "gender_orientation_holding_hands": {
                "skin_tone": True,
                "subcategory": {
                    "sexual_orientation": [
                        "people_holding_hands",
                        "rainbow_flag",
                        "transgender_flag",
                    ],
                },
                "rules": [
                    "man_and_woman_holding_hands",
                ],
            },
            "gender_orientation_love": {
                "skin_tone": True,
                "subcategory": {
                    "sexual_orientation": [
                        "kiss_woman_woman",
                        "kiss_man_man",
                    ],
                },
                "rules": [
                    "kiss_woman_man",
                    "kiss_man_woman",
                ],
            },
            "cultural_diversity": {
                "skin_tone": False,
                "subcategory": {
                    "culture": [
                        "globe_with_meridians",
                        "globe_showing_asia_australia",
                    ],
                },
                "rules": [
                    "globe_showing_Europe-Africa",
                    "globe_showing_Americas",
                ],
            },
            "offensive_language": {
                "skin_tone": False,
                "subcategory": {
                    "offensive_language": [
                        "-",
                        "stop_sign",
                    ],
                },
                "rules": [
                    "middle_finger",
                ],
            },
        },
    }

    locales = {
        LangType.DE: [LangWithAutoType.DE],
        LangType.EN: [LangWithAutoType.enUS, LangWithAutoType.enGB],
        LangType.FR: [LangWithAutoType.FR],
    }

    data = {}
    for lang in langs:
        static_rules[lang] = {}
        for locale in locales[lang]:
            static_rules[locale] = data[locale] = {}
            for csv in files[lang]:
                data[locale][csv] = pd.read_csv(
                    "training_data/" + locale + "/" + files[lang][csv],
                    keep_default_na=False,
                )

        static_rules[lang]["salutations"] = []
        static_rules[lang]["context_check"] = []

    if LangType.FR in langs:

        rule = Rule(
            "#parexemple",
            LangType.FR,
            re.compile(r"^#(?!.*[A-Z])\w\w\w\w\w+$"),
            None,
            (1, 2, "#"),
            "plain_language",
        )

        rule.explanation = "Lorsque vous mettez des majuscules, tout le monde sait immédiatement ce que vous voulez dire. #ParExemple"

        static_rules[LangType.FR]["hashtags"] = [rule]

        static_rules[LangType.FR]["noun_conjunction"] = {
            "singular": " ou ",
            "plural": " et ",
        }

        static_rules[LangType.FR]["masculine_articles"] = {
            "le": "la·le",
            "un": "un·e",
            "il": "iel",
            "ils": "lels",
            "lui": "ellui",
            "celui": "cellui",
            "ceux": "celleux",
            "les": "les",
            "leur": "leur",
            "du": "de la·du",
            "au": "à la·au",
        }
        static_rules[LangType.FR]["feminine_articles"] = {
            "la": "la·le",
            "une": "un·e",
            "elle": "iel",
            "elles": "lels",
            "lui": "ellui",
            "celle": "cellui",
            "celles": "celleux",
            "les": "les",
            "leur": "leur",
            "de la": "de la·du",
            "à la": "à la·au",
        }
        static_rules[LangType.FR]["inclusive_articles"] = {
            "la·le": "la·le",
            "un·e": "un·e",
            "iel": "iel",
            "lels": "lels",
            "ellui": "ellui",
            "cellui": "cellui",
            "celleux": "celleux",
            "les": "les",
            "leur": "leur",
            "lels": "lels",
            "de la·du": "de la·du",
            "à la·au": "à la·au",
        }
        static_rules[LangType.FR]["articles_map"] = dict(
            zip(
                static_rules[LangType.FR]["masculine_articles"].keys(),
                static_rules[LangType.FR]["feminine_articles"].keys(),
            )
        )
        static_rules[LangType.FR]["articles_map"].update(
            dict(
                zip(
                    static_rules[LangType.FR]["feminine_articles"].keys(),
                    static_rules[LangType.FR]["masculine_articles"].keys(),
                )
            )
        )
        static_rules[LangType.FR]["articles_map"].update(
            dict(
                zip(
                    static_rules[LangType.FR]["inclusive_articles"].keys(),
                    static_rules[LangType.FR]["masculine_articles"].keys(),
                )
            )
        )

        static_rules[LangType.FR]["articles"] = set(
            list(static_rules[LangType.FR]["masculine_articles"].keys())
            + list(static_rules[LangType.FR]["feminine_articles"].keys())
            + list(static_rules[LangType.FR]["inclusive_articles"].keys())
        )
        static_rules[LangType.FR]["articles_inclusive_map"] = static_rules[LangType.FR][
            "masculine_articles"
        ].copy()
        static_rules[LangType.FR]["articles_inclusive_map"].update(
            static_rules[LangType.FR]["feminine_articles"]
        )
        static_rules[LangType.FR]["articles_inclusive_map"].update(
            static_rules[LangType.FR]["inclusive_articles"]
        )

        static_rules[LangType.FR]["articles_binary_map"] = dict(
            zip(
                static_rules[LangType.FR]["masculine_articles"].keys(),
                static_rules[LangType.FR]["feminine_articles"].keys(),
            )
        )
        static_rules[LangType.FR]["articles_binary_map"].update(
            zip(
                static_rules[LangType.FR]["feminine_articles"].keys(),
                static_rules[LangType.FR]["masculine_articles"].keys(),
            )
        )
        static_rules[LangType.FR]["articles_binary_map"].update(
            static_rules[LangType.FR]["inclusive_articles"]
        )

        static_rules[LangType.FR]["noun_separator_options"] = ["et", "ou", "/"]

        static_rules[LangType.FR]["gender_neutral_nouns"] = [
            "nous",
            "vous",
            "tu",
            "personnes",
            "membres",
            "collègues",
            "individus",
            "volontaires",
            "cadres",
            "gestionnaires",
            "partenaires",
            "actionnaires",
            "stagiaires",
            "responsables",
            "spécialistes",
            "prestataires",
        ]

    if LangType.DE in langs:
        rule = Rule(
            "#zumbeispiel",
            LangType.DE,
            re.compile(r"^#(?!.*[A-Z])\w\w\w\w\w+$"),
            None,
            (1, 2, "#"),
            "plain_language",
        )

        rule.explanation = "Wenn du Wörter großschreibst, wissen alle gleich, was du meinst. #ZumBeispiel"

        static_rules[LangType.DE]["noun_conjunction"] = {
            "singular": "/",
            "plural": " und ",
        }

        static_rules[LangType.DE]["hashtags"] = [rule]

        static_rules[LangType.DE]["context_check"] = [
            "unabhängig",
            "entschieden",
        ]

        static_rules[LangType.DE]["hilf_verben"] = ["haben", "sind", "sein", "werden"]

        static_rules[LangType.DE]["formal_shallow_signal_words"] = [
            "sie",
            "ihr",
            "ihre",
            "ihren",
            "ihnen",
            "ihrem",
            "ihres",
        ]

        static_rules[LangType.DE]["formal_signal_words"] = {
            "lemma": [
                "geehrt",
                "Herr",
                "Frau",
                "Dame",
                "Bitte",
                "bitten",
                "gern",
            ],
            "text": [
                "Sie",
                "Ihr",
                "Ihre",
                "Ihren",
                "Ihnen",
                "Ihrem",
                "Ihres",
                "hätten",
                "könnten",
                "dürften",
                "würden",
                "sollten",
                "müssten",
                "müẞten",
                "möchten",
            ],
        }

        static_rules[LangType.DE]["standard_words"] = [
            "zusammen",
            "schaft",
            "nieder",
            "hinter",
            "wider",
            "unter",
            "reich",
            "ismus",
            "über",
            "voll",
            "nach",
            "miss",
            "ling",
            "lich",
            "lein",
            "leer",
            "keit",
            "heit",
            "haft",
            "chen",
            "zer",
            "weg",
            "vor",
            "ver",
            "ver",
            "ung",
            "tum",
            "nis",
            "mit",
            "los",
            "hin",
            "her",
            "ent",
            "emp",
            "ein",
            "ein",
            "dar",
            "bei",
            "aus",
            "auf",
            "arm",
            "zu",
            "un",
            "um",
            "ob",
            "le",
            "in",
            "ge",
            "er",
            "be",
            "an",
            "ab",
        ]

        # articles
        articles = list(
            zip(
                data[LangType.DE]["df_articles"]["Form"],
                data[LangType.DE]["df_articles"]["Masculine"],
                data[LangType.DE]["df_articles"]["Feminine"],
                data[LangType.DE]["df_articles"]["Neuter"],
                data[LangType.DE]["df_articles"]["Plural"],
                data[LangType.DE]["df_articles"]["Alternative"],
            )
        )

        static_rules[LangType.DE]["masculine_articles"] = {}
        static_rules[LangType.DE]["feminine_articles"] = {}
        static_rules[LangType.DE]["neuter_articles"] = {}
        static_rules[LangType.DE]["articles"] = []

        for article in articles:
            static_rules[LangType.DE]["articles"].append(article[1])
            static_rules[LangType.DE]["articles"].append(article[2])
            static_rules[LangType.DE]["articles"].append(article[3])
            static_rules[LangType.DE]["articles"].append(article[4])
            static_rules[LangType.DE]["articles"].append(article[5].replace("~", "*"))
            static_rules[LangType.DE]["articles"].append(article[5].replace("~", "_"))
            static_rules[LangType.DE]["articles"].append(article[5].replace("~", ":"))

            if article[1] not in static_rules[LangType.DE]["masculine_articles"]:
                static_rules[LangType.DE]["masculine_articles"][article[1]] = {}
            static_rules[LangType.DE]["masculine_articles"][article[1]][
                article[0]
            ] = article

            if article[2] not in static_rules[LangType.DE]["feminine_articles"]:
                static_rules[LangType.DE]["feminine_articles"][article[2]] = {}
            static_rules[LangType.DE]["feminine_articles"][article[2]][
                article[0]
            ] = article

            if article[3] not in static_rules[LangType.DE]["neuter_articles"]:
                static_rules[LangType.DE]["neuter_articles"][article[3]] = {}
            static_rules[LangType.DE]["neuter_articles"][article[3]][
                article[0]
            ] = article

        static_rules[LangType.DE]["articles"] = set(
            static_rules[LangType.DE]["articles"]
        )

        static_rules[LangType.DE]["primary_german_gender_endings"] = {
            "neuter": [
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
            "feminine": [
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
            "masculine": [
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

        static_rules[LangType.DE]["secondary_german_gender_endings"] = {
            # 3 out of four words ending with -nis and -sal are neuter nouns
            "neuter": [
                "nis",
                "sal",
            ],
            # There are exceptions such as Postillion, which is masculine while the oberwhelming majority of -ion words in German is feminine.
            "feminine": [
                "ion",
            ],
            # More than half of  words ending with -er, -en, -el are masculine
            "masculine": [
                "er",
                "en",
                "el",
            ],
        }

        # Ensure a matching entry in the gemran nouns table before adding a new postfix
        static_rules[LangType.DE]["german_nouns_postfix"] = [
            "sachkundige",
            "lead",
            "head",
            "tragende",
        ]

        static_rules[LangType.DE]["gender_neutral_nouns"] = {
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
                "gender": "feminine",
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
                "gender": "feminine",
            },
        }

        # https://de.wikipedia.org/wiki/Anrede
        # https://karrierebibel.de/namenstitel/
        static_rules[LangType.DE]["salutations"] = (
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

        static_rules[LangType.DE]["splittable_words"] = {
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

    if LangType.EN in langs:
        static_rules[LangType.EN]["context_check"] = [
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

        rule = Rule(
            "#forexample",
            LangType.EN,
            re.compile(r"^#(?!.*[A-Z])\w\w\w\w\w+$"),
            None,
            (1, 2, "#"),
            "plain_language",
        )

        rule.explanation = "When you capitalize words, everyone knows right away what you mean. #ForExample"

        static_rules[LangType.EN]["hashtags"] = [rule]

        static_rules[LangType.EN]["articles"] = ["the", "a", "an"]

        static_rules[LangType.EN]["a_not_startswith"] = (
            "a ",
            "an ",
            "someone",
            "something",
            "anything",
            "anyone",
            "everything",
            "everyone",
        )

        static_rules[LangType.EN]["uncountables"] = (
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

        static_rules[LangType.EN]["pattern_false_positives"] = [
            pattern_master,
            pattern_lead_prepos,
            pattern_lead_life,
            pattern_let_alone,
            pattern_of_kind,
            pattern_quick,
        ]

        static_rules[LangType.EN]["salutations"] = (
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

    return static_rules
