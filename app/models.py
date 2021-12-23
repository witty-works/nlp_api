from numpy import array
from pydantic import BaseModel, validator
from typing import Dict, List
from typing import Optional
from enum import Enum

import gettext
import string


class Lang(object):
    def __init__(self, locale):
        self.locale = locale[0:2]

        if self.locale == "en":
            trans_locale = "en_GB"
        else:
            trans_locale = "de_DE"

        language = gettext.translation(
            "messages", localedir="locales", languages=[trans_locale]
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


class GenderedRolesFormatType(str, Enum):
    BOTH = "both"
    INCLUSIVE_GENDER = "inclusive_gender"
    BINARY_GENDER = "binary_gender"


class Config(BaseModel):
    store_context: Optional[bool] = True
    primary_language: Optional[str] = "de-DE"
    preferred_languages: Optional[str] = "de,en"
    preferred_variants: Optional[str] = "de-DE,en-GB"
    german_gender_ending: Optional[str] = ":in"
    _gendereddenom_ending = {
        "/in": "/in",
        "/-in": "/-in",
        "_in": "_in",
        "*in": "\\*in",
        ":in": ":in",
        "In": r"In\b",
    }
    disabled_categories: Optional[List] = []
    gendered_roles_format: Optional[
        GenderedRolesFormatType
    ] = GenderedRolesFormatType.BOTH

    @validator("german_gender_ending")
    def valid_german_gender_ending(cls, v: str):
        if v not in cls._gendereddenom_ending:
            raise ValueError("Not supported german_gender_ending")
        return v

    @validator("disabled_categories", pre=True)
    def split_string_values(cls, v):
        if isinstance(v, str):
            return v.split(",")
        return v


class ForcedConfig(BaseModel):
    store_context: Optional[bool]
    primary_language: Optional[str]
    preferred_languages: Optional[str]
    preferred_variants: Optional[str]
    german_gender_ending: Optional[str]
    _gendereddenom_ending = {
        "/in": "/in",
        "/-in": "/-in",
        "_in": "_in",
        "*in": "\\*in",
        ":in": ":in",
        "In": r"In\b",
    }
    disabled_categories: Optional[List]
    gendered_roles_format: Optional[GenderedRolesFormatType]

    @validator("german_gender_ending")
    def valid_german_gender_ending(cls, v: str):
        if v not in cls._gendereddenom_ending:
            raise ValueError("Not supported german_gender_ending")
        return v

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
        lang: Lang,
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

        label = label if label != None else lang._("rules." + category + "_label")
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

        # remove '-' if multiple alternatives are provided
        # until https://github.com/witty-works/browser-extension/issues/189 is implemented
        if len(alternatives) > 1 and alternatives[0] != "-" and "-" in alternatives:
            alternatives.remove("-")

        rewrite_to_swiss_german = False
        if (
            lang.locale == "de"
            and "de-CH" in config.preferred_variants
            and config.preferred_variants.find("de-CH")
            <= config.preferred_variants.find("de")
        ):
            rewrite_to_swiss_german = True

        rewrite_to_british = False
        if (
            lang.locale == "en"
            and "en-GB" in config.preferred_variants
            and config.preferred_variants.find("en-GB")
            <= config.preferred_variants.find("en")
        ):
            rewrite_to_british = True

        cleaned_alternatives = []
        for i, alternative in enumerate(alternatives):
            if is_upper and category != "orthography":
                alternative = string.capwords(alternative[0:1]) + alternative[1:]

            if rewrite_to_swiss_german:
                alternative = alternative.replace("ß", "ss")

            if rewrite_to_british:
                alternative = alternative.replace("color", "colour")

            if "~" in alternative:
                if config.gendered_roles_format == "binary_gender":
                    alternative = alternative.replace("~", "")
                else:
                    variants = alternative.split("~")
                    if str(variants[1]) == "e":
                        alternative = (
                            str(variants[0])
                            + "e"
                            + config.german_gender_ending[0:-2]
                            + "r"
                        )
                    else:
                        alternative = (
                            str(variants[0])
                            + config.german_gender_ending[0:-2]
                            + str(variants[1])
                        )

                    cleaned_alternatives.append(alternative)

                    if config.gendered_roles_format == "both":
                        alternative = alternatives[i].replace("~", "")

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


class ResultsOut(BaseModel):
    results: List[ResultOut]
    language: str

    def factory(results, lang):
        return ResultsOut(results, lang.locale)

    factory = staticmethod(factory)

    def __init__(self, results, language):
        object.__setattr__(self, "results", results)
        object.__setattr__(self, "language", language)
