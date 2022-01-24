import csv
import json
from collections import defaultdict
import requests
from app.models import (
    ResultOut,
    Config,
)

test_text = "Hier ist ein Satz. Liebe {0}"
api_url = "https://lt.default.api.witty.works/v2/check"
# api_url = "https://api.languagetoolplus.com/v2/check"
api_url = "http://localhost:8081/v2/check"
# api_url = False
columns = defaultdict(list)
all_alternative_groups = []
all_alternatives = []
current_words = []
clean_words = []

with open(
    "../languagetool/LanguageTool-5.5/org/languagetool/resource/de/hunspell/ignore.txt",
    "r",
) as f:
    lines = f.readlines()
    for line in lines:
        li = line.strip()
        if not li.startswith("#"):
            current_words.append(li)

traning_data_dir = "training_data/de-DE"
training_data_full_path = traning_data_dir + "/gendered_noun.csv"
with open(training_data_full_path) as f:
    reader = csv.DictReader(f)
    for row in reader:
        value_sg = row["Sg_all_clean"]
        value_pl = row["Pl_all_clean"]
        value_sg = value_sg.replace("'", '"')
        value_pl = value_pl.replace("'", '"')
        all_alternative_groups += json.loads(value_sg)
        all_alternative_groups += json.loads(value_pl)

print("All alternative groups: " + str(len(all_alternative_groups)))

for all_alternative_group in all_alternative_groups:
    all_alternatives.extend(all_alternative_group.split("|"))

print("Alternatives: " + str(len(all_alternatives)))

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
with open("languagetool/ignore.txt", "r") as readfile:
    used_words = [line.strip() for line in readfile]

print("Previously used words: " + str(len(used_words)))

newly_added_words = []
with open("languagetool/ignore.txt", "w") as myfile:
    for locale in words:
        for word in words[locale]:
            if len(word) < 3:
                continue

            add_word = True

            if api_url and word not in used_words:
                text = test_text.format(word)

                response = requests.post(
                    api_url,
                    data={
                        "text": text,
                        "language": "auto",
                        "preferredVariants": locale,
                        "motherTongue": locale,
                        "disabledRuleIds": "SEHR_GEEHRTER_NAME,PROFANITY",
                        "disabledCategories": "GENDER_NEUTRALITY",
                    },
                )

                if response.status_code != 200:
                    print("Got error on: " + word)
                    exit

                if response.json()["matches"]:
                    print(word)
                    newly_added_words.append(word)
                else:
                    add_word = False

            if add_word:
                word = word.replace("/", "\/")
                word = word.replace("_", "\_")
                myfile.write(word)
                myfile.write("\n")

    all_alternatives = []
    training_data_full_path = traning_data_dir + "/articles.csv"
    with open(training_data_full_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            all_alternatives.append(row["Alternative"])

    for alternative in all_alternatives:
        for german_gender_ending in endings:
            word = ResultOut.getGenderedRolesFormatInclusive(
                alternative, german_gender_ending
            )

            if word not in used_words:
                # print(word)
                used_words.append(word)
                newly_added_words.append(word)

                word = word.replace("/", "\/")
                word = word.replace("_", "\_")
                myfile.write(word)
                myfile.write("\n")

print("Newly added words: " + str(len(newly_added_words)))
if len(newly_added_words) < 20:
    print(newly_added_words)

with open("languagetool/ignore.txt", "a") as myfile:
    myfile.write("# Old words (added by LT): \n")
    for word in current_words:
        myfile.write(word)
        myfile.write("\n")
