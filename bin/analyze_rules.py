import argparse
import re
import csv
import json
import os
import requests
import logging

from app.models import (
    ResultOut,
    Config,
    GenderedRolesFormatType,
)
from app.main import parse_word_types
from app.model import fetch_nlp_model
from app.settings import get_settings
from app.categories import categories
from app.rules import fetch_rules
from german_nouns.lookup import Nouns

log = logging.getLogger("urllib3")
log.setLevel(logging.ERROR)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-u",
        "--URL",
        help="Api url which should call check on training data, e.g. http://localhost:8081/v2/check",
        default="http://localhost:8081/v2/check",
    )
    parser.add_argument(
        "-l",
        "--Language",
        help="Language for which ignore file should be generated, currently: de or en",
        default="de",
    )
    parser.add_argument(
        "-p", "--Path", help="Path to languagetool ignore.txt file ", default=False
    )
    parser.add_argument(
        "-o",
        "--Original",
        help="Path to original languagetool ignore.txt file, like LanguageTool-5.5/org/languagetool/resource/de/hunspell/ignore.txt. Use only when running script for the first time.",
        default="",
    )
    return parser.parse_args()


def get_current_words(original_languagetool_path, ignore_languagetool_path):
    current_words = []
    if original_languagetool_path:
        with open(
            original_languagetool_path,
            "r",
        ) as f:
            lines = f.readlines()
            for line in lines:
                li = line.strip()
                if not li.startswith("#"):
                    current_words.append(li)
    else:
        start = False
        with open(
            ignore_languagetool_path,
            "r",
        ) as f:
            lines = f.readlines()
            for line in lines:
                if start == True:
                    li = line.strip()
                    current_words.append(li)
                if line == "# Old words (added by LT): \n":
                    start = True
    return current_words


def get_data_from_files(locale):
    if locale[0:2] == "de":
        locale = "de"
        rules = fetch_rules(["de"])
        nouns = Nouns()

    base_directory = "training_data/" + locale + "/"
    training_data_paths = []
    for file in os.listdir(base_directory):
        if not file.startswith("."):
            training_data_paths.append(base_directory + file)
    all_alternative_groups = []
    all_alternatives = []
    all_triggers = []
    all_lemma = []
    all_categories = []
    all_secondary_subcategories = []
    # https://www.notion.so/witty-works/Rule-Guidelines-432792da944141b1b4d0a01de290aa43#aac0d966bfeb4e33a5a346bba45d5ea8
    supported_word_types = {"s", "a", "adv", "v", "acr", "abbr", "i", "conj"}

    for training_data_path in training_data_paths:
        with open(training_data_path) as f:
            if not f.name.endswith(".csv"):
                continue

            reader = csv.DictReader(f)
            column_names = reader.fieldnames
            if "Lemma" in column_names:
                for row in reader:
                    category = None
                    if "Category" in row:
                        category = row["Category"]
                        all_categories.append(category)

                    subcategory = None
                    if "Primary_subcategory" in row:
                        subcategory = row["Primary_subcategory"]
                        all_categories.append(subcategory)

                    lemma = row["Lemma"].replace("'", '"')
                    if "Word_Type" in row:
                        word_type = row["Word_Type"]
                        if word_type is None:
                            print("Lemma '%s' is missing a word type." % (lemma))
                        else:
                            word_type = word_type.replace("'", '"')
                            word_types, lower_case, lemmatize = parse_word_types(
                                word_type
                            )

                            if not set(word_types).issubset(supported_word_types):
                                print(
                                    "Lemma '%s' contains an incorrect word type '%s'."
                                    % (lemma, word_type)
                                )
                                print(word_types)

                            if (
                                lemmatize
                                and "words" in f.name
                                and category
                                not in ["inclusive", "openly_discriminating"]
                            ):
                                all_lemma.append(lemma)

                            if " " not in lemma:
                                if (
                                    locale == "de"
                                    and "v" in word_types
                                    and lemma not in rules["de"]["verbs"]
                                ):
                                    print(
                                        "Verb lemma '"
                                        + lemma
                                        + "' missing from /de/verbs.csv"
                                    )

                                if (
                                    locale == "de"
                                    and "s" in word_types
                                    and len(nouns[lemma]) == 0
                                    and category != "openly_discriminating"
                                ):
                                    print(
                                        "Noun lemma '"
                                        + lemma
                                        + "' missing from german_nouns"
                                    )

                    if "Alt_split" in row:
                        value = row["Alt_split"]
                        value = value.replace("'", '"')
                        try:
                            alternatives = json.loads(value)
                            if (
                                locale == "de"
                                and str(f).find("abbreviations.csv") != -1
                            ):
                                alternatives.pop(0)

                            all_alternative_groups += alternatives
                        except ValueError:
                            continue

                    if subcategory not in [
                        "function",
                        "titles",
                    ] and category not in ["inclusive", "openly_discriminating"]:
                        all_triggers.append(lemma)

                    if "Secondary_subcategory" in row and row["Secondary_subcategory"]:
                        all_secondary_subcategories.append(row["Secondary_subcategory"])

    print(
        "All alternative groups for directory %s: %s"
        % (base_directory, str(len(all_alternative_groups)))
    )

    for all_alternative_group in all_alternative_groups:
        all_alternatives.extend(all_alternative_group.split("|"))
    print(
        "Alternatives for directory %s: %s "
        % (base_directory, str(len(all_alternatives)))
    )

    print("Trigger for directory %s: %s " % (base_directory, str(len(all_triggers))))

    for alternative in all_alternatives:
        if "\n" in alternative:
            print("Misplaced \\n in alternative: " + alternative)

        if "\t" in alternative:
            print("Misplaced \\t in alternative: " + alternative)

        if "|" in alternative:
            print("Misplaced | in alternative: " + alternative)

        if alternative != alternative.strip():
            print("Additional whitespace in alternative: " + alternative)

        if re.search("^[^-]*--[^-]*$", alternative):
            print("Potential missing - in ' --- ': " + alternative)

    return (
        set(all_lemma),
        set(all_triggers),
        set(all_alternatives),
        set(all_categories),
        set(all_secondary_subcategories),
    )


def generate_alternatives_english(all_alternatives):
    all_words = []
    clean_words = []

    for word in all_alternatives:
        word = word.replace("...", " ")
        all_words.extend(word.split())

    for word in all_words:
        for ch in ["(", ")", "^", ",", "?", "!", ":", ";"]:
            if ch in word:
                word = word.replace(ch, "")
        if "." in word:
            # special handling for "Express.js" etc.
            word = word.replace(".js", "-~-js")
            word = word.replace(".", "")
            word = word.replace("-~-js", ".js")
        if "/" in word:
            clean_words.extend(word.split("/"))
        elif len(word) >= 1:
            clean_words.append(word)

    return set(clean_words)


def analyze_correct_endings_german(word):
    if re.search("^.*  *$", word):
        print("Potential multiple spaces in a row in: " + word)
        issue_detected = True

    if re.search("^.*~~*$", word):
        print("Potential multiple '~' in a row in: " + word)
        issue_detected = True

    word = word.replace("~ und ~", "-~-und-~-")

    words = word.split()
    word = word.replace("-~-und-~-", "~ und ~")
    for sub_word in words:
        sub_word = sub_word.replace("-~-und-~-", "~ und ~")
        issue_detected = False

        if re.search("^.*innen~/~.*$", sub_word):
            print("Potential replace '/' with ' und ' in: " + word)
            issue_detected = True

        if (
            re.search("^.*[a-z]{3}in(nen)?[~ ].*$", sub_word)
            or re.search("^.*[a-z]{3}in~[^ ].*$", sub_word)
            or re.search("^.*[a-z]{3}innen~[^ ].*$", sub_word)
            or re.search("^.*[a-z]e~.*/.*$", sub_word)
            or re.search("^.+e~r.+$", sub_word)
            or re.search("^.+[^~]/[^~].+$", sub_word)
            or re.search("^.+[^~] und [^~].+$", sub_word)
            or re.search("~en", sub_word)
        ):
            print("Potential misplaced ~ in: " + word)
            issue_detected = True

        if sub_word.count("~") == 3:
            elements = sub_word.split("~")
            if not elements[3].startswith(elements[0]):
                if words[0] == elements[3]:
                    print(
                        "Potential case to word to the front '"
                        + elements[3]
                        + " "
                        + elements[0]
                        + "~"
                        + elements[1]
                        + "~"
                        + elements[2]
                        + "~"
                        + words[-1]
                        + "': "
                        + word
                    )
                    issue_detected = True
                else:
                    print(
                        "Potential case to change to '"
                        + elements[0]
                        + elements[1]
                        + "~"
                        + elements[3]
                        + "' form: "
                        + word
                    )
                    issue_detected = True

        if issue_detected:
            alternative_variations = set()
            for german_gender_ending in Config._gendereddenom_ending.keys():
                alternative_variations.update(
                    ResultOut.getAlternativeVariations(
                        GenderedRolesFormatType.BOTH, german_gender_ending, sub_word
                    )
                )

            for alternative_variation in sorted(alternative_variations):
                print(alternative_variation)


def generate_correct_endings_german(all_alternatives):
    endings = Config._gendereddenom_ending.keys()

    clean_words = []
    for word in sorted(all_alternatives):
        if "~" in word:
            analyze_correct_endings_german(word)

            for german_gender_ending in endings:
                alternative = ResultOut.getGenderedRolesFormatInclusive(
                    german_gender_ending, word
                )

                clean_words.append(alternative)

            word = ResultOut.getGenderedRolesFormatBinary(word)
        elif re.search("rau/", word):
            print("Potential missing ~ in a Frau~Mann case: " + word)

        clean_words.extend(word.split("/"))

    words_post = []
    for word in sorted(clean_words):
        word = word.replace(".", " ")
        word = word.replace("?", " ")
        word = word.replace("!", " ")
        word = word.replace(",", " ")
        word = word.replace("(", " ")
        word = word.replace(")", " ")

        words_post.extend(word.split(" "))

    words = {"de-DE": sorted(set(words_post)), "de-CH": []}

    for word in words["de-DE"]:
        if "ß" in word:
            words["de-CH"].append(word.replace("ß", "ss"))
    return words


def generate_used_words_list(path_to_ignore_file):
    used_words = []

    with open(path_to_ignore_file, "r") as readfile:
        used_words = [
            line.strip().replace("\/", "/").replace("\_", "_") for line in readfile
        ]

    print("Previously used words: " + str(len(used_words)))
    return used_words


def check_word(word, locale):
    response = requests.post(
        api_url,
        data={
            "text": word,
            "language": locale,
            "motherTongue": locale,
        },
    )

    if response.status_code != 200:
        print("Got error on: " + word)

    if not response.json()["matches"]:
        return False

    return True


def check_words_spelling(words, current_words=[], used_words=[]):
    words_to_write = []

    for locale in words:
        for word in sorted(words[locale]):
            if len(word) < 3 or word in current_words:
                continue

            add_word = True
            if api_url and word not in used_words:
                add_word = check_word(word, locale)

            if add_word:
                words_to_write.append(word)

    return set(words_to_write)


def add_words_to_ignore(path_to_ignore_file, words_to_write):
    words_to_write = sorted(words_to_write)
    with open(path_to_ignore_file, "w") as myfile:
        for word in words_to_write:
            word = word.replace("/", "\/")
            word = word.replace("_", "\_")
            myfile.write(word)
            myfile.write("\n")


def generate_german_articles():
    endings = Config._gendereddenom_ending.keys()
    all_alternatives = []
    articles = []

    with open("training_data/de/articles.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            all_alternatives.append(row["Alternative"])
    all_alternatives = sorted(set(all_alternatives))
    for alternative in all_alternatives:
        for german_gender_ending in endings:
            word = ResultOut.getGenderedRolesFormatInclusive(
                german_gender_ending, alternative
            )

            articles.append(word)

    return articles


def append_original_ignored_words(path_to_ignore_file, current_words):
    with open(path_to_ignore_file, "a") as myfile:
        myfile.write("# Old words (added by LT): \n")
        for word in current_words:
            myfile.write(word)
            myfile.write("\n")


def intersection(lst1, lst2):
    return list(set(lst1) & set(lst2))


def is_file(path_to_file):
    if os.path.isfile(path_to_file):
        return True
    return False


def update_ignore_file(words, original_languagetool_path, path_to_ignore_file):
    current_words = get_current_words(original_languagetool_path, path_to_ignore_file)
    used_words = generate_used_words_list(path_to_ignore_file)
    words_to_write = check_words_spelling(words, current_words, used_words)

    newly_added_words = intersection(words_to_write, used_words)
    print("Newly added words: " + str(len(newly_added_words)))
    if newly_added_words and len(newly_added_words) < 20:
        print("\n".join(sorted(newly_added_words)))

    add_words_to_ignore(path_to_ignore_file, words_to_write)
    append_original_ignored_words(path_to_ignore_file, current_words)


def print_trigger_alternative_overlap(locale, all_triggers, words):
    print("Trigger words, overlapping with alternatives for locale: " + locale)
    print("\n".join(sorted(intersection(all_triggers, words))))


args = parse_args()
lang = args.Language.lower()
if lang == "de":
    locales = [
        "de-DE",
    ]

elif lang == "en":
    locales = [
        "en-US",
    ]

else:
    raise ValueError(
        "Please specify correct language argument. Valid values are 'de' or 'en' (not case-sensitive)."
    )

settings = get_settings()
for spacy_model in settings.models:
    if spacy_model[0:2] == lang:
        model = fetch_nlp_model(lang, spacy_model)
        break

words = {}
lemmas = {}
for locale in locales:
    (
        all_lemma,
        all_triggers,
        all_alternatives,
        all_categories,
        all_secondary_subcategories,
    ) = get_data_from_files(locale)

    if locale == "de-DE":
        words = generate_correct_endings_german(all_alternatives)
        words[locale] += generate_german_articles()
    else:
        words[locale] = generate_alternatives_english(all_alternatives)

    words[locale] = [
        word
        for word in words[locale]
        if sum(1 for c in word if c.isupper() or c.isnumeric())
        < (2 if len(word) <= 4 else 3)
    ]
    print_trigger_alternative_overlap(locale, all_triggers, words[locale])

    all_lemma = sorted(all_lemma)
    for lemma in all_lemma:
        tokens = model(lemma)
        if lemma.lower() != tokens[0].lemma_.lower():
            print('"' + lemma + '": "' + lemma + '", # ' + tokens[0].lemma_)

    lemmas[locale] = list(all_lemma)

    print("Missing (sub-)categories")
    print(sorted(all_categories - set(categories.keys())))
    print("Missing secondary sub-categories")
    print(sorted(all_secondary_subcategories - set(categories.keys())))


original_languagetool_path = args.Original
api_url = args.URL

try:
    response = requests.get(api_url.rstrip("/check") + "/languages")
    assert response.status_code == 200
    languagetool_running = True

    print("Checking lemma for spelling mistakes ..")
    lemma_spelling_mistakes = check_words_spelling(lemmas)
    print("Following lemma may be spelling mistakes:")
    print("\n".join(sorted(lemma_spelling_mistakes)))
except requests.ConnectionError:
    languagetool_running = False

if args.Path:
    if not languagetool_running:
        print("Please first run the local server %s" % api_url)
        exit(1)

    path_to_ignore_file = args.Path
    if not is_file(path_to_ignore_file):
        raise FileNotFoundError("File %s cannot be found." % path_to_ignore_file)
    if args.Original and not is_file(original_languagetool_path):
        raise FileNotFoundError("File %s cannot be found." % original_languagetool_path)

    print("Checking alternatives for spelling mistakes ..")
    update_ignore_file(words, original_languagetool_path, path_to_ignore_file)
