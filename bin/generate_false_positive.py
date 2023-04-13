import csv
import json
import os
from collections import defaultdict

from app.models import (
    ResultOut,
    Config,
    GenderedRolesFormatType,
)
import re

import logging
import sys

# Logging configuration:
logging.basicConfig(level="ERROR")
logging.getLogger().handlers.clear()
formatter = logging.Formatter("[%(asctime)s] %(name)s %(levelname)s - %(message)s")
sh = logging.StreamHandler(sys.stdout)
sh.setFormatter(formatter)
logging.getLogger().addHandler(sh)

false_positive_path = "training_data/de/gender_false_positive.csv"
if os.path.exists(false_positive_path):
    os.remove(false_positive_path)

with open(false_positive_path, "w") as f:
    f.write("False_positives\n")


base_directory = "training_data/de/"
training_data_paths = []
for file in os.listdir(base_directory):
    training_data_paths.append(base_directory + file)

columns = defaultdict(list)
all_alternative_groups = []
all_alternatives = []
clean_words = []

all_file_allternatives = []
for training_data_path in training_data_paths:
    with open(training_data_path) as f:
        if (
            not f.name.endswith(".csv")
            or f.name.endswith("verbs.csv")
            or f.name.endswith(false_positive_path)
        ):
            continue

        print("Reading" + f.name)

        reader = csv.DictReader(f)
        column_names = reader.fieldnames
        if "Alt_split" in column_names:
            print(column_names)

            for row in reader:
                value = row["Alt_split"]
                value = value.replace("'", '"')
                try:
                    all_alternative_groups += json.loads(value)
                except:
                    continue


all_alternative_groups = set(all_alternative_groups)
print("Alternatives " + str(len(all_alternative_groups)))
for all_alternative_group in all_alternative_groups:
    all_alternatives.extend(all_alternative_group.split("|"))


endings = Config._gendereddenom_ending.keys()
for word in all_alternatives:
    if "~" in word:
        for german_gender_ending in endings:
            clean_words.extend(
                ResultOut.getAlternativeVariations(
                    GenderedRolesFormatType.BOTH, german_gender_ending, word
                )
            )

words = {"de-DE": sorted(set(clean_words)), "de-CH": []}

for word in words["de-DE"]:
    if "ß" in word:
        words["de-CH"].append(word.replace("ß", "ss"))

regexes = [
    # e.g. Kundinnen und Kunden
    r"[A-ZÄÜÖ]\w+ und [A-ZÄÜÖ]\w+",
    # e.g. Industriekauffrau/Industriekaufmann
    r"[A-ZÄÜÖ]\w+\/[A-ZÄÜÖ]\w+",
]

false_positives = []
for locale in words:
    print("Processing " + locale)
    print("Words " + str(len(words[locale])))
    for w in words[locale]:
        for regex in regexes:
            if re.fullmatch(regex, w):
                false_positives.append([w])

                break

print("False positives " + str(len(false_positives)))

header = ["False_positives"]
with open(false_positive_path, "w") as f:
    writer = csv.writer(f)
    # write the header
    writer.writerow(header)
    # write the data
    writer.writerows(false_positives)
