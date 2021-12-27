import click
import csv
import re


def intersection(lst1, lst2):
    return list(set(lst1) & set(lst2))


def read_csv(in_file):
    with open(in_file, newline="") as csvfile:
        triggers = []
        alternatives = alternative_words = []
        columns = []

        line_count = 0
        reader = csv.reader(csvfile, skipinitialspace=True)
        for row in reader:
            if line_count == 0:
                columns = row
                line_count += 1
            else:
                for i, column in enumerate(row):
                    if columns[i][0:3] != "Alt":
                        continue

                    if i == 0:
                        triggers.append(column)
                    else:
                        alternatives = alternatives + column.split("|")
                        alternative_words = alternative_words + column.split(" ")

        print(intersection(triggers, alternative_words))

        for alternative in alternatives:
            alternative = alternative.strip()

            if re.search("rau/", alternative):
                print("Potential missing ~ in a Frau~Mann case: " + alternative)

            if re.search("^.*[a-z]{3}in(nen)?(~| ).*$", alternative):
                print("Potential missing ~ in (~in): " + alternative)

            if re.search("^.*[a-z]{3}in~[^ ].*$", alternative):
                print("Potential missing ~ in (in~): " + alternative)

            if re.search("^.*[a-z]{3}innen~[^ ].*$", alternative):
                print("Potential missing ~ in (innen~): " + alternative)

            if re.search("^.*[a-z]e~.*/.*$", alternative):
                print("Potential missing ~ in (~e~): " + alternative)

            if re.search("^.+e~r.+$", alternative):
                print("Potential extra ~ in (er): " + alternative)


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
    """Processes the input file to generate list of problematic alternatives"""
    input = read_csv(in_file)
    print(in_file)


if __name__ == "__main__":
    process()
