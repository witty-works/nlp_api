from app.models import (
    Rule,
    Language,
    LangType,
    RuleType,
    Client,
    Alternative,
    AlternativeType,
    BasicWordType,
    LangVariantType,
    ResultSource,
)
from app.helper import is_addon_enabled, is_gender_star_ending, upperfirst
from app.categories import get_category_name
from app.query_definitions import (
    declensions_config,
    alternative_columns,
    alternative_column_list,
    rule_columns,
    rule_column_list,
)
from app.settings import Settings
import aiosqlite
import json
from spacy.tokens import Token
from copy import deepcopy


class Db:
    sqlite_db: aiosqlite.Connection
    male_to_female_normativ: dict
    substring_rules: dict = {}
    source_map: dict = {}
    male_to_female_normativ: dict = {}
    person_words: dict = {}
    misc_words: dict = {}
    french_feminine_nouns: dict = {}
    word_type_lemmas: dict = {}

    def __init__(
        self,
        sqlite_db: aiosqlite.Connection,
        languages: dict[LangType, Language],
    ):
        self.sqlite_db = sqlite_db
        self.languages = languages

    @staticmethod
    async def factory(settings: Settings, languages: dict[LangType, Language]):
        in_memory_url = "file:db?mode=memory&cache=shared&uri=true"
        sqlite_db = await aiosqlite.connect(in_memory_url, check_same_thread=False)

        query = (
            "SELECT name FROM sqlite_master WHERE type='table' AND name='rules_rule'"
        )
        cursor = await sqlite_db.execute(query)
        tables_exist = await cursor.fetchall()
        await cursor.close()

        if len(tables_exist) == 0:
            if settings.import_from_dump:
                await sqlite_db.executescript(open("./database/dump.sql", "r").read())
            else:
                source = await aiosqlite.connect("./database/db.sqlite3")
                await source.backup(sqlite_db)
                await source.close()

        db = Db(sqlite_db, languages)
        await db.init(settings)

        return db

    async def init(self, settings: Settings):
        query = f"SELECT base_form, plural FROM rules_frenchnoun WHERE male_form IS NOT NULL"
        rows = await self.fetch_rows(query)

        for row in rows:
            self.french_feminine_nouns[row[0]] = None
            self.french_feminine_nouns[row[1]] = None

        query = (
            f"SELECT id, citation, url FROM rules_source WHERE is_citation_shown = 1"
        )
        rows = await self.fetch_rows(query)

        for row in rows:
            self.source_map[row[0]] = ResultSource(text=row[1], url=row[2])

        for model_name in settings.models:
            lang = model_name[0:2]

            self.substring_rules[lang] = {}
            self.word_type_lemmas[lang] = {
                BasicWordType.NOUN: {},
                BasicWordType.VERB: {},
                BasicWordType.ADJECTIVE: {},
            }
            self.person_words[lang] = []
            self.misc_words[lang] = []

            query = f"SELECT {rule_column_list} FROM rules_rule WHERE language = ? and type = ? ORDER BY lemma_length DESC, first_is_word_type_lemmatize ASC"
            parameters = [lang, RuleType.SUBSTRING]
            rows = await self.fetch_rows(query, parameters)

            for row in rows:
                row = dict(zip(rule_columns, row))
                rule = Rule.factory(self.languages[lang], self.source_map, row)
                rule.false_positives = await self.fetch_false_positives(rule)
                self.substring_rules[lang][rule.lemma.lower()] = rule

                rewrite_to = (
                    LangVariantType.enGB
                    if lang == LangType.EN
                    else LangVariantType.deCH
                )
                rewritten_lemma = Language.convert_to(rule.lemma, rewrite_to)
                if rule.lemma != rewritten_lemma:
                    rule = Rule.factory(lang, self.source_map, row, rewrite_to)
                    rule.false_positives = await self.fetch_false_positives(
                        rule, rewrite_to
                    )
                    self.substring_rules[lang][rule.lemma.lower()] = rule

            if lang in declensions_config:
                query = f"SELECT LOWER(base_form) FROM {declensions_config[lang][BasicWordType.NOUN]["name"]} WHERE ner IN (?, ?)"
                parameters = ["person", "group"]
                rows = await self.fetch_rows(query, parameters)

                for row in rows:
                    self.person_words[lang].append(row[0])

                query = f"SELECT LOWER(base_form) FROM {declensions_config[lang][BasicWordType.NOUN]["name"]} WHERE ner = ?"
                parameters = ["misc"]
                rows = await self.fetch_rows(query, parameters)

                for row in rows:
                    self.misc_words[lang].append(row[0])

                if lang == LangType.DE:
                    query = f"SELECT base_form, female_form FROM {declensions_config[lang][BasicWordType.NOUN]["name"]} WHERE female_form IS NOT NULL"
                    rows = await self.fetch_rows(query)

                    for row in rows:
                        self.male_to_female_normativ[row[0]] = row[1]

            query = "SELECT text, lemma, word_type FROM rules_lemmatization WHERE language = ?"
            parameters = [lang]
            rows = await self.fetch_rows(query, parameters)
            for row in rows:
                self.word_type_lemmas[lang][row[2]][row[0]] = row[1]

    async def close(self):
        await self.sqlite_db.close()

    async def fetch_rows(self, query, parameters=None) -> list:
        cursor = await self.sqlite_db.execute(query, parameters)
        rows = await cursor.fetchall()
        await cursor.close()

        return rows

    async def fetch_false_positives(
        self, rule: Rule, rewrite_to: str | None = None
    ) -> list[str]:
        if len(rule.dynamic.false_positives):
            return rule.dynamic.false_positives

        if rule.false_positives is not None:
            return rule.false_positives

        query = "SELECT false_positive FROM rules_falsepositive WHERE rule_id = ?"
        parameters = [rule.id]

        false_positives = []
        rows = await self.fetch_rows(query, parameters)
        for row in rows:
            false_positives.append(row[0])
            if rewrite_to:
                false_positive = Language.convert_to(row[0], rewrite_to)
                if row[0] != false_positive:
                    false_positives.append(false_positive)

        return false_positives

    async def fetch_rules(
        self,
        language: Language,
        token: Token,
        text: str,
        lemma: str,
        addons: list[str],
        suffix_check: bool = False,
        rewrite_to: str | None = None,
    ) -> list[Rule]:
        female_lemma_filter = None

        if suffix_check:
            upper_char_count = sum(1 for c in text if c.isupper())
            # Elite-Partner (match) vs. ElitePartner (name -> ignore)
            if upper_char_count > 1 and text.count("-") < upper_char_count - 1:
                return []

            first_token_check = "first_token LIKE ?"
            text_filter = "%" + text[-4:]
            lemma_filter = "%" + lemma[-4:]
        else:
            first_token_check = "first_token = ?"
            text_filter = text
            lemma_filter = lemma

            if lemma in self.male_to_female_normativ:
                female_lemma_filter = self.male_to_female_normativ[lemma]

        token_filter_lower = text_filter.lower()
        lemma_filter_lower = lemma_filter.lower()

        if text == lemma:
            if token_filter_lower == text_filter:
                filters = {
                    first_token_check: text_filter,
                }
            else:
                filters = {
                    f"({first_token_check} and first_is_word_type_lower_case = 1)": token_filter_lower,
                    f"({first_token_check} and first_is_word_type_lower_case = 0)": text_filter,
                }
        else:
            if text_filter == token_filter_lower:
                filters = {
                    f"({first_token_check} AND first_is_word_type_lemmatize = 0)": text_filter,
                }
            else:
                filters = {
                    f"({first_token_check} AND first_is_word_type_lemmatize = 0 AND first_is_word_type_lower_case = 1)": token_filter_lower,
                    f"({first_token_check} AND first_is_word_type_lemmatize = 0 AND first_is_word_type_lower_case = 0)": text_filter,
                }

            if lemma_filter == lemma_filter_lower:
                filters[
                    f"({first_token_check} AND first_is_word_type_lemmatize = 1)"
                ] = lemma_filter
            else:
                filters[
                    f"({first_token_check} AND first_is_word_type_lemmatize = 1 AND first_is_word_type_lower_case = 1)"
                ] = lemma_filter_lower
                filters[
                    f"({first_token_check} AND first_is_word_type_lemmatize = 1 AND first_is_word_type_lower_case = 0)"
                ] = lemma_filter

        if female_lemma_filter is not None:
            filters[f"({first_token_check} AND first_is_word_type_lemmatize = 1)"] = (
                female_lemma_filter.lower()
            )

        query = f"SELECT {rule_column_list} FROM rules_rule WHERE language = ? AND type = ? AND diversity_dimension_json != '[]'"
        if not is_addon_enabled("hr", addons):
            query += " AND is_hr_rule = 0"

        filter_list = " OR ".join(filters.keys())
        query += f" AND ({filter_list})ORDER BY (CASE WHEN json_array_length(lemma_json) > 1 THEN lemma_length ELSE 0 END) DESC, first_word_type DESC, lemma_length DESC, first_is_word_type_lemmatize ASC"
        parameters = [
            language.lang,
            RuleType.SUFFIX if suffix_check else RuleType.DEFAULT,
        ] + list(filters.values())

        is_gender_star_ending_ = False
        rows = await self.fetch_rows(query, parameters)
        if language.lang == LangType.EN:
            if rewrite_to is None and len(rows) == 0:
                rewrite_to = "en-US"
                us_text = Language.convert_to(text, rewrite_to)
                if us_text != text:
                    return await self.fetch_rules(
                        language,
                        token,
                        us_text,
                        Language.convert_to(lemma, rewrite_to),
                        addons,
                        suffix_check,
                        "en-US",
                    )
        elif language.lang == LangType.DE:
            is_gender_star_ending_ = is_gender_star_ending(token.text)
            if not suffix_check and is_gender_star_ending_ and len(rows) == 0:
                new_text = is_gender_star_ending_[1] + is_gender_star_ending_[2]
                if new_text != text:
                    rules = await self.fetch_rules(
                        language, token, new_text, new_text, addons
                    )
                    if len(rules):
                        token.lemma_ = new_text

                    return rules

        rules = []
        for row in rows:
            rule = Rule.factory(
                language, self.source_map, dict(zip(rule_columns, row)), rewrite_to
            )
            if is_gender_star_ending_ and self.is_gendered_denom_rule(
                language.lang, rule.subcategories
            ):
                continue
            rules.append(rule)

        if suffix_check:
            text_lower = token.text.lower()
            for substring in self.substring_rules[language.lang]:
                if substring in text_lower:
                    rules.append(self.substring_rules[language.lang][substring])

        return rules

    async def fetch_rule_alternatives(
        self,
        client: Client,
        language: Language,
        rule: Rule,
        is_singular: bool | None,
        show_inspiration_alternatives: bool,
    ) -> list[Alternative]:
        if isinstance(rule.id, str):
            if rule.dynamic.alternatives is None:
                return rule.alternatives
            return deepcopy(rule.dynamic.alternatives)

        query = (
            f"SELECT {alternative_column_list} FROM rules_alternative WHERE rule_id = ?"
        )

        parameters = [rule.parent_id if rule.parent_id else rule.id]

        if not show_inspiration_alternatives:
            query += " and is_inspiration = 0"
            query += " and is_placeholder = 0"

        # TODO ignore pluralization for inspirations?
        if is_singular is not None:
            query += " and pluralization != ?"
            parameters.append("plural_only" if is_singular else "singular_only")

        query += " ORDER BY `order` ASC"

        alternatives = []
        rows = await self.fetch_rows(query, parameters)
        if len(rows) == 0:
            if not show_inspiration_alternatives:
                return await self.fetch_rule_alternatives(
                    client, language, rule, is_singular, True
                )
            if is_singular is not None:
                return await self.fetch_rule_alternatives(
                    client, language, rule, None, True
                )

        rule.adapt_alternatives = False
        for row in rows:
            lemma = row[alternative_columns["lemma"]]
            # remove until we can properly handle this in the UI
            # https://www.notion.so/witty-works/Rule-Guidelines-432792da944141b1b4d0a01de290aa43#9ab16aeb0c19416ca0b72fde152b5d86
            if "^" in lemma:
                continue

            if row[alternative_columns["is_remove"]]:
                lemma = None
                lemma_json = ()
                word_types_json = ()
            else:
                lemma_json = json.loads(row[alternative_columns["lemma_json"]])
                word_types_json = json.loads(
                    row[alternative_columns["word_types_json"]]
                )

            if lemma and language.locale == LangVariantType.enGB:
                lemma = Language.convert_to(lemma, language.locale)
                lemma_json = Language.convert_to(lemma_json, language.locale)

            alternative = Alternative(
                lemma,
                lemma_json,
                word_types_json,
                row[alternative_columns["is_remove"]],
                row[alternative_columns["is_inspiration"]],
                row[alternative_columns["is_placeholder"]],
                row[alternative_columns["is_advanced"]],
                row[alternative_columns["is_collective_noun"]],
                row[alternative_columns["is_gendered_noun"]],
                row[alternative_columns["label"]],
            )

            if row[alternative_columns["type"]] == AlternativeType.DEFAULT:
                alternative.type = AlternativeType.DEFAULT
            elif row[alternative_columns["type"]] == AlternativeType.PERSON_FIRST:
                alternative.type = AlternativeType.PERSON_FIRST
                if alternative.label is None or len(alternative.label) == 0:
                    alternative.label = language.translate("PERSONFIRST")
                alternative.url = language.translate("IDENTITYVSPERSONURL")
            elif row[alternative_columns["type"]] == AlternativeType.IDENTITY_FIRST:
                alternative.type = AlternativeType.IDENTITY_FIRST
                if alternative.label is None or len(alternative.label) == 0:
                    alternative.label = language.translate("IDENTITYFIRST")
                alternative.url = language.translate("IDENTITYVSPERSONURL")

            alternatives.append(alternative)
            if not alternative.is_remove or not alternative.is_inspiration:
                rule.adapt_alternatives = True

        return alternatives

    async def fetch_declensions(
        self,
        lang: LangType,
        word_type: BasicWordType,
        text: str,
        token: Token | None = None,
    ) -> dict | None:
        if lang == LangType.FR and word_type != BasicWordType.NOUN:
            return None

        if token is not None and token._.forms is not None:
            return token._.forms

        text = (
            upperfirst(text)
            if lang == LangType.DE and word_type == BasicWordType.NOUN
            else text.lower()
        )

        columns = declensions_config[lang][word_type]["columns"]
        column_list = ", ".join(columns)
        table_name = declensions_config[lang][word_type]["name"]

        filters = []
        parameters = []
        for column in columns:
            if column in [
                "is_absolute",
                "gender_1",
                "gender_2",
                "collective_noun",
                "collective_noun_2",
                "female_form",
                "male_form",
                "helping_verb",
            ]:
                continue

            filters.append(f"{column} = ? COLLATE NOCASE")
            parameters.append(text)

        parameters.append(text)
        filter_list = " OR ".join(filters)

        query = f"SELECT {column_list} FROM {table_name} WHERE {filter_list} ORDER BY IIF(base_form = ?, 1, 0) DESC, LENGTH(base_form) DESC LIMIT 1"

        rows = await self.fetch_rows(query, parameters)

        forms = None if len(rows) == 0 else dict(zip(columns, rows[0]))
        if token is not None:
            token._.forms = forms

        return forms

    def is_gendered_denom_rule(self, lang: LangType, subcategories) -> bool:
        if lang != LangType.DE:
            return False

        if isinstance(subcategories, str):
            return get_category_name(subcategories) in [
                "titles",
                "function",
                "gender_identity",
                "hidden_image",
                "leadership",
                "male_stereotype",
                "female_stereotype",
                "gendered_denominations_ending",
            ]

        for subcategory in subcategories:
            if self.is_gendered_denom_rule(lang, subcategory):
                return True

        return False
