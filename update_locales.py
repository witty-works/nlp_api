import os
from datetime import datetime
import click
import csv
import polib
import re


def add_entry(poFiles, category, columns, label, column, row):
    msgid = "rules." + category + "_" + label
    for locale in poFiles:
        if locale == "pot":
            msgstr = ""
        else:
            msgstr = row[columns[column + " " + locale[0:2].upper()]].strip()
            if msgstr == "-":
                msgstr = ""

            if msgstr == "":
                print(
                    "Empty text given for '"
                    + category
                    + "' key '"
                    + label
                    + "' ("
                    + locale
                    + ")"
                )

        entry = polib.POEntry(msgid=msgid, msgstr=msgstr)
        poFiles[locale].append(entry)


def read_csv(in_file):
    poFiles = {"pot": polib.POFile(), "en_US": polib.POFile(), "de_DE": polib.POFile()}
    for locale in poFiles:
        current_date = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

        poFiles[locale].metadata = {
            "Project-Id-Version": "1.0",
            "Report-Msgid-Bugs-To": "engineering@witty.works",
            "POT-Creation-Date": current_date,
            "PO-Revision-Date": current_date,
            "Last-Translator": "engineering@witty.works",
            "Language-Team": "engineering@witty.works",
            "MIME-Version": "1.0",
            "Content-Type": "text/plain; charset=utf-8",
            "Content-Transfer-Encoding": "8bit",
        }

    with open(in_file, newline="") as csvfile:
        columns = {
            "Subcategory": 0,
            "Category": None,
            "Category Label EN": None,
            "Category Label DE": None,
            "Reason EN": None,
            "Reason DE": None,
            "Solution EN": None,
            "Solution DE": None,
            "Super Short EN": None,
            "Super Short DE": None,
            "Status English": None,
            "Status German": None,
            "Inclusive?": None,
            "Gravity": None,
        }

        colors = {
            "unconscious_bias": "orange",
            "openly_discriminating": "brown",
            "gendered": "yellow",
            "style": "blue",
            "orthography": "blue",
            "inclusive": "green",
            "job_requirements": "yellow",
            "abbreviation": "yellow",
            "corporate_rules": "yellow",
            "default": "yellow",
        }

        categories = {}

        line_count = 0
        reader = csv.reader(csvfile, skipinitialspace=True)
        for row in reader:
            if line_count == 0:
                for i, column in enumerate(row):
                    column = column.strip()
                    if column in columns:
                        columns[column] = i
                line_count += 1
            else:
                if (
                    row[columns["Category Label EN"]] == ""
                    and row[columns["Category Label DE"]] == ""
                ):
                    continue

                sub_category = row[columns["Subcategory"]].strip()
                if sub_category == "New Category":
                    continue

                categories[sub_category] = {}
                add_entry(
                    poFiles, sub_category, columns, "label", "Category Label", row
                )
                add_entry(poFiles, sub_category, columns, "reason", "Reason", row)
                add_entry(poFiles, sub_category, columns, "solution", "Solution", row)
                add_entry(
                    poFiles, sub_category, columns, "explanation", "Super Short", row
                )

                try:
                    category = re.search(
                        "https:\/\/www.notion.so\/([_a-z]+)-[a-z0-9]+",
                        row[columns["Category"]],
                    ).group(1)

                    if category not in colors.keys():
                        raise AttributeError
                except AttributeError:
                    print("Color missing for category: " + row[columns["Category"]])
                    category = "default"

                categories[sub_category]["color"] = colors[category]
                categories[sub_category]["inclusive"] = (
                    row[columns["Inclusive?"]] == "👍"
                )
                categories[sub_category]["category"] = re.sub(
                    "https://www\.notion\.so\/([_a-z]+)-[a-z0-9]+",
                    "\\1",
                    row[columns["Category"]],
                )
                try:
                    gravity = int(row[columns["Gravity"]])
                except:
                    gravity = 5
                categories[sub_category]["gravity"] = gravity

    locales_path = os.path.dirname(__file__) + "/locales"

    for locale in poFiles:
        if locale == "pot":
            poFiles[locale].save(locales_path + "/messages.pot")
        else:
            locale_path = locales_path + "/" + locale + "/LC_MESSAGES"
            os.makedirs(locale_path, exist_ok=True)

            poFiles[locale].save(locale_path + "/messages.po")
            poFiles[locale].to_binary()
            poFiles[locale].save_as_mofile(locale_path + "/messages.mo")

    f = open("app/categories.py", "w")
    f.write("categories = " + repr(categories) + "\n")
    f.close()


@click.command()
@click.option(
    "--in",
    "-i",
    "in_file",
    required=True,
    help="Path to csv fle to be processed",
    type=click.Path(exists=True, dir_okay=False, readable=True),
)
def process(in_file):
    """Processes the input file to generate new .pot and .po files"""
    read_csv(in_file)
    print(in_file)


if __name__ == "__main__":
    process()
