import csv
import json
import os
import sys
from collections import defaultdict
from webbrowser import get
import requests
from app.models import (
    ResultOut,
    Config,
)
import argparse


def parse_args(args):
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
        help="Langauge for which ignore file should be generated, currently: German or English",
        default="German",
    )
    return parser.parse_args()


args = parse_args(sys.argv[1:])
language = ""
api_url = args.URL
all_alternative_groups = []
all_alternatives = []
current_words = []


def get_current_words(original_languagetool_path):
    with open(
        original_languagetool_path,
        "r",
    ) as f:
        lines = f.readlines()
        for line in lines:
            li = line.strip()
            if not li.startswith("#"):
                current_words.append(li)
    return current_words


def get_alt_from_files(base_directory):
    training_data_paths = []
    for file in os.listdir(base_directory):
        training_data_paths.append(base_directory + file)
    all_alternative_groups = []
    all_alternatives = []

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
    return set(all_alternatives)


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


def generate_correct_endings_german(all_alternatives, endings):
    clean_words = []
    for word in all_alternatives:
        if "~" in word:
            for german_gender_ending in endings:
                alternative = ResultOut.getGenderedRolesFormatInclusive(
                    word, german_gender_ending
                )

                clean_words.append(alternative)

            clean_words.extend(ResultOut.getGenderedRolesFormatBinary(word).split("/"))
        else:
            clean_words.extend(word.split("/"))

    words_post = []
    for word in clean_words:
        word = word.replace(".", " ")
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


def check_words_spelling(newly_added_words):
    words_to_write = []
    for locale in words:
        for word in words[locale]:
            if len(word) < 3:
                continue
            add_word = True
            if api_url and word not in used_words:
                response = requests.post(
                    api_url,
                    data={
                        "text": word,
                        "language": locale,
                        "motherTongue": locale,
                        "disabledRuleIds": "SEHR_GEEHRTER_NAME,PROFANITY",
                        "disabledCategories": "GENDER_NEUTRALITY",
                    },
                )
                if response.status_code != 200:
                    print("Got error on: " + word)
                if response.json()["matches"]:
                    newly_added_words.append(word)
                else:
                    add_word = False

            if add_word and not (word in current_words):
                words_to_write.append(word)
    return set(words_to_write), newly_added_words


def add_words_to_ignore(path_to_ignore_file, words_to_write):
    words_to_write = sorted(words_to_write, key=str.lower)
    with open(path_to_ignore_file, "w") as myfile:
        for word in words_to_write:
            word = word.replace("/", "\/")
            word = word.replace("_", "\_")
            myfile.write(word)
            myfile.write("\n")


def generate_german_articles():
    all_alternatives = []
    articles = []
    training_data_full_path = base_directory + "/articles.csv"
    with open(training_data_full_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            all_alternatives.append(row["Alternative"])
    all_alternatives = set(all_alternatives)
    for alternative in all_alternatives:
        for german_gender_ending in endings:
            word = ResultOut.getGenderedRolesFormatInclusive(
                alternative, german_gender_ending
            )

            if not (word in used_words):
                newly_added_words.append(word)
            articles.append(word)
    articles = set(articles)
    return articles


def add_articles_german(path_to_ignore_file, articles):
    with open(path_to_ignore_file, "a") as myfile:
        for article in articles:
            article = article.replace("/", "\/")
            article = article.replace("_", "\_")
            myfile.write(article)
            myfile.write("\n")


def append_original_ignored_words(path_to_ignore_file, current_words):
    with open(path_to_ignore_file, "a") as myfile:
        myfile.write("# Old words (added by LT): \n")
        for word in current_words:
            myfile.write(word)
            myfile.write("\n")


if args.Language == "German":
    path_to_ignore_file = "languagetool/German/ignore.txt"
    original_languagetool_path = "languagetool/German/hunspell/ignore.txt"
    base_directory = "training_data/de-DE/"
    current_words = get_current_words(original_languagetool_path)
    all_alternatives = get_alt_from_files(base_directory)
    endings = Config._gendereddenom_ending.keys()
    words = generate_correct_endings_german(all_alternatives, endings)
    used_words = generate_used_words_list(path_to_ignore_file)
    newly_added_words = []
    words_to_write, newly_added_words = check_words_spelling(newly_added_words)
    add_words_to_ignore(path_to_ignore_file, words_to_write)
    articles = generate_german_articles()
    print("Newly added words: " + str(len(newly_added_words)))
    if newly_added_words and len(newly_added_words) < 20:
        print(newly_added_words)
    add_articles_german(path_to_ignore_file, articles)
    append_original_ignored_words(path_to_ignore_file, current_words)
elif args.Language == "English":
    path_to_ignore_file = "languagetool/English/ignore.txt"
    original_languagetool_path = "languagetool/English/hunspell/ignore.txt"
    base_directory_US = "training_data/en-US/"
    current_words = get_current_words(original_languagetool_path)
    # en-US words
    all_alternatives_US = get_alt_from_files(base_directory_US)
    words = {}
    words["en-US"] = generate_alternatives_english(all_alternatives_US)
    # en-GB words
    base_directory_GB = "training_data/en-GB/"
    all_alternatives_GB = get_alt_from_files(base_directory_GB)
    words["en-GB"] = generate_alternatives_english(all_alternatives_GB)
    used_words = generate_used_words_list(path_to_ignore_file)
    newly_added_words = []
    words_to_write, newly_added_words = check_words_spelling(newly_added_words)
    print("Newly added words: " + str(len(newly_added_words)))
    if newly_added_words and len(newly_added_words) < 20:
        print(newly_added_words)
    add_words_to_ignore(path_to_ignore_file, words_to_write)
    append_original_ignored_words(path_to_ignore_file, current_words)
