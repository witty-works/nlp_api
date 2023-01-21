import csv

from app.main import german_verb_splittable

# csv header
fieldnames = ["name", "area", "country_code2", "country_code3"]

with open("verbs.csv", "w", encoding="UTF8", newline="") as f:
    with open("./training_data/de/verbs.csv") as csv_file:
        csv_reader = csv.reader(csv_file, delimiter=",")
        line_count = 0
        for row in csv_reader:
            if line_count == 0:
                line_count += 1

                fieldnames = row
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
            elif line_count == 1:
                prefix = german_verb_splittable(row[0])
                if prefix == False:
                    prefix = ""

                row[-1] = prefix

                row_dict = {fieldnames[i]: row[i] for i in range(len(fieldnames))}

                writer.writerow(row_dict)
