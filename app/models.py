from pydantic import BaseModel, validator
from typing import Dict, List
from typing import Optional
from enum import Enum

import gettext
import string


class Language(object):
    def __init__(self, locale):
        self.locale = locale
        self.lang = locale[0:2]

        language = gettext.translation(
            "messages", localedir="locales", languages=[locale.replace("-", "_")]
        )

        language.install()

        self.gettext = language.gettext

    def _(self, message: str, placeholders={}):
        message = self.gettext(message)

        for key in placeholders:
            message = message.replace("%" + key, placeholders[key])

        return message


class EventType(str, Enum):
    CHECK = "check"
    IGNORE = "ignore"
    ALTERNATIVE = "alternative"
    ERROR = "error"


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


class GermanGenderEnding(str, Enum):
    SLASH = "/in"
    SLASH_DASH = "/-in"
    UNDERSCORE = "_in"
    STAR = "*in"
    COLON = ":in"
    CAPITAL_LETTER = "In"


class SingularThey(str, Enum):
    HE_OR_SHE = "he_or_she"
    ALL_PRONOUNS = "all_pronouns"


class GenderedRolesFormatType(str, Enum):
    BOTH = "both"
    INCLUSIVE_GENDER = "inclusive_gender"
    BINARY_GENDER = "binary_gender"


class Config(BaseModel):
    store_context: Optional[bool] = True
    primary_language: str = LangWithAutoType.deDE
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
    german_gender_ending: str = GermanGenderEnding.COLON
    _gendereddenom_ending = {
        GermanGenderEnding.SLASH: "/in",
        GermanGenderEnding.SLASH_DASH: "/-in",
        GermanGenderEnding.UNDERSCORE: "_in",
        GermanGenderEnding.STAR: "\\*in",
        GermanGenderEnding.COLON: ":in",
        GermanGenderEnding.CAPITAL_LETTER: r"In\b",
    }
    disabled_categories: List = []
    gendered_roles_format: GenderedRolesFormatType = GenderedRolesFormatType.BOTH
    singular_they: str = SingularThey.HE_OR_SHE

    @validator("german_gender_ending")
    def valid_german_gender_ending(cls, v: str):
        if v not in Config._gendereddenom_ending:
            raise ValueError("Not supported german_gender_ending: " + v)
        return v

    @validator("primary_language", pre=True)
    def valid_primary_language(cls, v):
        if v not in Config._supported_locales:
            raise ValueError("Not supported primary_language: " + v)
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


class ForcedConfig(BaseModel):
    store_context: Optional[bool]
    primary_language: Optional[str]
    preferred_languages: Optional[List]
    preferred_variants: Optional[List]
    german_gender_ending: Optional[str]
    disabled_categories: Optional[List]
    gendered_roles_format: Optional[GenderedRolesFormatType]
    singular_they: Optional[str]

    @validator("german_gender_ending")
    def valid_german_gender_ending(cls, v: str):
        if v not in Config._gendereddenom_ending:
            raise ValueError("Not supported german_gender_ending")
        return v

    @validator("primary_language", pre=True)
    def valid_primary_language(cls, v):
        if v not in Config._supported_locales:
            raise ValueError("Not supported primary_language: " + v)
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
    def split_string_values(cls, v):
        if isinstance(v, str):
            return v.split(",")
        return v


class ConfRequest(BaseModel):
    organization: str
    users: list
    forced: ForcedConfig
    suggestion: Config
    false_positive: Optional[list] = []


class RequestIn(BaseModel):
    type: str = "check"
    text: str
    lang: Optional[LangWithAutoType] = "auto"
    id: Optional[str] = None
    client: Optional[str] = None
    config: Optional[Config] = Config()


class RequestInEvent(RequestIn):
    type: EventType
    context: Optional[str]
    start: Optional[int]
    end: Optional[int]
    details: Dict[str, str]


class ResultOut(BaseModel):
    text: str
    context: str
    category: str
    subcategory: str
    start: int
    end: int
    alternatives: List[str]
    label: str
    reason: str
    solution: str

    def factory(
        config: Config,
        lang: Language,
        text,
        full_text,
        category,
        subcategory,
        start,
        end=None,
        alternatives=[],
        label=None,
        reason=None,
        solution=None,
        explanation=None,
    ):
        if end == None:
            end = start + len(text)

        if config.store_context:
            context_start = max(int(start) - 100, 0)
            context_end = min(int(end) + 100, len(full_text))
            context = full_text[context_start:context_end]
        else:
            context = ""

        params = {}
        if subcategory == "gendered_denominations_ending":
            params["gendered_denominations_ending"] = config.german_gender_ending

        label = label if label else lang._("rules." + category + "_label")
        if category != subcategory:
            label += ": " + lang._("rules." + subcategory + "_label")

        reason = (
            reason
            if reason != None
            else lang._("rules." + subcategory + "_reason", params)
        )
        solution = (
            solution
            if solution != None
            else lang._("rules." + subcategory + "_solution", params)
        )
        explanation = (
            explanation
            if explanation != None
            else lang._("rules." + subcategory + "_explanation", params)
        )

        is_upper = text[0:1].isupper()

        if isinstance(alternatives, Dict):
            alternatives = list(alternatives.values())

        # remove empty strings
        if "" in alternatives:
            alternatives.remove("")

        # remove until we can properly handle this in the UI
        # https://www.notion.so/witty-works/Rule-Guidelines-432792da944141b1b4d0a01de290aa43#9ab16aeb0c19416ca0b72fde152b5d86
        if "^" in alternatives:
            alternatives.remove("^")

        cleaned_alternatives = []
        for i, alternative in enumerate(alternatives):
            if is_upper and category != "orthography":
                alternative = string.capwords(alternative[0:1]) + alternative[1:]

            if lang.locale == "de-CH":
                alternative = alternative.replace("ß", "ss")

            if "~" in alternative:
                if config.gendered_roles_format in ["both", "inclusive_gender"]:
                    cleaned_alternatives.append(
                        ResultOut.getGenderedRolesFormatInclusive(
                            alternative,
                            config.german_gender_ending,
                        )
                    )

                if config.gendered_roles_format in ["both", "binary_gender"]:
                    cleaned_alternatives.append(
                        ResultOut.getGenderedRolesFormatBinary(
                            alternative,
                        )
                    )
            else:
                cleaned_alternatives.append(alternative)

        return ResultOut(
            text,
            context,
            category,
            subcategory,
            start,
            end,
            cleaned_alternatives,
            label,
            reason,
            solution,
            explanation,
        )

    factory = staticmethod(factory)

    def __init__(
        self,
        text,
        context,
        category,
        subcategory,
        start,
        end,
        alternatives,
        label,
        reason,
        solution,
        explanation,
    ):
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "context", context)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "subcategory", subcategory)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "alternatives", alternatives)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "solution", solution)
        object.__setattr__(self, "explanation", explanation)

    @staticmethod
    def getGenderedRolesFormatBinary(alternative):
        if alternative.count("~") > 1 or alternative.find("~innenschaft") != -1:
            return alternative.replace("~", "")

        return alternative.replace("~", "/")

    @staticmethod
    def getGenderedRolesFormatInclusive(alternative, german_gender_ending):
        variants = alternative.split("~")
        beginning = str(variants[0])
        if str(variants[1]) == "e":
            beginning += "e"
            ending = "r"
        else:
            ending = str(variants[1])

        if german_gender_ending == "In":
            if alternative.count("~") > 1:
                ending = ending.capitalize()
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

        return beginning + separator + ending


class Result(BaseModel):
    detail: List

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

    factory = staticmethod(factory)

    def __init__(self, detail):
        object.__setattr__(self, "detail", detail)


class ResultsOut(BaseModel):
    results: List[ResultOut]
    language: str
    limit_reached: bool

    def factory(results, lang, limit_reached=False):
        if lang != None:
            lang = lang.lang

        return ResultsOut(results, lang, limit_reached)

    factory = staticmethod(factory)

    def __init__(self, results, language, limit_reached):
        object.__setattr__(self, "results", results)
        object.__setattr__(self, "language", language)
        object.__setattr__(self, "limit_reached", limit_reached)
