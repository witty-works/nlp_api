import argparse
import os
import requests
import logging
import asyncio

from app.main import (
    gendered_alternatives,
    get_rules_db,
    fetch_rows,
)
from app.models import (
    Config,
)

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
    return parser.parse_args()


def get_current_words(ignore_languagetool_path):
    current_words = []
    start = False
    with open(
        ignore_languagetool_path,
        "r",
    ) as f:
        lines = f.readlines()
        for line in lines:
            if start is True:
                li = line.strip()
                current_words.append(li)
            if line == "# Old words (added by LT): \n":
                start = True

    return current_words


async def generate_alternatives(all_alternatives):
    endings = [
        "_in",
        "*in",
        ":in",
        "In",
    ]

    all_words = []
    clean_words = []

    for row in all_alternatives:
        all_words.extend(row[0].split())

    for word in all_words:
        if word.startswith("~") and word.endswith("~"):
            binary = True
            for ending in endings:
                if ending == "In":
                    separator = "/"
                    noun_separator = ""
                else:
                    separator = noun_separator = ending[0:-2]

                alternatives, _ = await gendered_alternatives(
                    word,
                    "de",
                    True,
                    binary,
                    separator,
                    noun_separator,
                )

                binary = False

                for alternative in alternatives:
                    alternative = alternative.replace("/", " ")
                    clean_words.extend(alternative.split())
        else:
            for ch in ["(", ")", "^", ",", "?", "!", ":", ";", "~"]:
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


def generate_used_words_list(path_to_ignore_file):
    used_words = []

    with open(path_to_ignore_file, "r") as readfile:
        used_words = [
            line.strip().replace(r"\/", r"/").replace(r"\_", r"_") for line in readfile
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
            word = word.replace(r"/", r"\/")
            word = word.replace("_", r"\_")
            myfile.write(word)
            myfile.write("\n")


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


def update_ignore_file(words, lang):
    path_to_ignore_file = f"./languagetool/{lang}_ignore.txt"
    current_words = get_current_words(path_to_ignore_file)
    used_words = generate_used_words_list(path_to_ignore_file)
    words_to_write = check_words_spelling(words, current_words, used_words)

    newly_added_words = intersection(words_to_write, used_words)
    print("\nNewly added words: " + str(len(newly_added_words)))
    if newly_added_words and len(newly_added_words) < 20:
        print("\n".join(sorted(newly_added_words)))

    add_words_to_ignore(path_to_ignore_file, words_to_write)
    append_original_ignored_words(path_to_ignore_file, current_words)
    print("\nDone")


async def get_all_alternatives(language):
    query = f"SELECT lemma FROM rules_alternative WHERE language = ? ORDER BY rule_id"
    return await fetch_rows(query, [language])

async def get_all_rules(language):
    query = f"SELECT lemma FROM rules_rule WHERE language = ?"
    return await fetch_rows(query, [language])


async def generate_ignore_file(lang, api_url):
    # initialize the DB
    await get_rules_db()

    all_lemmas = await get_all_rules(lang)
    all_lemmas.extend(await get_all_alternatives(lang))

    locale = "en-US" if lang == "en" else "de-DE"

    lemmas = {}
    lemmas[locale] = await generate_alternatives(all_lemmas)
    if lang == "de":
        for lemma in lemmas["de-DE"]:
            lemmas["de-CH"] = []
            if "ß" in lemma:
                lemmas["de-CH"].append(lemma.replace("ß", "ss"))

    try:
        print("Checking if LanguageTool is running ..")
        response = requests.get(api_url.rstrip("/check") + "/languages")
        if response.status_code != 200:
            raise Exception("LanguageTool returned status code: " + response.status_code)

        languagetool_running = True

        print("Checking alternatives for spelling mistakes and updating ignore file ..")
        update_ignore_file(lemmas, lang)
    except requests.ConnectionError:
        print("LanguageTool is not running.")
        languagetool_running = False

    if not languagetool_running:
        print("Please first run the local server %s" % api_url)
        exit(1)


args = parse_args()
lang = args.Language.lower()
api_url = args.URL


coroutine = generate_ignore_file(lang, api_url)
asyncio.run(coroutine)
print("Complete")
exit
