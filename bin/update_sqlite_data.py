import sqlite3
import argparse
import os


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
cursor = source.cursor()

cursor.execute(f"DROP table IF EXISTS rules_source")
cursor.execute(f"DROP table IF EXISTS rules_diversitydimension")
cursor.execute(f"DROP table IF EXISTS rules_category")
cursor.execute(f"DROP table IF EXISTS rules_trainingsentence")

query = "SELECT name FROM sqlite_master WHERE type='table' and name NOT LIKE 'sqlite_%' and name NOT LIKE 'rules_%'"
cursor.execute(query)

for table in cursor.fetchall():
    cursor.execute(f"DROP table IF EXISTS {table[0]}")
with open("./database/dump.sql", "w") as f:
    for line in source.iterdump():
        f.write("%s\n" % line)
