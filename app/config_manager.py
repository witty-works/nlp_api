"""Configuration management functions for user and organization settings."""

from typing import Optional

from fastapi import HTTPException

from app.context import AppContext
from app.text_utils import parse_word_type
from app.models import (
    BaseRequestIn,
    CheckRequestIn,
    LangType,
    ResultConf,
    RuleConfig,
)
from app.categories import (
    get_category_keys,
    get_parent_category_name,
    make_category_advanced,
)
from app.categories import inclusive_categories


def parse_term_replacement(
    lemma: str, term_replacement: dict, context: AppContext
) -> dict:
    word_type = (
        term_replacement["word_type"] if "word_type" in term_replacement else "~"
    )

    word_type, lower_case, lemmatize = parse_word_type(word_type)

    word_type = tuple(
        [
            {
                "word_type": word_type,
                "lower_case": lower_case,
                "lemmatize": lemmatize,
            }
        ]
    )

    if lower_case and not lemmatize:
        lemma = lemma.lower()

    if list(filter(lemma.endswith, context.term_replacement_langs)) != []:
        term_replacement["lang"] = lemma[-2:]
        term_replacement["lemma"] = lemma[0:-3]
    else:
        term_replacement["lang"] = None
        term_replacement["lemma"] = lemma

    lang = LangType.EN if term_replacement["lang"] is None else term_replacement["lang"]
    term_replacement["words"] = context.model.tokenize(term_replacement["lemma"], lang)
    term_replacement["word_types"] = word_type * len(term_replacement["words"])

    term_replacement["false_positives"] = []
    term_replacement["parsed_alternatives"] = []
    for alternative in term_replacement["alternatives"]:
        term_replacement["false_positives"].append(alternative)

        alternative = {"lemma": alternative}
        alternative["words"] = context.model.tokenize(alternative["lemma"], lang)
        alternative["word_types"] = word_type * len(alternative["words"])
        term_replacement["parsed_alternatives"].append(alternative)

    return term_replacement


def parse_term_replacements(
    term_replacements_source: dict | None, context: AppContext
) -> dict:
    term_replacements = {}
    if term_replacements_source is not None:
        for lemma in term_replacements_source:
            term_replacement = dict(term_replacements_source[lemma])
            term_replacement = parse_term_replacement(lemma, term_replacement, context)

            term_replacements[lemma] = term_replacement

    return term_replacements


async def fetch_user_organization_configs(
    email: str, context: AppContext
) -> dict | None:
    configs = await context.redis.fetch_user_configs_from_redis(email)

    configs["organization_name"] = None
    configs["organization_config_hash"] = None
    configs["organization_domains"] = None

    if "organization_id" in configs and configs["organization_id"] is not None:
        organization_configs = (
            await context.redis.fetch_organization_configs_from_redis(
                configs["organization_id"]
            )
        )

        configs["organization_name"] = organization_configs["name"]

        configs["organization_config_hash"] = organization_configs.get("config_hash")

        configs["organization_domains"] = organization_configs.get("domains", {})

        configs["organization_config"] = organization_configs["config"]

        configs["organization_term_replacements"] = organization_configs[
            "term_replacements"
        ]

        configs["organization_false_positives"] = organization_configs[
            "false_positives"
        ]
    else:
        configs["organization_id"] = None

    return configs


def apply_configs(
    check_request_in: CheckRequestIn,
    configs: dict,
    force_disables: bool = True,
):
    disabled_categories = check_request_in.config.disabled_categories
    if "force_categories" not in configs or configs["force_categories"] is None:
        configs["force_categories"] = []

    for config in configs:
        if config == "force_categories":
            continue

        data = configs[config]
        if data is None:
            continue

        if config == "categories":
            for category in data:
                category_data = data[category]
                if category_data["status"] != "force":
                    continue

                # BC handling for old category names
                if category.startswith("advanced_"):
                    category = make_category_advanced(
                        category.removeprefix("advanced_")
                    )

                if category_data["value"]:
                    if category in disabled_categories:
                        disabled_categories.remove(category)
                else:
                    force_disables_category = force_disables
                    if not force_disables_category and len(configs["force_categories"]):
                        parent_category = get_parent_category_name(category)
                        force_disables_category = (
                            parent_category in configs["force_categories"]
                        )

                    if force_disables_category and category not in disabled_categories:
                        disabled_categories.append(category)
        elif config == "store_context":
            if data["status"] == "force" and not data["value"]:
                check_request_in.config.__setattr__("store_context", False)
        elif config == "llm_alternatives":
            if data["status"] == "force" and data["value"]:
                check_request_in.config.__setattr__("llm_alternatives", True)
        elif data["status"] == "force":
            check_request_in.config.__setattr__(config, data["value"])

    for category in inclusive_categories:
        if (
            category in check_request_in.config.disabled_categories
            and category not in disabled_categories
        ):
            disabled_categories.append(category)

    check_request_in.config.__setattr__("disabled_categories", disabled_categories)


async def fetch_configs_for_request(
    request_in: BaseRequestIn, user_email: Optional[str], context: AppContext
) -> dict:
    request_in.config.__setattr__("store_context", True)
    request_in.config.__setattr__("llm_alternatives", False)
    request_in.config.__setattr__(
        "alternatives_max_count", context.settings.alternatives_max_count
    )

    if not user_email:
        request_in.config.__setattr__("disabled_categories", get_category_keys(True))
    
        return {}

    try:
        configs = await fetch_user_organization_configs(user_email, context)
    except HTTPException:
        return {}

    apply_configs(request_in, configs["config"])

    if "organization_config" in configs:
        apply_configs(request_in, configs["organization_config"], False)

        configs["term_replacements"] |= configs["organization_term_replacements"]
        configs["false_positives"] = list(
            set(configs["false_positives"] + configs["organization_false_positives"])
        )

    return configs


async def fetch_organization_configs_for_request(
    request_in: BaseRequestIn, organization_id: Optional[str], context: AppContext
) -> dict:
    request_in.config.__setattr__("store_context", True)
    request_in.config.__setattr__("llm_alternatives", False)

    if not organization_id:
        return {}

    try:
        configs = await context.redis.fetch_organization_configs_from_redis(
            organization_id
        )
    except HTTPException:
        return {}

    for config in configs["configs"]:
        if configs["configs"][config]["status"] == "suggestion":
            configs["configs"][config]["status"] = "force"

    apply_configs(request_in, configs["config"])

    return configs


def fetch_config_change(
    configs: dict,
    check_request_in: Optional[BaseRequestIn] = None,
) -> bool | None:
    if not check_request_in:
        return True

    if (
        "config_hash" in configs
        and check_request_in.config_hash != configs["config_hash"]
    ):
        return True

    if (
        "organization_config_hash" in configs
        and check_request_in.organization_config_hash
        != configs["organization_config_hash"]
    ):
        return True

    return None


def fetch_result_conf(configs: dict) -> ResultConf | None:
    if "config" not in configs:
        return None

    organization_config = (
        RuleConfig.model_validate(configs["organization_config"])
        if "organization_config" in configs
        else None
    )

    config = RuleConfig.model_validate(configs["config"])

    return ResultConf(
        id=configs["id"],
        name=configs["name"],
        config=config,
        organization_id=configs["organization_id"],
        organization_name=configs["organization_name"],
        organization_config=organization_config,
        domains=configs["domains"],
        organization_domains=configs["organization_domains"],
        config_hash=configs["config_hash"],
        organization_config_hash=configs["organization_config_hash"],
    )


def debug_configs(request_in: BaseRequestIn) -> dict:
    if "none" in request_in.config.disabled_categories:
        request_in.config.__setattr__("disabled_categories", [])
    elif request_in.config.disabled_categories == []:
        request_in.config.__setattr__(
            "disabled_categories", ["plain_language_advanced"]
        )

    configs = {
        "categories": {},
        "llm_alternatives": {"status": "suggestion", "value": True},
    }
    apply_configs(request_in, configs)

    return configs
