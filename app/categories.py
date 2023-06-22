import json
from functools import lru_cache


@lru_cache()
def get_categories():
    categories_file = open("training_data/categories.json")
    categories = json.load(categories_file)

    diversity_dimensions_drivers_file = open(
        "training_data/diversity_dimension_drivers.json"
    )
    categories.update(json.load(diversity_dimensions_drivers_file))

    return categories


@lru_cache()
def get_category_keys(only_category_advanced_keys=False):
    categories = get_categories()

    category_keys = list(categories.keys())

    category_advanced_keys = []
    for category in category_keys:
        category_data = categories[category]
        category_advanced_keys.append(category + "_base")

        if (
            "category" in category_data
            and "proficiency_level" in category_data
            and "proficiency_level" != "openly_discriminating"
        ):
            category_advanced_keys.append("advanced_" + category)
            category_advanced_keys.append("advanced_" + category + "_base")

    if only_category_advanced_keys:
        return category_advanced_keys

    return category_keys + category_advanced_keys


@lru_cache()
def get_proficiency_levels():
    proficiency_levels_file = open("training_data/proficiency_levels.json")
    return json.load(proficiency_levels_file)


def get_category_name(category):
    return category.removeprefix("advanced_").removesuffix("_base")


def get_category(category):
    category = get_category_name(category)

    categories = get_categories()
    if category not in categories:
        return None

    return categories[category]


def is_category_inclusive(category):
    category_data = get_category(category)
    if category_data is None or "proficiency_level" not in category_data:
        return False

    proficiency_levels = get_proficiency_levels()
    if category_data["proficiency_level"] not in proficiency_levels:
        return False

    return proficiency_levels[category_data["proficiency_level"]]["inclusive"]


def get_proficiency_level(category):
    if category == "openly_discriminating":
        return "openly_discriminating"

    category_data = get_category(category)
    if category_data is None:
        return None

    if "proficiency_level" not in category_data:
        if "category" in category_data and category_data["category"] == "orthography":
            return "orthography"

        return None

    if category_data["proficiency_level"] == "openly_discriminating":
        return "openly_discriminating"

    return "inclusive" if is_category_inclusive(category) else "unconscious_bias"


def map_gravity(category):
    if category == "corporate_rules":
        return 0.9

    if is_category_inclusive(category):
        return None

    return int(map_importance(category))


def map_importance(category):
    proficiency_level = get_proficiency_level(category)
    if proficiency_level is None:
        return 2.0

    if (
        proficiency_level == "orthography"
        or proficiency_level == "openly_discriminating"
    ):
        return 1.0

    if not category.startswith("advanced_"):
        return 2.0

    return 3.0
