import csv
import json
from collections import defaultdict
import requests

test_text = "Hier ist ein Satz. Liebe "
api_url = "https://lt.default.api.witty.works/v2/check"
# api_url = "https://api.languagetoolplus.com/v2/check"
# api_url = "http://localhost:8081/v2/check"
# api_url = False
columns = defaultdict(list)
all_alternative_groups = []
all_alternatives = []
current_words = []
clean_words = []

with open(
    "languagetool/LanguageTool-5.5/org/languagetool/resource/de/hunspell/ignore.txt",
    "r",
) as f:
    lines = f.readlines()
    for line in lines:
        li = line.strip()
        if not li.startswith("#"):
            current_words.append(li)

traning_data_dir = "training_data"
training_data_file_name = "gendered_noun_DE.csv"
training_data_full_path = traning_data_dir + "/" + training_data_file_name
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

endings = ["\/in", "\/-in", "\_in", "*in", ":in", "In"]
for word in all_alternatives:
    if "~" in word:
        clean_words.extend(word.replace("~", "").split("/"))

        variants = word.split("~")
        for german_gender_ending in endings:
            beginning = str(variants[0])
            if str(variants[1]) == "e":
                beginning += "e"
                ending = "r"
            else:
                ending = str(variants[1])

            if german_gender_ending == "In":
                ending = ending.capitalize()
                separator = ""
            else:
                separator = german_gender_ending[0:-2]

            new_word = beginning + separator + ending

            clean_words.append(new_word)
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
            if word == "":
                continue

            if api_url and word not in used_words:
                text = test_text + word

                response = requests.post(
                    api_url,
                    data={
                        "text": text,
                        "language": "auto",
                        "motherTongue": locale,
                        "preferredVariants": locale,
                    },
                )

                if response.status_code != 200:
                    print("Got error on: " + word)
                    exit

                if (
                    response.json()["matches"]
                    and response.json()["matches"][0]["shortMessage"]
                    == "Rechtschreibfehler"
                ):
                    newly_added_words.append(word)
                    myfile.write(word)
                    myfile.write("\n")

            else:
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
