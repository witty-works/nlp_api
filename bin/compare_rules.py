import argparse
import csv
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


def get_data_from_files(locale):
    if locale[0:2] == "de":
        locale = "de"

    base_directory = "training_data/" + locale + "/"
    training_data_paths = []
    for file in os.listdir(base_directory):
        training_data_paths.append(base_directory + file)

    lemmas = {}

    for training_data_path in training_data_paths:
        with open(training_data_path) as f:
            if not f.name.endswith(".csv"):
                continue

            reader = csv.DictReader(f)
            for row in reader:
                if "Alt_split" in row:
                    alternatives = [s.strip() for s in row["Alt_split"].split("|")]

                    lemma = row["Lemma"].replace("'", '"').strip()

                    if lemma in lemmas:
                        lemmas[lemma] += alternatives
                    else:
                        lemmas[lemma] = alternatives

    return lemmas


def intersection(lst1, lst2):
    return list(set(lst1) & set(lst2))


def difference(lst1, lst2):
    return list(set(lst1) - set(lst2))


def is_file(path_to_file):
    if os.path.isfile(path_to_file):
        return True
    return False


def get_data_file(file):
    lemmas = {}
    inspirations = 0

    with open(file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (
                "ungegenderte Begriffe" in row
                and "<div" not in row["ungegenderte Begriffe"]
            ):
                if "..." in row["ungegenderte Begriffe"]:
                    inspirations += 1
                    continue

                alternatives = [
                    s.strip() for s in row["gendergerechte Alternativen"].split(";")
                ]

                lemma = (
                    row["ungegenderte Begriffe"]
                    .replace(" (sg.)", "")
                    .replace(" (pl.)", "")
                    .strip()
                )

                if lemma in lemmas:
                    lemmas[lemma] += alternatives
                else:
                    lemmas[lemma] = alternatives

    print("Number of rewording suggestions in gendergeschickt")
    print(inspirations)

    return lemmas


args = parse_args()
training_data_lemmas = get_data_from_files(args.Locale)

if not is_file(args.File):
    raise FileNotFoundError("File %s cannot be found." % args.File)

lemmas = get_data_file(args.File)

training_data_lemmas_keys = training_data_lemmas.keys()
lemmas_keys = lemmas.keys()

print("lemmas in training_data")
print(len(training_data_lemmas_keys))
print("lemmas in gendergeschickt")
print(len(lemmas_keys))

print("lemmas missing in gendergeschickt")
diff = difference(set(training_data_lemmas_keys), set(lemmas_keys))
print(len(diff))
# print(diff)

print("lemmas missing in training_data")
diff = difference(set(lemmas_keys), set(training_data_lemmas_keys))
print(len(diff))
# print(diff)

training_data_lemmas_keys_lower = [s.lower() for s in training_data_lemmas_keys]

lemmas_keys_lower = [s.lower() for s in lemmas_keys]

intersect = intersection(set(lemmas_keys), set(training_data_lemmas_keys))
intersect_lower = intersection(training_data_lemmas_keys_lower, lemmas_keys_lower)

print("lemmas with different casing")
print(
    difference(
        intersection(training_data_lemmas_keys_lower, lemmas_keys_lower),
        [s.lower() for s in intersect],
    )
)

print("lemmas in both training_data and file")
print(len(intersect_lower))
print(intersect)
