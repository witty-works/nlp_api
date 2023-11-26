from pydantic import field_validator, BaseModel, Field
from typing import Dict, List, Optional, Union
from enum import Enum
from collections import namedtuple
import json, typing

from starlette.responses import Response

import string
import re

from app.categories import (
    get_proficiency_level,
    get_category,
    get_category_name,
    map_gravity,
)
from app.privacy_filter import get_privacy_filter


class Client(BaseModel):
    name: Optional[str] = None
    version: Optional[str] = None


class Language(object):
    def __init__(self, locale):
        self.locale = locale
        self.lang = locale[0:2]
        self.gettext = None

    def _(self, category, key):
        try:
            category_data = get_category(category)

            text = category_data["translations"][self.lang][key]
            text = self.convert_sharp_ss(text)
        except KeyError:
            text = ""

        return text

    def convert_sharp_ss(self, text):
        if self.locale != "de-CH":
            return text

        return text.replace("ß", "ss")


class EventType(str, Enum):
    CHECK = "check"
    IGNORE = "ignore"
    ALTERNATIVE = "alternative"
    ERROR = "error"


class ContentType(str, Enum):
    ADVANCED = "advanced"
    VIDEO = "video"


class LangType(str, Enum):
    EN = "en"
    DE = "de"


class LangWithAutoType(str, Enum):
    AUTO = "auto"
    EN = "en"
    DE = "de"
    deDE = "de-DE"
    deCH = "de-CH"
    deAT = "de-AT"
    enUS = "en-US"
    enGB = "en-GB"


class RuleType(str, Enum):
    DEFAULT = "default"
    PREFIX = "prefix"
    SUFFIX = "suffix"
    SUBSTRING = "substring"


class LangVariantType(str, Enum):
    deDE = "de-DE"
    deCH = "de-CH"
    deAT = "de-AT"
    enUS = "en-US"
    enGB = "en-GB"


class GermanGenderEndingType(str, Enum):
    SLASH = "/in"
    SLASH_DASH = "/-in"
    UNDERSCORE = "_in"
    STAR = "*in"
    COLON = ":in"
    PARENTHESIS_DASH = "(-)"
    PARENTHESIS = "()"
    CAPITAL_LETTER = "In"
    BINARY = "binary"


class SingularTheyType(str, Enum):
    HE_OR_SHE = "he_or_she"
    ALL_PRONOUNS = "all_pronouns"


class GenderedRolesFormatType(str, Enum):
    NONE = "none"
    BOTH = "both"
    INCLUSIVE_GENDER = "inclusive_gender"
    BINARY_GENDER = "binary_gender"


class Alternative(BaseModel):
    lemma: str
    word_types: Optional[str] = None
    type: Optional[str] = None
    label: Optional[str] = None
    pluralization: Optional[str] = None
    is_inspiration: Optional[bool] = False
    is_advanced: Optional[bool] = False


class RuleIn(BaseModel):
    text: str
    lang: LangType
    lemma: str
    word_types: str
    subcategories: list[str]
    lower_case: bool = True
    alternatives: Optional[list[Alternative]] = []
    false_positives: Optional[list[str]] = []


class Config(BaseModel):
    store_context: bool = True
    plan: Optional[str] = None
    primary_language: Optional[LangVariantType] = None
    preferred_languages: List = [LangWithAutoType.EN, LangWithAutoType.DE]
    _supported_langs = [
        LangType.DE,
        LangType.EN,
    ]
    preferred_variants: List = [LangWithAutoType.enUS, LangWithAutoType.deDE]
    _supported_locales = [
        LangWithAutoType.deDE,
        LangWithAutoType.deCH,
        LangWithAutoType.deAT,
        LangWithAutoType.enUS,
        LangWithAutoType.enGB,
    ]
    german_gender_ending: GermanGenderEndingType = GermanGenderEndingType.STAR
    _gendereddenom_ending = {
        GermanGenderEndingType.STAR: re.compile(r"^[A-ZÄÖÜ][a-zäöü]+\*in(nen)?$"),
        GermanGenderEndingType.UNDERSCORE: re.compile(r"^[A-ZÄÖÜ][a-zäöü]+_in(nen)?$"),
        GermanGenderEndingType.COLON: re.compile(r"^[A-ZÄÖÜ][a-zäöü]+:in(nen)?$"),
        GermanGenderEndingType.SLASH: re.compile(r"^[A-ZÄÖÜ][a-zäöü]+/in(nen)?$"),
        GermanGenderEndingType.SLASH_DASH: re.compile(r"^[A-ZÄÖÜ][a-zäöü]+/-in(nen)?$"),
        GermanGenderEndingType.PARENTHESIS_DASH: re.compile(
            r"^[A-ZÄÖÜ][a-zäöü]+\(-in(nen)?\)$"
        ),
        GermanGenderEndingType.PARENTHESIS: re.compile(
            r"^[A-ZÄÖÜ][a-zäöü]+\(in(nen)?\)$"
        ),
        GermanGenderEndingType.CAPITAL_LETTER: re.compile(
            r"^[A-ZÄÖÜ][a-zäöü]+In(nen)?$"
        ),
    }
    _gendereddenom_ending_article = {
        GermanGenderEndingType.STAR: re.compile(r"^[a-zäöü]{3,7}\*[a-zäöü]{3,7}$"),
        GermanGenderEndingType.UNDERSCORE: re.compile(r"^[a-zäöü]{3,7}_[a-zäöü]{3,7}$"),
        GermanGenderEndingType.COLON: re.compile(r"^[a-zäöü]{3,7}:[a-zäöü]{3,7}$"),
        GermanGenderEndingType.SLASH: re.compile(r"^[a-zäöü]{3,7}/[a-zäöü]{3,7}$"),
        GermanGenderEndingType.SLASH_DASH: re.compile(r"^[a-zäöü]{3,7}/[a-zäöü]{3,7}$"),
        GermanGenderEndingType.CAPITAL_LETTER: re.compile(
            r"^[a-zäöü]{3,7}/[a-zäöü]{3,7}$"
        ),
    }
    _gendereddenom_ending_word_type = {
        GermanGenderEndingType.STAR: (0, 0, "*"),
        GermanGenderEndingType.UNDERSCORE: (0, 0, "_"),
        GermanGenderEndingType.COLON: (0, 0, ":"),
        GermanGenderEndingType.SLASH: (-1, 2, "/"),
        GermanGenderEndingType.SLASH_DASH: (0, 0, "/"),
        GermanGenderEndingType.PARENTHESIS_DASH: (-1, 2, ")"),
        GermanGenderEndingType.PARENTHESIS: (-1, 4, "("),
        GermanGenderEndingType.CAPITAL_LETTER: (0, 0, "I"),
    }
    disabled_categories: List = []
    gendered_roles_format: GenderedRolesFormatType = GenderedRolesFormatType.BOTH
    show_inspiration_alternatives: bool = False
    alternatives_max_count: Optional[int] = None

    @field_validator("preferred_languages", mode="before")
    @classmethod
    def valid_preferred_languages(cls, v):
        if isinstance(v, str) and v != "":
            v = [s.strip() for s in v.split(",")]

        if isinstance(v, list) and v != []:
            for lang in v:
                if lang not in Config._supported_langs.default:
                    raise ValueError(
                        "Contains not supported preferred_languages: " + ",".join(v)
                    )

            return v

        return []

    @field_validator("preferred_variants", mode="before")
    @classmethod
    def valid_preferred_variants(cls, v):
        if isinstance(v, str) and v != "":
            v = [s.strip() for s in v.split(",")]

        if isinstance(v, list) and v != []:
            for lang in v:
                if lang not in Config._supported_locales.default:
                    raise ValueError(
                        "Contains not supported preferred_variants: " + ",".join(v)
                    )

            return v

        return []

    @field_validator("disabled_categories", mode="before")
    @classmethod
    def valid_disabled_categories(cls, v):
        if isinstance(v, str):
            return v.split(",")
        return v


class StatusType(str, Enum):
    FORCE = "force"
    SUGGESTION = "suggestion"


class BooleanConfigType(BaseModel):
    value: bool
    status: StatusType


class IntegerConfigType(BaseModel):
    value: int
    status: StatusType


class LangVariantConfigType(BaseModel):
    value: List[LangVariantType]
    status: StatusType


class GermanGenderEndingConfigType(BaseModel):
    value: GermanGenderEndingType
    status: StatusType


class GenderedRolesFormatConfigType(BaseModel):
    value: GenderedRolesFormatType
    status: StatusType


class SingularTheyConfigType(BaseModel):
    value: SingularTheyType
    status: StatusType


class RuleConfig(BaseModel):
    store_context: Optional[BooleanConfigType] = None
    preferred_variants: Optional[LangVariantConfigType] = None
    german_gender_ending: Optional[GermanGenderEndingConfigType] = None
    gendered_roles_format: Optional[GenderedRolesFormatConfigType] = None
    categories: Dict[str, BooleanConfigType] = {}
    show_inspiration_alternatives: Optional[BooleanConfigType] = None

    @field_validator("preferred_variants", mode="before")
    @classmethod
    def valid_preferred_variants(cls, v):
        if "value" in v and isinstance(v["value"], str) and v["value"] != "":
            v["value"] = [s.strip() for s in v.split(",")]

        if isinstance(v["value"], list) and v["value"] != []:
            for lang in v["value"]:
                if lang not in Config._supported_locales.default:
                    raise ValueError(
                        "Contains not supported preferred_variants: " + ",".join(v)
                    )

            return v


class Explanation(BaseModel):
    text: str
    icon: Optional[str] = None
    url: Optional[str] = None


class TermReplacement(BaseModel):
    alternatives: List[str]
    explanation: Optional[Explanation] = None
    proficiency_level: Optional[str] = None
    lang: Optional[LangType] = None
    word_type: Optional[str] = None


class DomainType(str, Enum):
    DENY = "deny"
    ALLOW = "allow"


class DomainConfig(BaseModel):
    list: List[str]
    type: DomainType


class ConfRequest(BaseModel):
    id: str
    name: str
    config: RuleConfig
    false_positives: List[str] = []
    term_replacements: Dict[str, TermReplacement] = {}
    domains: Optional[DomainConfig] = None
    config_hash: Optional[str] = None
    sync_date: Optional[str] = None


class UserConfRequest(ConfRequest):
    email: str
    organization_id: Optional[str] = None
    notifications: Optional[int] = None
    has_consented_to_mailing: Optional[bool] = None
    team_analytics: Optional[bool] = None


class OrganizationConfRequest(ConfRequest):
    plan: str


class ConfResponse(BaseModel):
    id: str
    name: str
    plan: Optional[str] = None
    config: RuleConfig
    false_positives: List[str] = []
    term_replacements: Dict[str, TermReplacement] = {}
    domains: Optional[DomainConfig] = None
    config_hash: Optional[str] = None


class UserConfResponse(ConfRequest):
    email: str
    organization_id: Optional[str] = None
    organization_name: Optional[str] = None
    organization_config: Optional[RuleConfig] = None
    organization_false_positives: Optional[List[str]] = []
    organization_term_replacements: Optional[Dict[str, TermReplacement]] = {}
    organization_domains: Optional[DomainConfig] = None
    organization_config_hash: Optional[str] = None
    notifications: Optional[int] = None
    has_consented_to_mailing: Optional[bool] = None
    team_analytics: Optional[bool] = None


class BaseRequestIn(BaseModel):
    client: Optional[str] = None


class RequestIn(BaseRequestIn):
    type: str = "check"
    text: str
    lang: Optional[LangWithAutoType] = LangWithAutoType.AUTO
    id: Optional[str] = None
    config: Optional[Config] = Config()
    config_hash: Optional[str] = None
    organization_config_hash: Optional[str] = None


class ResultAlternative(BaseModel):
    text: Optional[str] = None
    remove: Optional[bool] = None
    inspiration: Optional[bool] = None
    context: Optional[str] = None


class ResultExplanation(BaseModel):
    text: str
    icon: Optional[str] = None
    url: Optional[str] = None
    context: Optional[str] = None
    content: Optional[ContentType] = None


class ResultOut(BaseModel):
    text: str
    lemma: str | None = Field(default=None, exclude=True, title="lemma")
    context: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    start: int
    end: int
    alternatives: Union[List[ResultAlternative], None] = None
    label: Optional[str] = None
    explanation: Optional[ResultExplanation] = None
    gravity: Optional[float] = None
    proficiency_level: Optional[str] = None

    @staticmethod
    def factory(
        config: Config,
        client: namedtuple,
        lang: Language,
        text,
        lemma,
        full_text,
        offsets,
        subcategory,
        start,
        end=None,
        alternatives=None,
        label=None,
        explanation=None,
        url=None,
        icon=None,
        gravity=None,
        explanation_context=None,
        content=None,
        proficiency_level=None,
    ):
        if end is None:
            end = start + len(text)

        context = None
        if config.store_context:
            context_start = max(int(start) - 100, 0)
            context_end = min(int(end) + 100, len(full_text))
            context = full_text[context_start:context_end]

            privacy_filter = get_privacy_filter()
            context = privacy_filter.clean_var(context)

        subcategory_name = get_category_name(subcategory)
        subcategory_data = get_category(subcategory_name)

        if subcategory_data is not None and "category" in subcategory_data:
            category = subcategory_data["category"]
            subcategory_key = subcategory_name
            category_data = subcategory_data
        else:
            subcategory_key = subcategory
            category = subcategory
            category_data = get_category(category)

        if category_data is not None:
            if icon is None and "emoji" in category_data:
                icon = category_data["emoji"]

            if proficiency_level is None and "proficiency_level" in category_data:
                proficiency_level = get_proficiency_level(subcategory_key)

            if category != "orthography":
                label = lang._(subcategory_key, "hs_name")
                category_label = lang._(category, "hs_name")
                if category_label != "" and category_label != label:
                    label = (
                        category_label if label == "" else category_label + ": " + label
                    )

                if lang._(subcategory_key, "lead_video"):
                    content = ContentType("video")
                elif lang._(subcategory_key, "hard_facts"):
                    content = ContentType("advanced")

        if category != "orthography" and category != "corporate_rules" and url is None:
            url = lang._(subcategory, "canonical_url")
            if url is not None and len(url) == 0:
                url = None

            if url is not None and client.name == "web-ext":
                url += "?reducedView=true"

        explanation = (
            explanation if explanation else lang._(subcategory_key, "short_explanation")
        )

        # Not logged-in
        hide_details = config.plan is None

        if hide_details or alternatives is None or len(alternatives) == 0:
            alternatives = []
        else:
            (
                text,
                start,
                alternatives,
                explanation_context,
            ) = ResultOut.clean_alternatives(
                config,
                lang,
                text,
                category,
                subcategory,
                start,
                ResultOut.isUpper(text, full_text, start, category, lang),
                alternatives,
                explanation_context,
                config.alternatives_max_count,
            )

        if category == "orthography":
            label = lang.convert_sharp_ss(label)
            explanation = lang.convert_sharp_ss(explanation)

        explanation = {
            "text": explanation,
            "icon": icon,
            "url": url,
            "context": explanation_context,
            "content": content,
        }

        if hide_details:
            category = None
            subcategory = None
            alternatives = None
            label = None
            explanation = None
        else:
            gravity = map_gravity(subcategory)

        if offsets and len(offsets["chars"]) > end:
            utf16_start = offsets["chars"][start]
            utf16_end = offsets["chars"][end]
        else:
            utf16_start = start
            utf16_end = end

        return ResultOut(
            text=text,
            lemma=lemma,
            context=context,
            category=category,
            subcategory=subcategory,
            start=utf16_start,
            end=utf16_end,
            alternatives=alternatives,
            label=label,
            explanation=explanation,
            gravity=gravity,
            proficiency_level=proficiency_level,
        )

    @staticmethod
    def clean_alternatives(
        config: Config,
        lang: Language,
        text,
        category,
        subcategory,
        start,
        is_upper,
        alternatives,
        explanation_context,
        alternatives_max_count,
    ):
        if alternatives is None:
            return []

        alternatives = list(alternatives)

        # remove empty strings
        if "" in alternatives:
            alternatives.remove("")

        # remove until we can properly handle this in the UI
        # https://www.notion.so/witty-works/Rule-Guidelines-432792da944141b1b4d0a01de290aa43#9ab16aeb0c19416ca0b72fde152b5d86
        if "^" in alternatives:
            alternatives.remove("^")

        prefix = False
        if text.startswith("zu "):
            prefix = "zu "
        elif text.startswith("a "):
            prefix = "a "
        elif text.startswith("an "):
            prefix = "an "

        add_inspiration_alternatives = True
        cleaned_alternatives = {}

        for alternative in alternatives:
            if alternative != " ":
                alternative = alternative.strip()

            # requests for user input are not yet supported
            # https://wittyworks.productboard.com/roadmap/3751070-browser-extension/features/13529555/detail
            if "((" in alternative:
                continue

            (
                alternative,
                alternative_context,
                remove,
            ) = ResultOut.parse_alternative(alternative, category != "orthography")

            if (
                prefix
                and not remove
                and not alternative.startswith(prefix)
                and not ResultOut.isInspirationAlternative(alternative)
            ):
                prefix = False

            if not alternative and not remove:
                if explanation_context is None:
                    explanation_context = alternative_context

                continue

            if category != "orthography":
                if is_upper and alternative:
                    alternative = string.capwords(alternative[0:1]) + alternative[1:]
            else:
                alternative = lang.convert_sharp_ss(alternative)

            if alternative == text:
                continue

            inspiration = None
            if ResultOut.isInspirationAlternative(alternative, subcategory):
                if (
                    not config.show_inspiration_alternatives
                    and not add_inspiration_alternatives
                ):
                    continue

                inspiration = True
                if alternative[-5:] == "(...)":
                    alternative = alternative[0:-5]
                    alternative.strip()

                if alternative_context is None:
                    alternative_context = "💡"

            else:
                add_inspiration_alternatives = False

            alternative_variations = ResultOut.getAlternativeVariations(
                config.gendered_roles_format, config.german_gender_ending, alternative
            )

            for variation in alternative_variations:
                if variation in cleaned_alternatives:
                    continue

                key = variation
                variation = ResultAlternative(
                    text=variation,
                    remove=remove,
                    inspiration=inspiration,
                    context=alternative_context,
                )

                cleaned_alternatives[key] = variation

            if (
                alternatives_max_count is not None
                and len(cleaned_alternatives) >= alternatives_max_count
            ):
                break

        cleaned_alternatives = list(cleaned_alternatives.values())
        if (
            alternatives_max_count is not None
            and len(cleaned_alternatives) >= alternatives_max_count
        ):
            cleaned_alternatives = cleaned_alternatives[0:alternatives_max_count]

        if prefix:
            prefix_length = len(prefix)
            start += prefix_length
            text = text[prefix_length:]
            for cleaned_alternative in cleaned_alternatives:
                if (
                    cleaned_alternative.text is None
                    or cleaned_alternative.remove
                    or cleaned_alternative.inspiration
                ):
                    continue

                cleaned_alternative.text = cleaned_alternative.text[prefix_length:]

        return text, start, cleaned_alternatives, explanation_context

    @staticmethod
    def parse_alternative(alternative, parse_context=True):
        alternative_context = None
        if parse_context and "---" in alternative:
            alternative_split = alternative.split("---")
            if len(alternative_split) == 2:
                alternative = alternative_split[0].strip()
                alternative_context = alternative_split[1].strip()

        if alternative == "-":
            alternative = None
            remove = True
        else:
            remove = None

        return alternative, alternative_context, remove

    @staticmethod
    def isUpper(text, full_text, start, category, lang):
        if category != "orthography" and text[0:1].isupper():
            punctuation = "[.!?:]" if lang.lang == "de" else "[.!?]"

            preceeding_text = full_text[max(0, start - 5) : start]
            if (
                re.search(r"^ *$", preceeding_text) is not None
                or re.search(r"\s{3,}}$", preceeding_text, re.MULTILINE) is not None
                or re.search(punctuation + r"\s*$", preceeding_text, re.MULTILINE)
                is not None
            ):
                return True

        return False

    @staticmethod
    def countWords(text):
        return sum(map(str(text).count, [" ", "-"]))

    @staticmethod
    def isInspirationAlternative(alternative, subcategory=None):
        return (
            alternative is not None
            and subcategory != "abbreviation"
            and (alternative.count("...") > 0)
        )

    @staticmethod
    def getAlternativeVariations(
        gendered_roles_format: GenderedRolesFormatType,
        german_gender_ending: GermanGenderEndingType,
        alternative: str,
    ):
        if alternative and "~" in alternative:
            if gendered_roles_format == GenderedRolesFormatType.NONE:
                return []

            return ResultOut.getGenderedRoleFormatVariations(
                gendered_roles_format, german_gender_ending, alternative
            )

        return [alternative]

    @staticmethod
    def getGenderedRoleFormatVariations(
        gendered_roles_format: GenderedRolesFormatType,
        german_gender_ending: GermanGenderEndingType,
        alternative: str,
    ):
        alternative_variations = []

        alternative = alternative.replace("~ und ~", "~~und~~")
        words = alternative.split()
        variations_count = 1
        for i, word in enumerate(words):
            if "~" in word:
                word = word.replace("~~und~~", "~ und ~")
                words[i] = ResultOut.getGenderedRoles(
                    gendered_roles_format, german_gender_ending, word
                )
                variations_count = max(variations_count, len(words[i]))

        for i in range(0, variations_count):
            alternative_variations.append("")

        for i, word in enumerate(words):
            if isinstance(word, list) and len(word) < variations_count:
                word = word * variations_count

            if not isinstance(word, list) or len(word) < variations_count:
                word = [word] * variations_count

            for v, variation in enumerate(word):
                alternative_variations[v] = alternative_variations[v] + variation
                if i < len(words) - 1:
                    alternative_variations[v] = alternative_variations[v] + " "

        return alternative_variations

    @staticmethod
    def getGenderedRolesFormatBinary(alternative):
        if alternative.count("~") > 1 or alternative.find("~innenschaft") != -1:
            return alternative.replace("~", "")

        return alternative.replace("~", "/")

    @staticmethod
    def getGenderedRolesFormatInclusive(german_gender_ending, alternative):
        variants = alternative.split("~")
        beginning = str(variants[0])
        if str(variants[1]) == "e" and len(variants) == 4 and variants[3][-1] == "r":
            beginning += "e"
            ending = "r"
        else:
            ending = str(variants[1])

        if german_gender_ending == "In":
            if (
                alternative.count("~") > 1
                or (variants[0] and variants[0][0].isupper())
                and len(variants[1]) <= 3
            ):
                ending = ending[0:1].capitalize() + ending[1:]
                separator = ""
            else:
                separator = "/"
        elif german_gender_ending == "/-in":
            separator = "/-" if alternative.count("~") > 1 else "/"
        else:
            separator = german_gender_ending[0:1]

        if len(variants) == 3:
            ending += separator + variants[2]

        return beginning + separator + ending

    @staticmethod
    def genderedRolesFormatInclusive(gendered_roles_format):
        return gendered_roles_format in [
            GenderedRolesFormatType.BOTH,
            GenderedRolesFormatType.INCLUSIVE_GENDER,
        ]

    @staticmethod
    def genderedRolesFormatBinary(gendered_roles_format):
        return gendered_roles_format in [
            GenderedRolesFormatType.BOTH,
            GenderedRolesFormatType.BINARY_GENDER,
        ]

    @staticmethod
    def getGenderedRoles(
        gendered_roles_format: GenderedRolesFormatType,
        german_gender_ending: GermanGenderEndingType,
        alternative,
    ):
        alternative_variations = []
        if ResultOut.genderedRolesFormatInclusive(gendered_roles_format):
            alternative_variations.append(
                ResultOut.getGenderedRolesFormatInclusive(
                    german_gender_ending,
                    alternative,
                )
            )

        if ResultOut.genderedRolesFormatBinary(gendered_roles_format):
            alternative_variation = ResultOut.getGenderedRolesFormatBinary(
                alternative,
            )

            if alternative_variation not in alternative_variations:
                alternative_variations.append(alternative_variation)

        return alternative_variations


class ErrorMessage(BaseModel):
    message: str


class Result(BaseModel):
    detail: List

    @staticmethod
    def factory(detail):
        detail = [
            {
                "loc": [
                    "body",
                    "text",
                ],
                "msg": detail,
                "type": "value_error.not_supported",
            }
        ]

        return Result(detail)

    def __init__(self, detail):
        object.__setattr__(self, "detail", detail)


class ResultConf(BaseModel):
    id: str
    name: str
    plan: Optional[str] = None
    config: Optional[RuleConfig] = None
    organization_id: Optional[str] = None
    organization_name: Optional[str] = None
    organization_config: Optional[RuleConfig] = None
    domains: Optional[DomainConfig] = None
    organization_domains: Optional[DomainConfig] = None
    config_hash: Optional[str] = None
    organization_config_hash: Optional[str] = None


class ResultsOut(BaseModel):
    results: List[ResultOut]
    language: str
    limit_reached: bool = False
    config_changed: Optional[bool] = None
    notifications: Optional[int] = None
    has_consented_to_mailing: Optional[bool] = None


class PrettyJSONResponse(Response):
    media_type = "application/json"

    def render(self, content: typing.Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=4,
            separators=(", ", ": "),
        ).encode("utf-8")
