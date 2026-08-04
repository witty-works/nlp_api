from app.models import (
    LangType,
    LangVariantType,
    Config,
    Client,
    Language,
    EntityType,
    Alternative,
    ResultOut,
    GermanGenderEndingType,
    FrenchGenderSeparatorType,
    WordType,
)
from app.categories import is_sub_category_enabled
from app.http import Http
from app.settings import Settings
from app.db import Db
from app.alternatives_engine import inklusivum
from logging import Logger
from app.helper import upperfirst


class LanguageTool:
    # https://languagetool.org/development/api/org/languagetool/rules/Categories.html
    lt_style_categories_plain_language = [
        "FALSE_FRIENDS",  # rubber vs. eraser
        "REGIONALISMS",  # use of regional terms
        "COLLOQUIALISMS",  # use of slang
        "CONFUSED_WORDS",  # proscribed vs prescribed
        "REDUNDANCY",  # f.e. "tuna fish" https://community.languagetool.org/rule/list?offset=0&max=10&lang=en&filter=&categoryFilter=Redundant+Phrases&_action_list=Filter
        "STYLE",  # https://community.languagetool.org/rule/list?offset=0&max=10&lang=en&filter=&categoryFilter=Style&_action_list=Filter
    ]
    settings: Settings
    logger: Logger
    static_rules: dict
    db: Db
    categories: list
    http: Http

    def __init__(
        self,
        settings: Settings,
        logger: Logger,
        static_rules: dict,
        db: Db,
        categories: list,
        http: Http,
    ):
        self.settings = settings
        self.logger = logger
        self.static_rules = static_rules
        self.db = db
        self.categories = categories
        self.http = http

    async def languagetool_matches(
        self,
        config: Config,
        client: Client,
        language: Language,
        full_text: str,
        ent_spans: list[tuple[int, int, str]],
        offsets: dict,
        matches: list,
    ) -> list:
        list_results = []
        ignore = ["@", "#"]

        gendered_denom = (
            language.lang == LangType.DE
            and Config.gendered_roles_format_inclusive(config.gendered_roles_format)
        )

        for match in matches:
            start = int(match["offset"])
            end = start + int(match["length"])

            if offsets and start in offsets["utf16_chars"]:
                start = offsets["utf16_chars"][start]

            if offsets and end in offsets["utf16_chars"]:
                end = offsets["utf16_chars"][end]

            text = full_text[start:end]

            # Ignore case issues at the start of sentence due to chunking issues
            # https://github.com/witty-works/browser-extension/pull/880
            if match["rule"]["id"] == "DE_CASE":
                preceding_text = full_text[start - 10 : start]
                preceding_text = preceding_text.rstrip(" ")
                # check if before the word there is only spaces and a newline or tab
                if len(preceding_text) and preceding_text[-1] in ["\n", "\t"]:
                    continue

            if match["rule"]["id"] == "WHITESPACE_RULE" and (
                start == 0 or full_text[0:end].isspace()
            ):
                continue

            # Ignore typos on names
            if match["rule"]["category"]["id"] == "TYPOS":
                # Ignore spelling issues on name
                if text[0:1].isupper():
                    is_entity = False
                    for ent_start, ent_end, ent_label in ent_spans:
                        if (
                            ent_start >= start
                            and ent_start < end
                            and ent_end >= end
                        ) or (
                            ent_start <= start
                            and ent_end > start
                            and ent_end <= end
                        ):
                            is_entity = (
                                ent_label
                                in self.static_rules["named_entity_labels"][
                                    EntityType.NAME
                                ]
                            )
                            break

                    if is_entity:
                        continue

                # Ignore capitalization after salutation
                # TODO: Train NER to handle salutations better like "\n Hallo Konstantina\n\nWie geht es dir?"
                subtext = (
                    full_text[0:start]
                    .lstrip()
                    .lower()
                    .replace("'", "")
                    .replace("'", "")
                    .split("\n")
                )
                if len(subtext) == 1 and any(
                    substring.lower() + " " in subtext[0]
                    for substring in self.static_rules[language.lang]["salutations"]
                ):
                    continue

            # Ignore typos on words that are already written in the Inklusivum.
            # Its articles and noun endings are not in any dictionary, so the
            # spell checker reports every one of them.
            if (
                language.lang == LangType.DE
                and config.german_gender_ending == GermanGenderEndingType.INKLUSIVUM
                and match["rule"]["category"]["id"] == "TYPOS"
                and await self.is_inklusivum_form(text)
            ):
                continue

            if language.lang == LangType.FR:
                # Ignore typos in French female noun forms
                if text in self.db.french_feminine_nouns:
                    continue

                # Skip words that look like french gender separator followed up the ending
                if start > 5 and (
                    full_text[start - 1 : start] == config.french_gender_separator[0]
                    or full_text[start : start + 1] == config.french_gender_separator[0]
                ):
                    continue

                # Skip words that look like a word followed by french gender separator
                if (
                    language.lang == LangType.FR
                    and config.french_gender_separator[0]
                    == FrenchGenderSeparatorType.SLASH
                    and len(full_text) >= end
                    and full_text[end : end + 1] == FrenchGenderSeparatorType.SLASH
                    and match["rule"]["id"] == "D_N"
                ):
                    continue

            if (
                language.lang == LangType.DE
                and config.german_gender_ending == GermanGenderEndingType.COLON
                and match["rule"]["id"] == "LEERZEICHEN_HINTER_DOPPELPUNKT"
                and full_text[start + 1 : end]
                in self.static_rules[LangType.DE]["masculine_articles"]
            ):
                continue

            # ignore full_text that starts with @ or #
            if text[0:1] in ignore or (
                start > 0 and full_text[start - 1 : start] in ignore
            ):
                continue

            # ignore german gender ending as spelling mistakes
            if gendered_denom and self.has_gender_denom_ending(
                text, full_text, start, config
            ):
                continue

            try:
                subcategory = match["rule"]["category"]["id"]

                if match["rule"]["id"] in ["SONDERZEICHEN", "ROEMISCHE_ZAHL"]:
                    continue
                elif subcategory in self.lt_style_categories_plain_language:
                    subcategory = "orthography"

                    if match["rule"]["category"]["id"] == "COLLOQUIALISMS":
                        subcategory = "plain_language"
                    elif match["rule"]["category"]["id"] == "STYLE":
                        if match["rule"]["id"] in [
                            "PASSIVE_VOICE_SIMPLE",
                            "PASSIVE_VOICE",
                            "TOO_LONG_SENTENCE",
                            "TOO_LONG_SENTENCE_DE",
                            "TOO_LONG_PARAGRAPH",
                            "INDIAN_ENGLISH",
                            "THREE_NN",
                            "FOUR_NN",
                            "GOTTA",
                            "GONNA_TEMP",
                            "TRYNA",
                            "DONTCHA",
                            "DUNNO",
                            "WANNA",
                            "GOTCHA",
                            "GIMME",
                            "DIS",
                            "DAT",
                            "LUV",
                            "BOUT_TO",
                            "LEMME",
                            "Y_ALL",
                            "WHATCHA",
                        ]:
                            subcategory = "plain_language"
                        elif match["rule"]["id"] in ["PROFANITY_XML", "RUDE_SARCASTIC"]:
                            subcategory = "offensive_language"
                elif subcategory == "PLAIN_ENGLISH":
                    subcategory = "plain_language_advanced"
                elif subcategory == "DIFFICULT_WORDS":
                    if match["rule"]["id"] == "ABKUERZUNG":
                        continue

                    if (
                        match["rule"]["id"] == "ANGLIZISMEN"
                        or "Fremdwörter" in match["message"]
                    ):
                        subcategory = "anglicism_advanced"
                    else:
                        subcategory = "plain_language_advanced"
                elif match["rule"]["category"]["name"] == "Leichte Sprache":
                    subcategory = "plain_language_advanced"
                else:
                    subcategory = subcategory.lower()
                    if subcategory not in self.categories:
                        subcategory = "orthography"
            except KeyError:
                subcategory = "orthography"

            if not is_sub_category_enabled(config.disabled_categories, subcategory):
                continue

            alternatives = self.fetch_alternatives(match)

            label = match["shortMessage"]
            if label == "":
                try:
                    label = match["rule"]["category"]["name"]
                    if language.lang == LangType.FR and label == "style rules":
                        label = "Règles de style"
                    else:
                        label = upperfirst(label)
                except KeyError:
                    pass

            if not subcategory.startswith(
                "abbreviation"
            ) and not subcategory.startswith("anglicism"):
                explanation = match["message"]
            else:
                explanation = None

            list_results.append(
                ResultOut.factory(
                    config,
                    client,
                    language,
                    text,
                    text,
                    full_text,
                    offsets,
                    subcategory,
                    start,
                    end,
                    alternatives,
                    label,
                    explanation,
                )
            )

        return list_results

    async def apply_languagetool_rules(
        self,
        config: Config,
        client: Client,
        language: Language,
        text: str,
        ent_spans: list[tuple[int, int, str]],
        offsets: dict,
    ) -> list:
        if not self.settings.languagetool_api:
            return []

        payload = {
            "text": text,
            "language": language.locale,
            "disabledCategories": [
                "GENDER_NEUTRALITY",  # Handled via Witty rules
            ],
            "enabledCategories": [],
            "disabledRules": [
                # Ignore case issues at the start of sentence due to chunking issues
                # https://github.com/witty-works/browser-extension/pull/880
                "UPPERCASE_SENTENCE_START",
                # Ignore "70%", "100km" needing a space between the unit
                "EINHEIT_LEERZEICHEN",
                # Ignore unpaired brackets like a)
                "EN_UNPAIRED_BRACKETS",
                "UNPAIRED_BRACKETS",
                # People prever to keep using Twitter
                "TWITTER_X",
                # long sentences
                "TOO_LONG_SENTENCE_DE",
                "TOO_LONG_SENTENCE",
                # long words
                "LANGES_WORT",
            ],
        }

        if payload["language"][0:2] == LangType.EN and is_sub_category_enabled(
            config, "plain_language"
        ):
            payload["level"] = "picky"

        if is_sub_category_enabled(
            config.disabled_categories, "plain_language_advanced"
        ):
            if payload["language"] == LangVariantType.deDE:
                payload["language"] += "-x-simple-language"

            if payload["language"][0:2] == LangType.EN:
                payload["enabledCategories"].append("PLAIN_ENGLISH")
        else:
            payload["disabledCategories"].append("PLAIN_ENGLISH")

        if config.primary_language is not None:
            payload["motherTongue"] = config.primary_language

        if is_sub_category_enabled(config.disabled_categories, "orthography"):
            if "casing" in config.disabled_categories:
                payload["disabledCategories"].append("CASING")

            if "plain_language" in config.disabled_categories:
                payload["disabledCategories"] += self.lt_style_categories_plain_language
        elif is_sub_category_enabled(config.disabled_categories, "plain_language"):
            payload["enabledCategories"] += self.lt_style_categories_plain_language
        else:
            return []

        payload = self.convert_to_csv(payload, "disabledCategories")
        payload = self.convert_to_csv(payload, "enabledCategories")
        payload = self.convert_to_csv(payload, "disabledRules")

        # Include optional premium credentials if provided in settings
        try:
            if self.settings.languagetool_username:
                payload["username"] = self.settings.languagetool_username
            if self.settings.languagetool_api_key:
                payload["apiKey"] = self.settings.languagetool_api_key
        except Exception:
            # In case settings are missing attributes for some reason, ignore
            pass

        result = await self.http.fetch_json_post(
            self.settings.languagetool_api + "/check",
            payload,
            {},
            "LanguageTool",
            self.settings.languagetool_verify_ssl,
        )

        if (
            not isinstance(result, dict)
            or "matches" not in result
            or len(result["matches"]) == 0
        ):
            return []

        return await self.languagetool_matches(
            config, client, language, text, ent_spans, offsets, result["matches"]
        )

    def convert_to_csv(self, payload: dict, key: str) -> dict:
        if len(payload[key]):
            payload[key] = ",".join(payload[key])
        else:
            del payload[key]

        return payload

    async def is_inklusivum_form(self, text: str) -> bool:
        """Whether the text is an Inklusivum article, pronoun or noun form.

        Articles and pronouns are a closed set. Nouns are confirmed against
        the lexicon rather than by shape, so that an ordinary misspelling that
        happens to end in -e is still reported.
        """
        if text.lower() in self.static_rules[LangType.DE]["inklusivum_articles"]:
            return True

        exceptions = self.static_rules[LangType.DE]["inklusivum_nouns"]

        for candidate in inklusivum.base_form_candidates(text):
            forms = await self.db.fetch_declensions(
                LangType.DE, WordType.NOUN, candidate
            )
            if not forms:
                continue

            feminine = forms.get("female_form")
            if not feminine:
                continue

            if inklusivum.is_form_of(text, candidate, feminine, exceptions):
                return True

        return False

    def has_gender_denom_ending(
        self, text: str, full_text: str, offset: int, config: Config
    ) -> bool:
        offset_with_text = offset + len(text)
        for ending in config._gendereddenom_ending:
            if full_text[offset_with_text : offset_with_text + len(ending)] == ending:
                return True

            # innen case
            ending = ending + "nen"
            if full_text[offset_with_text : offset_with_text + len(ending)] == ending:
                return True

        return False

    def fetch_alternatives(self, match: dict) -> list[Alternative]:
        """Extract alternatives from a LanguageTool match result.

        Args:
            match: Match dictionary from LanguageTool response

        Returns:
            List of Alternative objects
        """
        alternatives = []
        if "replacements" in match:
            for replacement in match["replacements"]:
                value = replacement["value"] or "-"
                alternatives.append(Alternative(value))

        return alternatives
