import argparse
import re
import csv
import json
import os
import sys
import requests
from app.models import (
    ResultOut,
    Config,
)


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
    base_directory = "training_data/" + locale + "/"
    training_data_paths = []
    for file in os.listdir(base_directory):
        training_data_paths.append(base_directory + file)
    all_alternative_groups = []
    all_alternatives = []
    all_triggers = []

    for training_data_path in training_data_paths:
        with open(training_data_path) as f:
            reader = csv.DictReader(f)
            column_names = reader.fieldnames
            if "Alt_split" in column_names:
                for row in reader:
                    value = row["Alt_split"]
                    value = value.replace("'", '"')
                    try:
                        all_alternative_groups += json.loads(value)
                    except ValueError:
                        continue

                    if row["Primary_subcategory"] not in ["function", "titles"]:
                        value = row["Lemma"]
                        value = value.replace("'", '"')
                        all_triggers.append(value)

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
        if re.search("^[^-]*--[^-]*$", alternative):
            print("Potential missing - in ' --- ': " + alternative)

    return set(all_triggers), set(all_alternatives)


def generate_alternatives_english(all_alternatives):
    all_words = []
    clean_words = []

    for word in all_alternatives:
        all_words.extend(word.split())

    for word in all_words:
        for ch in ["(", ")", ".", "^", ","]:
            if ch in word:
                word = word.replace(ch, "")
        if "/" in word:
            clean_words.extend(word.split("/"))
        elif len(word) >= 1:
            clean_words.append(word)

    return set(clean_words)


def analyze_correct_endings_german(word):
    if re.search("^.*[a-z]{3}in(nen)?[~ ].*$", word):
        print("Potential missing ~ in (~in): " + word)

    if re.search("^.*[a-z]{3}in~[^ ].*$", word):
        print("Potential missing ~ in (in~): " + word)

    if re.search("^.*[a-z]{3}innen~[^ ].*$", word):
        print("Potential missing ~ in (innen~): " + word)

    if re.search("^.*[a-z]e~.*/.*$", word):
        print("Potential missing ~ in (~e~): " + word)

    if re.search("^.+e~r.+$", word):
        print("Potential extra ~ in (er): " + word)

    if re.search("^.+[^~]/[^~].+$", word):
        print("Potential missing ~ in (/): " + word)

    if re.search("^.+[^~] und [^~].+$", word):
        print("Potential missing ~ in (und): " + word)

    if re.search("~en", word):
        print("Potential misplaced ~ in (~en): " + word)

    occurrence = word.count("~")
    if occurrence != 1 and occurrence != 3:
        print("Potential misplaced ~ in: " + word)


def generate_correct_endings_german(all_alternatives):
    endings = Config._gendereddenom_ending.keys()

    clean_words = []
    for word in all_alternatives:
        if "~" in word:
            analyze_correct_endings_german(word)

            for german_gender_ending in endings:
                alternative = ResultOut.getGenderedRolesFormatInclusive(
                    word, german_gender_ending
                )

                clean_words.append(alternative)

            word = ResultOut.getGenderedRolesFormatBinary(word)
        elif re.search("rau/", word):
            print("Potential missing ~ in a Frau~Mann case: " + word)

        clean_words.extend(word.split("/"))

    words_post = []
    for word in clean_words:
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


def check_words_spelling(words, current_words, used_words):
    words_to_write = []

    for locale in words:
        for word in words[locale]:
            if len(word) < 3 or word in current_words:
                continue

            add_word = True
            if api_url and word not in used_words:
                add_word = check_word(word, locale)

            if add_word:
                words_to_write.append(word)

    return set(words_to_write)


def add_words_to_ignore(path_to_ignore_file, words_to_write):
    words_to_write = sorted(words_to_write, key=str.casefold)
    with open(path_to_ignore_file, "w") as myfile:
        for word in words_to_write:
            word = word.replace("/", "\/")
            word = word.replace("_", "\_")
            myfile.write(word)
            myfile.write("\n")


def generate_german_articles(locale):
    endings = Config._gendereddenom_ending.keys()
    all_alternatives = []
    articles = []

    with open("training_data/" + locale + "/articles.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            all_alternatives.append(row["Alternative"])
    all_alternatives = set(all_alternatives)
    for alternative in all_alternatives:
        for german_gender_ending in endings:
            word = ResultOut.getGenderedRolesFormatInclusive(
                alternative, german_gender_ending
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
        print(newly_added_words)

    add_words_to_ignore(path_to_ignore_file, words_to_write)
    append_original_ignored_words(path_to_ignore_file, current_words)


def print_trigger_alternative_overlap(locale, all_triggers, words):
    print("Trigger words, overlapping with alternatives for locale: " + locale)
    print(intersection(all_triggers, words))


args = parse_args()
if args.Language.lower() == "de":
    locale = "de-DE"

    all_triggers, all_alternatives = get_data_from_files(locale)

    words = generate_correct_endings_german(all_alternatives)
    words[locale] += generate_german_articles(locale)

    print_trigger_alternative_overlap(locale, all_triggers, words[locale])
elif args.Language.lower() == "en":
    locales = [
        "en-US",
        # "en-GB",
    ]

    words = {}
    for locale in locales:
        all_triggers, all_alternatives = get_data_from_files(locale)

        words[locale] = generate_alternatives_english(all_alternatives)

        print_trigger_alternative_overlap(locale, all_triggers, words[locale])
else:
    raise ValueError(
        "Please specify correct language argument. Valid values are 'de' or 'en' (not case-sensitive)."
    )

if args.Path:
    current_words = []
    path_to_ignore_file = args.Path
    original_languagetool_path = args.Original
    api_url = args.URL

    try:
        response = requests.get(api_url.rstrip("/check") + "/languages")
        assert response.status_code == 200
    except requests.ConnectionError:
        print("Please first run the local server %s" % api_url)
        exit(1)

    if not is_file(path_to_ignore_file):
        raise FileNotFoundError("File %s cannot be found." % path_to_ignore_file)
    if args.Original and not is_file(original_languagetool_path):
        raise FileNotFoundError("File %s cannot be found." % original_languagetool_path)

    update_ignore_file(words, original_languagetool_path, path_to_ignore_file)
