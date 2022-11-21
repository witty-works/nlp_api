import pandas as pd
import ast
from collections import namedtuple
from german_nouns.lookup import Nouns

rules = {
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

rules["en-GB"] = rules["en-US"].copy()

for locale in rules:
    for csv in rules[locale]:
        rules[locale][csv] = pd.read_csv(
            "training_data/" + locale + "/" + rules[locale][csv], keep_default_na=False
        )

# list of "hollow word" sentences
rules["de-DE"]["terms_style"] = list(rules["de-DE"]["df_style_sentences"]["Lemma"])

# list of "d_and_i_words word" sentences
rules["de-DE"]["df_terms_d_and_i_words"] = list(
    rules["de-DE"]["df_d_and_i_words_sentences"]["Lemma"],
)

# list of "d_and_i_words word" sentences
rules["de-DE"]["df_d_and_i_words"] = list(
    zip(
        rules["de-DE"]["df_d_and_i_words"]["Lemma"],
        rules["de-DE"]["df_d_and_i_words"]["Word_Type"],
    )
)

# list of "df_communal_words word" sentences
rules["de-DE"]["df_communal_words"] = list(
    zip(
        rules["de-DE"]["df_communal_words"]["Lemma"],
        rules["de-DE"]["df_communal_words"]["Word_Type"],
    )
)

# dictionaries to handle false positives
rules["de-DE"]["gender_false_positive"] = list(
    rules["de-DE"]["df_gender_false_positive"]["False_positives"]
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
df_gender = rules["de-DE"]["df_gender_ct"]
# gender: words + singular alternatives + plural alternatives + all alternatives + subcategory
gender_words_data = list(
    zip(
        df_gender["Lemma"],
        df_gender["Word_Type"],
        map(ast.literal_eval, df_gender["Sg_all_split"]),
        map(ast.literal_eval, df_gender["Pl_all_split"]),
        map(ast.literal_eval, df_gender["Alt_split"]),
        df_gender["Primary_subcategory"],
    )
)
# df gendered no noun
df_gendered_no_noun = rules["de-DE"]["df_gender_no_noun_word"]
# gendered: words + alternatives split + subcategory
gender_words_data_no_noun = list(
    zip(
        df_gendered_no_noun["Lemma"],
        df_gendered_no_noun["Word_Type"],
        map(ast.literal_eval, df_gendered_no_noun["Alt_split"]),
        df_gendered_no_noun["Primary_subcategory"],
    )
)
# articles
articles = list(
    zip(
        rules["de-DE"]["df_articles"]["Form"],
        rules["de-DE"]["df_articles"]["Masculine"],
        rules["de-DE"]["df_articles"]["Feminine"],
        rules["de-DE"]["df_articles"]["Neuter"],
        rules["de-DE"]["df_articles"]["Plural"],
        rules["de-DE"]["df_articles"]["Alternative"],
    )
)
male_articles = list(rules["de-DE"]["df_articles"]["Masculine"])

# df unconscious bias nouns with plural
df_bias = rules["de-DE"]["df_ub_plur_word"]
# unconscious bias: words + singular alternatives split + plural alternatives split + subcategory
bias_words_data_noun = list(
    zip(
        df_bias["Lemma"],
        df_bias["Word_Type"],
        map(ast.literal_eval, df_bias["Sg_all_split"]),
        map(ast.literal_eval, df_bias["Pl_all_split"]),
        df_bias["Primary_subcategory"],
    )
)
# df unconscious bias words without plurals
df_bias_no_plur = rules["de-DE"]["df_ub_no_plur_word"]
# unconscious bias: words + alternatives split + subcategory
bias_words_data_no_plur = list(
    zip(
        df_bias_no_plur["Lemma"],
        df_bias_no_plur["Word_Type"],
        map(ast.literal_eval, df_bias_no_plur["Alt_split"]),
        df_bias_no_plur["Primary_subcategory"],
    )
)
# df style
df_style = rules["de-DE"]["df_style_word"]
# style: words + alternatives + subcategory
style_words_data = list(
    zip(
        df_style["Lemma"],
        df_style["Word_Type"],
        map(ast.literal_eval, df_style["Alt_split"]),
        df_style["Primary_subcategory"],
    )
)
# df open discrimination words
df_discrimination_words = rules["de-DE"]["df_open_dis_word"]
# open discrimination: words + alternative_split + subcategory
open_disc_words_data = list(
    zip(
        df_discrimination_words["Lemma"],
        df_discrimination_words["Word_Type"],
        map(ast.literal_eval, df_discrimination_words["Alt_split"]),
        df_discrimination_words["Primary_subcategory"],
    )
)
# df abbreviation
df_abbreviation = rules["de-DE"]["df_abbreviation"]
# abbreviation: lemma + category + subcategory + alternatives
abbreviation = list(
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
df_discrimination_sentences = rules["de-DE"]["df_open_dis_sentence"]
# open discrimination: sentences +alternatives split + subcategory
open_disc_sentences_data = list(
    zip(
        df_discrimination_sentences["Lemma"],
        map(ast.literal_eval, df_discrimination_sentences["Alt_split"]),
        df_discrimination_sentences["Primary_subcategory"],
    )
)
# df gendered sentences
df_gendered_sentences = rules["de-DE"]["df_gendered_sentences"]
# gendered: sentences + alternatives split + subcategory
gender_sentences_data = list(
    zip(
        df_gendered_sentences["Lemma"],
        map(ast.literal_eval, df_gendered_sentences["Alt_split"]),
        df_gendered_sentences["Primary_subcategory"],
    )
)
# df unconscious bias sentences
df_bias_sentences = rules["de-DE"]["df_ub_sentences"]
# unconscious bias: sentences + alternatives split + subcategory
bias_sentences_data = list(
    zip(
        df_bias_sentences["Lemma"],
        map(ast.literal_eval, df_bias_sentences["Alt_split"]),
        df_bias_sentences["Primary_subcategory"],
    )
)
# df style sentences
df_style_sentences = rules["de-DE"]["df_style_sentences"]
# style: sentences + alternatives + subcategory
style_sentences_data = list(
    zip(
        df_style_sentences["Lemma"],
        map(ast.literal_eval, df_style_sentences["Alt_split"]),
        df_style_sentences["Primary_subcategory"],
    )
)
### en-US & en_GB:
## words:
# df open discrimination words
df_discrimination_US = rules["en-US"]["df_open_dis_word"]
df_discrimination_GB = rules["en-GB"]["df_open_dis_word"]
# open discrimination: lemma + alternatives split + subcategory
open_disc_words_data_US = list(
    zip(
        df_discrimination_US["Lemma"],
        df_discrimination_US["Word_Type"],
        map(ast.literal_eval, df_discrimination_US["Alt_split"]),
        df_discrimination_US["Primary_subcategory"],
    )
)
open_disc_words_data_GB = list(
    zip(
        df_discrimination_GB["Lemma"],
        df_discrimination_GB["Word_Type"],
        map(ast.literal_eval, df_discrimination_GB["Alt_split"]),
        df_discrimination_GB["Primary_subcategory"],
    )
)
# df open discrimination words gender no noun
df_gender_no_noun_US = rules["en-US"]["df_gendered_no_noun_word"]
df_gender_no_noun_GB = rules["en-GB"]["df_gendered_no_noun_word"]
# gender no noun: lemma + alternatives split + subcategory
gender_words_data_US = list(
    zip(
        df_gender_no_noun_US["Lemma"],
        df_gender_no_noun_US["Word_Type"],
        map(ast.literal_eval, df_gender_no_noun_US["Alt_split"]),
        df_gender_no_noun_US["Primary_subcategory"],
    )
)
gender_words_data_GB = list(
    zip(
        df_gender_no_noun_GB["Lemma"],
        df_gender_no_noun_GB["Word_Type"],
        map(ast.literal_eval, df_gender_no_noun_GB["Alt_split"]),
        df_gender_no_noun_GB["Primary_subcategory"],
    )
)
# df style
df_style_US = rules["en-US"]["df_style_word"]
df_style_GB = rules["en-GB"]["df_style_word"]
# style: lemma + alternatives split + subcategory
style_words_data_US = list(
    zip(
        df_style_US["Lemma"],
        df_style_US["Word_Type"],
        map(ast.literal_eval, df_style_US["Alt_split"]),
        df_style_US["Primary_subcategory"],
    )
)
style_words_data_GB = list(
    zip(
        df_style_GB["Lemma"],
        df_style_GB["Word_Type"],
        map(ast.literal_eval, df_style_GB["Alt_split"]),
        df_style_GB["Primary_subcategory"],
    )
)
# df unconscious bias
df_bias_US = rules["en-US"]["df_ub_no_plur_word"]
df_bias_GB = rules["en-GB"]["df_ub_no_plur_word"]
# unconscious bias: lemma + alternatives split + subcategory
bias_words_data_US = list(
    zip(
        df_bias_US["Lemma"],
        df_bias_US["Word_Type"],
        map(ast.literal_eval, df_bias_US["Alt_split"]),
        df_bias_US["Primary_subcategory"],
    )
)
bias_words_data_GB = list(
    zip(
        df_bias_GB["Lemma"],
        df_bias_GB["Word_Type"],
        map(ast.literal_eval, df_bias_GB["Alt_split"]),
        df_bias_GB["Primary_subcategory"],
    )
)

# df inclusive
df_inclusive_US = rules["en-US"]["df_inclusive_word"]
df_inclusive_GB = rules["en-GB"]["df_inclusive_word"]
# inclusive: lemma + subcategory
inclusive_words_data_US = list(
    zip(
        df_inclusive_US["Lemma"],
        df_inclusive_US["Word_Type"],
        df_inclusive_US["Primary_subcategory"],
    )
)
inclusive_words_data_GB = list(
    zip(
        df_inclusive_GB["Lemma"],
        df_inclusive_GB["Word_Type"],
        df_inclusive_GB["Primary_subcategory"],
    )
)
# df homonyms words
df_homonyms_US = rules["en-US"]["df_homonyms_words"]
df_homonyms_GB = rules["en-GB"]["df_homonyms_words"]
# homonyms : lemma+word_type+category+subcategory+alternatives
homonyms_word_US = list(
    zip(
        df_homonyms_US["Lemma"],
        df_homonyms_US["Word_Type"],
        df_homonyms_US["Category"],
        df_homonyms_US["Primary_subcategory"],
        map(ast.literal_eval, df_homonyms_US["Alt_split"]),
    )
)
homonyms_word_GB = list(
    zip(
        df_homonyms_GB["Lemma"],
        df_homonyms_GB["Word_Type"],
        df_homonyms_GB["Category"],
        df_homonyms_GB["Primary_subcategory"],
        map(ast.literal_eval, df_homonyms_GB["Alt_split"]),
    )
)

# df abbreviation english
df_abbreviation_US = rules["en-US"]["df_abbreviation"]
df_abbreviation_GB = rules["en-GB"]["df_abbreviation"]
# abbreviation : lemma+category+subcategory+alternatives
abbreviation_US = list(
    zip(
        df_abbreviation_US["Lemma"],
        df_abbreviation_US["Word_Type"],
        df_abbreviation_US["Category"],
        df_abbreviation_US["Primary_subcategory"],
        map(ast.literal_eval, df_abbreviation_US["Alt_split"]),
    )
)
abbreviation_GB = list(
    zip(
        df_abbreviation_GB["Lemma"],
        df_abbreviation_GB["Word_Type"],
        df_abbreviation_GB["Category"],
        df_abbreviation_GB["Primary_subcategory"],
        map(ast.literal_eval, df_abbreviation_GB["Alt_split"]),
    )
)
# df gendered noun
df_gender_noun_US = rules["en-US"]["df_gendered_noun_word"]
df_gender_noun_GB = rules["en-GB"]["df_gendered_noun_word"]
# gendered noun: lemma + singular alternatives split + plural alternatives split + primary subcategory + secondary subcategory
gender_noun_words_data_US = list(
    zip(
        df_gender_noun_US["Lemma"],
        df_gender_noun_US["Word_Type"],
        map(ast.literal_eval, df_gender_noun_US["Sg_all_split"]),
        map(ast.literal_eval, df_gender_noun_US["Pl_all_split"]),
        df_gender_noun_US["Primary_subcategory"],
        df_gender_noun_US["Secondary_subcategory"],
    )
)
gender_noun_words_data_GB = list(
    zip(
        df_gender_noun_GB["Lemma"],
        df_gender_noun_GB["Word_Type"],
        map(ast.literal_eval, df_gender_noun_GB["Sg_all_split"]),
        map(ast.literal_eval, df_gender_noun_GB["Pl_all_split"]),
        df_gender_noun_GB["Primary_subcategory"],
        df_gender_noun_GB["Secondary_subcategory"],
    )
)
# df gendered unconscious bias plural
df_gendered_ub_US = rules["en-US"]["df_ub_plur_word"]
df_gendered_ub_GB = rules["en-GB"]["df_ub_plur_word"]
# gendered unconscious bias plural: lemma + singular alternatives split + plural alternatives split + subcategory
gender_bias_words_data_US = list(
    zip(
        df_gendered_ub_US["Lemma"],
        df_gendered_ub_US["Word_Type"],
        map(ast.literal_eval, df_gendered_ub_US["Sg_all_split"]),
        map(ast.literal_eval, df_gendered_ub_US["Pl_all_split"]),
        df_gendered_ub_US["Primary_subcategory"],
        df_gendered_ub_US["Secondary_subcategory"],
    )
)
gender_bias_words_data_GB = list(
    zip(
        df_gendered_ub_GB["Lemma"],
        df_gendered_ub_US["Word_Type"],
        map(ast.literal_eval, df_gendered_ub_GB["Sg_all_split"]),
        map(ast.literal_eval, df_gendered_ub_GB["Pl_all_split"]),
        df_gendered_ub_GB["Primary_subcategory"],
        df_gendered_ub_GB["Secondary_subcategory"],
    )
)

##sentences
# df inclusive sentences
df_inclusive_sentences_US = rules["en-US"]["df_inclusive_sentence"]
df_inclusive_sentences_GB = rules["en-GB"]["df_inclusive_sentence"]
# inclusive sentences: lemma + subcategory
inclusive_sentences_data_US = list(
    zip(
        df_inclusive_sentences_US["Lemma"],
        df_inclusive_sentences_US["Primary_subcategory"],
    )
)
inclusive_sentences_data_GB = list(
    zip(
        df_inclusive_sentences_GB["Lemma"],
        df_inclusive_sentences_GB["Primary_subcategory"],
    )
)
# df open discrimination sentences
df_open_dis_sentences_US = rules["en-US"]["df_open_dis_sentence"]
df_open_dis_sentences_GB = rules["en-GB"]["df_open_dis_sentence"]
# open discrimination sentences: lemma + alternatives split + subcategory
open_dis_sentences_US = list(
    zip(
        df_open_dis_sentences_US["Lemma"],
        map(ast.literal_eval, df_open_dis_sentences_US["Alt_split"]),
        df_open_dis_sentences_US["Primary_subcategory"],
    )
)
open_dis_sentences_GB = list(
    zip(
        df_open_dis_sentences_GB["Lemma"],
        map(ast.literal_eval, df_open_dis_sentences_GB["Alt_split"]),
        df_open_dis_sentences_GB["Primary_subcategory"],
    )
)
# df gendered sentences
df_gendered_sentences_US = rules["en-US"]["df_gendered_sentence"]
df_gendered_sentences_GB = rules["en-GB"]["df_gendered_sentence"]
# gendered sentences: lemma + alternatives split + primary subcategory
gender_sentences_data_US = list(
    zip(
        df_gendered_sentences_US["Lemma"],
        map(ast.literal_eval, df_gendered_sentences_US["Alt_split"]),
        df_gendered_sentences_US["Primary_subcategory"],
    )
)
gender_sentences_data_GB = list(
    zip(
        df_gendered_sentences_GB["Lemma"],
        map(ast.literal_eval, df_gendered_sentences_GB["Alt_split"]),
        df_gendered_sentences_GB["Primary_subcategory"],
    )
)
# df style sentences
df_style_sentences_US = rules["en-US"]["df_style_sentence"]
df_style_sentences_GB = rules["en-GB"]["df_style_sentence"]
# style sentences: lemma + alternatives split + subcategory
style_sentences_data_US = list(
    zip(
        df_style_sentences_US["Lemma"],
        map(ast.literal_eval, df_style_sentences_US["Alt_split"]),
        df_style_sentences_US["Primary_subcategory"],
    )
)
style_sentences_data_GB = list(
    zip(
        df_style_sentences_GB["Lemma"],
        map(ast.literal_eval, df_style_sentences_GB["Alt_split"]),
        df_style_sentences_GB["Primary_subcategory"],
    )
)
# df unconscious bias sentences
df_bias_sentences_US = rules["en-US"]["df_ub_sentence"]
df_bias_sentences_GB = rules["en-GB"]["df_ub_sentence"]
# unconscious bias sentences: lemma + alternatives split + subcategory
bias_sentences_data_US = list(
    zip(
        df_bias_sentences_US["Lemma"],
        map(ast.literal_eval, df_bias_sentences_US["Alt_split"]),
        df_bias_sentences_US["Primary_subcategory"],
    )
)
bias_sentences_data_GB = list(
    zip(
        df_bias_sentences_GB["Lemma"],
        map(ast.literal_eval, df_bias_sentences_GB["Alt_split"]),
        df_bias_sentences_GB["Primary_subcategory"],
    )
)

df_bias_singular_they_US = rules["en-US"]["df_ub_singular_they"]
df_bias_singular_they_GB = rules["en-GB"]["df_ub_singular_they"]
# unconscious bias singular they: lemma + alternatives split + subcategory
bias_singular_they_alternatives_US = list(
    zip(
        df_bias_singular_they_US["Lemma"],
        df_bias_singular_they_US["Word_Type"],
        map(ast.literal_eval, df_bias_singular_they_US["Alt_split"]),
        df_bias_singular_they_US["Primary_subcategory"],
    )
)
bias_singular_they_alternatives_GB = list(
    zip(
        df_bias_singular_they_GB["Lemma"],
        df_bias_singular_they_GB["Word_Type"],
        map(ast.literal_eval, df_bias_singular_they_GB["Alt_split"]),
        df_bias_singular_they_GB["Primary_subcategory"],
    )
)

FalsePositive = namedtuple("FalsePositive", "gender style")

false_positives = FalsePositive(
    rules["de-DE"]["gender_false_positive"], rules["de-DE"]["style_false_positive"]
)

m_w_alternatives_w = ["-", "d/w/m", "*/w/m", "w/d/m", "w/*/m"]
m_w_alternatives_f = []
m_w_alternatives_w_parenthesis = []
m_w_alternatives_f_parenthesis = []
for item in m_w_alternatives_w:
    item_f = item.replace("w", "f")
    m_w_alternatives_f.append(item_f)

    if item == "-":
        m_w_alternatives_w_parenthesis.append(item)
        m_w_alternatives_f_parenthesis.append(item)
    else:
        m_w_alternatives_w_parenthesis.append("(" + item + ")")
        m_w_alternatives_f_parenthesis.append("(" + item_f + ")")

m_w_regexes = {
    r"\s(\w\/m)": m_w_alternatives_w,  # w/m
    r"\s(\f\/m)": m_w_alternatives_f,  # f/m
    r"\s(\(\w\/m\))": m_w_alternatives_w_parenthesis,  # (w/m)
    r"\s(\(\f\/m\))": m_w_alternatives_f_parenthesis,  # (f/m)
    r"\s(m\/w)": m_w_alternatives_w,  # m/w
    r"\s(m\/f)": m_w_alternatives_f,  # m/f
    r"\s(\(m\/w\))": m_w_alternatives_w_parenthesis,  # (m/w)
    r"\s(\(m\/f\))": m_w_alternatives_f_parenthesis,  # (m/f)
    r"\s(m\/w\/d)": m_w_alternatives_w,  # m/w/d
    r"\s(m\/f\/d)": m_w_alternatives_f,  # m/f/d
    r"\s(\(m\/w\/d\))": m_w_alternatives_w_parenthesis,  # (m/w/d)
    r"\s(\(m\/f\/d\))": m_w_alternatives_f_parenthesis,  # (m/f/d)
    r"\s(m\/w\/\*)": m_w_alternatives_w,  # m/w/*
    r"\s(m\/f\/\*)": m_w_alternatives_f,  # m/f/*
    r"\s(\(m\/w\/\*\))": m_w_alternatives_w_parenthesis,  # (m/w/*)
    r"\s(\(m\/f\/\*\))": m_w_alternatives_f_parenthesis,  # (m/f/*)
}

primary_german_genus_endings = {
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

secondary_german_genus_endings = {
    # 3 out of four words ending with -nis and -sal are neuter nouns
    "n": [
        "nis", "sal",
    ],
    # There are exceptions such as Postillion, which is masculine while the oberwhelming majority of -ion words in German is feminine.
    "f": [
        "ion",
    ],
    # More than half of  words ending with -er, -en, -el are masculine
    "m": [
        "er", "en", "el",
    ],
}

list_false_column = [
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

pattern_false_positives = {
    "en": [
        pattern_master,
        pattern_lead_prepos,
        pattern_lead_life,
        pattern_need_to,
    ],
    "de": [],
}

german_nouns = Nouns()

conjunctions = {
    # all the multi-word conjunctions are included as individual words except for "weder noch"
    "de": [
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
    ],
    "en": [
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
    ],
}
