import os
from datetime import datetime
import click
import csv
import polib
import re


def parse_explanation(explanation):
    icon = None
    explanation = explanation.strip()
    pipe_sign_position = explanation.find("|")
    if pipe_sign_position != -1:
        icon = explanation[0:pipe_sign_position]
        explanation = explanation[pipe_sign_position + 1 :]

    return icon, explanation


def parse_row_column(locales, category, sub_category, columns, label, column, row):
    msgid = "rules." + sub_category + "_" + label

    result = {}
    for locale in locales:
        result[locale] = {}

        if locale == "pot" or (category == "orthography" and label == "anchor"):
            msgstr = ""
        else:
            msgstr = row[columns[column + " " + locale[0:2].upper()]].strip()

            if msgstr == "n/a" or msgstr == "-":
                msgstr = ""
            elif msgstr == "" or msgstr == "Missing":
                msgstr = ""
                print(
                    "Empty text given for '"
                    + sub_category
                    + "' key '"
                    + label
                    + "' ("
                    + locale
                    + ")"
                )
            elif label == "explanation":
                if msgstr.find("|") == -1:
                    print(
                        "Pipesign missing for '"
                        + sub_category
                        + "' key '"
                        + label
                        + "' ("
                        + locale
                        + ")"
                    )
                else:
                    result["emoji"], msgstr = parse_explanation(msgstr)

        result[locale] = {
            "msgid": msgid,
            "msgstr": msgstr,
        }

    return result


def read_csv(in_file):
    poFiles = {"pot": polib.POFile(), "en_US": polib.POFile(), "de_DE": polib.POFile()}
    locales = poFiles.keys()

    for locale in locales:
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
            "Anchor EN": None,
            "Anchor DE": None,
            "Short explanation EN": None,
            "Short explanation DE": None,
            "Inclusive?": None,
            "Gravity": None,
            "Importance": None,
            "Status API": None,
        }

        columnMap = {
            "anchor": "Anchor",
            "explanation": "Short explanation",
        }

        gravities = {"red": 1.0, "orange": 2.0, "yellow": 3.0, "": 3.0, "none": None}

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
                if row[columns["Status API"]] == "Idea":
                    continue

                sub_category = row[columns["Subcategory"]].strip()
                if sub_category == "New Category":
                    continue

                categories[sub_category] = {}

                categories[sub_category]["inclusive"] = (
                    row[columns["Inclusive?"]] == "👍"
                )
                categories[sub_category]["category"] = re.sub(
                    "https://www\.notion\.so\/([_a-z]+)-[a-z0-9]+",
                    "\\1",
                    row[columns["Category"]],
                )

                for key in columnMap:
                    category = categories[sub_category]["category"]
                    categories[sub_category][key] = parse_row_column(
                        locales,
                        category,
                        sub_category,
                        columns,
                        key,
                        columnMap[key],
                        row,
                    )

                if sub_category == "corporate_rules":
                    gravity = 0.9
                else:
                    try:
                        gravity = str(row[columns["Gravity"]])
                        gravity = gravities[gravity]
                    except ValueError:
                        gravity = None

                categories[sub_category]["gravity"] = gravity

                try:
                    importance = int(row[columns["Importance"]])
                except ValueError:
                    importance = 3.0
                categories[sub_category]["importance"] = importance

    sorted_categories = {}
    for i in sorted(categories.keys()):
        sorted_categories[i] = categories[i]

    for sub_category in sorted_categories:
        for key in columnMap:
            data = sorted_categories[sub_category][key]

            for locale in locales:
                entry = polib.POEntry(
                    msgid=data[locale]["msgid"], msgstr=data[locale]["msgstr"]
                )
                poFiles[locale].append(entry)

                if "emoji" in data:
                    sorted_categories[sub_category]["emoji"] = data["emoji"]

            del sorted_categories[sub_category][key]

    locales_path = os.path.dirname(__file__) + "/../locales"

    for locale in locales:
        if locale == "pot":
            poFiles[locale].save(locales_path + "/messages.pot")
        else:
            locale_path = locales_path + "/" + locale + "/LC_MESSAGES"
            os.makedirs(locale_path, exist_ok=True)

            poFiles[locale].save(locale_path + "/messages.po")
            poFiles[locale].to_binary()
            poFiles[locale].save_as_mofile(locale_path + "/messages.mo")

    f = open(os.path.dirname(__file__) + "/../app/categories.py", "w")
    f.write("categories = " + repr(sorted_categories) + "\n")
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
