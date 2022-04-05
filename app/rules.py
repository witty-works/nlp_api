import pandas as pd
import ast
from collections import namedtuple

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
            "training_data/" + locale + "/" + rules[locale][csv]
        )

# list of "hollow word" sentences
rules["de-DE"]["terms_style"] = list(rules["de-DE"]["df_style_sentences"]["Lemma"])

# list of "d_and_i_words word" sentences
rules["de-DE"]["terms_d_and_i_words"] = list(
    rules["de-DE"]["df_d_and_i_words_sentences"]["Lemma"]
)

# dictionaries to handle false positives
rules["de-DE"]["false_positive_agentic_const"] = [
    "selbst",
    "stark",
    "flexible",
    "Probleme",
    "unabhängig",
    "Entwickler",
]
rules["de-DE"]["gender_false_positive"] = list(
    rules["de-DE"]["df_gender_false_positive"]["False_positives"]
)
rules["de-DE"]["false_positive_style"] = ["international"]
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
gender_words_alternatives = list(
    zip(
        df_gender["Lemma"],
        map(ast.literal_eval, df_gender["Sg_all_split"]),
        map(ast.literal_eval, df_gender["Pl_all_split"]),
        map(ast.literal_eval, df_gender["Alt_split"]),
        df_gender["Primary_subcategory"],
    )
)
# df gendered no noun
df_gendered_no_noun = rules["de-DE"]["df_gender_no_noun_word"]
# gendered: words + alternatives split + subcategory
gender_words_alternatives_no_noun = list(
    zip(
        df_gendered_no_noun["Lemma"],
        map(ast.literal_eval, df_gendered_no_noun["Alt_split"]),
        df_gendered_no_noun["Primary_subcategory"],
    )
)
# articles
articles = list(
    zip(
        rules["de-DE"]["df_articles"]["Lemma"],
        rules["de-DE"]["df_articles"]["Alternative"],
    )
)
# df unconscious bias nouns with plural
df_bias = rules["de-DE"]["df_ub_plur_word"]
# unconscious bias: words + singular alternatives split + plural alternatives split + subcategory
bias_words_alternatives_noun = list(
    zip(
        df_bias["Lemma"],
        map(ast.literal_eval, df_bias["Sg_all_split"]),
        map(ast.literal_eval, df_bias["Pl_all_split"]),
        df_bias["Primary_subcategory"],
    )
)
# df unconscious bias words without plurals
df_bias_no_plur = rules["de-DE"]["df_ub_no_plur_word"]
# unconscious bias: words + alternatives split + subcategory
bias_words_alternatives_no_plur = list(
    zip(
        df_bias_no_plur["Lemma"],
        map(ast.literal_eval, df_bias_no_plur["Alt_split"]),
        df_bias_no_plur["Primary_subcategory"],
    )
)
# df style
df_style = rules["de-DE"]["df_style_word"]
# style: words + alternatives + subcategory
style_words_alternatives = list(
    zip(
        df_style["Lemma"],
        map(ast.literal_eval, df_style["Alt_split"]),
        df_style["Primary_subcategory"],
    )
)
# df open discrimination words
df_discrimination_words = rules["de-DE"]["df_open_dis_word"]
# open discrimination: words + alternative_split + subcategory
open_disc_words_alternatives = list(
    zip(
        df_discrimination_words["Lemma"],
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
open_disc_sentences_alternatives = list(
    zip(
        df_discrimination_sentences["Lemma"],
        map(ast.literal_eval, df_discrimination_sentences["Alt_split"]),
        df_discrimination_sentences["Primary_subcategory"],
    )
)
# df gendered sentences
df_gendered_sentences = rules["de-DE"]["df_gendered_sentences"]
# gendered: sentences + alternatives split + subcategory
gender_sentences_alternatives = list(
    zip(
        df_gendered_sentences["Lemma"],
        map(ast.literal_eval, df_gendered_sentences["Alt_split"]),
        df_gendered_sentences["Primary_subcategory"],
    )
)
# df unconscious bias sentences
df_bias_sentences = rules["de-DE"]["df_ub_sentences"]
# unconscious bias: sentences + alternatives split + subcategory
bias_sentences_alternatives = list(
    zip(
        df_bias_sentences["Lemma"],
        map(ast.literal_eval, df_bias_sentences["Alt_split"]),
        df_bias_sentences["Primary_subcategory"],
    )
)
# df style sentences
df_style_sentences = rules["de-DE"]["df_style_sentences"]
# style: sentences + alternatives + subcategory
style_sentences_alternatives = list(
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
open_disc_words_alternatives_US = list(
    zip(
        df_discrimination_US["Lemma"],
        map(ast.literal_eval, df_discrimination_US["Alt_split"]),
        df_discrimination_US["Primary_subcategory"],
    )
)
open_disc_words_alternatives_GB = list(
    zip(
        df_discrimination_GB["Lemma"],
        map(ast.literal_eval, df_discrimination_GB["Alt_split"]),
        df_discrimination_GB["Primary_subcategory"],
    )
)
# df open discrimination words gender no noun
df_gender_no_noun_US = rules["en-US"]["df_gendered_no_noun_word"]
df_gender_no_noun_GB = rules["en-GB"]["df_gendered_no_noun_word"]
# gender no noun: lemma + alternatives split + subcategory
gender_words_alternatives_US = list(
    zip(
        df_gender_no_noun_US["Lemma"],
        map(ast.literal_eval, df_gender_no_noun_US["Alt_split"]),
        df_gender_no_noun_US["Primary_subcategory"],
    )
)
gender_words_alternatives_GB = list(
    zip(
        df_gender_no_noun_GB["Lemma"],
        map(ast.literal_eval, df_gender_no_noun_GB["Alt_split"]),
        df_gender_no_noun_GB["Primary_subcategory"],
    )
)
# df style
df_style_US = rules["en-US"]["df_style_word"]
df_style_GB = rules["en-GB"]["df_style_word"]
# style: lemma + alternatives split + subcategory
style_words_alternatives_US = list(
    zip(
        df_style_US["Lemma"],
        map(ast.literal_eval, df_style_US["Alt_split"]),
        df_style_US["Primary_subcategory"],
    )
)
style_words_alternatives_GB = list(
    zip(
        df_style_GB["Lemma"],
        map(ast.literal_eval, df_style_GB["Alt_split"]),
        df_style_GB["Primary_subcategory"],
    )
)
# df unconscious bias
df_bias_US = rules["en-US"]["df_ub_no_plur_word"]
df_bias_GB = rules["en-GB"]["df_ub_no_plur_word"]
# unconscious bias: lemma + alternatives split + subcategory
bias_words_alternatives_US = list(
    zip(
        df_bias_US["Lemma"],
        map(ast.literal_eval, df_bias_US["Alt_split"]),
        df_bias_US["Primary_subcategory"],
    )
)
bias_words_alternatives_GB = list(
    zip(
        df_bias_GB["Lemma"],
        map(ast.literal_eval, df_bias_GB["Alt_split"]),
        df_bias_GB["Primary_subcategory"],
    )
)

# df inclusive
df_inclusive_US = rules["en-US"]["df_inclusive_word"]
df_inclusive_GB = rules["en-GB"]["df_inclusive_word"]
# inclusive: lemma + subcategory
inclusive_words_alternatives_US = list(
    zip(df_inclusive_US["Lemma"], df_inclusive_US["Primary_subcategory"])
)
inclusive_words_alternatives_GB = list(
    zip(df_inclusive_GB["Lemma"], df_inclusive_GB["Primary_subcategory"])
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
# gendered noun: lemma + singular alternatives split + plural alternatives split + subcategory
gender_noun_words_alternatives_US = list(
    zip(
        df_gender_noun_US["Lemma"],
        map(ast.literal_eval, df_gender_noun_US["Sg_all_split"]),
        map(ast.literal_eval, df_gender_noun_US["Pl_all_split"]),
        df_gender_noun_US["Primary_subcategory"],
    )
)
gender_noun_words_alternatives_GB = list(
    zip(
        df_gender_noun_GB["Lemma"],
        map(ast.literal_eval, df_gender_noun_GB["Sg_all_split"]),
        map(ast.literal_eval, df_gender_noun_GB["Pl_all_split"]),
        df_gender_noun_GB["Primary_subcategory"],
    )
)
# df gendered unconscious bias plural
df_gendered_ub_US = rules["en-US"]["df_ub_plur_word"]
df_gendered_ub_GB = rules["en-GB"]["df_ub_plur_word"]
# gendered unconscious bias plural: lemma + singular alternatives split + plural alternatives split + subcategory
gender_bias_words_alternatives_US = list(
    zip(
        df_gendered_ub_US["Lemma"],
        map(ast.literal_eval, df_gendered_ub_US["Sg_all_split"]),
        map(ast.literal_eval, df_gendered_ub_US["Pl_all_split"]),
        df_gendered_ub_US["Primary_subcategory"],
    )
)
gender_bias_words_alternatives_GB = list(
    zip(
        df_gendered_ub_GB["Lemma"],
        map(ast.literal_eval, df_gendered_ub_GB["Sg_all_split"]),
        map(ast.literal_eval, df_gendered_ub_GB["Pl_all_split"]),
        df_gendered_ub_GB["Primary_subcategory"],
    )
)

##sentences
# df inclusive sentences
df_inclusive_sentences_US = rules["en-US"]["df_inclusive_sentence"]
df_inclusive_sentences_GB = rules["en-GB"]["df_inclusive_sentence"]
# inclusive sentences: lemma + subcategory
inclusive_sentences_alternatives_US = list(
    zip(
        df_inclusive_sentences_US["Lemma"],
        df_inclusive_sentences_US["Primary_subcategory"],
    )
)
inclusive_sentences_alternatives_GB = list(
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
# gendered sentences: lemma + alternatives split + subcategory
gender_sentences_alternatives_US = list(
    zip(
        df_gendered_sentences_US["Lemma"],
        map(ast.literal_eval, df_gendered_sentences_US["Alt_split"]),
        df_gendered_sentences_US["Primary_subcategory"],
    )
)
gender_sentences_alternatives_GB = list(
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
style_sentences_alternatives_US = list(
    zip(
        df_style_sentences_US["Lemma"],
        map(ast.literal_eval, df_style_sentences_US["Alt_split"]),
        df_style_sentences_US["Primary_subcategory"],
    )
)
style_sentences_alternatives_GB = list(
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
bias_sentences_alternatives_US = list(
    zip(
        df_bias_sentences_US["Lemma"],
        map(ast.literal_eval, df_bias_sentences_US["Alt_split"]),
        df_bias_sentences_US["Primary_subcategory"],
    )
)
bias_sentences_alternatives_GB = list(
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
        map(ast.literal_eval, df_bias_singular_they_US["Alt_split"]),
        df_bias_singular_they_US["Primary_subcategory"],
    )
)
bias_singular_they_alternatives_GB = list(
    zip(
        df_bias_singular_they_GB["Lemma"],
        map(ast.literal_eval, df_bias_singular_they_GB["Alt_split"]),
        df_bias_singular_they_GB["Primary_subcategory"],
    )
)

FalsePositive = namedtuple("FalsePositive", "gender agentic")


def get_false_positive(gender_false_positive, false_positive_agentic_const):
    fp = FalsePositive(
        gender_false_positive,
        false_positive_agentic_const,
    )
    return fp


false_positive = get_false_positive(
    rules["de-DE"]["gender_false_positive"],
    rules["de-DE"]["false_positive_agentic_const"],
)
