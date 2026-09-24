"""Configuration management functions for user and organization settings."""

import hashlib
import json
import logging
from functools import lru_cache
from typing import Optional

from fastapi import HTTPException

from app.api_keys import KeyConfig, key_config
from app.context import AppContext
from app.settings import Settings
from app.text_utils import parse_word_type
from pydantic import ValidationError

from app.models import (
    BaseRequestIn,
    CheckRequestIn,
    Config,
    LangType,
    LlmAccessType,
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


def build_default_user_configs(
    email: str, settings: Settings, entry: Optional[KeyConfig] = None
) -> dict:
    """Configuration for a user nobody ever synced into Redis.

    A deployment without the dashboard has no `SyncUserToNlpApi` job, so an
    API key resolves to an email that has no stored config at all. Without this
    fallback `/v2.0/auth` answers 403 and every client concludes it is signed
    out.

    The two flags are reported as a suggestion where clients may set them for
    themselves and as a force where they may not, so the configured default is
    what takes effect either way: a suggestion applies to any request that does
    not mention the field, and a force to every request.
    """
    status = "suggestion" if settings.client_config_enabled else "force"
    config = {
        "store_context": {
            "value": settings.default_user_store_context,
            "status": status,
        },
        "llm_alternatives": {
            "value": settings.default_user_llm_alternatives,
            "status": status,
        },
        "categories": {},
        "force_categories": [],
    }

    # A synced API key's config (app/api_keys.py): its `config` as suggestions, so clients reading
    # /v2.0/auth show them as the defaults, its `force` as forces. Disabled
    # categories are forced the way the dashboard forces them, per category.
    key_defaults = {}
    if entry is not None:
        key_defaults = dict(entry.config)
        for field, value in entry.config.items():
            # The two flags clients may not set for themselves are forced, as
            # above; the rest a request may override.
            field_status = status if field in CLIENT_OPTIONAL else "suggestion"
            config[field] = {"value": value, "status": field_status}
        for field, value in entry.force.items():
            if field == "disabled_categories":
                for category in value:
                    config["categories"][category] = {"value": False, "status": "force"}
            else:
                config[field] = {"value": value, "status": "force"}

    configs = {
        # Stable and non-identifying: this ends up in the metrics hashes, which
        # the dashboard deployment fills with pseudonymous ids as well.
        "id": hashlib.sha256(email.lower().encode("utf-8")).hexdigest()[:16],
        "name": email,
        "email": email,
        "organization_id": None,
        "config": config,
        "false_positives": [],
        "term_replacements": {},
        "domains": None,
    }

    # Same contract as the dashboard's hash: it only has to change when the
    # config does, so a client can tell whether its stored copy is stale.
    configs["config_hash"] = hashlib.md5(
        json.dumps(configs, sort_keys=True).encode("utf-8"), usedforsecurity=False
    ).hexdigest()
    # Not part of the hash: what the server fills in for a request that does
    # not set these fields itself, which the stored config cannot say (a
    # suggestion there is only reported to clients).
    configs["key_defaults"] = key_defaults

    return configs


async def fetch_user_organization_configs(
    email: str, context: AppContext, allow_default: bool = False
) -> dict | None:
    try:
        configs = await context.redis.fetch_user_configs_from_redis(email)
    except HTTPException:
        # Only the request path substitutes defaults. The management endpoints
        # keep reporting a 404 so "no config is stored for this email" stays
        # distinguishable from "the stored config happens to be the default".
        if not allow_default:
            raise

        # A dashboard-synced config wins. Without one, a user of a synced API
        # key gets its config, and anyone else the deployment's defaults.
        entry = key_config(context.redis, email)
        if entry is None and not context.settings.default_user_config_enabled:
            raise

        configs = build_default_user_configs(email, context.settings, entry)

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


# The two fields a request only decides itself where CLIENT_CONFIG_ENABLED is on.
CLIENT_OPTIONAL = ("store_context", "llm_alternatives")


def set_config_field(config: Config, field: str, value, source: str) -> bool:
    """Assign one field as the request's own config would take it: validated
    and normalised (`"de-CH"` becomes `["de-CH"]`, strings become enums). A
    value that does not validate is logged and left out, so a stale stored
    config cannot fail the request. Whether it was set."""
    try:
        Config.__pydantic_validator__.validate_assignment(config, field, value)
    except ValidationError as error:
        logging.getLogger("nlp_api").warning(
            "%s: invalid value for %s ignored: %s",
            source,
            field,
            error.errors(include_input=False, include_url=False),
        )
        return False

    return True


@lru_cache(maxsize=4)
def parse_default_config(default_config: str) -> dict:
    """DEFAULT_CONFIG as a dict of validated request config fields. Raises
    ValueError naming what is wrong; startup calls this, so a typo stops the
    server instead of being skipped on every request."""
    if not default_config:
        return {}
    try:
        defaults = json.loads(default_config)
    except ValueError:
        raise ValueError(
            f"DEFAULT_CONFIG is not valid JSON: {default_config!r}"
        ) from None
    if not isinstance(defaults, dict):
        raise ValueError("DEFAULT_CONFIG must be a JSON object")
    unknown = sorted(set(defaults) - set(Config.model_fields))
    if unknown:
        raise ValueError(
            f"DEFAULT_CONFIG has no such config option: {', '.join(unknown)}"
        )
    try:
        Config(**defaults)
    except ValidationError as error:
        raise ValueError(
            f"DEFAULT_CONFIG: {error.errors(include_input=False, include_url=False)}"
        ) from None

    return defaults


def apply_defaults(config: Config, defaults: dict, settled: set, source: str) -> None:
    """Fill in `defaults` for the fields nothing has settled yet (the request
    did not set them, no earlier default did)."""
    for field, value in defaults.items():
        if field not in settled:
            set_config_field(config, field, value, source)


def apply_configs(
    check_request_in: CheckRequestIn,
    configs: dict,
    force_disables: bool = True,
    settled: set | None = None,
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
        elif config in ("store_context", "llm_alternatives"):
            # Forcing applies in both directions: the client value is the
            # starting point now that it is no longer overwritten up front, so
            # a `force: false` has to actually turn the flag off rather than
            # rely on it already being off. A suggestion only fills in for a
            # request that never mentioned the field — which is also why the
            # first config to suggest one wins over any later one.
            taken = (
                check_request_in.config.model_fields_set if settled is None else settled
            )
            if data["status"] == "force" or config not in taken:
                check_request_in.config.__setattr__(config, bool(data["value"]))
                if settled is not None:
                    settled.add(config)
        elif data["status"] == "force":
            set_config_field(check_request_in.config, config, data["value"], "config")

    for category in inclusive_categories:
        if (
            category in check_request_in.config.disabled_categories
            and category not in disabled_categories
        ):
            disabled_categories.append(category)

    check_request_in.config.__setattr__("disabled_categories", disabled_categories)


def llm_available(settings: Settings, model: Optional[str] = None) -> bool:
    """Whether this deployment can reach an LLM at all, for anybody.

    No model configured means there is nothing to reach, which is treated the
    same as having turned LLM use off: refused rather than attempted, so an
    unconfigured deployment answers 403 instead of failing at the provider.
    """
    return settings.llm_access != LlmAccessType.DISABLED and bool(
        settings.resolve_llm_model(model)
    )


def llm_alternatives_allowed(settings: Settings, user_email: Optional[str]) -> bool:
    """Whether this request may spend the deployment's LLM budget.

    The operator's call, and the last word: LLM calls are billed to whoever runs
    the API, so neither a client asking for them nor a dashboard `force` rule
    can turn them on where this says no.
    """
    if not llm_available(settings):
        return False

    if settings.llm_access == LlmAccessType.EVERYONE:
        return True

    if not user_email:
        return False

    if not settings.llm_allowed_users:
        return True

    # An API key is its user's email by this point, so one list covers a key and
    # a dashboard login alike.
    return user_email.lower() in {
        allowed.lower().strip() for allowed in settings.llm_allowed_users
    }


def apply_default_config(
    request_in: BaseRequestIn, context: AppContext, settled: set
) -> None:
    """Fill in what this deployment prefers (DEFAULT_CONFIG) where nothing is
    settled yet. A key's defaults, a synced config and a `force` rule layered
    on later still win."""
    # Not during tests. The suite asserts on what the built-in defaults produce,
    # and this would let a value in someone's local .env change the expected
    # output of every fixture that does not name the field itself. The same
    # reasoning already applies to the testing user mapping.
    if context.settings.testing:
        return

    defaults = parse_default_config(context.settings.default_config or "")
    apply_defaults(request_in.config, defaults, settled, "DEFAULT_CONFIG")


async def fetch_configs_for_request(
    request_in: BaseRequestIn, user_email: Optional[str], context: AppContext
) -> dict:
    """Build the request's config from its layers, each filling in or
    overriding the one before:

    1. the built-in defaults of `Config`;
    2. what the request sent (`store_context` and `llm_alternatives` only
       where CLIENT_CONFIG_ENABLED is on);
    3. DEFAULT_CONFIG, for fields the request did not send;
    4. a synced API key's `config`, for fields the request did not send;
    5. suggestions in a synced config, for the two flags above;
    6. `force` rules in the user's, then the organisation's config;
    7. LLM_ACCESS / LLM_ALLOWED_USERS, which can only turn the LLM off.

    Every value is validated as it is applied. `settled` is what the request
    or an earlier layer decided, which later defaults leave alone.
    """
    settled = set(request_in.config.model_fields_set)

    # `store_context` and `llm_alternatives` are only the client's to set where
    # the deployment says so. Where it does not, they are reset here before any
    # config is layered on; where it does, a `force` rule in a synced config
    # still overrules whatever arrived, and `llm_access` overrules everything.
    if not context.settings.client_config_enabled:
        settled -= set(CLIENT_OPTIONAL)
        request_in.config.__setattr__("store_context", True)
        request_in.config.__setattr__("llm_alternatives", False)

    apply_default_config(request_in, context, settled)

    request_in.config.__setattr__(
        "alternatives_max_count", context.settings.alternatives_max_count
    )

    configs = {}
    if not user_email:
        request_in.config.__setattr__("disabled_categories", get_category_keys(True))
    else:
        try:
            configs = await fetch_user_organization_configs(user_email, context, True)
        except HTTPException:
            # No config to layer on. The endpoints all refuse an empty one, so
            # there is nothing left to protect against here.
            pass

    if configs:
        # An API key's defaults take the place of the deployment's, and a
        # force in any config still wins over both.
        apply_defaults(
            request_in.config, configs.get("key_defaults", {}), settled, "API key"
        )
        apply_configs(request_in, configs["config"], settled=settled)

        if "organization_config" in configs:
            apply_configs(
                request_in, configs["organization_config"], False, settled=settled
            )

            configs["term_replacements"] |= configs["organization_term_replacements"]
            configs["false_positives"] = list(
                set(
                    configs["false_positives"] + configs["organization_false_positives"]
                )
            )

    # Last, so that it overrules both the client and any synced config. The
    # config reported back (/v2.0/auth) says so too, so a client need not offer
    # LLM suggestions the server will refuse.
    if not llm_alternatives_allowed(context.settings, user_email):
        request_in.config.__setattr__("llm_alternatives", False)
        if isinstance(configs.get("config"), dict):
            configs["config"]["llm_alternatives"] = {"value": False, "status": "force"}

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


def debug_configs(request_in: BaseRequestIn, settings: Settings) -> dict:
    if "none" in request_in.config.disabled_categories:
        request_in.config.__setattr__("disabled_categories", [])
    elif request_in.config.disabled_categories == []:
        request_in.config.__setattr__(
            "disabled_categories", ["plain_language_advanced"]
        )

    configs = {
        "categories": {},
        # The debug routes have no user to resolve, so `users` cannot be checked
        # against anything — they sit behind their own basic auth instead. What
        # still applies is whether the deployment has an LLM at all.
        "llm_alternatives": {"status": "suggestion", "value": llm_available(settings)},
    }
    apply_configs(request_in, configs)

    return configs
