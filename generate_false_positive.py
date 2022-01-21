import csv
import json
import os
from collections import defaultdict
import requests
from app.models import (
    ResultOut,
    Config,
)
import re
import argparse
import logging
import sys

# Logging configuration:
logging.basicConfig(level="ERROR")
logging.getLogger().handlers.clear()
formatter = logging.Formatter("[%(asctime)s] %(name)s %(levelname)s - %(message)s")
sh = logging.StreamHandler(sys.stdout)
sh.setFormatter(formatter)
logging.getLogger().addHandler(sh)


parser = argparse.ArgumentParser()
parser.add_argument(
    "-u",
    "--URL",
    help="Api url which should call check on training data, e.g. http://localhost:8000/",
    default="http://localhost:8000/",
)
args = parser.parse_args()
false_positive_path = "training_data/de-DE/gender_false_positive.csv"

# Run checks:
def check_if_false_positive_contains_dummy_data(path_to_false_positive):
    with open(path_to_false_positive) as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            dummy = ", ".join(row)
    if dummy == "False_positives":
        return True
    return False


def check_if_server_is_running(api_url):
    try:
        response = requests.get(api_url)
        if response.status_code == 200:
            return True
        else:
            return False
    except requests.ConnectionError as e:
        logging.error("Please first run the local server %s", api_url)
        exit(1)


is_running = check_if_server_is_running(args.URL)
if not is_running:
    logging.error(
        "Cannot connect to server %s. Please check if server is running properly",
        args.URL,
    )
    exit(1)

if not check_if_false_positive_contains_dummy_data(false_positive_path):
    logging.error(
        "Local false positive file %s must be empty. Please remove or clean file before running the script.",
        false_positive_path,
    )
    exit(1)

rules = {}
rules["training_data/de-DE/agentic.csv"] = ["Alt_split"]
rules["training_data/de-DE/gendered_noun.csv"] = ["Sg_all_clean", "Pl_all_clean"]
# following files do not add anything to false_positive list
"""
rules["training_data/de-DE/hollow_sentences.csv"] = [
    "Alternative_Plural_split",
    "Alternative_Singular_split",
]
rules["training_data/de-DE/hollow_words.csv"] = [
    "Alternative_Plural_split",
    "Alternative_Singular_split",
]

rules["training_data/de-DE/open_dis_words.csv"] = ["Alt_split"]
rules["training_data/de-DE/style_sentences.csv"] = ["Alt_split"]

rules["training_data/de-DE/style_words.csv"] = ["Alt_split"]

rules["training_data/de-DE/ub_no_noun_words.csv"] = ["Alt_split"]
"""
rules["training_data/de-DE/ub_noun_words.csv"] = ["Alt_split"]
rules["training_data/de-DE/ub_sentences.csv"] = ["Alt_split"]

columns = defaultdict(list)
all_alternative_groups = []
all_alternatives = []
clean_words = []

all_file_allternatives = []
for r in rules:
    training_data_full_path = r
    with open(training_data_full_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            for column in rules[r]:
                value = row[column]
                value = value.replace("'", '"')
                try:
                    all_alternative_groups += json.loads(value)
                except:
                    continue
    all_file_allternatives += all_alternative_groups

all_alternative_groups = set(all_alternative_groups)

for all_alternative_group in all_alternative_groups:
    all_alternatives.extend(all_alternative_group.split("|"))


endings = Config._gendereddenom_ending.keys()
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

words = {"de-DE": sorted(set(clean_words)), "de-CH": []}

for word in words["de-DE"]:
    if "ß" in word:
        words["de-CH"].append(word.replace("ß", "ss"))

# e.g. Kundinnen und Kunden
regex1 = r"[A-Z]\w+ und [A-Z]\w+"
# e.g. Industriekauffrau/Industriekaufmann
regex2 = r"[A-Z]\w+\/[A-Z]\w+"


potential_false_positive = defaultdict(list)
for locale in words:
    for w in words[locale]:
        if re.fullmatch(regex1, w) or re.fullmatch(regex2, w):
            potential_false_positive[locale].append(w)


def checked_false_positive_list(api_url, potential_false_positive):
    false_positive_checked = []
    for locale in potential_false_positive:
        for word in potential_false_positive[locale]:
            response = requests.post(
                api_url,
                json={
                    "text": word,
                    "lang": locale,
                    "config": {
                        "disabled_categories": ["orthography"],
                    },
                },
            )

            if response.status_code != 200:
                print("Got error on: " + word)
                continue

            info = "trying: " + word + " for locale: " + locale
            if response.json()["results"]:
                false_positive_checked.append([word])
                info += " - added"
            else:
                info += " - skipped"

            print(info)

    return false_positive_checked


check_endpoint_url = args.URL + "check"
false_positive_checked = checked_false_positive_list(
    check_endpoint_url, potential_false_positive
)
header = ["False_positives"]
with open(false_positive_path, "w") as f:
    writer = csv.writer(f)
    # write the header
    writer.writerow(header)
    # write the data
    writer.writerows(false_positive_checked)
