import csv
import json
from collections import defaultdict
import string
import requests

test_text = "Liebe "
url_test = "https://lt.default.api.witty.works/v2/check"
columns = defaultdict(list)
all_words = []

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
        all_words += json.loads(value_sg)
        all_words += json.loads(value_pl)

clean_words = []
endings = ["\/in", "\/-in", "\_in", "*in", ":in", "In"]
forbidden_words = endings + ["innenschaft"]
for word in all_words:
    if "~" in word:
        variants = word.split("~")
        for german_gender_ending in endings:
            if str(variants[1]) == "e":
                new_word = str(variants[0]) + "e" + german_gender_ending[0:-2] + "r"
                clean_words.append(new_word)
            else:
                new_word = (
                    str(variants[0]) + german_gender_ending[0:-2] + str(variants[1])
                )
                clean_words.append(new_word)
        if variants[-1] not in forbidden_words:
            clean_words.append(variants[-1])
    else:
        clean_words.append(word)

ignored = [
    "(auf ...)",
    "(...)",
    "...)",
    "(...",
    "...",
    "die",
    "für",
    "sich",
    "von",
    "im",
    "o.",
    "Ä.",
    "oder",
    "und",
    "hat",
    "AG",
]
encapsulated_words = []
for word in clean_words:
    if "|" in word:
        word = word.replace("| ", "")
    if "ß" in word:
        word = word.replace("ß", "ss")
    if " " in word:
        word.replace(",", "")
        for i in ignored:
            if i in word:
                word = word.replace(i, "")
        word = word.replace(",", "")
        word = word.replace("(", "")
        word = word.replace(")", "")
        word_list = word.split()
        encapsulated_words.extend(word.split())
    else:
        encapsulated_words.append(word)

words_post = []
for w in encapsulated_words:
    if "/" in w and "\/" not in w:
        words_post.extend(w.split("/"))
    else:
        words_post.append(w)

current_words = []
with open(
    "languagetool/LanguageTool-5.5/org/languagetool/resource/de/hunspell/ignore.txt",
    "r",
) as f:
    lines = f.readlines()
    for line in lines:
        li = line.strip()
        if not li.startswith("#"):
            current_words.append(li)

words_post = sorted(set(words_post))

used_words = []
with open("languagetool/ignore.txt", "r") as readfile:
    used_words = [line.strip() for line in readfile]

with open("languagetool/ignore.txt", "w") as myfile:
    for word in words_post:
        if word not in used_words:
            response = requests.post(
                url_test,
                data={"text": (test_text + word), "language": "auto"},
            )
            if response.status_code == 503:
                continue

            if response.json()["matches"]:
                myfile.write(word)
                myfile.write("\n")

        else:
            myfile.write(word)
            myfile.write("\n")

with open("languagetool/ignore.txt", "a") as myfile:
    myfile.write("# Old words (added by LT): \n")
    for word in current_words:
        myfile.write(word)
        myfile.write("\n")
