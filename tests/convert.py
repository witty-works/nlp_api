import json

list = {
    "text": "Wir suchen Ninja Programmierer für unsere Kunden",
    "config": {"store_context": False},
}

conv = json.dumps(list)

print(conv)
