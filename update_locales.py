import os
from datetime import datetime
import click
import csv
import polib

def add_entry(poFiles, category, columns, label, column, row):
    colors = {
        "Gendered": "yellow",
        "Non-Inclusive": "brown",
        "Inclusive": "green",
        "Discriminating": "orange",
        "Style": "blue",
    }

    msgid = u"rules." + category + "_" + label
    for locale in poFiles:
        if locale == "pot":
            msgstr = u""
        elif label == "color":
            msgstr = colors[row[columns[column]]]
        else:
            msgstr = row[columns[column + " " + locale[0:2].upper()]]

        entry = polib.POEntry(msgid=msgid,msgstr=msgstr)
        poFiles[locale].append(entry)

def read_csv(in_file):
    poFiles = { "pot": polib.POFile(), "en_GB": polib.POFile(), "de_DE": polib.POFile() }
    for locale in poFiles:
        current_date = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

        poFiles[locale].metadata = {
            'Project-Id-Version': '1.0',
            'Report-Msgid-Bugs-To': 'engineering@witty.works',
            'POT-Creation-Date': current_date,
            'PO-Revision-Date': current_date,
            'Last-Translator': 'engineering@witty.works',
            'Language-Team': 'engineering@witty.works',
            'MIME-Version': '1.0',
            'Content-Type': 'text/plain; charset=utf-8',
            'Content-Transfer-Encoding': '8bit',
        }

    with open(in_file, newline='') as csvfile:
        columns = {
            "Category": 0,
            "Category Label EN": None,
            "Category Label DE": None,
            "Reason EN": None,
            "Reason DE": None,
            "Solution EN": None,
            "Solution DE": None,
            "Color Scheme": None,
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
                category = row[columns["Category"]]
                if category == "New Category":
                    continue

                if row[columns["Category Label EN"]] != "-" or row[columns["Category Label DE"]] != "-":
                    add_entry(poFiles, category, columns, "label", "Category Label", row)

                add_entry(poFiles, category, columns, "reason", "Reason", row)
                add_entry(poFiles, category, columns, "solution", "Solution", row)
                add_entry(poFiles, category, columns, "color", "Color Scheme", row)

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

@click.command()
@click.option("--in", "-i", "in_file", required=True,
    help="Path to csv fle to be processed",
    type=click.Path(exists=True, dir_okay=False, readable=True))
def process(in_file):
    """ Processes the input file to generate new .pot and .po files """
    input = read_csv(in_file)
    print(in_file)

if __name__ == "__main__":
    process()