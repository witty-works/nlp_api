from app.models import BasicWordType, LangType


def invert_list_to_dict(list_to_convert: list) -> dict:
    return dict(zip(list_to_convert, list(range(len(list_to_convert)))))


rule_columns = [
    "id",
    "text_id",
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
    "is_placeholder",
    "is_inspiration",
    "is_advanced",
    "is_collective_noun",
    "is_gendered_noun",
    "label",
]
alternative_columns = invert_list_to_dict(alternative_columns)
alternative_column_list = ", ".join(alternative_columns.keys())

declensions_config = {
    LangType.EN: {
        BasicWordType.VERB: {
            "name": "rules_englishverb",
            "columns": [
                "past_tense",
                "past_participle",
                "present_participle",
                "third_person_singular",
                "base_form",
            ],
        },
        BasicWordType.ADJECTIVE: {
            "name": "rules_englishadjective",
            "columns": [
                "comparative",
                "superlative",
                "is_absolute",
                "base_form",
            ],
        },
        BasicWordType.NOUN: {
            "name": "rules_englishnoun",
            "columns": ["base_form", "plural", "plural_2"],
        },
    },
    LangType.DE: {
        BasicWordType.VERB: {
            "name": "rules_germanverb",
            "columns": [
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
                "base_form",
            ],
        },
        BasicWordType.ADJECTIVE: {
            "name": "rules_germanadjective",
            "columns": [
                "comparative",
                "superlative",
                "is_absolute",
                "base_form",
            ],
        },
        BasicWordType.NOUN: {
            "name": "rules_germannoun",
            "columns": [
                "gender_1",
                "sg_nom",
                "sg_dat",
                "sg_gen",
                "sg_acc",
                "pl_nom",
                "pl_dat",
                "pl_gen",
                "pl_acc",
                "collective_noun",
                "collective_noun_2",
                "sg_dat_2",
                "sg_gen_2",
                "base_form",
                "female_form",
                "male_form",
            ],
        },
    },
}

verb_form_map = {
    "Part": "past_participle",
    "Inf": "infinitiv_zu",
    "Fin": {
        "Past": {
            "1": "past_tense_ich",
            "3": "past_tense_ich",
        },
        "Pres": {
            "1": "present_ich",
            "2": "present_du",
            "3": "present_pronoun",
        },
    },
}
