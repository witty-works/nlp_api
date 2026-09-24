"""French articles in front of a suggested noun."""

import pytest

from app.alternatives_engine.utils import add_article
from app.models import LangType


@pytest.mark.parametrize(
    "article,noun,expected",
    [
        ("la·le", "étudiant·e", "l'étudiant·e"),
        ("le", "économiste", "l'économiste"),
        ("la", "Île", "l'Île"),
        ("la·le", "enseignant·e", "l'enseignant·e"),
        ("la·le", "directeur·rice", "la·le directeur·rice"),
    ],
)
def test_le_and_la_are_elided_before_a_vowel(article, noun, expected):
    assert add_article(LangType.FR, noun, article, "·") == expected


def test_the_article_takes_the_configured_separator():
    assert add_article(LangType.FR, "directeur/rice", "la·le", "/") == (
        "la/le directeur/rice"
    )
