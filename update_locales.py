import os
from datetime import datetime
import click
import csv
import polib
import re
from app.models import ResultOut


def parse_explanation(explanation):
    icon = None
    explanation = explanation.strip()
    pipe_sign_position = explanation.find("|")
    if pipe_sign_position != -1:
        icon = explanation[0:pipe_sign_position]
        explanation = explanation[pipe_sign_position + 1 :]

    return icon, explanation


def add_entry(po_files, category, columns, label, column, row, add_to_po_file=True):
    msgid = "rules." + category + "_" + label

    result = {}
    for locale in po_files:
        if locale == "pot":
            msgstr = ""
        else:
            msgstr = row[columns[column + " " + locale[0:2].upper()]].strip()
            if msgstr == "n/a" or msgstr == "-":
                msgstr = ""
            elif msgstr == "" or msgstr == "Missing":
                msgstr = ""
                if label != "reason" and label != "solution":

                    print(
                        "Empty text given for '"
                        + category
                        + "' key '"
                        + label
                        + "' ("
                        + locale
                        + ")"
                    )
            elif label == "explanation" and msgstr.find("|") == -1:
                print(
                    "Pipesign missing for '"
                    + category
                    + "' key '"
                    + label
                    + "' ("
                    + locale
                    + ")"
                )

            result[locale[0:2]] = msgstr

            if label == "explanation":
                emoji, msgstr = parse_explanation(msgstr)
                result["emoji"] = emoji

        if add_to_po_file:
            entry = polib.POEntry(msgid=msgid, msgstr=msgstr)
            po_files[locale].append(entry)

    return result


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
            "Short explanation EN": None,
            "Short explanation DE": None,
            "Status English": None,
            "Status German": None,
            "Inclusive?": None,
            "Gravity": None,
            "Importance": None,
            "Status EN": None,
            "Status DE": None,
        }

        gravities = {"red": 1, "orange": 2, "yellow": 3, "": 3, "none": None}

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
                categories[sub_category]["name"] = add_entry(
                    poFiles, sub_category, columns, "label", "Category Label", row
                )

                categories[sub_category]["status"] = add_entry(
                    poFiles,
                    sub_category,
                    columns,
                    "status",
                    "Status",
                    row,
                    False,
                )

                add_entry(poFiles, sub_category, columns, "reason", "Reason", row)
                add_entry(poFiles, sub_category, columns, "solution", "Solution", row)

                categories[sub_category]["explanation"] = add_entry(
                    poFiles,
                    sub_category,
                    columns,
                    "explanation",
                    "Short explanation",
                    row,
                )

                categories[sub_category]["inclusive"] = (
                    row[columns["Inclusive?"]] == "👍"
                )
                categories[sub_category]["category"] = re.sub(
                    "https://www\.notion\.so\/([_a-z]+)-[a-z0-9]+",
                    "\\1",
                    row[columns["Category"]],
                )

                try:
                    gravity = gravities[str(row[columns["Gravity"]])]
                except ValueError:
                    gravity = None
                categories[sub_category]["gravity"] = gravity

                try:
                    importance = int(row[columns["Importance"]])
                except ValueError:
                    importance = None
                categories[sub_category]["importance"] = importance

                categories[sub_category]["emoji"] = categories[sub_category][
                    "explanation"
                ]["emoji"]
                del categories[sub_category]["explanation"]["emoji"]

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

    return

    active_categories = [
        "openly_discriminating",
        "unconscious_bias",
        "gendered",
        "orthography",
        "style",
        "inclusive",
    ]

    with open("categories.csv", "w", newline="") as csvfile:
        fieldnames = [
            "hs_path",
            "hs_name",
            "name",
            "language",
            "emoji",
            "introduction",
            "category_name",
            "sort",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for category_name, category in categories.items():
            if category_name == category["category"]:
                if category_name in active_categories:
                    for language in ["en", "de"]:
                        if category["status"][language] != "Deployed":
                            continue

                        if category_name == "inclusive":
                            sort = 4
                        else:
                            sort = category["gravity"]

                        writer.writerow(
                            {
                                "hs_path": ResultOut.transliterate(
                                    category["name"][language]
                                ),
                                "hs_name": category["name"][language],
                                "name": category["name"][language],
                                "language": language,
                                "emoji": category["emoji"],
                                "introduction": category["introduction"][language],
                                "lead_title": category["title"][language],
                                "lead_text": category["text"][language],
                                "category_name": category_name,
                                "sort": sort,
                            }
                        )

                del category["status"]
                del category["name"]
                del category["introduction"]
                del category["title"]
                del category["text"]
                del category["explanation"]

    with open("subcategories.csv", "w", newline="") as csvfile:
        fieldnames = [
            "name",
            "language",
            "emoji",
            "introduction",
            "anchor",
            "subcategory_name",
            "category_name",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for category_name, category in categories.items():
            if category_name != category["category"]:
                if (
                    category["category"] in active_categories
                    and len(category["name"][language]) > 0
                ):
                    for language in ["en", "de"]:
                        if category["status"][language] != "Deployed":
                            continue

                        writer.writerow(
                            {
                                "name": category["name"][language],
                                "language": language,
                                "emoji": category["emoji"],
                                "introduction": category["introduction"][language],
                                "anchor": ResultOut.transliterate(
                                    category["name"][language]
                                ),
                                "subcategory_name": category_name,
                                "category_name": category["category"],
                            }
                        )

                del category["status"]
                del category["name"]
                del category["introduction"]
                del category["explanation"]

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
