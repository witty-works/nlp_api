import os
from datetime import datetime
import click
import csv
import polib
from app.categories import categories
from app.models import Language


def read_csv(in_file, categories):
    po_files = {"pot": polib.POFile(), "en_US": polib.POFile(), "de_DE": polib.POFile()}
    locales = po_files.keys()

    for locale in locales:
        current_date = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

        po_files[locale].metadata = {
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

        if locale == "pot":
            continue

        lang = Language(locale)
        for subcategory in categories.keys():
            if "explanation" not in categories[subcategory]:
                categories[subcategory]["explanation"] = {}

            key = "rules." + subcategory + "_explanation"
            categories[subcategory]["explanation"][lang.lang] = lang._(key)
            if categories[subcategory]["explanation"][lang.lang] == key:
                categories[subcategory]["explanation"][lang.lang] = ""

    with open(in_file, newline="") as csvfile:
        columns = {
            "subcategory_name": None,
            "category_name": None,
            "hs_path": None,
            "hs_name": None,
            "language": None,
            "emoji": None,
            "short_explanation": None,
            "lead_video": None,
            "sub_head": None,
            "gravity": None,
            "is_active": None,
        }

        base_url = {
            "en": "https://www.witty.works/en/subcategories/",
            "de": "https://www.witty.works/de/subkategorien/",
        }

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
                if row[columns["is_active"]] == 0:
                    continue

                subcategory = row[columns["subcategory_name"]].strip()
                language = row[columns["language"]]

                categories[subcategory]["inclusive"] = (
                    row[columns["category_name"]] == "inclusive"
                )

                categories[subcategory]["category"] = row[
                    columns["category_name"]
                ].strip()

                if "name" not in categories[subcategory]:
                    categories[subcategory]["name"] = {}

                if categories[subcategory]["inclusive"]:
                    categories[subcategory]["gravity"] = None
                    categories[subcategory]["importance"] = 3
                else:
                    categories[subcategory]["gravity"] = float(row[columns["gravity"]])
                    categories[subcategory]["importance"] = int(row[columns["gravity"]])

                if "content" not in categories[subcategory]:
                    categories[subcategory]["content"] = {}

                if "url" not in categories[subcategory]:
                    categories[subcategory]["url"] = {}

                categories[subcategory]["emoji"] = row[columns["emoji"]]

                if "explanation" not in categories[subcategory]:
                    categories[subcategory]["explanation"] = {}

                categories[subcategory]["name"][language] = row[columns["hs_name"]]
                if row[columns["short_explanation"]] != "":
                    categories[subcategory]["explanation"][language] = row[
                        columns["short_explanation"]
                    ]
                if row[columns["lead_video"]]:
                    categories[subcategory]["content"][language] = "video"
                elif row[columns["sub_head"]]:
                    categories[subcategory]["content"][language] = "advanced"

                if row[columns["is_active"]] == "1":
                    categories[subcategory]["url"][language] = (
                        base_url[language] + row[columns["hs_path"]]
                    )

    translated = ["name", "explanation"]
    sorted_categories = {}
    for subcategory in sorted(categories.keys()):
        data = categories[subcategory]

        for locale in locales:
            lang = locale[0:2]
            for key in translated:
                msgid = "rules." + subcategory + "_" + key
                msgstr = ""
                if locale != "pot" and lang in data[key]:
                    msgstr = data[key][lang]

                entry = polib.POEntry(msgid=msgid, msgstr=msgstr)
                po_files[locale].append(entry)

        del data["explanation"]

        if "content" in data and data["content"] == {}:
            del data["content"]

        sorted_categories[subcategory] = data

    locales_path = os.path.dirname(__file__) + "/../locales"

    for locale in locales:
        if locale == "pot":
            po_files[locale].save(locales_path + "/messages.pot")
        else:
            locale_path = locales_path + "/" + locale + "/LC_MESSAGES"
            os.makedirs(locale_path, exist_ok=True)

            po_files[locale].save(locale_path + "/messages.po")
            po_files[locale].to_binary()
            po_files[locale].save_as_mofile(locale_path + "/messages.mo")

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
    read_csv(in_file, categories)
    print(in_file)


if __name__ == "__main__":
    process()
