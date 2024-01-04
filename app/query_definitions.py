from app.models import BasicWordType, LangType

def invert_list_to_dict(list_to_convert: list) -> dict:
    return dict(zip(list_to_convert, list(range(len(list_to_convert)))))


rule_columns = [
    "id",
    "parent_id",
    "lemma",
    "language",
    "lemma_json",
    "pattern",
    "is_pattern_match",
    "type",
    "entity_type",
    "label",
    "label_type",
    "pluralization",
    "word_types_json",
    "diversity_dimension_json",
]
rule_columns = invert_list_to_dict(rule_columns)
rule_column_list = ", ".join(rule_columns.keys())

alternative_columns = [
    "lemma",
    "lemma_json",
    "word_types_json",
    "is_remove",
    "is_inspiration",
    "is_advanced",
    "is_collective_noun",
    "label",
]
alternative_columns = invert_list_to_dict(alternative_columns)
alternative_column_list = ", ".join(alternative_columns.keys())

declensions_config = {
    LangType.EN: {
        BasicWordType.VERB: {
            "name": "rules_englishverb",
            "columns": [
                "base_form",
                "past_tense",
                "past_participle",
                "present_participle",
                "third_person_singular",
            ],
        },
        BasicWordType.ADJECTIVE: {
            "name": "rules_englishadjective",
            "columns": ["base_form", "comparative", "superlative", "is_absolute"],
        },
        BasicWordType.NOUN: {"name": "rules_englishnoun", "columns": ["base_form", "plural"]},
    },
    LangType.DE: {
        BasicWordType.VERB: {
            "name": "rules_germanverb",
            "columns": [
                "base_form",
                "present_ich",
                "present_du",
                "present_pronoun",
                "past_tense_ich",
                "past_participle",
                "conjunctive_ich",
                "imperativ_singular",
                "imperativ_plural",
                "helping_verb",
                "infinitiv_zu",
            ],
        },
        BasicWordType.ADJECTIVE: {
            "name": "rules_germanadjective",
            "columns": ["base_form", "comparative", "superlative", "is_absolute"],
        },
        BasicWordType.NOUN: {
            "name": "rules_germannoun",
            "columns": [
                "gender_1",
                "base_form",
                "female_form",
                "male_form",
                "sg_nom",
                "sg_dat",
                "sg_gen",
                "sg_acc",
                "pl_nom",
                "pl_dat",
                "pl_gen",
                "pl_acc",
                "sg_dat_2",
                "sg_gen_2",
            ],
        },
    },
}