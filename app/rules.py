import pandas as pd
import ast
from collections import namedtuple
from german_nouns.lookup import Nouns

files = {
    "de-DE": {
        # load Gender (nouns, not nouns) and sentences de
        "df_gender_ct": "gendered_noun_words.csv",
        "df_gender_no_noun_word": "gendered_no_noun_words.csv",
        "df_gendered_sentences": "gendered_sentences.csv",
        # load articles for gendered denom
        "df_articles": "articles.csv",
        # load style words
        "df_style_word": "style_words.csv",
        "df_style_sentences": "style_sentences.csv",
        # load openly discriminating words de
        "df_open_dis_word": "open_dis_words.csv",
        "df_open_dis_sentence": "open_dis_sentences.csv",
        # load unconscious_bias word (nouns with plurals and nouns, adj, verbs without plural) and sentences de
        "df_ub_plur_word": "ub_plur_words.csv",
        "df_ub_no_plur_word": "ub_no_plur_words.csv",
        "df_ub_sentences": "ub_sentences.csv",
        # load inslusive words
        "df_d_and_i_words": "d_and_i_words.csv",
        # load inslusive sentences
        "df_d_and_i_words_sentences": "d_and_i_sentences.csv",
        # load communal coded terms
        "df_communal_words": "communal.csv",
        # load gender false positive
        "df_gender_false_positive": "gender_false_positive.csv",
        # load abbreviations
        "df_abbreviation": "abbreviations.csv",
    },
    "en-US": {
        # load openly discriminating words
        "df_open_dis_word": "open_dis_words.csv",
        "df_open_dis_sentence": "open_dis_sentences.csv",
        # load inclusive language
        "df_inclusive_word": "inclusive_words.csv",
        "df_inclusive_sentence": "inclusive_sentences.csv",
        # load style words
        "df_style_word": "style_words.csv",
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

files["en-GB"] = files["en-US"].copy()

rules = {"en": {}, "de": {}}

rules["m_f_regexes"] = {
    r"(?i)\s(\()?(m)\/(f|w)(\/[*a-z])*(\))?": None,  # (m/f..)
    r"(?i)\s(\()?(f|w)\/(m)(\/[*a-z])*(\))?": None,  # (f/m..)
}

rules["d_f_m_regexes"] = {
    r"(?i)\s(\()?(d|x|\*)(\/v)?\/f(\/[*a-z])*(\))?": None,  # (d/f/m..)
}

data = {}

for locale in files:
    rules[locale] = data[locale] = {}
    for csv in files[locale]:
        data[locale][csv] = pd.read_csv(
            "training_data/" + locale + "/" + files[locale][csv], keep_default_na=False
        )

# list of "hollow word" sentences
rules["de-DE"]["terms_style"] = list(data["de-DE"]["df_style_sentences"]["Lemma"])

# list of "d_and_i_words word" sentences
rules["de-DE"]["df_terms_d_and_i_words"] = list(
    data["de-DE"]["df_d_and_i_words_sentences"]["Lemma"],
)

# list of "d_and_i_words word" sentences
rules["de-DE"]["df_d_and_i_words"] = list(
    zip(
        data["de-DE"]["df_d_and_i_words"]["Lemma"],
        data["de-DE"]["df_d_and_i_words"]["Word_Type"],
    )
)

# list of "df_communal_words word" sentences
rules["de-DE"]["df_communal_words"] = list(
    zip(
        data["de-DE"]["df_communal_words"]["Lemma"],
        data["de-DE"]["df_communal_words"]["Word_Type"],
    )
)

# dictionaries to handle false positives
rules["de-DE"]["gender_false_positive"] = list(
    data["de-DE"]["df_gender_false_positive"]["False_positives"]
)
rules["de-DE"]["style_false_positive"] = ["international"]
rules["de-DE"]["exceptions"] = [
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
## words:
# df gender
df_gender = data["de-DE"]["df_gender_ct"]
# gender: words + singular alternatives + plural alternatives + all alternatives + subcategory
rules["de-DE"]["gender_words_data"] = list(
    zip(
        df_gender["Lemma"],
        df_gender["Word_Type"],
        map(ast.literal_eval, df_gender["Sg_all_split"]),
        map(ast.literal_eval, df_gender["Pl_all_split"]),
        df_gender["Primary_subcategory"],
    )
)
# df gendered no noun
df_gendered_no_noun = data["de-DE"]["df_gender_no_noun_word"]
# gendered: words + alternatives split + subcategory
rules["de-DE"]["gender_words_data_no_noun"] = list(
    zip(
        df_gendered_no_noun["Lemma"],
        df_gendered_no_noun["Word_Type"],
        map(ast.literal_eval, df_gendered_no_noun["Alt_split"]),
        df_gendered_no_noun["Primary_subcategory"],
    )
)
# articles
rules["de-DE"]["articles"] = list(
    zip(
        data["de-DE"]["df_articles"]["Form"],
        data["de-DE"]["df_articles"]["Masculine"],
        data["de-DE"]["df_articles"]["Feminine"],
        data["de-DE"]["df_articles"]["Neuter"],
        data["de-DE"]["df_articles"]["Plural"],
        data["de-DE"]["df_articles"]["Alternative"],
    )
)
rules["de-DE"]["male_articles"] = list(data["de-DE"]["df_articles"]["Masculine"])

# df unconscious bias nouns with plural
df_bias = data["de-DE"]["df_ub_plur_word"]
# unconscious bias: words + singular alternatives split + plural alternatives split + subcategory
rules["de-DE"]["bias_words_data_noun"] = list(
    zip(
        df_bias["Lemma"],
        df_bias["Word_Type"],
        map(ast.literal_eval, df_bias["Sg_all_split"]),
        map(ast.literal_eval, df_bias["Pl_all_split"]),
        df_bias["Primary_subcategory"],
    )
)
# df unconscious bias words without plurals
df_bias_no_plur = data["de-DE"]["df_ub_no_plur_word"]
# unconscious bias: words + alternatives split + subcategory
rules["de-DE"]["bias_words_data_no_plur"] = list(
    zip(
        df_bias_no_plur["Lemma"],
        df_bias_no_plur["Word_Type"],
        map(ast.literal_eval, df_bias_no_plur["Alt_split"]),
        df_bias_no_plur["Primary_subcategory"],
    )
)
# df style
df_style = data["de-DE"]["df_style_word"]
# style: words + alternatives + subcategory
rules["de-DE"]["style_words_data"] = list(
    zip(
        df_style["Lemma"],
        df_style["Word_Type"],
        map(ast.literal_eval, df_style["Alt_split"]),
        df_style["Primary_subcategory"],
    )
)
# df open discrimination words
df_discrimination_words = data["de-DE"]["df_open_dis_word"]
# open discrimination: words + alternative_split + subcategory
rules["de-DE"]["open_disc_words_data"] = list(
    zip(
        df_discrimination_words["Lemma"],
        df_discrimination_words["Word_Type"],
        map(ast.literal_eval, df_discrimination_words["Alt_split"]),
        df_discrimination_words["Primary_subcategory"],
    )
)
# df abbreviation
df_abbreviation = data["de-DE"]["df_abbreviation"]
# abbreviation: lemma + category + subcategory + alternatives
rules["de-DE"]["abbreviation"] = list(
    zip(
        df_abbreviation["Lemma"],
        df_abbreviation["Word_Type"],
        df_abbreviation["Category"],
        df_abbreviation["Primary_subcategory"],
        map(ast.literal_eval, df_abbreviation["Alt_split"]),
    )
)

## sentences:
# df open discrimination sentence
df_discrimination_sentences = data["de-DE"]["df_open_dis_sentence"]
# open discrimination: sentences +alternatives split + subcategory
rules["de-DE"]["open_disc_sentences_data"] = list(
    zip(
        df_discrimination_sentences["Lemma"],
        map(ast.literal_eval, df_discrimination_sentences["Alt_split"]),
        df_discrimination_sentences["Primary_subcategory"],
    )
)
# df gendered sentences
df_gendered_sentences = data["de-DE"]["df_gendered_sentences"]
# gendered: sentences + alternatives split + subcategory
rules["de-DE"]["gender_sentences_data"] = list(
    zip(
        df_gendered_sentences["Lemma"],
        map(ast.literal_eval, df_gendered_sentences["Alt_split"]),
        df_gendered_sentences["Primary_subcategory"],
    )
)
# df unconscious bias sentences
df_bias_sentences = data["de-DE"]["df_ub_sentences"]
# unconscious bias: sentences + alternatives split + subcategory
rules["de-DE"]["bias_sentences_data"] = list(
    zip(
        df_bias_sentences["Lemma"],
        map(ast.literal_eval, df_bias_sentences["Alt_split"]),
        df_bias_sentences["Primary_subcategory"],
    )
)
# df style sentences
df_style_sentences = data["de-DE"]["df_style_sentences"]
# style: sentences + alternatives + subcategory
rules["de-DE"]["style_sentences_data"] = list(
    zip(
        df_style_sentences["Lemma"],
        map(ast.literal_eval, df_style_sentences["Alt_split"]),
        df_style_sentences["Primary_subcategory"],
    )
)

FalsePositive = namedtuple("FalsePositive", "gender style")

rules["de-DE"]["false_positives"] = FalsePositive(
    rules["de-DE"]["gender_false_positive"], rules["de-DE"]["style_false_positive"]
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

rules["de"]["conjunctions"] = [
    # all the multi-word conjunctions are included as individual words except for "weder noch"
    "aber",
    "als",
    # "als dass als ob",
    # "als wenn",
    # "anstatt dass",
    "außer",
    "ausser",
    "auch",
    "bevor",
    "beziehungsweise",
    "bis",
    "da",
    "dass",
    "denn",
    "desto",
    "damit",
    "doch",
    "ehe",
    "eh",
    "entweder",
    "oder",
    "einerseits",
    "andererseits",
    "falls",
    "ferner",
    "indem",
    "indessen",
    "indes",
    "insofern",
    "insoweit",
    "soweit",
    "je",
    "jedoch",
    "nachdem",
    "ob",
    "obgleich",
    "obschon",
    "obwohl",
    "obzwar",
    "oder",
    # "ohne dass",
    "respektive",
    "so",
    "sobald",
    "sodass",
    # "so dass",
    "sofern",
    "solange",
    "sondern",
    "sonst",
    "sooft",
    "soviel",
    "soweit",
    "sowie",
    # "sowohl als auch",
    "statt",
    "um",
    "umso",
    "und",
    "wobei",
    "während",
    "währenddessen",
    # "weder noch",
    "weil",
    "wenn",
    "wie",
    "wo",
    "wohingegen",
    "zumal",
    "zwar",
    "und",
    "oder",
    "aber",
]

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

### en-US & en_GB:

for locale in ["en-US", "en-GB"]:
    ## words:
    # df open discrimination words
    df_discrimination = data[locale]["df_open_dis_word"]
    # open discrimination: lemma + alternatives split + subcategory
    rules[locale]["open_disc_words_data"] = list(
        zip(
            df_discrimination["Lemma"],
            df_discrimination["Word_Type"],
            map(ast.literal_eval, df_discrimination["Alt_split"]),
            df_discrimination["Primary_subcategory"],
        )
    )

    # df open discrimination words gender no noun
    df_gender_no_noun = data[locale]["df_gendered_no_noun_word"]
    # gender no noun: lemma + alternatives split + subcategory
    rules[locale]["gender_words_data"] = list(
        zip(
            df_gender_no_noun["Lemma"],
            df_gender_no_noun["Word_Type"],
            map(ast.literal_eval, df_gender_no_noun["Alt_split"]),
            df_gender_no_noun["Primary_subcategory"],
        )
    )

    # df style
    df_style = data[locale]["df_style_word"]
    # style: lemma + alternatives split + subcategory
    rules[locale]["style_words_data"] = list(
        zip(
            df_style["Lemma"],
            df_style["Word_Type"],
            map(ast.literal_eval, df_style["Alt_split"]),
            df_style["Primary_subcategory"],
        )
    )

    # df unconscious bias
    df_bias = data[locale]["df_ub_no_plur_word"]
    # unconscious bias: lemma + alternatives split + subcategory
    rules[locale]["bias_words_data"] = list(
        zip(
            df_bias["Lemma"],
            df_bias["Word_Type"],
            map(ast.literal_eval, df_bias["Alt_split"]),
            df_bias["Primary_subcategory"],
        )
    )

    # df inclusive
    df_inclusive = data[locale]["df_inclusive_word"]
    # inclusive: lemma + subcategory
    rules[locale]["inclusive_words_data"] = list(
        zip(
            df_inclusive["Lemma"],
            df_inclusive["Word_Type"],
            df_inclusive["Primary_subcategory"],
        )
    )

    # df homonyms words
    df_homonyms = data[locale]["df_homonyms_words"]
    # homonyms : lemma+word_type+category+subcategory+alternatives
    rules[locale]["homonyms_word"] = list(
        zip(
            df_homonyms["Lemma"],
            df_homonyms["Word_Type"],
            df_homonyms["Category"],
            df_homonyms["Primary_subcategory"],
            map(ast.literal_eval, df_homonyms["Alt_split"]),
        )
    )

    # df abbreviation english
    df_abbreviation = data[locale]["df_abbreviation"]
    # abbreviation : lemma+category+subcategory+alternatives
    rules[locale]["abbreviation"] = list(
        zip(
            df_abbreviation["Lemma"],
            df_abbreviation["Word_Type"],
            df_abbreviation["Category"],
            df_abbreviation["Primary_subcategory"],
            map(ast.literal_eval, df_abbreviation["Alt_split"]),
        )
    )

    # df gendered noun
    df_gender_noun = data[locale]["df_gendered_noun_word"]
    # gendered noun: lemma + singular alternatives split + plural alternatives split + primary subcategory + secondary subcategory
    rules[locale]["gender_noun_words_data"] = list(
        zip(
            df_gender_noun["Lemma"],
            df_gender_noun["Word_Type"],
            map(ast.literal_eval, df_gender_noun["Sg_all_split"]),
            map(ast.literal_eval, df_gender_noun["Pl_all_split"]),
            df_gender_noun["Primary_subcategory"],
            df_gender_noun["Secondary_subcategory"],
        )
    )

    # df gendered unconscious bias plural
    df_gendered_ub = data[locale]["df_ub_plur_word"]
    # gendered unconscious bias plural: lemma + singular alternatives split + plural alternatives split + subcategory
    rules[locale]["gender_bias_words_data"] = list(
        zip(
            df_gendered_ub["Lemma"],
            df_gendered_ub["Word_Type"],
            map(ast.literal_eval, df_gendered_ub["Sg_all_split"]),
            map(ast.literal_eval, df_gendered_ub["Pl_all_split"]),
            df_gendered_ub["Primary_subcategory"],
            df_gendered_ub["Secondary_subcategory"],
        )
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

    # df open discrimination sentences
    df_open_dis_sentences = data[locale]["df_open_dis_sentence"]
    # open discrimination sentences: lemma + alternatives split + subcategory
    rules[locale]["open_dis_sentences"] = list(
        zip(
            df_open_dis_sentences["Lemma"],
            map(ast.literal_eval, df_open_dis_sentences["Alt_split"]),
            df_open_dis_sentences["Primary_subcategory"],
        )
    )

    # df gendered sentences
    df_gendered_sentences = data[locale]["df_gendered_sentence"]
    # gendered sentences: lemma + alternatives split + primary subcategory
    rules[locale]["gender_sentences_data"] = list(
        zip(
            df_gendered_sentences["Lemma"],
            map(ast.literal_eval, df_gendered_sentences["Alt_split"]),
            df_gendered_sentences["Primary_subcategory"],
        )
    )

    # df style sentences
    df_style_sentences = data[locale]["df_style_sentence"]
    # style sentences: lemma + alternatives split + subcategory
    rules[locale]["style_sentences_data"] = list(
        zip(
            df_style_sentences["Lemma"],
            map(ast.literal_eval, df_style_sentences["Alt_split"]),
            df_style_sentences["Primary_subcategory"],
        )
    )

    # df unconscious bias sentences
    df_bias_sentences = data[locale]["df_ub_sentence"]
    # unconscious bias sentences: lemma + alternatives split + subcategory
    rules[locale]["bias_sentences_data"] = list(
        zip(
            df_bias_sentences["Lemma"],
            map(ast.literal_eval, df_bias_sentences["Alt_split"]),
            df_bias_sentences["Primary_subcategory"],
        )
    )

    df_bias_singular_they = data[locale]["df_ub_singular_they"]
    # unconscious bias singular they: lemma + alternatives split + subcategory
    rules[locale]["bias_singular_they_alternatives"] = list(
        zip(
            df_bias_singular_they["Lemma"],
            df_bias_singular_they["Word_Type"],
            map(ast.literal_eval, df_bias_singular_they["Alt_split"]),
            df_bias_singular_they["Primary_subcategory"],
        )
    )

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
    "fossil carbon",
    "fossil energy",
    "fossil finance",
    "fossil find",
    "fossil finding",
    "fossil fuel",
    "fossil fuels",
    "fossil gen 6",
    "fossil group",
    "fossil promo",
    "fossil smart watch",
    "fossil watch",
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

# need to
pattern_need_to = [[{"LEMMA": "need", "POS": "VERB"}, {"LEMMA": {"IN": ["to", "for"]}}]]

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
    pattern_of_kind,
    pattern_quick,
]

rules["en"]["conjunctions"] = [
    "and",
    "but",
    "or",
    "so",
    "because",
    "however",
    "after",
    "since",
    "during",
    "than",
    "unless",
    "that",
    "while",
]
