"""Sentence-level gendered form builders for alternatives."""

from spacy.tokens import Doc
from app.models import LangType, WordType, GenderedRolesFormatType
from app.alternatives_engine import formatting
from app.alternatives_engine import utils


async def build_sentence_gendered_forms(
    model,
    static_rules: dict,
    lang: LangType,
    sentence_male_tokens: Doc,
    sentence_female_tokens: Doc,
    separator: str,
    noun_separator: str,
    separate_gender_plural: bool,
    article: str | None,
):
    inclusive_form = ""
    binary_form = ""
    male_form_sub_sentence = ""
    female_form_sub_sentence = ""
    sub_sentence_contains_noun = False

    if article:
        article = article.lower()

    for token_index in range(len(sentence_male_tokens)):
        if (
            sentence_male_tokens[token_index].text
            != sentence_female_tokens[token_index].text
        ):
            inclusive_form += formatting.inclusive_alternative(
                static_rules,
                lang,
                sentence_male_tokens[token_index].text,
                sentence_female_tokens[token_index].text,
                "",
                separator,
                noun_separator,
                separate_gender_plural,
            )
            conjunction = (
                static_rules[lang]["noun_conjunction"]["singular"]
                if model.is_token_singular(lang, sentence_male_tokens[token_index])
                else static_rules[lang]["noun_conjunction"]["plural"]
            )
            if lang == LangType.FR:
                if (
                    token_index > 0
                    and sentence_male_tokens[token_index - 1].lemma_
                    in static_rules[lang]["masculine_articles"]
                ):
                    is_noun = True
                    sub_sentence_contains_noun = True
                else:
                    is_noun = (
                        await model._fetch_word_type(
                            lang,
                            sentence_male_tokens[token_index],
                            WordType.NOUN,
                            True,
                            True,
                        )
                        == WordType.NOUN
                    )
                    if sub_sentence_contains_noun == True or is_noun:
                        sub_sentence_contains_noun = True

                if male_form_sub_sentence != "":
                    male_form_sub_sentence += sentence_male_tokens[
                        token_index - 1
                    ].whitespace_
                    female_form_sub_sentence += sentence_female_tokens[
                        token_index - 1
                    ].whitespace_

                male_form_sub_sentence += sentence_male_tokens[token_index].text
                female_form_sub_sentence += (
                    sentence_female_tokens[token_index].text
                    if token_index > 0 or is_noun
                    else sentence_female_tokens[token_index].text.lower()
                )
            else:
                binary_form += (
                    sentence_female_tokens[token_index].text
                    + conjunction
                    + sentence_male_tokens[token_index].text
                )
        else:
            inclusive_form += sentence_male_tokens[token_index].text
            if male_form_sub_sentence != "":
                if sub_sentence_contains_noun:
                    binary_form += (
                        male_form_sub_sentence
                        + conjunction
                        + female_form_sub_sentence
                        + sentence_female_tokens[token_index - 1].whitespace_
                    )
                else:
                    # TODO add user preference to choose male form over female form
                    binary_form += (
                        female_form_sub_sentence
                        + sentence_male_tokens[token_index - 1].whitespace_
                    )
                male_form_sub_sentence = ""
                female_form_sub_sentence = ""
                sub_sentence_contains_noun = False

            binary_form += sentence_male_tokens[token_index].text

        inclusive_form += sentence_male_tokens[token_index].whitespace_

        if male_form_sub_sentence == "":
            binary_form += sentence_male_tokens[token_index].whitespace_

    if male_form_sub_sentence != "":
        if article:
            if article in static_rules[lang]["articles_inclusive_map"]:
                male_article = article
                female_article = article
            if article in static_rules[lang]["masculine_articles"]:
                male_article = article
                female_article = static_rules[lang]["articles_binary_map"][article]
            else:
                male_article = static_rules[lang]["articles_binary_map"][article]
                female_article = article

            male_form_sub_sentence = utils.add_article(
                lang, male_form_sub_sentence, male_article, separator
            )
            female_form_sub_sentence = utils.add_article(
                lang, female_form_sub_sentence, female_article, separator
            )

        binary_form += male_form_sub_sentence + conjunction + female_form_sub_sentence

    if article:
        inclusive_form = utils.add_article(
            lang,
            inclusive_form,
            static_rules[lang]["articles_inclusive_map"][article],
            separator,
        )

    return (
        male_form_sub_sentence,
        female_form_sub_sentence,
        {
            GenderedRolesFormatType.INCLUSIVE_GENDER: inclusive_form,
            GenderedRolesFormatType.BINARY_GENDER: binary_form,
        },
    )
