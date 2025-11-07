"""Text and word type parsing utilities."""

from spacy.tokens import Doc

from app.context import AppContext
from app.models import LangType, WordType
from app.helper import remove_gender_ending


def parse_word_type(word_type: str, lower_case: bool = True) -> tuple[str, bool, bool]:
    lemmatize = True

    if not word_type:
        return "", lower_case, lemmatize

    match word_type[0]:
        case "~":
            # exact match
            lower_case = True
            lemmatize = False
            word_type = word_type[1:]
        case "=":
            # exact match
            lower_case = False
            lemmatize = False
            word_type = word_type[1:]
        case "-":
            # force lower case off
            lower_case = False
            lemmatize = True
            word_type = word_type[1:]

    return word_type, lower_case, lemmatize


async def german_lemmatization(
    tokens: Doc, token_index: int, context: AppContext
) -> str:
    token = tokens[token_index]
    word_type = await context.model.fetch_word_type(LangType.DE, token)

    match word_type:
        case WordType.NOUN:
            if (
                token.text != token.lemma_
                or not token.text[0].isupper()
                or len(token.text) <= 3
            ):
                return token.lemma_

            word = remove_gender_ending(token.text)

            result = await context.nouns.german_noun_lookup(word, token)
            if result is not None:
                target = "male_form" if result["male_form"] else "base_form"
                return result[target]

        case WordType.VERB:
            verb_form = token.morph.get("VerbForm")
            verb_form = verb_form[0] if len(verb_form) else ""

            if verb_form not in context.verb_form_map:
                return token.lemma_

            column_name = False
            if isinstance(context.verb_form_map[verb_form], dict):
                tense = token.morph.get("Tense")
                tense = tense[0] if len(tense) else ""
                person = token.morph.get("Person")
                person = person[0] if len(person) else ""

                if (
                    tense in context.verb_form_map[verb_form]
                    and person in context.verb_form_map[verb_form][tense]
                ):
                    parameters = [token.text + "%"]
                    operator = "LIKE"
                    column_name = context.verb_form_map[verb_form][tense][person]
            else:
                if token_index > 0 and tokens[token_index - 1].text == "zu":
                    parameters = ["zu " + token.text]
                    prev = True
                else:
                    parameters = [token.text]
                    prev = False
                operator = "="
                column_name = context.verb_form_map[verb_form]

            if column_name:
                table_name = context.declensions_config[LangType.DE][WordType.VERB][
                    "name"
                ]
                query = f"SELECT base_form, {column_name} FROM {table_name} WHERE {column_name} {operator} ? LIMIT 1"

                rows = await context.db.fetch_rows(query, parameters)
                if len(rows):
                    if operator == "LIKE":
                        token_index_offset = 1
                        for sentence_token in token.sent:
                            if sentence_token.i > token.i:
                                token_index_offset += 1
                                if (
                                    tokens[token_index].text
                                    + " "
                                    + sentence_token.text.lower()
                                    == rows[0][1]
                                ):
                                    if (
                                        sentence_token.text.lower() == "schwarz"
                                        and token_index_offset > 2
                                    ):
                                        sentence_token._.connected_token = token
                                        token._.child_token = sentence_token
                                        token._.label = sentence_token._.label = (
                                            tokens[token_index].text
                                            + " .. "
                                            + sentence_token.text.lower()
                                        )
                                    else:
                                        token._.token_index_offset = token_index_offset

                                    await context.db.fetch_declensions(
                                        LangType.DE, WordType.VERB, rows[0][0], token
                                    )

                                    token._.form = column_name
                                    if token_index_offset == 2:
                                        token._.text = (
                                            tokens[token_index].text
                                            + tokens[token_index].whitespace_
                                            + sentence_token.text
                                        )
                                    return rows[0][0]
                        return token.lemma_

                    if prev:
                        token._.start = tokens[token_index - 1].idx
                        token._.text = (
                            tokens[token_index - 1].text
                            + tokens[token_index - 1].whitespace_
                            + tokens[token_index].text
                        )
                        token._.form = column_name

                    await context.db.fetch_declensions(
                        LangType.DE, WordType.VERB, rows[0][0]
                    )
                    return rows[0][0]

    return token.lemma_
