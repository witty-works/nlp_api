"""A gender ending does not make a word too long to read.

The plain language check flags words of more than 18 characters, or with a
part of more than 12. The ending of a gendered form (`·rices`, `:innen`) is
no part of the word to read; the star form, which the tokenizer splits off,
was never counted.
"""

import pytest

from app.rule_processors import is_too_long_word


@pytest.mark.parametrize(
    "word",
    ["Administrator:innen", "Administrator_innen", "administrateur·rices", "administrateur·rice·s"],
)
def test_a_gendered_form_is_measured_without_its_ending(word):
    assert not is_too_long_word(word)


@pytest.mark.parametrize(
    "word",
    ["Diversitätsdimensionen", "Diversitätsbeauftragte:r", "Wiederherstellungscodes"],
)
def test_a_long_word_is_still_too_long(word):
    assert is_too_long_word(word)


def test_a_short_word_is_not(word="Lehrer:innen"):
    assert not is_too_long_word(word)
