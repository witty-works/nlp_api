import pandas as pd
import copy

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
