import json
from functools import lru_cache


# Centralized list of inclusive language-related categories used across the API.
inclusive_categories = [
    "communal",
    "d_and_i",
    "emotional_security",
    "inclusive",
    "orthography",
]


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
def get_config_option_labels() -> dict:
    """Display labels for the enum-typed config fields, keyed by field.

    Shipped in the same data directory as categories.json and copied from the
    dashboard the same way, so the wording a user sees in the extension is the
    wording the dashboard uses. The API's enums stay the authority on which
    values *exist*; this only says how to name them.
    """
    return load_json_data("training_data/config_options.json")


def get_config_option_labels_for(field: str, lang: str) -> dict:
    """Labels for one field in one language, falling back to English.

    A value the dashboard has no label for is simply absent — clients show the
    raw value, which reads fine for punctuation such as `(-)`.
    """
    translations = get_config_option_labels().get(field, {}).get("translations", {})

    return translations.get(lang) or translations.get("en") or {}


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


def get_category_list(language=None) -> tuple[list[dict], list[dict]]:
    """The categories a client may switch off, plus the groups they sit in.

    A deployment without the dashboard has nothing to populate
    `organization_config.categories` with, so this is the only way a client can
    learn which keys `config.disabled_categories` accepts. Only the drivers are
    togglable; the dimensions they belong to are reported separately so a client
    can group and label them without hard-coding the taxonomy.

    `advanced_key` is reported rather than a "has an advanced variant" flag,
    because the two keys are independent: results come back under whichever one
    matched, and switching a category off entirely means naming both.
    """
    categories = get_categories()
    advanced_keys = set(get_category_keys(True))

    def label(key):
        return language._(key, "hs_name") if language is not None else None

    category_list = []
    group_keys = []
    for key, data in categories.items():
        parent = data.get("category")
        if not parent:
            # A dimension rather than a driver — it carries no rules of its own.
            continue

        if parent not in group_keys:
            group_keys.append(parent)

        advanced_key = make_category_advanced(key)
        category_list.append(
            {
                "key": key,
                "label": label(key),
                "parent": parent,
                "advanced_key": (
                    advanced_key if advanced_key in advanced_keys else None
                ),
                "proficiency_level": get_proficiency_level(key),
            }
        )

    groups = [{"key": key, "label": label(key)} for key in group_keys]

    return category_list, groups


def get_category_name(category):
    return category.removesuffix("_advanced")


def is_category_advanced(category):
    return category.endswith("_advanced")


def make_category_advanced(category):
    if is_category_advanced(category):
        return category
    return category + "_advanced"


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


def is_sub_category_enabled(
    disabled_categories: list, subcategories: list[str]
) -> bool | str:
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
