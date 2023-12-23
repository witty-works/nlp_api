import sqlite3
import argparse
import os
import json

from app.query_definitions import declensions_config


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-l",
        "--Locale",
        help="Locale to compare",
        default="de-DE",
    )
    parser.add_argument("-f", "--File", help="File to compare", default=False)
    return parser.parse_args()


def is_file(path_to_file):
    if os.path.isfile(path_to_file):
        return True
    return False


args = parse_args()
if not is_file(args.File):
    raise FileNotFoundError("File %s cannot be found." % args.File)

os.system(f"cp {args.File} ./database/db.sqlite3")
source = sqlite3.connect("./database/db.sqlite3")

tables_to_keep = [
    "rules_germanverb",
    "rules_germanadjective",
    "rules_germannoun",
    "rules_englishverb",
    "rules_englishadjective",
    "rules_englishnoun",
    "rules_falsepositive",
    "rules_alternative",
    "rules_rule",
    "rules_lemmatization",
]
columns = ["created_at", "updated_at", "comment"]

for table in tables_to_keep:
    for column in columns:
        source.execute(f"ALTER TABLE {table} DROP COLUMN {column}")

query = "SELECT name FROM sqlite_master WHERE type='table' and name NOT LIKE 'sqlite_%'"
for table in source.execute(query).fetchall():
    if table[0] not in tables_to_keep:
        source.execute(f"DROP table IF EXISTS {table[0]}")


lookup = {}
lemma_plural_lookup = {}
langs = ["en", "de"]
for lang in langs:
    query = "SELECT text, lemma, is_plural FROM rules_lemmatization WHERE language = ?"
    parameters = [lang]
    lookup[lang] = {}
    lemma_plural_lookup[lang] = {}
    rows = source.execute(query, parameters).fetchall()
    for row in rows:
        lookup[lang][row[0]] = row[1]
        if row[2]:
            lemma_plural_lookup[lang][row[0]] = row[1]

    if lang == "de":
        columns = declensions_config["de"]["n"]["columns"]
        column_count = len(columns)
        column_filter = ", ".join(columns)
        base_form_i = columns.index("base_form")
        male_form_i = columns.index("male_form")

        query = f"SELECT {column_filter} FROM rules_germannoun"
        rows = source.execute(query).fetchall()
        for row in rows:
            target = row[male_form_i] if row[male_form_i] else row[base_form_i]
            for i in range(column_count):
                if row[i] and row[i] != target and row[i] != row[base_form_i]:
                    lookup[lang][row[i]] = target
                    if columns[i].startswith("pl_"):
                        lemma_plural_lookup[lang][row[i]] = target

with open("./training_data/lookup.json", "w") as fp:
    json.dump(lookup, fp, indent=2)

with open("./training_data/lemma_plural_lookup.json", "w") as fp:
    json.dump(lemma_plural_lookup, fp, indent=2)

source.execute("DROP table IF EXISTS rules_lemmatization")

with open("./database/dump.sql", "w") as f:
    for line in source.iterdump():
        f.write("%s\n" % line)
