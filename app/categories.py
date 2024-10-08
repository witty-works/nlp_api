import json
from functools import lru_cache


@lru_cache()
def load_json_data(file_name):
    with open(file_name) as file:
        return json.load(file)


@lru_cache()
def get_categories():
    categories = load_json_data("training_data/categories.json")
    categories.update(get_diversity_dimensions_drivers())

    return categories


@lru_cache()
def get_diversity_dimensions_drivers():
    return load_json_data("training_data/diversity_dimension_drivers.json")


@lru_cache()
def get_proficiency_levels():
    return load_json_data("training_data/proficiency_levels.json")


def get_category_keys(only_category_advanced_keys=False):
    categories = get_categories()

    category_keys = list(categories.keys())

    category_advanced_keys = []
    for category in category_keys:
        category_data = categories[category]

        if (
            "category" in category_data
            and "proficiency_level" in category_data
            and "proficiency_level" != "openly_discriminating"
        ):
            category_advanced_keys.append(category + "_advanced")

    if only_category_advanced_keys:
        return category_advanced_keys

    return category_keys + category_advanced_keys


def get_category_name(category):
    return category.removesuffix("_advanced")


def is_category_advanced(category):
    return category.endswith("_advanced")


def get_category(category):
    category = get_category_name(category)

    categories = get_categories()
    if category not in categories:
        return None

    return categories[category]


def get_parent_category_name(category):
    parent_category = get_category(category)

    if parent_category is None:
        return None

    return parent_category["category"]


def is_category_inclusive(category):
    category_data = get_category(category)
    proficiency_levels = get_proficiency_levels()

    return (
        category_data
        and category_data.get("proficiency_level") in proficiency_levels
        and proficiency_levels[category_data["proficiency_level"]]["inclusive"]
    )


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

    if is_category_advanced(category):
        return 3.0

    return 2.0


def is_sub_category_enabled(disabled_categories: list, subcategories: list[str]) -> bool | str:
    if isinstance(subcategories, str):
        subcategories = [subcategories]

    for subcategory in subcategories:
        if subcategory in disabled_categories:
            continue

        category_data = get_category(subcategory)
        if category_data is None:
            continue

        if (
            "category" in category_data
            and category_data["category"] in disabled_categories
        ):
            continue

        return subcategory

    return False
