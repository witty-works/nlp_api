import json
from functools import lru_cache

# Abstracting repeated logic into reusable functions to enhance code modularity
# Utilizing caching for frequently accessed data to improve performance
# Standardizing naming conventions and coding style for consistency

@lru_cache()
def load_json_data(file_name):
    with open(file_name) as file:
        return json.load(file)

@lru_cache()
def get_categories():
    return load_json_data("training_data/categories.json")

@lru_cache()
def get_diversity_dimensions_drivers():
    return load_json_data("training_data/diversity_dimension_drivers.json")

@lru_cache()
def get_proficiency_levels():
    return load_json_data("training_data/proficiency_levels.json")

def get_category_keys(only_category_advanced_keys=False):
    categories = get_categories()
    categories.update(get_diversity_dimensions_drivers())

    category_keys = list(categories.keys())

    if only_category_advanced_keys:
        return [key for key in category_keys if is_category_advanced(key)]

    return category_keys

def get_category_name(category):
    return category.removesuffix("_advanced")

def is_category_advanced(category):
    return category.endswith("_advanced")

def get_category(category):
    category = get_category_name(category)
    categories = get_categories()
    categories.update(get_diversity_dimensions_drivers())

    return categories.get(category, None)

def get_parent_category_name(category):
    parent_category = get_category(category)
    return parent_category.get("category", None) if parent_category else None

def is_category_inclusive(category):
    category_data = get_category(category)
    proficiency_levels = get_proficiency_levels()

    return category_data and category_data.get("proficiency_level") in proficiency_levels and proficiency_levels[category_data["proficiency_level"]]["inclusive"]

def get_proficiency_level(category):
    category_data = get_category(category)
    if not category_data:
        return None

    return category_data.get("proficiency_level", "unconscious_bias")

def map_gravity(category):
    if category == "corporate_rules":
        return 0.9

    if is_category_inclusive(category):
        return None

    return int(map_importance(category))

def map_importance(category):
    proficiency_level = get_proficiency_level(category)
    if proficiency_level == "openly_discriminating":
        return 1.0

    if is_category_advanced(category):
        return 3.0

    return 2.0
