from app.models import Config, Client, Language, Alternative, ResultOut, LangType
from app.categories import is_sub_category_enabled
from app.settings import Settings

from logging import Logger
from spacy.tokens import Doc
from cmp_version import VersionString
import emoji
import re


class EmojiCheck:
    def __init__(self, settings: Settings, logger: Logger, static_rules: dict):
        self.settings = settings
        self.logger = logger
        self.static_rules = static_rules

    def get_emoji(self, emoji_text: str) -> str:
        return emoji.emojize(f":{emoji_text}:", language="alias")

    def get_emoji_context(self, alternative: str, lang: LangType) -> str:
        return (
            emoji.demojize(alternative, language=lang)
            .replace(":", "")
            .replace("_", " ")
            .title()
        )

    def handle(
        self,
        config: Config,
        client: Client,
        language: Language,
        static_rules: dict,
        full_text: str,
        token_index: int,
        tokens: Doc,
        offsets: dict,
        list_full: list,
    ) -> list:
        if (
            client.name == "web-ext"
            and client.version != "0.0.0"
            and client.version < VersionString("1.28.0.1")
        ):
            return token_index

        token = tokens[token_index]
        if not token._.is_emoji:
            return token_index

        token_count = len(tokens)

        # 👨🏽‍👩🏽‍👧🏽 case https://github.com/carpedm20/emoji/issues/204
        if (
            token_index + 1 < token_count
            and tokens[token_index + 1].text.endswith("\u200d")
        ) or (token_index > 0 and tokens[token_index - 1].text.endswith("\u200d")):
            return token_index

        alternatives = []
        explanation_context = self.get_emoji_context(token.text, language.lang)

        emoji_description = token._.emoji_desc
        emoji_base = re.sub(r"\b[-a-z]+\b skin tone", "", emoji_description)

        emoji_base = emoji_base.strip().replace(" ", "_")

        subcategory = None
        for emoji_config_name in static_rules["emoji"]:
            emoji_config = static_rules["emoji"][emoji_config_name]
            included = False
            for rule in emoji_config["rules"]:
                if rule in emoji_base:
                    included = rule
                    break

            if not included:
                continue

            emojis = []
            for subcategory in emoji_config["subcategory"]:
                if is_sub_category_enabled(config.disabled_categories, subcategory):
                    emojis += emoji_config["subcategory"][subcategory]

            if len(emojis) == 0:
                continue

            if (
                "skin_tone" not in emoji_base
                and emoji_config["skin_tone"]
                and len(emojis) <= 3
            ):
                skin_tones = (
                    static_rules["skin_tones"]["full"]
                    if len(emojis) == 1
                    else static_rules["skin_tones"]["minimal"]
                )
            else:
                skin_tones = []

            for alternative_text in emojis:
                if alternative_text == "-":
                    alternative = Alternative("-")
                    alternative.is_remove = True
                    alternatives.append(alternative)

                    continue

                alternative_text = emoji_base.replace(rule, alternative_text)
                alternative = self.get_emoji(alternative_text)

                # if person is not available, then check of "woman" is available
                if ":" in alternative and emoji_config_name == "person_gender":
                    alternative_text = emoji_base.replace(rule, "woman")
                    alternative = self.get_emoji(alternative_text)

                if ":" not in alternative and alternative != token.text:
                    alternative = Alternative(alternative)
                    alternative.label = self.get_emoji_context(
                        alternative.lemma, language.lang
                    )
                    alternatives.append(alternative)

            for alternative_text in emojis:
                alternative_text = emoji_base.replace(rule, alternative_text)

                for skin_tone in skin_tones:
                    alternative_skin_tone_text = alternative_text + skin_tone
                    alternative = self.get_emoji(alternative_skin_tone_text)

                    # if person is not available, then check of "woman" is available
                    if ":" in alternative and emoji_config_name == "person_gender":
                        alternative_skin_tone_text = (
                            emoji_base.replace(rule, "woman") + skin_tone
                        )
                        alternative = self.get_emoji(alternative_skin_tone_text)

                    if ":" not in alternative and alternative != token.text:
                        alternative = Alternative(alternative)
                        alternative.label = self.get_emoji_context(
                            alternative.lemma, language.lang
                        )
                        alternatives.append(alternative)

            if len(alternatives) == 1:
                continue

            # match found
            break

        if len(alternatives) == 0 and "skin tone" in emoji_description:
            subcategory = "culture"
            for skin_tone in static_rules["skin_tones"]["all"]:
                alternative = self.get_emoji(emoji_base + skin_tone)
                if ":" not in alternative and alternative != token.text:
                    alternative = Alternative(alternative)
                    alternative.label = self.get_emoji_context(
                        alternative.lemma, language.lang
                    )
                    alternatives.append(alternative)

        explanation = (
            language.translate("EMOJISKINTONE")
            if "skin tone" in emoji_description
            else None
        )

        if subcategory and len(alternatives) >= 1:
            list_full.append(
                ResultOut.factory(
                    config,
                    client,
                    language,
                    token.text,
                    token.text,
                    full_text,
                    offsets,
                    subcategory,
                    token.idx,
                    None,
                    alternatives,
                    None,
                    explanation,
                    None,
                    None,
                    explanation_context,
                )
            )

            return token_index + 1

        if token_index + 1 < len(tokens):
            subcategory = explanation = None
            emoji_index = token_index
            while emoji_index + 1 < len(tokens) and (
                tokens[emoji_index + 1]._.is_emoji
                or tokens[emoji_index + 1].text.endswith("\u200d")
            ):
                emoji_index += 1

                if token.text == tokens[emoji_index].text:
                    subcategory = "ability"
                    explanation = language.translate("EMOJIREPETITION")
                elif explanation is not None:
                    emoji_index -= 1
                    break

            if subcategory is None and emoji_index >= token_index + 1:
                subcategory = (
                    "ability" if emoji_index >= token_index + 2 else "ability_advanced"
                )

                explanation = language.translate("EMOJIOVERUSE")

            if subcategory is not None and is_sub_category_enabled(
                config.disabled_categories, subcategory
            ):
                text = token.text
                for text_index in range(token_index, emoji_index):
                    text += tokens[text_index].whitespace_ + tokens[text_index + 1].text

                alternatives = [
                    Alternative(token.text),
                    Alternative("-", None, None, True),
                ]

                list_full.append(
                    ResultOut.factory(
                        config,
                        client,
                        language,
                        text,
                        text,
                        full_text,
                        offsets,
                        subcategory,
                        token.idx,
                        None,
                        alternatives,
                        None,
                        explanation,
                    )
                )

                return emoji_index + 1

        return token_index
