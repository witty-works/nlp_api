from pydantic import BaseModel, validator
from typing import Dict, List, Optional, Union
from enum import Enum

import json, typing

from starlette.responses import Response

import string
import re

from app.categories import (
    get_proficiency_level,
    get_category,
    get_category_name,
    map_gravity,
    map_importance,
)
from app.privacy_filter import get_privacy_filter


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


class LangGermanVariantType(str, Enum):
    deDE = "de-DE"
    deCH = "de-CH"
    deAT = "de-AT"


class LangEnglishVariantType(str, Enum):
    enUS = "en-US"
    enGB = "en-GB"


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
    CAPITAL_LETTER = "In"
    STR_SLASH = "slash_in"
    STR_SLASH_DASH = "slash_dash_in"
    STR_UNDERSCORE = "underscore_in"
    STR_STAR = "asterisk_in"
    STR_COLON = "colon_in"
    STR_CAPITAL_LETTER = "uppercase_in"


class SingularTheyType(str, Enum):
    HE_OR_SHE = "he_or_she"
    ALL_PRONOUNS = "all_pronouns"


class GenderedRolesFormatType(str, Enum):
    NONE = "none"
    BOTH = "both"
    INCLUSIVE_GENDER = "inclusive_gender"
    BINARY_GENDER = "binary_gender"


class Config(BaseModel):
    store_context: bool = True
    plan: Optional[str]
    primary_language: Optional[LangVariantType]
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
        GermanGenderEndingType.STAR: r"(?i)(\b[a-zäöü]+)\*([a-z]+\b)",
        GermanGenderEndingType.UNDERSCORE: r"(?i)(\b[a-zäöü]+)_([a-z]+\b)",
        GermanGenderEndingType.COLON: r"(?i)(\b[a-zäöü]+):([a-z]+\b)",
        GermanGenderEndingType.SLASH: r"(?i)(\b[a-zäöü]+)/([a-z]+\b)",
        GermanGenderEndingType.SLASH_DASH: r"(?i)(\b[a-zäöü]+)/-([a-z]+\b)",
        GermanGenderEndingType.CAPITAL_LETTER: r"(?i)(\b[a-zäöü]+)([a-z]+\b)",
    }
    disabled_categories: List = []
    gendered_roles_format: GenderedRolesFormatType = GenderedRolesFormatType.BOTH
    show_inspiration_alternatives: bool = False
    alternatives_max_count: Optional[int]

    @validator("german_gender_ending")
    def valid_german_gender_ending(cls, v: str):
        if v not in Config._gendereddenom_ending:
            mapping = {
                GermanGenderEndingType.STR_SLASH: GermanGenderEndingType.SLASH,
                GermanGenderEndingType.STR_SLASH_DASH: GermanGenderEndingType.SLASH_DASH,
                GermanGenderEndingType.STR_UNDERSCORE: GermanGenderEndingType.UNDERSCORE,
                GermanGenderEndingType.STR_STAR: GermanGenderEndingType.STAR,
                GermanGenderEndingType.STR_COLON: GermanGenderEndingType.COLON,
                GermanGenderEndingType.STR_CAPITAL_LETTER: GermanGenderEndingType.CAPITAL_LETTER,
            }

            if v in mapping:
                return mapping[v]

            raise ValueError("Not supported german_gender_ending: " + v)
        return v

    @validator("preferred_languages", pre=True)
    def valid_preferred_languages(cls, v):
        if isinstance(v, str) and v != "":
            v = [s.strip() for s in v.split(",")]

        if isinstance(v, list) and v != []:
            for lang in v:
                if lang not in Config._supported_langs:
                    raise ValueError(
                        "Contains not supported preferred_languages: " + ",".join(v)
                    )

            return v

        return []

    @validator("preferred_variants", pre=True)
    def valid_preferred_variants(cls, v):
        if isinstance(v, str) and v != "":
            v = [s.strip() for s in v.split(",")]

        if isinstance(v, list) and v != []:
            for lang in v:
                if lang not in Config._supported_locales:
                    raise ValueError(
                        "Contains not supported preferred_variants: " + ",".join(v)
                    )

            return v

        return []

    @validator("disabled_categories", pre=True)
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
    store_context: Optional[BooleanConfigType]
    preferred_variants: Optional[LangVariantConfigType]
    german_gender_ending: Optional[GermanGenderEndingConfigType]
    gendered_roles_format: Optional[GenderedRolesFormatConfigType]
    categories: Dict[str, BooleanConfigType] = {}
    # BC code
    inclusive: Optional[BooleanConfigType]
    # BC code
    style: Optional[BooleanConfigType]
    # BC code
    orthography: Optional[BooleanConfigType]
    show_inspiration_alternatives: Optional[BooleanConfigType]

    @validator("german_gender_ending")
    def valid_german_gender_ending(cls, v: str):
        if "value" in v and v["value"] not in Config._gendereddenom_ending:
            raise ValueError("Not supported german_gender_ending")
        return v

    @validator("preferred_variants", pre=True)
    def valid_preferred_variants(cls, v):
        if "value" in v and isinstance(v["value"], str) and v["value"] != "":
            v["value"] = [s.strip() for s in v.split(",")]

        if isinstance(v["value"], list) and v["value"] != []:
            for lang in v["value"]:
                if lang not in Config._supported_locales:
                    raise ValueError(
                        "Contains not supported preferred_variants: " + ",".join(v)
                    )

            return v


class Explanation(BaseModel):
    text: str
    icon: Optional[str]
    url: Optional[str]


class TermReplacement(BaseModel):
    alternatives: List[str]
    explanation: Optional[Explanation]
    proficiency_level: Optional[str]
    lang: Optional[LangType]
    word_type: Optional[str]


class DomainType(str, Enum):
    DENY = "deny"
    ALLOW = "allow"


class DomainConfig(BaseModel):
    list: List[str]
    type: DomainType


class LanguageRequest(BaseModel):
    version: float
    text: str
    client: str
    config: Config
    configs: dict


class GermanLanguageRequest(LanguageRequest):
    locale: LangGermanVariantType


class EnglishLanguageRequest(LanguageRequest):
    locale: LangEnglishVariantType


class ConfRequest(BaseModel):
    id: str
    name: str
    config: RuleConfig
    false_positives: List[str] = []
    term_replacements: Dict[str, TermReplacement] = {}
    domains: Optional[DomainConfig]
    config_hash: Optional[str]
    sync_date: Optional[str]


class UserConfRequest(ConfRequest):
    email: str
    organization_id: Optional[str]
    notifications: Optional[int]
    has_consented_to_mailing: Optional[bool]
    team_analytics: Optional[bool]


class OrganizationConfRequest(ConfRequest):
    plan: str


class ConfResponse(BaseModel):
    id: str
    name: str
    plan: Optional[str]
    config: RuleConfig
    false_positives: List[str] = []
    term_replacements: Dict[str, TermReplacement] = {}
    domains: Optional[DomainConfig]
    config_hash: Optional[str]


class UserConfResponse(ConfRequest):
    email: str
    organization_id: Optional[str]
    organization_name: Optional[str]
    organization_config: Optional[RuleConfig]
    organization_false_positives: Optional[List[str]] = []
    organization_term_replacements: Optional[Dict[str, TermReplacement]] = {}
    organization_domains: Optional[DomainConfig]
    organization_config_hash: Optional[str]
    notifications: Optional[int]
    has_consented_to_mailing: Optional[bool]
    team_analytics: Optional[bool]


class RequestIn(BaseModel):
    type: str = "check"
    text: str
    lang: Optional[LangWithAutoType] = LangWithAutoType.AUTO
    id: Optional[str]
    client: Optional[str]
    config: Optional[Config] = Config()
    config_hash: Optional[str]
    organization_config_hash: Optional[str]


class RequestInEvent(RequestIn):
    type: EventType
    context: Optional[str]
    start: Optional[int]
    end: Optional[int]
    details: Dict[str, str]


class ResultAlternative(BaseModel):
    text: Optional[str]
    remove: Optional[bool]
    inspiration: Optional[bool]
    context: Optional[str]


class ResultExplanation(BaseModel):
    text: str
    icon: Optional[str]
    url: Optional[str]
    context: Optional[str]
    content: Optional[ContentType]


class ResultOut(BaseModel):
    text: str
    context: Optional[str]
    category: Optional[str]
    subcategory: Optional[str]
    start: int
    end: int
    alternatives: Union[List[ResultAlternative], None]
    label: Optional[str]
    explanation: Optional[ResultExplanation]
    gravity: Optional[float]
    proficiency_level: Optional[str]

    @staticmethod
    def factory(
        version: float,
        config: Config,
        lang: Language,
        text,
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
            if url is not None:
                url += "?reducedView=true"

        explanation = (
            explanation if explanation else lang._(subcategory_key, "short_explanation")
        )

        # Not logged-in
        hide_details = config.plan is None

        if hide_details or alternatives is None or alternatives == []:
            alternatives = []
        else:
            if isinstance(alternatives, Dict):
                alternatives = list(alternatives.values())

            (
                text,
                start,
                alternatives,
                explanation_context,
            ) = ResultOut.clean_alternatives(
                version,
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
        version: float,
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
            if alternative == text:
                continue

            # requests for user input are not yet supported
            # https://wittyworks.productboard.com/roadmap/3751070-browser-extension/features/13529555/detail
            if "((" in alternative:
                continue

            (
                alternative,
                alternative_context,
                remove,
            ) = ResultOut.parse_alternative(alternative, category != "orthography")

            if prefix and not remove and not alternative.startswith(prefix):
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

                if alternative_context is None:
                    alternative_context = "💡 Inspiration"

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
                if cleaned_alternative.text is None:
                    continue

                cleaned_alternative.text = cleaned_alternative.text[prefix_length:]

        return text, start, cleaned_alternatives, explanation_context

    @staticmethod
    def parse_alternative(alternative, parse_context=True):
        if parse_context and "---" in alternative:
            alternative, alternative_context = alternative.split("---")
            alternative = alternative.strip()
            alternative_context = alternative_context.strip()
        else:
            alternative_context = None

        if alternative == "-":
            alternative = None
            remove = True
        else:
            remove = None

        return alternative, alternative_context, remove

    @staticmethod
    def isUpper(text, full_text, start, category, lang):
        if category != "orthography" and text[0:1].isupper():
            if lang.lang == "de":
                punctuation = "[.!?:]"
            else:
                punctuation = "[.!?]"

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
            if alternative.count("~") > 1:
                separator = "/-"
            else:
                separator = "/"
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
    plan: Optional[str]
    config: Optional[RuleConfig]
    organization_id: Optional[str]
    organization_name: Optional[str]
    organization_config: Optional[RuleConfig]
    domains: Optional[DomainConfig]
    organization_domains: Optional[DomainConfig]
    config_hash: Optional[str]
    organization_config_hash: Optional[str]


class ResultsOut(BaseModel):
    results: List[ResultOut]
    language: str
    limit_reached: bool
    config_changed: Optional[bool]
    notifications: Optional[int]
    has_consented_to_mailing: Optional[bool]


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
