import csv
import json
import os
from collections import defaultdict
import requests
from app.models import (
    ResultOut,
    Config,
)
import argparse

parser = argparse.ArgumentParser()
parser.add_argument(
    "-u",
    "--URL",
    help="Api url which should call check on training data, e.g. http://localhost:8081/v2/check",
    default="http://localhost:8081/v2/check",
)
args = parser.parse_args()

api_url = args.URL
columns = defaultdict(list)
all_alternative_groups = []
all_alternatives = []
current_words = []
clean_words = []
path_to_ignore_file = "languagetool/German/ignore.txt"
original_languagetoool_path = "languagetool/German/hunspell/ignore.txt"
# change to original Languagetool path
with open(
    original_languagetoool_path,
    "r",
) as f:
    lines = f.readlines()
    for line in lines:
        li = line.strip()
        if not li.startswith("#"):
            current_words.append(li)

base_directory = "training_data/de-DE/"
training_data_paths = []
for file in os.listdir(base_directory):
    training_data_paths.append(base_directory + file)

columns = defaultdict(list)
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

print("All alternative groups: " + str(len(all_alternative_groups)))

for all_alternative_group in all_alternative_groups:
    all_alternatives.extend(all_alternative_group.split("|"))

print("Alternatives: " + str(len(all_alternatives)))
clean_words = []
all_alternatives = set(all_alternatives)
print("all_alternatives= ", len(all_alternatives))
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

used_words = []
with open(path_to_ignore_file, "r") as readfile:
    used_words = [
        line.strip().replace("\/", "/").replace("\_", "_") for line in readfile
    ]

print("Previously used words: " + str(len(used_words)))
count = 0
count_r = 0
newly_added_words = []
words_to_write = []
print(words["de-CH"])
print("words len= ", len(words["de-DE"]) + len(words["de-CH"]))
with open(path_to_ignore_file, "w") as myfile:
    for locale in words:
        for word in words[locale]:
            if word == "mitreissen":
                print("SPASS")
                print(locale)
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
                    count_r += 1
                    newly_added_words.append(word)
                else:
                    add_word = False

            if add_word and not (word in current_words):
                words_to_write.append(word)
    words_to_write = set(words_to_write)
    for word in words_to_write:
        word = word.replace("/", "\/")
        word = word.replace("_", "\_")
        count += 1
        myfile.write(word)
        myfile.write("\n")

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
    for article in articles:
        article = article.replace("/", "\/")
        article = article.replace("_", "\_")
        myfile.write(article)
        myfile.write("\n")
print("count_r= ", count_r)
print("count= ", count)
print("Newly added words: " + str(len(newly_added_words)))

if newly_added_words and len(newly_added_words) < 20:
    print(newly_added_words)

with open(path_to_ignore_file, "a") as myfile:
    myfile.write("# Old words (added by LT): \n")
    for word in current_words:
        myfile.write(word)
        myfile.write("\n")
