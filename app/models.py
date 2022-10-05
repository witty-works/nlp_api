from pydantic import BaseModel, validator
from typing import Dict, List, Optional, Union
from enum import Enum

import gettext
import string
import re
import math

from app.categories import categories
from app.settings import get_settings
from app.privacy_filter import get_privacy_filter


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
    store_context: Optional[bool] = True
    simple_language: Optional[bool] = False
    hide_details: Optional[bool] = False
    primary_language: Optional[LangWithAutoType]
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
        GermanGenderEndingType.STAR: r"\s(\S+)(\*in)",
        GermanGenderEndingType.UNDERSCORE: r"\s(\S+)(_in)",
        GermanGenderEndingType.COLON: r"\s(\S+)(:in)",
        GermanGenderEndingType.SLASH: r"\s(\S+)(/in)",
        GermanGenderEndingType.SLASH_DASH: r"\s(\S+)(/-in)",
        GermanGenderEndingType.CAPITAL_LETTER: r"\s(\S+)(In\b)",
    }
    disabled_categories: List = []
    gendered_roles_format: GenderedRolesFormatType = GenderedRolesFormatType.BOTH
    singular_they: str = SingularTheyType.HE_OR_SHE
    show_inspiration_alternatives: Optional[bool] = False
    maximum_importance: float = 2.0

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

    @validator("primary_language", pre=True)
    def valid_primary_language(cls, v):
        if v and v not in Config._supported_locales:
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

    # This is a quick fix, in principle we should adjust the model singular_they: SingularTheyType = SingularTheyType.HE_OR_SHE
    # and then also update the browser extension https://github.com/witty-works/browser-extension/pull/423
    @validator("singular_they", pre=True)
    def valid_singular_they(cls, v):
        if isinstance(v, bool):
            if v:
                return SingularTheyType.ALL_PRONOUNS

            return SingularTheyType.HE_OR_SHE
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
    simple_language: Optional[BooleanConfigType]
    preferred_variants: Optional[LangVariantConfigType]
    german_gender_ending: Optional[GermanGenderEndingConfigType]
    gendered_roles_format: Optional[GenderedRolesFormatConfigType]
    inclusive: Optional[BooleanConfigType]
    style: Optional[BooleanConfigType]
    orthography: Optional[BooleanConfigType]
    singular_they: Optional[SingularTheyConfigType]
    show_inspiration_alternatives: Optional[BooleanConfigType]
    maximum_importance: Optional[IntegerConfigType]

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
    gravity: Optional[float]


class TermReplacement1_1(BaseModel):
    term: str
    alternatives: List[str]
    explanation: Optional[Explanation]
    gravity: Optional[int]


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
    domains: Optional[DomainConfig]
    config_hash: Optional[str]
    notifications: Optional[int]
    has_consented_to_mailing: Optional[bool]


class ConfRequest1_1(BaseModel):
    id: str
    name: str
    plan: str
    users: List[str]
    config: RuleConfig
    false_positives: List[str] = []
    term_replacements: List[TermReplacement1_1] = []


class UserConfRequest(ConfRequest):
    email: str
    organization_id: Optional[str]


class OrganizationConfRequest(ConfRequest):
    plan: str


class RequestIn(BaseModel):
    type: str = "check"
    text: str
    lang: Optional[LangWithAutoType] = "auto"
    id: Optional[str] = None
    client: Optional[str] = None
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

    @staticmethod
    def factory(
        version: float,
        config: Config,
        lang: Language,
        text,
        full_text,
        category,
        subcategory,
        start,
        end=None,
        alternatives=None,
        anchor=None,
        explanation=None,
        url=None,
        icon=None,
        gravity=None,
        explanation_context=None,
    ):
        if end == None:
            end = start + len(text)

        context = None
        if config.store_context:
            context_start = max(int(start) - 100, 0)
            context_end = min(int(end) + 100, len(full_text))
            context = full_text[context_start:context_end]

            privacy_filter = get_privacy_filter()
            context = privacy_filter.clean_var(context)

        params = {}
        if subcategory == "gendered_denominations_ending":
            params["gendered_denominations_ending"] = config.german_gender_ending

        anchor = anchor if anchor else lang._("rules." + category + "_anchor")
        sub_anchor = None

        if subcategory in categories:
            category_key = subcategory
        else:
            category_key = category

        if category != "orthography" and category != "corporate_rules":
            if category != subcategory:
                sub_anchor = lang._("rules." + subcategory + "_anchor")

            if url == None:
                settings = get_settings()
                url = (
                    settings.learning_bites_base_url
                    + "/"
                    + lang.lang
                    + "/"
                    + ("categories" if lang.lang == "en" else "kategorien")
                    + "/"
                    + anchor
                )

                if sub_anchor != None:
                    url += "#" + sub_anchor

        label = ResultOut.reverseTransliterate(anchor, lang)
        if sub_anchor != None and anchor != sub_anchor:
            label += ": " + ResultOut.reverseTransliterate(sub_anchor, lang)

        explanation = (
            explanation
            if explanation
            else lang._("rules." + category_key + "_explanation")
        )

        if icon == None and "emoji" in categories[category_key]:
            icon = categories[category_key]["emoji"]

        gravity = gravity if gravity != None else categories[category_key]["gravity"]

        if (config.hide_details and version >= 2.1) or alternatives == None:
            alternatives = []
        else:
            if isinstance(alternatives, Dict):
                alternatives = list(alternatives.values())

            (alternatives, explanation_context) = ResultOut.clean_alternatives(
                version,
                config,
                lang,
                text,
                category,
                subcategory,
                ResultOut.isUpper(text, full_text, start, category, lang),
                alternatives,
                explanation_context,
            )

        if category == "orthography":
            explanation = ResultOut.convert_sharp_ss(lang, explanation)

        explanation = {
            "text": explanation,
            "icon": icon,
            "url": url,
            "context": explanation_context,
        }

        if version <= 1.1:
            if gravity != None:
                gravity = math.ceil(gravity)

            return ResultOut1_1(
                text=text,
                context=context,
                category=category,
                subcategory=subcategory,
                start=start,
                end=end,
                alternatives=alternatives,
                label=label,
                explanation=explanation,
                gravity=gravity,
            )

        if config.hide_details and version >= 2.1:
            category = None
            subcategory = None
            alternatives = None
            label = None
            explanation = None
            gravity = None

        return ResultOut(
            text=text,
            context=context,
            category=category,
            subcategory=subcategory,
            start=start,
            end=end,
            alternatives=alternatives,
            label=label,
            explanation=explanation,
            gravity=gravity,
        )

    @staticmethod
    def clean_alternatives(
        version: float,
        config: Config,
        lang: Language,
        text,
        category,
        subcategory,
        is_upper,
        alternatives,
        explanation_context,
    ):
        # remove empty strings
        if "" in alternatives:
            alternatives.remove("")

        # remove until we can properly handle this in the UI
        # https://www.notion.so/witty-works/Rule-Guidelines-432792da944141b1b4d0a01de290aa43#9ab16aeb0c19416ca0b72fde152b5d86
        if "^" in alternatives:
            alternatives.remove("^")

        add_inspiration_alternatives = True
        cleaned_alternatives = {}
        for alternative in alternatives:
            if alternative == text:
                continue

            # requests for user input are not yet supported
            # https://wittyworks.productboard.com/roadmap/3751070-browser-extension/features/13529555/detail
            if "((" in alternative:
                continue

            alternative_context = None
            remove = None
            if category != "orthography":
                if "---" in alternative:
                    alternative, alternative_context = alternative.split("---")
                    alternative = alternative.strip()
                    alternative_context = alternative_context.strip()
                    if alternative == "":
                        if explanation_context == None:
                            explanation_context = alternative_context

                        continue

                if is_upper:
                    alternative = string.capwords(alternative[0:1]) + alternative[1:]
            else:
                alternative = ResultOut.convert_sharp_ss(lang, alternative)

            if alternative == "-" and version >= 1.1:
                alternative = None
                remove = True

            inspiration = None
            if ResultOut.isInspirationAlternative(text, alternative, subcategory):
                if (
                    not config.show_inspiration_alternatives
                    and not add_inspiration_alternatives
                ):
                    continue

                inspiration = True
            else:
                add_inspiration_alternatives = False

            alternative_variations = ResultOut.getAlternativeVariations(
                config.gendered_roles_format, config.german_gender_ending, alternative
            )

            for variation in alternative_variations:
                if variation in cleaned_alternatives:
                    continue

                key = variation
                if version >= 1.1:
                    variation = ResultAlternative(
                        text=variation,
                        remove=remove,
                        inspiration=inspiration,
                        context=alternative_context,
                    )

                cleaned_alternatives[key] = variation

        return list(cleaned_alternatives.values()), explanation_context

    @staticmethod
    def convert_sharp_ss(lang, text):
        if lang.locale != "de-CH":
            return text

        return text.replace("ß", "ss")

    @staticmethod
    def isUpper(text, full_text, start, category, lang):
        if category != "orthography" and text[0:1].isupper():
            if lang.lang == "de":
                punctuation = "[.!?:]"
            else:
                punctuation = "[.!?]"

            preceeding_text = full_text[max(0, start - 5) : start]
            if (
                re.search(r"^ *$", preceeding_text) != None
                or re.search(r"\s{3,}}$", preceeding_text, re.MULTILINE) != None
                or re.search(punctuation + r"\s*$", preceeding_text, re.MULTILINE)
                != None
            ):
                return True

        return False

    @staticmethod
    def reverseTransliterate(string, lang):
        string = string.replace("_", " ")

        if lang.lang == "en":
            return string.capitalize()

        return string.title().replace("ue", "ü").replace("ae", "ä").replace("oe", "ö")

    @staticmethod
    def countWords(text):
        return sum(map(str(text).count, [" ", "-"]))

    @staticmethod
    def isInspirationAlternative(text, alternative, subcategory=None):
        return (
            alternative != None
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


class ResultOut1_1(ResultOut):
    gravity: Optional[int]


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


class ResultConf1_1(BaseModel):
    id: str
    name: str
    plan: Optional[str]
    config: Optional[RuleConfig]


class ResultConf(ResultConf1_1):
    organization_id: Optional[str]
    organization_name: Optional[str]
    organization_config: Optional[RuleConfig]
    domains: Optional[DomainConfig]
    organization_domains: Optional[DomainConfig]
    config_hash: Optional[str]
    organization_config_hash: Optional[str]


class ResultsOut1_1(BaseModel):
    results: List[ResultOut1_1]
    language: str
    limit_reached: bool
    organization_config: Union[ResultConf1_1, dict, None]


class ResultsOut(BaseModel):
    results: List[ResultOut]
    language: str
    limit_reached: bool
    config_changed: Optional[bool]
    notifications: Optional[int]
    has_consented_to_mailing: Optional[bool]
