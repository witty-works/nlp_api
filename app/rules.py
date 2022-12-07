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
    r"(?i)\s(\()?(d|\*)\/f\/m(\/[*a-z])*(\))?": None,  # (d/f/m..)
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
    "have a problem with",
    "great deal",
    "fossil fuels",
    "best-practices",
    "waste my life",
    "best practice",
    "servant leaderships",
    "great enthusiasm",
    "force close",
    "lead exposure",
    "know best",
    "lead life",
    "bipolar disorder",
    "positions of authority",
    "self-driven minibus",
    "armed forces",
    "exceptionally good",
    "fossil finding",
    "fossil gen 6",
    "residential camps",
    "proof of authority",
    "fossil watch",
    "master's",
    "decisive moment",
    "paper waste",
    "lead-in",
    "nothing of the kind",
    "master student",
    "waste of breath",
    "waste of time",
    "direct public offering",
    "force to be reckoned",
    "of one kind or another",
    "POW camp",
    "master mechanism",
    "nature of authority",
    "lead the way",
    "Air Force",
    "presenting as female",
    "ethical hacker",
    "tough situation",
    "self-important",
    "minority interests",
    "authority figure",
    "very good",
    "letter of athority",
    "sounded forced",
    "dwarf star",
    "dirty trick",
    "master plan",
    "master-chemical-mechanism",
    "baby boomer",
    "labor force",
    "white paper",
    "really simple syndication",
    "goods",
    "back problems",
    "profit and loss",
    "waste energy",
    "problem-solving",
    "strong interest",
    "histrionic personality disorder",
    "dwarf satellite",
    "minority enterprises",
    "push the boundaries",
    "fossil promo",
    "good friends",
    "good at",
    "of a kind",
    "great at",
    "Minority Ethnic",
    "wild fruit",
    "fossil fuel",
    "one-trick pony",
    "fruit salad",
    "exceptional achievement",
    "best practices",
    "queer community",
    "fuzzy logic",
    "self-driven car",
    "quick checks",
    "assigned female",
    "sleepaway camps",
    "master class",
    "communal leadership",
    "boot camp",
    "self-driven trains",
    "competitive strategy",
    "waste their lives",
    "payment in kind",
    "alpha reader",
    "force out",
    "best available",
    "strong response",
    "a little forced",
    "residential camp",
    "competitive advantage",
    "waste our lives",
    "summer camp",
    "communal leaderships",
    "waste collectors",
    "good-looking",
    "presents as male",
    "minority shareholder",
    "biological father",
    "ethical security hackers",
    "waste effort",
    "identify as male",
    "good result",
    "works best",
    "has autism",
    "good hackers",
    "excessive force",
    "genetic father",
    "data analysis",
    "great time",
    "fossil smart watch",
    "do the trick",
    "force quit",
    "prison camp",
    "tough questions",
    "substance user",
    "good food",
    "opinion shaper",
    "prisoner-of-war camp",
    "good relations",
    "strong emotions",
    "lead a dog's life",
    "assigns female",
    "assign female",
    "passion fruit",
    "tour de force",
    "great lengths",
    "quick meeting",
    "good job",
    "toughen up",
    "gas up",
    "epileptic seizures",
    "anything of the kind",
    "competitive landscape",
    "waste collection",
    "competitive analysis",
    "only as strong as",
    "performance marketing",
    "bear fruit",
    "great day",
    "minority interest",
    "assigns male",
    "Indian Act",
    "undergrad student",
    "present as male",
    "trick up",
    "in full force",
    "assign male",
    "his best",
    "problem-solve",
    "good results",
    "first-mover advantage",
    "alpha read",
    "sub-camp",
    "assigned male",
    "poison fruit",
    "camp counselor",
    "Musqueam Indian Band",
    "global majority",
    "fruit of",
    "in the minority",
    "unique selling proposition",
    "your best",
    "generate a lead",
    "internment camp",
    "opinion shapers",
    "identify as female",
    "whitespace",
    "fierce competition",
    "best wishes",
    "performance indicators",
    "objectives and key results",
    "the authorities",
    "analyses",
    "trick or treat",
    "fit like a glove",
    "feel good",
    "competitive environment",
    "best effort",
    "epileptic episode",
    "work camp",
    "force of arms",
    "queer communities",
    "for the best",
    "tough situations",
    "fruit and vegetable",
    "great importance",
    "fossil carbon",
    "lead pipe",
    "forbidden fruit",
    "exceptional viable product",
    "camp counselors",
    "servant leadership",
    "good enough",
    "good faith",
    "unique selling point",
    "ethical hackers",
    "waste of",
    "nurture leads",
    "on-time performance",
    "her best",
    "performance review",
    "work best",
    "lead piping",
    "health problems",
    "fossil finance",
    "of their kind",
    "assigning female",
    "surpassed expectations",
    "their best",
    "extremely well",
    "Indian status",
    "know every trick",
    "exceptionally well",
    "quick call",
    "win the advantage",
    "math camp",
    "strong desire",
    "dirty tricks",
    "presented as female",
    "force to reckon",
    "sleepaway camp",
    "waste of money",
    "has a problem with",
    "common problem",
    "whitepaper",
    "strong as an ox",
    "lead bank",
    "some kind of",
    "direct message",
    "win over",
    "by force",
    "problem-solver",
    "performance indicator",
    "medical analysis",
    "math camps",
    "unique visitors",
    "lead nowhere",
    "waste feelings",
    "not a problem",
    "fossil energy",
    "quick exit",
    "play a trick",
    "police force",
    "waste money",
    "communal leader",
    "autism spectrum disorder",
    "force for good",
    "identifies as male",
    "assigning male",
    "great job",
    "grow fruit",
    "competitive market",
    "master students",
    "unique visitor",
    "analysis team",
    "fruit preserves",
    "epileptic seizure",
    "undergrad students",
    "biological son",
    "sending you the best",
    "great-hearted",
    "do best",
    "no problem",
    "waste collector",
    "win an advantage",
    "task force",
    "of his kind",
    "ethical security hacker",
    "unique sellings points",
    "vaccination drives",
    "data analytics",
    "good hacker",
    "strong feelings",
    "genetic mother",
    "birth father",
    "trick of the trade",
    "minority shareholders",
    "sound forced",
    "directed",
    "alpha reading",
    "identifies as female",
    "fruit juice",
    "genetic son",
    "vaccination drive",
    "self-driven train",
    "holiday camp",
    "waste your life",
    "lead service line",
    "force in",
    "detention camp",
    "birth mother",
    "fruit preserve",
    "great effort",
    "good offer",
    "quick check",
    "surpass expectations",
    "forbidden fruits",
    "certificate of authority",
    "user experience",
    "follow a lead",
    "waste time",
    "presenting as male",
    "good impression",
    "lead generation",
    "of its kind",
    "servant leader",
    "award-winning type",
    "presented as male",
    "death camp",
    "unique selling propositions",
    "competitive cyclist",
    "waste receptacle",
    "best regards",
    "fossil find",
    "optical trick",
    "perform a trick",
    "growth hackers",
    "our best",
    "Nazi camp",
    "back problem",
    "concussive force",
    "best-practice",
    "lead manager",
    "of her kind",
    "do the best",
    "would be great",
    "position of authority",
    "force of habit",
    "concentration camp",
    "extreme mood",
    "lead-foot",
    "problem-solves",
    "good fit",
    "camp mother",
    "fruit loops",
    "growth hacker",
    "generally accepted",
    "look for leads",
    "waste away",
    "opioid addiction",
    "stong hunch",
    "whitebox testing",
    "fossil group",
    "competitive pricing",
    "performance of",
    "trick of ther light",
    "PhD students",
    "minority enterprise",
    "presents as female",
    "the force be with you",
    "epileptic episodes",
    "knows best",
    "statement of authority",
    "all the best",
    "present as female",
    "greater",
    "competitive intelligence",
    "going gets tough",
    "performance test",
    "generate leads",
    "tough question",
    "lead astray",
    "waste of feelings",
    "labor camp",
    "self-driven cars",
    "PhD student",
    "holiday camps",
    "wheelchair-user",
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

# lead+someone(optional)+prepostion(on, down, up, to, away, back, along, with, off, by, in)
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

rules["en"]["pattern_false_positives"] = [
    pattern_master,
    pattern_lead_prepos,
    pattern_lead_life,
    pattern_need_to,
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
