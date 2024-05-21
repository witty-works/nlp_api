from pydantic import field_validator, BaseModel
from typing import Optional
from enum import Enum
from collections import namedtuple
import json, typing

from starlette.responses import Response

import string
import re

from eng import TextFixer, Target

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
    def __init__(self, locale: str):
        self.locale = locale
        self.lang = locale[0:2]
        self.gettext = None

    def _(self, category: str, key: str) -> str:
        try:
            category_data = get_category(category)

            lang = "en" if self.lang == "fr" else self.lang
            text = category_data["translations"][lang][key]
            text = self.convert_sharp_ss(text)
        except KeyError:
            text = ""

        return text

    def convert_sharp_ss(self, text: str) -> str:
        if self.locale == LangVariantType.deCH:
            return self.convert_to(text, self.locale)

        return text

    @staticmethod
    def convert_to(
        text: str | list | tuple | None, locale: str | None = None
    ) -> str | list:
        if text is None or locale is None:
            return text

        if not isinstance(text, str):
            return [Language.convert_to(word, locale) for word in text]

        if locale[0:2] == "en":
            target = "uk" if locale == "en-GB" else "us"
            fixer = TextFixer(content=text, target=Target(target))
            return fixer.apply()

        if locale == LangVariantType.deCH:
            return text.replace("ß", "ss")

        return text


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
    FR = "fr"


class BasicWordType(str, Enum):
    VERB = "v"
    ADJECTIVE = "a"
    NOUN = "n"


# https://www.notion.so/witty-works/Rule-Guidelines-432792da944141b1b4d0a01de290aa43#aac0d966bfeb4e33a5a346bba45d5ea8
class WordType(str, Enum):
    VERB = "v"
    ADJECTIVE = "a"
    ADVERB = "adv"
    NOUN = "n"
    PRONOUN = "pron"
    EMOJI = "emoji"
    CONJUNCTION = "conj"
    NUMBER = "num"
    CARDINAL = "card"


class LangWithAutoType(str, Enum):
    AUTO = "auto"
    EN = "en"
    DE = "de"
    FR = "fr"
    deDE = "de-DE"
    deCH = "de-CH"
    deAT = "de-AT"
    enUS = "en-US"
    enGB = "en-GB"
    frFR = "fr-FR"
    frCH = "fr-CH"


class RuleType(str, Enum):
    DEFAULT = "default"
    PREFIX = "prefix"
    SUFFIX = "suffix"
    SUBSTRING = "substring"


class EntityType(str, Enum):
    DEFAULT = "default"
    NAME = "name"
    NON_NAME = "non_name"
    PERSON = "person"
    NON_PERSON = "non_person"
    NUMBER = "number"
    DATETIME = "datetime"


class PluralizationType(str, Enum):
    DEFAULT = "default"
    SINGULAR_ONLY = "singular_only"
    PLURAL_ONLY = "plural_only"


class RuleLabelEnum:
    DEFAULT = "default"
    NOT_FOR_PEOPLE = "not_for_people"
    BE_SPECIFIC = "be_specific"
    NAME_DISABILITY = "name_disability"
    ONLY_IF_GENDER_IDENTITY_RELEVANT = "only_if_gender_identity_relevant"
    NOT_FOR_NON_COMBAT = "not_for_non_combat"
    ASK_FOR_PREFERENCE = "ask_for_preference"
    ASK_ABOUT_TRADITIONS = "ask_about_traditions"
    ONLY_WHEN_REFERENCING_RELIGIOUS_PRACTICE = (
        "only_when_referencing_religious_practice"
    )
    DONT_USE_FOR_SUBSTANCE_USE = "dont_use_for_substance_use"
    DONT_USE_TO_DESCRIBE_QUALITY = "dont_use_to_describe_quality"
    USE_IN_TECH_ONLY = "use_in_tech_only"


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


class GenderedRolesFormatType(str, Enum):
    NONE = "none"
    BOTH = "both"
    INCLUSIVE_GENDER = "inclusive_gender"
    BINARY_GENDER = "binary_gender"


class Alternative:
    lemma: str
    words: Optional[list] = None
    word_types: Optional[list] = None
    type: Optional[str] = None
    label: Optional[str] = None
    pluralization: Optional[PluralizationType] = PluralizationType.DEFAULT
    is_inspiration: Optional[bool] = False
    is_advanced: Optional[bool] = False
    is_collective_noun: Optional[bool] = False
    is_remove: Optional[bool] = False
    is_gendered_noun: Optional[bool] = False
    is_placeholder: Optional[bool] = False

    def __init__(
        self,
        lemma: str,
        words: list = None,
        word_types: list = None,
        is_remove: list = False,
        is_inspiration: list = False,
        is_placeholder: list = False,
        is_advanced: list = False,
        is_collective_noun: list = False,
        is_gendered_noun: list = False,
        label: str | None = None,
    ):
        self.lemma = lemma
        if words is None:
            words = [lemma]
        self.words = words
        if word_types is None or len(word_types) == 0:
            word_types = [
                {"word_type": "", "lower_case": True, "lemmatize": True}
            ] * len(self.words)
        self.word_types = word_types

        self.is_remove = is_remove
        self.is_inspiration = is_inspiration or is_placeholder
        self.is_placeholder = is_placeholder
        self.is_advanced = is_advanced
        self.is_collective_noun = is_collective_noun
        self.is_gendered_noun = is_gendered_noun
        self.label = label


class Rule:
    id: str
    text_id: Optional[str]
    parent_id: Optional[int]
    lang: str
    lemma: str
    words: tuple
    word_types: tuple
    actual_word_types: Optional[str] = None
    subcategories: Optional[list[str]] = []
    is_advanced: bool = False
    alternatives: Optional[list[Alternative]] = []
    false_positives: Optional[list[str]] = None
    explanation: Optional[str] = None
    url: Optional[str] = None
    icon: Optional[str] = None
    type: Optional[RuleType] = RuleType.DEFAULT
    label: Optional[str] = None
    pattern: Optional[str] = None
    is_pattern_match: Optional[bool] = None
    entity_type: Optional[EntityType] = EntityType.DEFAULT
    pluralization: Optional[PluralizationType] = PluralizationType.DEFAULT

    def __init__(
        self,
        id: str,
        lang: str,
        lemma: str,
        words,
        word_types,
        subcategories=None,
        alternatives=None,
        actual_word_types=None,
    ):
        self.id = id
        self.text_id = id
        self.lang = lang
        self.lemma = lemma
        self.words = words
        self.word_types = word_types

        if subcategories is None:
            subcategories = []
        self.subcategories = subcategories
        if alternatives is None:
            alternatives = []

        self.alternatives = alternatives

        if actual_word_types is not None and actual_word_types != "":
            self.actual_word_types = actual_word_types.split("|")

    def get_word_types(self):
        if self.actual_word_types is not None:
            return self.actual_word_types

        word_types = []
        if self.word_types is not None:
            for word_type in self.word_types:
                word_types.append(word_type["word_type"])

        return word_types


class AlternativeIn(BaseModel):
    lemma: str
    word_types: Optional[list] = None
    type: Optional[str] = None
    label: Optional[str] = None
    pluralization: Optional[str] = "default"
    is_inspiration: Optional[bool] = False
    is_gendered_noun: Optional[bool] = False
    is_advanced: Optional[bool] = False
    is_collective_noun: Optional[bool] = False
    is_remove: Optional[bool] = False
    is_placeholder: Optional[bool] = False


class RuleIn(BaseModel):
    text: str
    lang: LangType
    lemma: str
    word_types: list
    actual_word_types: Optional[str] = None
    subcategories: list[str]
    alternatives: Optional[list[AlternativeIn]] = []
    false_positives: Optional[list[str]] = []
    label: Optional[str] = None
    pattern: Optional[str] = None
    is_pattern_match: Optional[bool] = None
    type: Optional[RuleType] = RuleType.DEFAULT
    entity_type: Optional[EntityType] = EntityType.DEFAULT
    pluralization: Optional[PluralizationType] = PluralizationType.DEFAULT
    lemmatizations: Optional[dict[str, str]] = {}


class Config(BaseModel):
    store_context: bool = True
    plan: Optional[str] = None
    addons: Optional[list[str]] = None
    primary_language: Optional[LangVariantType] = None
    preferred_languages: list = [
        LangWithAutoType.EN,
        LangWithAutoType.DE,
        LangWithAutoType.FR,
    ]
    _supported_langs = [
        LangType.DE,
        LangType.EN,
        LangType.FR,
    ]
    preferred_variants: list = [
        LangWithAutoType.enUS,
        LangWithAutoType.deDE,
        LangWithAutoType.frFR,
    ]
    _supported_locales = [
        LangWithAutoType.deDE,
        LangWithAutoType.deCH,
        LangWithAutoType.deAT,
        LangWithAutoType.enUS,
        LangWithAutoType.enGB,
        LangWithAutoType.frFR,
        LangWithAutoType.frCH,
    ]
    german_gender_ending: GermanGenderEndingType = GermanGenderEndingType.STAR
    _gendereddenom_ending = {
        GermanGenderEndingType.STAR: re.compile(
            r"^([A-ZÄÖÜ][a-zäöü]+)\*(innen|in|r|nja|ze|iza|eza)$"
        ),
        GermanGenderEndingType.UNDERSCORE: re.compile(
            r"^([A-ZÄÖÜ][a-zäöü]+)_(innen|in|r|nja|ze|iza|eza)$"
        ),
        GermanGenderEndingType.COLON: re.compile(
            r"^([A-ZÄÖÜ][a-zäöü]+):(innen|in|r|nja|ze|iza|eza)$"
        ),
        GermanGenderEndingType.SLASH: re.compile(
            r"^([A-ZÄÖÜ][a-zäöü]+)/(innen|in|r|nja|ze|iza|eza)$"
        ),
        GermanGenderEndingType.SLASH_DASH: re.compile(
            r"^([A-ZÄÖÜ][a-zäöü]+)/-(innen|in|r|nja|ze|iza|eza)$"
        ),
        GermanGenderEndingType.CAPITAL_LETTER: re.compile(
            r"^([A-ZÄÖÜ][a-zäöü]+)(In(nen)?|R|Nja|Ze)$"
        ),
        GermanGenderEndingType.PARENTHESIS_DASH: re.compile(
            r"^^([A-ZÄÖÜ][a-zäöü]+)\(-(innen|in|r|nja|ze|iza|eza)\)$"
        ),
        GermanGenderEndingType.PARENTHESIS: re.compile(
            r"^([A-ZÄÖÜ][a-zäöü]+)\((innen|in|r|nja|ze|iza|eza)\)$"
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
    disabled_categories: list = []
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


class LangVariantConfigType(BaseModel):
    value: list[LangVariantType]
    status: StatusType


class GermanGenderEndingConfigType(BaseModel):
    value: GermanGenderEndingType
    status: StatusType


class GenderedRolesFormatConfigType(BaseModel):
    value: GenderedRolesFormatType
    status: StatusType


class RuleConfig(BaseModel):
    store_context: Optional[BooleanConfigType] = None
    preferred_variants: Optional[LangVariantConfigType] = None
    german_gender_ending: Optional[GermanGenderEndingConfigType] = None
    gendered_roles_format: Optional[GenderedRolesFormatConfigType] = None
    categories: Optional[dict[str, BooleanConfigType]] = {}
    force_categories: Optional[list[str]] = []
    addons: Optional[list[str]] = None
    show_inspiration_alternatives: Optional[BooleanConfigType] = None

    @field_validator("preferred_variants", mode="before")
    @classmethod
    def valid_preferred_variants(cls, v):
        if v is None:
            return

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
    alternatives: list[str]
    explanation: Optional[Explanation] = None
    proficiency_level: Optional[str] = None
    word_type: Optional[str] = None


class DomainType(str, Enum):
    DENY = "deny"
    ALLOW = "allow"


class DomainConfig(BaseModel):
    list: list[str]
    type: DomainType


class ConfRequest(BaseModel):
    id: str
    name: str
    plan: Optional[str] = None
    config: RuleConfig
    false_positives: list[str] = []
    term_replacements: dict[str, TermReplacement | dict] = {}
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
    trial_ends_at: Optional[str] = None


class ConfResponse(BaseModel):
    id: str
    name: str
    plan: Optional[str] = None
    trial_ends_at: Optional[str] = None
    config: RuleConfig
    false_positives: list[str] = []
    term_replacements: dict[str, TermReplacement] = {}
    domains: Optional[DomainConfig] = None
    config_hash: Optional[str] = None


class UserConfResponse(ConfRequest):
    email: str
    organization_id: Optional[str] = None
    organization_name: Optional[str] = None
    organization_config: Optional[RuleConfig] = None
    organization_false_positives: Optional[list[str]] = []
    organization_term_replacements: Optional[dict[str, TermReplacement]] = {}
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
    text_id: str
    context: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    start: int
    end: int
    alternatives: list[ResultAlternative] | None = None
    label: Optional[str] = None
    explanation: Optional[ResultExplanation] = None
    gravity: Optional[float] = None
    proficiency_level: Optional[str] = None

    @staticmethod
    def factory(
        config: Config,
        client: namedtuple,
        lang: Language,
        text: str,
        text_id: str,
        full_text: str,
        offsets: dict,
        subcategory: str,
        start: int,
        end: int | None,
        alternatives: list[Alternative] | None,
        label: str | None,
        explanation: str | None,
        url: str | None = None,
        icon: str | None = None,
        explanation_context: str | None = None,
        content: str | None = None,
        gravity: float | None = None,
        proficiency_level: str | None = None,
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

        (
            text,
            start,
            alternatives,
        ) = ResultOut.clean_alternatives(
            lang,
            text,
            category,
            start,
            ResultOut.isUpper(text, text_id, full_text, start, category, lang.lang),
            alternatives,
            config.alternatives_max_count,
        )

        if category == "orthography":
            label = lang.convert_sharp_ss(label)
            explanation = lang.convert_sharp_ss(explanation)

        gravity = map_gravity(subcategory) if gravity is None else gravity

        if lang.locale == "en-GB":
            label = Language.convert_to(label, lang.locale)
            explanation = Language.convert_to(explanation, lang.locale)
            explanation_context = Language.convert_to(explanation_context, lang.locale)

        explanation = {
            "text": explanation,
            "icon": icon,
            "url": url,
            "context": explanation_context,
            "content": content,
        }

        if offsets and len(offsets["chars"]) > end:
            utf16_start = offsets["chars"][start]
            utf16_end = offsets["chars"][end]
        else:
            utf16_start = start
            utf16_end = end

        return ResultOut(
            text=text,
            text_id=text_id,
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
        lang: Language,
        text: str,
        category: str,
        start: int,
        is_upper: bool,
        alternatives: list[Alternative],
        alternatives_max_count: int,
    ):
        if alternatives is None:
            return []

        prefix = False
        if text.startswith("zu "):
            prefix = "zu "
        elif text.startswith("a "):
            prefix = "a "
        elif text.startswith("an "):
            prefix = "an "

        cleaned_alternatives = {}

        for alternative in alternatives:
            if alternative.is_remove:
                variation = ResultAlternative(
                    remove=True,
                    context=alternative.label,
                )

                cleaned_alternatives[alternative.lemma] = variation
            else:
                if alternative != " ":
                    alternative.lemma = alternative.lemma.strip()

                if (
                    prefix
                    and not alternative.is_inspiration
                    and not alternative.lemma.startswith(prefix)
                ):
                    prefix = False

                if category != "orthography":
                    if is_upper and alternative.lemma:
                        alternative.lemma = (
                            alternative.lemma[0].upper() + alternative.lemma[1:]
                        )
                elif alternative.lemma is not None:
                    alternative.lemma = lang.convert_sharp_ss(alternative.lemma)

                if alternative.lemma == text:
                    continue

                if alternative.is_inspiration:
                    if (
                        alternative.label is not None
                        and len(alternative.label)
                        and "💡" not in alternative.label
                    ):
                        alternative.label = "💡 " + alternative.label
                    else:
                        alternative.label = "💡"

                variation = ResultAlternative(
                    text=alternative.lemma,
                    inspiration=(True if alternative.is_inspiration else None),
                    context=alternative.label,
                )

                cleaned_alternatives[alternative.lemma] = variation

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

        return text, start, cleaned_alternatives

    @staticmethod
    def isUpper(
        text: str, text_id: str, full_text: str, start: int, category: str, lang: str
    ):
        if category != "orthography" and text[0].isupper():
            if text_id[0].islower():
                return True

            punctuation = "[.!?:]" if lang == LangType.DE else "[.!?]"

            preceeding_text = full_text[max(0, start - 5) : start]
            if (
                re.search(r"^ *$", preceeding_text) is not None
                or re.search(r"\s{3,}}$", preceeding_text, re.MULTILINE) is not None
                or re.search(punctuation + r"\s*$", preceeding_text, re.MULTILINE)
                is not None
            ):
                return True

        return False


class ErrorMessage(BaseModel):
    message: str


class Result(BaseModel):
    detail: list

    @staticmethod
    def factory(detail: str):
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

    def __init__(self, detail: str):
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
    results: list[ResultOut]
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
