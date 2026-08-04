import pytest

from app.dee_articles import generate_dee_inclusive


@pytest.mark.parametrize(
    "form,masc,fem,expected",
    [
        ("nominativ", "der", "die", "de"),
        ("genitiv", "des", "der", "ders"),
        ("dativ", "dem", "der", "derm"),
        ("nominativ", "ein", "eine", "ein"),
        ("genitiv", "eines", "einer", "einers"),
        ("dativ", "einem", "einer", "einerm"),
        ("nominativ", "jeder", "jede", "jedey"),
        ("genitiv", "jedes", "jeder", "jeders"),
        ("dativ", "jedem", "jeder", "jederm"),
        ("nominativ", "unser", "unsre", "unse"),
        ("genitiv", "unsres", "unsrer", "unsers"),
        ("dativ", "unsrem", "unsrer", "unserm"),
        ("dativ", "zum", "zur", "zurm"),
    ],
)
def test_generate_dee_inclusive(form, masc, fem, expected):
    got = generate_dee_inclusive(form, masc, fem)
    assert got == expected
