import click
import csv


def intersection(lst1, lst2):
    return list(set(lst1) & set(lst2))


def read_csv(in_file):
    with open(in_file, newline="") as csvfile:
        triggers = []
        alternative_words = []

        line_count = 0
        reader = csv.reader(csvfile, skipinitialspace=True)
        for row in reader:
            if line_count == 0:
                line_count += 1
            else:
                for i, column in enumerate(row):
                    if i == 0:
                        triggers.append(column)
                    else:
                        alternative_words = alternative_words + column.split(" ")

        print(intersection(triggers, alternative_words))


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
