import pandas as pd
import copy
from collections import defaultdict

rules = {
    "de-DE": {
        # load agentic language
        "df_agentic_ct": "agentic.csv",
        # load Gender denom
        "df_gender_ct": "gendered_noun.csv",
        "df_articles": "articles.csv",
        # load style words
        "df_style_word": "style_words.csv",
        "df_style_sentences": "style_sentences.csv",
        # load openly discriminating words de
        "df_open_dis_word": "open_dis_words.csv",
        "df_open_dis_sentence": "open_dis_sentences.csv",
        # load unconscious_bias word (nouns, not nouns) and sentences de
        "df_ub_noun_word": "ub_noun_words.csv",
        "df_ub_no_noun_word": "ub_no_noun_words.csv",
        "df_ub_sentences": "ub_sentences.csv",
        # load inslusive words
        "df_d_and_i_words": "d_and_i_words.csv",
        # load inslusive sentences
        "df_d_and_i_words_sentences": "d_and_i_sentences.csv",
        # load communal coded terms
        "df_communal_words": "communal.csv",
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
    "flexible",
    "Probleme",
    "unabhängig",
    "Entwickler",
]
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
# df agentic
df_agentic = rules["de-DE"]["df_agentic_ct"]
# agentic: words + alternatives
agentic_words_alternatives = list(zip(df_agentic["Lemma"], df_agentic["Alt_split"]))
# df gender
df_gender = rules["de-DE"]["df_gender_ct"]
# gender: words + singular alternatives + plural alternatives + subcategory
gender_words_alternatives = list(
    zip(
        df_gender["Lemma"],
        df_gender["Sg_all_clean"],
        df_gender["Pl_all_clean"],
        df_gender["Primary_subcategory"],
    )
)
# articles
articles = list(
    zip(
        rules["de-DE"]["df_articles"]["Lemma"],
        rules["de-DE"]["df_articles"]["Alternative"],
    )
)
# df unconscious bias noun
df_bias = rules["de-DE"]["df_ub_noun_word"]
# unconscious bias: words + singular alternatives split + plural alternatives split + subcategory
bias_words_alternatives_noun = list(
    zip(
        df_bias["Lemma"],
        df_bias["Sg_all_split"],
        df_bias["Pl_all_split"],
        df_bias["Primary_subcategory"],
    )
)
# df unconscious bias no noun
df_bias_no_noun = rules["de-DE"]["df_ub_no_noun_word"]
# unconscious bias: words + alternatives split + subcategory
bias_words_alternatives_no_noun = list(
    zip(
        df_bias_no_noun["Lemma"],
        df_bias_no_noun["Alt_split"],
        df_bias_no_noun["Primary_subcategory"],
    )
)
# df style
df_style = rules["de-DE"]["df_style_word"]
# style: words + alternatives + subcategory
style_words_alternatives = list(
    zip(df_style["Lemma"], df_style["Alt_split"], df_style["Primary_subcategory"])
)
# df open discrimination words
df_discrimination_words = rules["de-DE"]["df_open_dis_word"]
# open discrimination: words + alternative_split + subcategory
open_disc_words_alternatives = list(
    zip(
        df_bias_no_noun["Lemma"],
        df_bias_no_noun["Alt_split"],
        df_bias_no_noun["Primary_subcategory"],
    )
)
## sentences:
# df open discrimination sentence
df_discrimination_sentences = rules["de-DE"]["df_open_dis_sentence"]
# open discrimination: sentences +alternatives split + subcategory
open_disc_sentences_alternatives = list(
    zip(
        df_discrimination_sentences["Lemma"],
        df_discrimination_sentences["Alt_split"],
        df_discrimination_sentences["Primary_subcategory"],
    )
)
# df unconscious bias sentences
df_bias_sentences = rules["de-DE"]["df_ub_sentences"]
# unconscious bias: sentences + alternatives split + subcategory
bias_sentences_alternatives = list(
    zip(
        df_bias_sentences["Lemma"],
        df_bias_sentences["Alt_split"],
        df_bias_sentences["Primary_subcategory"],
    )
)
# df style sentences
df_style_sentences = rules["de-DE"]["df_style_sentences"]
# style: sentences + alternatives + subcategory
style_sentences_alternatives = list(
    zip(
        df_style_sentences["Lemma"],
        df_style_sentences["Alt_split"],
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
        df_discrimination_US["Alt_split"],
        df_discrimination_US["Primary_subcategory"],
    )
)
open_disc_words_alternatives_GB = list(
    zip(
        df_discrimination_US["Lemma"],
        df_discrimination_US["Alt_split"],
        df_discrimination_US["Primary_subcategory"],
    )
)
# df open discrimination words gender no noun
df_gender_no_noun_US = rules["en-US"]["df_gendered_no_noun_word"]
df_gender_no_noun_GB = rules["en-GB"]["df_gendered_no_noun_word"]
# gender no noun: lemma + alternatives split + subcategory
gender_words_alternatives_US = list(
    zip(
        df_gender_no_noun_US["Lemma"],
        df_gender_no_noun_US["Alt_split"],
        df_gender_no_noun_US["Primary_subcategory"],
    )
)
gender_words_alternatives_GB = list(
    zip(
        df_gender_no_noun_GB["Lemma"],
        df_gender_no_noun_GB["Alt_split"],
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
        df_style_US["Alt_split"],
        df_style_US["Primary_subcategory"],
    )
)
style_words_alternatives_GB = list(
    zip(
        df_style_GB["Lemma"],
        df_style_GB["Alt_split"],
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
        df_bias_US["Alt_split"],
        df_bias_US["Primary_subcategory"],
    )
)
bias_words_alternatives_GB = list(
    zip(
        df_bias_GB["Lemma"],
        df_bias_GB["Alt_split"],
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
# df gendered noun
df_gender_noun_US = rules["en-US"]["df_gendered_noun_word"]
df_gender_noun_GB = rules["en-GB"]["df_gendered_noun_word"]
# gendered noun: lemma + singular alternatives split + plural alternatives split + subcategory
gender_noun_words_alternatives_US = list(
    zip(
        df_gender_noun_US["Lemma"],
        df_gender_noun_US["Sg_all_split"],
        df_gender_noun_US["Pl_all_split"],
        df_gender_noun_US["Primary_subcategory"],
    )
)
gender_noun_words_alternatives_GB = list(
    zip(
        df_gender_noun_GB["Lemma"],
        df_gender_noun_GB["Sg_all_split"],
        df_gender_noun_GB["Pl_all_split"],
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
        df_gendered_ub_US["Sg_all_split"],
        df_gendered_ub_US["Pl_all_split"],
        df_gendered_ub_US["Primary_subcategory"],
    )
)
gender_bias_words_alternatives_GB = list(
    zip(
        df_gendered_ub_GB["Lemma"],
        df_gendered_ub_GB["Sg_all_split"],
        df_gendered_ub_GB["Pl_all_split"],
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
        df_open_dis_sentences_US["Alt_split"],
        df_open_dis_sentences_US["Primary_subcategory"],
    )
)
open_dis_sentences_GB = list(
    zip(
        df_open_dis_sentences_GB["Lemma"],
        df_open_dis_sentences_GB["Alt_split"],
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
        df_gendered_sentences_US["Alt_split"],
        df_gendered_sentences_US["Primary_subcategory"],
    )
)
gender_sentences_alternatives_GB = list(
    zip(
        df_gendered_sentences_GB["Lemma"],
        df_gendered_sentences_GB["Alt_split"],
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
        df_style_sentences_US["Alt_split"],
        df_style_sentences_US["Primary_subcategory"],
    )
)
style_sentences_alternatives_GB = list(
    zip(
        df_style_sentences_GB["Lemma"],
        df_style_sentences_GB["Alt_split"],
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
        df_bias_sentences_US["Alt_split"],
        df_bias_sentences_US["Primary_subcategory"],
    )
)
bias_sentences_alternatives_GB = list(
    zip(
        df_bias_sentences_GB["Lemma"],
        df_bias_sentences_GB["Alt_split"],
        df_bias_sentences_GB["Primary_subcategory"],
    )
)
