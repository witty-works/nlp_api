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
        rules["de-DE"]["df_articles"]["Masculine"],
        rules["de-DE"]["df_articles"]["Feminine"],
        rules["de-DE"]["df_articles"]["Neuter"],
        rules["de-DE"]["df_articles"]["Plural"],
        rules["de-DE"]["df_articles"]["Alternative"],
    )
)
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
        df_abbreviation_US["Category"],
        df_abbreviation_US["Primary_subcategory"],
        map(ast.literal_eval, df_abbreviation_US["Alt_split"]),
    )
)
abbreviation_GB = list(
    zip(
        df_abbreviation_GB["Lemma"],
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

list_false_column = [
    "fit like a glove",
    "good fit",
    "analysis team",
    "data analysis",
    "data analytics",
    "baby boomer",
    "decisive moment",
    "vaccination drive",
    "vaccination drives",
    "fierce competition",
    "fossil fuels",
    "fossil fuel",
    "fossil watch",
    "fossil smart watch",
    "fossil promo",
    "fossil gen 6",
    "fossil group",
    "fossil finding",
    "fossil find",
    "fossil finance",
    "fossil energy",
    "fossil carbon",
    "of its kind",
    "of their kind",
    "of his kind",
    "of her kind",
    "payment in kind",
    "anything of the kind",
    "of one kind or another",
    "of a kind",
    "some kind of",
    "nothing of the kind",
    "lead nowhere",
    "lead astray",
    "lead a dog's life",
    "lead off",
    "lead on",
    "lead someone by the nose",
    "lead someone down the garden path",
    "lead someone up the garden path",
    "lead someone on",
    "lead someone on a merry chase",
    "lead someone to believe something",
    "lead someone to do something",
    "lead the way",
    "lead-foot",
    "lead-in",
    "lead up to",
    "lead to",
    "lead with",
    "lead generation",
    "generate leads",
    "generate a lead",
    "nurture leads",
    "follow a lead",
    "look for leads",
    "lead bank",
    "lead manager",
    "lead pipe",
    "lead service line",
    "lead piping",
    "lead in drinking water",
    "lead exposure",
    "servant leader",
    "communal leader",
    "servant leadership",
    "communal leadership",
    "master's",
    "Master of Arts",
    "Master of Science",
    "Master of Laws",
    "Master of Education",
    "Master of Fine Arts",
    "Master of Music",
    "Master of Business Administration",
    "master class",
    "master of ceremonies",
    "master plan",
    "master-chemical-mechanism",
    "master mechanism",
    "need to",
    "performance indicator",
    "performance indicators",
    "performance review",
    "performance marketing",
    "performance test",
    "performance of",
    "PhD student",
    "PhD students",
    "undergrad students",
    "undergrad student",
    "unique selling proposition",
    "unique selling propositions",
    "unique selling point",
    "unique sellings points",
    "user experience",
    "wheelchair-user",
    "substance user",
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

# lead+someone(optional)+prepostion(on, down, up, to, away, back, along)
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
