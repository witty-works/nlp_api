import sqlite3
import argparse
import os
import json

from app.query_definitions import declensions_config
from app.models import LangType


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-f",
        "--file",
        help="File to compare",
    )
    return parser.parse_args()


def is_file(path_to_file):
    if os.path.isfile(path_to_file):
        return True
    return False


args = parse_args()
if not is_file(args.file):
    raise FileNotFoundError("File %s cannot be found." % args.file)

os.system(f"cp {args.file} ./database/db.sqlite3")
source = sqlite3.connect("./database/db.sqlite3")

tables_to_keep = [
    "rules_germanverb",
    "rules_germanadjective",
    "rules_germannoun",
    "rules_englishverb",
    "rules_englishadjective",
    "rules_englishnoun",
    "rules_frenchnoun",
    "rules_falsepositive",
    "rules_alternative",
    "rules_rule",
    "rules_source",
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

source.execute(
    "DELETE FROM rules_alternative WHERE is_active = 0 OR rule_id IN (SELECT id FROM rules_rule WHERE is_active = 0)"
)
source.execute("DELETE FROM rules_rule WHERE is_active = 0")

lookup = {}
lemma_plural_lookup = {}
langs = [LangType.EN, LangType.DE, LangType.FR]
for lang in langs:
    query = "SELECT text, lemma, is_plural FROM rules_lemmatization WHERE language = ?"

    if lang == LangType.FR:
        query += " UNION SELECT base_form, male_form, 0 FROM rules_frenchnoun WHERE male_form IS NOT NULL"
    parameters = [lang]
    lookup[lang] = {}
    lemma_plural_lookup[lang] = []
    rows = source.execute(query, parameters).fetchall()
    for row in rows:
        lookup[lang][row[0]] = row[1]
        if row[2]:
            lemma_plural_lookup[lang].append(row[0])

    if lang in [LangType.DE, LangType.FR]:
        table_name = declensions_config[lang]["n"]["name"]

        columns = declensions_config[lang]["n"]["columns"]
        columns.remove("gender_1")
        if lang == LangType.FR:
            columns.remove("gender_2")

        column_count = len(columns)
        column_filter = ", ".join(columns)
        base_form_i = columns.index("base_form")
        male_form_i = columns.index("male_form")

        query = f"SELECT {column_filter} FROM {table_name}"
        rows = source.execute(query).fetchall()
        for row in rows:
            target = row[male_form_i] if row[male_form_i] else row[base_form_i]
            for i in range(column_count):
                if columns[i].startswith("collective_noun"):
                    if row[i]:
                        lemma_plural_lookup[lang].append(row[i])
                    continue
                if row[i] and row[i] != target and row[i] != row[base_form_i]:
                    lookup[lang][row[i]] = target
                    if columns[i].startswith("pl_") or columns[i].startswith("plural"):
                        lemma_plural_lookup[lang].append(row[i])

with open("./training_data/lookup.json", "w") as fp:
    json.dump(lookup, fp, indent=2)

with open("./training_data/lemma_plural_lookup.json", "w") as fp:
    json.dump(lemma_plural_lookup, fp, indent=2)

source.execute("DROP table IF EXISTS rules_lemmatization")

with open("./database/dump.sql", "w") as f:
    for line in source.iterdump():
        f.write("%s\n" % line)
