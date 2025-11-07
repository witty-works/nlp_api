from pydantic import field_validator, BaseModel, Field
from typing import Union, Optional, Annotated, Any
from annotated_types import Len
from enum import Enum
from collections import namedtuple
import json
from cmp_version import VersionString
from functools import lru_cache

from starlette.responses import Response

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

    @classmethod
    def parse(cls, version: Optional[str]) -> "Client":
        if version is None:
            version = "0.0.0"

        name = "web-ext"
        if ":" in version:
            name, version = version.split(":", 2)

        return cls(name=name, version=version)


class Language(object):
    translations = {}

    def __init__(self, locale: str, translations: dict[str, dict[str, str]]):
        self.locale = locale
        self.lang = locale[0:2]
        self.gettext = None
        self.translations = translations

    def _(self, category: str, key: str) -> str:
        try:
            category_data = get_category(category)

            lang = (
                self.lang
                if key in category_data["translations"][self.lang]
                else LangType.EN
            )
            text = category_data["translations"][lang][key]
            text = self.convert_sharp_ss(text)
        except KeyError:
            text = ""

        return text

    def translate(self, key: str):
        try:
            return self.translations[key][self.lang]
        except KeyError:
            return None

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

        if locale[0:2] == LangType.EN:
            target = "uk" if locale == "en-GB" else "us"
            fixer = TextFixer(content=text, target=Target(target))
            return fixer.apply()

        if locale == LangVariantType.deCH:
            return text.replace("ß", "ss")

        return text


class MetricsType(str, Enum):
    ALL = "all"
    AUTH_COUNTS = "auth_counts"
    AUTH_PLANS = "auth_plans"
    AUTH_HOST = "auth_host"
    CHECK_COUNTS = "check_counts"
    CHECK_PLANS = "check_plans"
    CHECK_HOST = "check_host"
    REPHRASE_COUNTS = "rephrase_counts"
    REPHRASE_PLANS = "rephrase_plans"
    REPHRASE_HOST = "rephrase_host"
    PROMPT_COUNTS = "prompt_counts"
    PROMPT_PLANS = "prompt_plans"
    PROMPT_HOST = "prompt_host"


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
    ARTICLE = "article"


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


class ReviewType(str, Enum):
    INCLUDE_PREVIOUS = "include_previous"
    EXPLAIN_EDITS = "explain_edits"
    NO_EXPLANATION = "no_explanation"
    USE_EXPLANATION = "use_explanation"


class RuleType(str, Enum):
    DEFAULT = "default"
    PREFIX = "prefix"
    SUFFIX = "suffix"
    SUBSTRING = "substring"


class AlternativeType(str, Enum):
    DEFAULT = "default"
    PERSON_FIRST = "person_first"
    IDENTITY_FIRST = "identity_first"


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
    frFR = "fr-FR"


class GermanGenderEndingType(str, Enum):
    SLASH = "/in"
    SLASH_DASH = "/-in"
    UNDERSCORE = "_in"
    STAR = "*in"
    COLON = ":in"
    PARENTHESIS_DASH = "(-)"
    PARENTHESIS = "()"
    CAPITAL_LETTER = "In"


class FrenchGenderSeparatorType(str, Enum):
    POINT_MEDIAN = "·"
    POINT_MEDIAN_S = "·s"
    POINT = "."
    POINT_S = ".s"
    SLASH = "/"
    SLASH_S = "/s"


class GenderedRolesFormatBasicType(str, Enum):
    INCLUSIVE_GENDER = "inclusive_gender"
    BINARY_GENDER = "binary_gender"


class GenderedRolesFormatType(str, Enum):
    NONE = "none"
    BOTH = "both"
    INCLUSIVE_GENDER = "inclusive_gender"
    BINARY_GENDER = "binary_gender"


class Lemma:
    lemma: str
    words: tuple
    word_types: tuple

    def __init__(
        self,
        lemma: str,
        words: list = None,
        word_types: list = None,
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

    def get_word_types(self):
        word_types = []
        if self.word_types is not None:
            for word_type in self.word_types:
                word_types.append(word_type["word_type"])

        return word_types

    def get_first_word_type(self):
        word_types = self.get_word_types()
        return word_types[0] if len(word_types) else ""


class Alternative(Lemma):
    type: Optional[AlternativeType] = AlternativeType.DEFAULT
    label: Optional[str] = None
    pluralization: Optional[PluralizationType] = PluralizationType.DEFAULT
    is_inspiration: Optional[bool] = False
    is_advanced: Optional[bool] = False
    is_collective_noun: Optional[bool] = False
    is_remove: Optional[bool] = False
    is_gendered_noun: Optional[bool] = False
    is_placeholder: Optional[bool] = False
    url: Optional[str] = None
    male_form: Optional[str] = None
    female_form: Optional[str] = None
    gender_role: Optional[GenderedRolesFormatBasicType] = None
    is_plural: Optional[bool] = None

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
        super().__init__(lemma, words, word_types)

        self.is_remove = is_remove
        self.is_inspiration = is_inspiration or is_placeholder
        self.is_placeholder = is_placeholder
        self.is_advanced = is_advanced
        self.is_collective_noun = is_collective_noun
        self.is_gendered_noun = is_gendered_noun
        self.label = label


class ResultSource(BaseModel):
    text: str
    url: Optional[str] = None


class Article(BaseModel):
    form: Optional[str] = None
    masculine: Optional[str] = None
    feminine: Optional[str] = None
    neuter: Optional[str] = None
    plural: Optional[str] = None
    inclusive: Optional[str] = None
    fallback: Optional[str] = None

    def get_article(self, gender: str, lemma: str) -> str | None:
        match gender:
            case "masculine":
                return self.masculine
            case "neuter":
                return self.neuter
            case "feminine":
                return self.feminine
            case None:
                return self.fallback

        if lemma.endswith("in"):
            return self.feminine

        return None


class RuleDynamic(BaseModel):
    alternatives: Optional[list] = None
    false_positives: Optional[list[str]] = Field(default_factory=list)
    subcategory: Optional[str] = None
    article: Optional[Article] = None


class Rule(Lemma):
    id: str
    text_id: Optional[str]
    parent_id: Optional[int]
    lang: str
    actual_word_types: Optional[str] = None
    subcategories: Optional[list[str]] = None
    is_advanced: bool = False
    alternatives: Optional[list[Alternative]] = None
    false_positives: Optional[list[str]] = None
    case_sensitive_false_positives: Optional[list[str]] = None
    explanation: Optional[str] = None
    url: Optional[str] = None
    icon: Optional[str] = None
    icon_image: Optional[str] = None
    type: Optional[RuleType] = RuleType.DEFAULT
    label: Optional[str] = None
    label_type: Optional[str] = RuleLabelEnum.DEFAULT
    pattern: Optional[str] = None
    is_pattern_match: Optional[bool] = None
    entity_type: Optional[EntityType] = EntityType.DEFAULT
    pluralization: Optional[PluralizationType] = PluralizationType.DEFAULT
    source: Optional[ResultSource] = None
    adapt_alternatives: bool = False
    dynamic: RuleDynamic = RuleDynamic()

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

        super().__init__(lemma, words, word_types)

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

        return super().get_word_types()

    def reset(self):
        self.dynamic.false_positives = []
        self.dynamic.subcategory = None
        self.dynamic.article = None

    @staticmethod
    def factory(
        language: Language,
        source_map: dict[int, str],
        row: dict,
        rewrite_to: str | None = None,
    ):
        rule = Rule(
            row["id"],
            row["language"],
            row["lemma"],
            json.loads(row["lemma_json"]),
            json.loads(row["word_types_json"]),
            json.loads(row["diversity_dimension_json"]),
            None,
            row["actual_word_types"],
        )

        if rewrite_to:
            rule.lemma = Language.convert_to(rule.lemma, LangVariantType.enGB)
            rule.words = Language.convert_to(rule.words, LangVariantType.enGB)

        rule.text_id = row["text_id"]
        rule.parent_id = row["parent_id"]
        rule.pattern = row["pattern"]
        rule.is_pattern_match = row["is_pattern_match"]
        rule.label = (
            row["label"] if row["label"] else language.translate(row["label_type"])
        )
        rule.label_type = row["label_type"]
        rule.type = row["type"]
        rule.pluralization = row["pluralization"]
        rule.entity_type = row["entity_type"]
        rule.explanation = row["explanation"]
        rule.icon = row["emoji"]
        rule.url = row["url"]

        try:
            rule.source = source_map[row["source_id"]]
        except KeyError:
            pass

        return rule


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


class LemmatizationIn(BaseModel):
    text: str
    lemma: str
    word_type: str


class RuleIn(BaseModel):
    text: str
    lang: LangType
    lemma: str
    word_types: list | dict
    actual_word_types: Optional[str] = None
    subcategories: list[str]
    alternatives: Optional[list[AlternativeIn]] = Field(default_factory=list)
    false_positives: Optional[list[str]] = Field(default_factory=list)
    label: Optional[str] = None
    pattern: Optional[str] = None
    is_pattern_match: Optional[bool] = None
    type: Optional[RuleType] = RuleType.DEFAULT
    entity_type: Optional[EntityType] = EntityType.DEFAULT
    pluralization: Optional[PluralizationType] = PluralizationType.DEFAULT
    lemmatizations: Optional[list[LemmatizationIn]] = Field(default_factory=list)


class Config(BaseModel):
    store_context: bool = True
    llm_alternatives: bool = False
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
            r"^([A-ZÄÖÜ][a-zäöü]+)\(-(innen|in|r|nja|ze|iza|eza)\)$"
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
    french_gender_separator: FrenchGenderSeparatorType = (
        FrenchGenderSeparatorType.POINT_MEDIAN
    )

    disabled_categories: list = Field(default_factory=list)
    gendered_roles_format: GenderedRolesFormatType = GenderedRolesFormatType.BOTH
    show_inspiration_alternatives: bool = False
    alternatives_max_count: Optional[int] = None

    def get_gender_separators_from_config(self, lang: LangType):
        return Config.get_gender_separators(self.get_gender_separator(lang))

    def get_gender_separator(self, lang: LangType):
        if lang == LangType.EN:
            return None

        return (
            self.german_gender_ending
            if lang == LangType.DE
            else self.french_gender_separator
        )

    @staticmethod
    def gendered_roles_format_inclusive(gendered_roles_format: GenderedRolesFormatType):
        return gendered_roles_format in [
            GenderedRolesFormatType.BOTH,
            GenderedRolesFormatType.INCLUSIVE_GENDER,
        ]

    @staticmethod
    def gendered_roles_format_binary(gendered_roles_format: GenderedRolesFormatType):
        return gendered_roles_format in [
            GenderedRolesFormatType.BOTH,
            GenderedRolesFormatType.BINARY_GENDER,
        ]

    @staticmethod
    @lru_cache()
    def get_gender_separators(
        gender_separator: Union[
            GermanGenderEndingType | FrenchGenderSeparatorType | None
        ],
    ):
        if gender_separator is None:
            return "", "", False

        if gender_separator in GermanGenderEndingType._member_map_.values():
            if gender_separator == GermanGenderEndingType.CAPITAL_LETTER:
                separator = "/"
                noun_separator = ""
            else:
                separator = noun_separator = gender_separator[0:-2]
            separate_gender_plural = False
        else:
            separator = noun_separator = gender_separator[0]
            separate_gender_plural = gender_separator.endswith("s")

        return separator, noun_separator, separate_gender_plural

    @staticmethod
    def get_french_noun_separator(french_gender_separator: FrenchGenderSeparatorType):
        return (
            french_gender_separator[0],
            french_gender_separator[0],
            french_gender_separator.endswith("s"),
        )

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


class FrenchGenderSeparatorConfigType(BaseModel):
    value: FrenchGenderSeparatorType
    status: StatusType


class GenderedRolesFormatConfigType(BaseModel):
    value: GenderedRolesFormatType
    status: StatusType


class RuleConfig(BaseModel):
    store_context: Optional[BooleanConfigType] = None
    llm_alternatives: Optional[BooleanConfigType] = None
    preferred_variants: Optional[LangVariantConfigType] = None
    german_gender_ending: Optional[GermanGenderEndingConfigType] = None
    french_gender_separator: Optional[FrenchGenderSeparatorConfigType] = None
    gendered_roles_format: Optional[GenderedRolesFormatConfigType] = None
    categories: Optional[dict[str, BooleanConfigType]] = Field(default_factory=dict)
    force_categories: Optional[list[str]] = Field(default_factory=list)
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


class Image(BaseModel):
    src: str
    width: Optional[int] = None
    height: Optional[int] = None
    alt: Optional[str] = None


class Explanation(BaseModel):
    text: str
    long_text: Optional[str] = None
    video_url: Optional[str] = None
    image_url: Optional[Image] = None
    icon: Optional[str] = None
    icon_image: Optional[str] = None
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
    false_positives: list[str] = Field(default_factory=list)
    term_replacements: dict[str, TermReplacement | dict] = Field(default_factory=dict)
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
    config: RuleConfig
    false_positives: list[str] = Field(default_factory=list)
    term_replacements: dict[str, TermReplacement] = Field(default_factory=dict)
    domains: Optional[DomainConfig] = None
    config_hash: Optional[str] = None


class UserConfResponse(ConfRequest):
    email: str
    organization_id: Optional[str] = None
    organization_name: Optional[str] = None
    organization_config: Optional[RuleConfig] = None
    organization_false_positives: Optional[list[str]] = Field(default_factory=list)
    organization_term_replacements: Optional[dict[str, TermReplacement]] = Field(
        default_factory=dict
    )
    organization_domains: Optional[DomainConfig] = None
    organization_config_hash: Optional[str] = None
    organization_trial_ends_at: Optional[str] = None
    notifications: Optional[int] = None
    has_consented_to_mailing: Optional[bool] = None
    team_analytics: Optional[bool] = None


class BaseRequestIn(BaseModel):
    client: Optional[str] = None
    config: Optional[Config] = Field(default_factory=Config)
    config_hash: Optional[str] = None
    organization_config_hash: Optional[str] = None


class RephraseAlternative(BaseModel):
    text: str
    collective_noun: Optional[bool] = None
    gender_role: Optional[GenderedRolesFormatBasicType] = None
    male_form: Optional[str] = None
    female_form: Optional[str] = None


class RephraseRequestIn(BaseRequestIn):
    type: str = "rephrase"
    model: Optional[str] = None
    sentence: Annotated[str, Len(min_length=1, max_length=300)]
    text: str
    start: int
    alternatives: list[RephraseAlternative]
    gender_separator: Union[
        GermanGenderEndingType | FrenchGenderSeparatorType | None
    ] = None
    lang: LangType


class CheckRequestIn(BaseRequestIn):
    type: str = "check"
    text: str
    lang: Optional[LangWithAutoType] = LangWithAutoType.AUTO
    id: Optional[str] = None


class ResultAlternative(BaseModel):
    text: Optional[str] = None
    remove: Optional[bool] = None
    inspiration: Optional[bool] = None
    collective_noun: Optional[bool] = None
    type: Optional[AlternativeType] = None
    url: Optional[str] = None
    context: Optional[str] = None
    male_form: Optional[str] = None
    female_form: Optional[str] = None
    gender_role: Optional[GenderedRolesFormatBasicType] = None


class ResultExplanation(Explanation):
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
    source: Optional[ResultSource] = None

    @staticmethod
    def factory(
        config: Config,
        client: namedtuple,
        language: Language,
        text: str,
        text_id: str,
        full_text: str,
        offsets: dict,
        subcategory: str,
        start: int,
        end: int | None = None,
        alternatives: list[Alternative] | None = None,
        label: str | None = None,
        explanation: str | None = None,
        url: str | None = None,
        icon: str | None = None,
        explanation_context: str | None = None,
        source: Optional[ResultSource] = None,
        content: str | None = None,
        gravity: float | None = None,
        proficiency_level: str | None = None,
        icon_image: str | None = None,
        long_explanation: str | None = None,
        video_url: str | None = None,
        image_url: str | None = None,
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
            if icon_image is None and "emoji_image" in category_data:
                # If the corporate_rules rule has an emoji set, use that in place of the emoji_image
                icon_image = (
                    category_data["emoji_image"]
                    if subcategory != "corporate_rules" or icon is None
                    else None
                )

            if icon is None and "emoji" in category_data:
                icon = category_data["emoji"]

            if proficiency_level is None and "proficiency_level" in category_data:
                proficiency_level = get_proficiency_level(subcategory_key)

            if category != "orthography":
                label = language._(subcategory_key, "hs_name")
                category_label = language._(category, "hs_name")
                if category_label != "" and category_label != label:
                    label = (
                        category_label if label == "" else category_label + ": " + label
                    )

                if language._(subcategory_key, "lead_video"):
                    content = ContentType("video")
                elif language._(subcategory_key, "hard_facts"):
                    content = ContentType("advanced")

        if category != "orthography" and category != "corporate_rules" and url is None:
            url = language._(subcategory, "canonical_url")
            if url is not None and len(url) == 0:
                url = None

            if (
                url is not None
                and client.name == "web-ext"
                and client.version < VersionString("1.34.0")
            ):
                url += "?reducedView=true"

        explanation = (
            explanation
            if explanation
            else language._(subcategory_key, "short_explanation")
        )

        if category != "orthography":
            long_explanation = (
                long_explanation
                if long_explanation
                else language._(subcategory_key, "sub_head")
            )
            if long_explanation is None or long_explanation == "":
                long_explanation = explanation

            video_url = (
                video_url
                if video_url
                else language._(subcategory_key, "lead_video_url")
            )
            if video_url == "":
                video_url = None

            image_url = (
                image_url if image_url else language._(subcategory_key, "lead_image")
            )
            if not isinstance(image_url, dict):
                image_url = None

        (
            text,
            start,
            alternatives,
        ) = ResultOut.clean_alternatives(
            language,
            text,
            category,
            start,
            ResultOut.isUpper(text, text_id, full_text, start, category, language.lang),
            alternatives,
            config.alternatives_max_count,
        )

        if category == "orthography":
            label = language.convert_sharp_ss(label)
            explanation = language.convert_sharp_ss(explanation)

        gravity = map_gravity(subcategory) if gravity is None else gravity

        if language.locale == "en-GB":
            label = Language.convert_to(label, language.locale)
            explanation = Language.convert_to(explanation, language.locale)
            explanation_context = Language.convert_to(
                explanation_context, language.locale
            )

        explanation = {
            "text": explanation,
            "icon": icon,
            "icon_image": icon_image,
            "url": url,
            "context": explanation_context,
            "content": content,
            "long_text": long_explanation,
            "video_url": video_url,
            "image_url": image_url,
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
            source=source,
        )

    @staticmethod
    def upper_first(text):
        if not text:
            return text

        return text[0].upper() + text[1:]

    @staticmethod
    def clean_alternatives(
        language: Language,
        text: str,
        category: str,
        start: int,
        is_upper: bool,
        alternatives: list[Alternative],
        alternatives_max_count: int,
    ):
        if alternatives is None:
            return text, start, []

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

                if category != "orthography":
                    if is_upper:
                        alternative.lemma = ResultOut.upper_first(alternative.lemma)
                        alternative.male_form = ResultOut.upper_first(
                            alternative.male_form
                        )
                        alternative.female_form = ResultOut.upper_first(
                            alternative.female_form
                        )
                elif alternative.lemma is not None:
                    alternative.lemma = language.convert_sharp_ss(alternative.lemma)

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
                    collective_noun=(
                        True
                        if alternative.is_collective_noun
                        and language.lang == LangType.FR
                        else None
                    ),
                    male_form=alternative.male_form,
                    female_form=alternative.female_form,
                    gender_role=alternative.gender_role,
                )

                if alternative.type != AlternativeType.DEFAULT:
                    variation.type = alternative.type
                    variation.url = alternative.url

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

        return text, start, cleaned_alternatives

    @staticmethod
    def isUpper(
        text: str, text_id: str, full_text: str, start: int, category: str, lang: str
    ):
        if category != "orthography" and text[0].isupper():
            if text_id[0].islower():
                return True

            punctuation = "[.!?:]" if lang == LangType.DE else "[.!?]"

            preceding_text = full_text[max(0, start - 5) : start]
            if (
                re.search(r"^ *$", preceding_text) is not None
                or re.search(r"\s{3,}}$", preceding_text, re.MULTILINE) is not None
                or re.search(punctuation + r"\s*$", preceding_text, re.MULTILINE)
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
    organization_trial_ends_at: Optional[str] = None
    config_hash: Optional[str] = None
    organization_config_hash: Optional[str] = None


class RephrasesOut(BaseModel):
    sentence: str
    results: dict[str, str]

    @staticmethod
    def factory(sentence: str, results: dict[str, str]):
        return RephrasesOut(sentence=sentence, results=results)


class PromptOut(BaseModel):
    check_results: list[ResultOut]
    initial_response: Optional[str] = None
    limit_reached: bool
    reviewed_response: Optional[str] = None


class ResultsOut(BaseModel):
    results: list[ResultOut]
    language: str
    limit_reached: bool = False
    config_changed: Optional[bool] = None
    notifications: Optional[int] = None
    has_consented_to_mailing: Optional[bool] = None
    gender_separator: Union[
        GermanGenderEndingType | FrenchGenderSeparatorType | None
    ] = None


class PrettyJSONResponse(Response):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=4,
            separators=(", ", ": "),
        ).encode("utf-8")
