"""bin/install_spacy_models.py: the pinned spaCy model wheels outside the lock."""

import json
import re

import pytest

from bin import install_spacy_models as script


def test_every_pinned_wheel_has_its_own_url_and_a_hash():
    pins = json.load(open("bin/spacy-models.json"))["models"]

    assert set(pins) == {
        f"{lang}_{kind}_{size}"
        for lang, kind in (("en", "core_web"), ("de", "core_news"), ("fr", "core_news"))
        for size in ("sm", "md", "lg")
    }
    for name, pin in pins.items():
        assert pin["url"].endswith(f"/{name}-3.8.0/{name}-3.8.0-py3-none-any.whl")
        assert re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])


def test_the_default_is_the_three_large_models():
    assert script.select("en,de,fr", "lg") == [
        "en_core_web_lg",
        "de_core_news_lg",
        "fr_core_news_lg",
    ]


def test_a_selection_keeps_the_language_order_and_the_size():
    assert script.select(" fr , en ", "sm") == ["en_core_web_sm", "fr_core_news_sm"]


@pytest.mark.parametrize(
    "langs,size,message",
    [("en", "xl", "sm, md or lg"), ("", "lg", "no models"), ("es", "lg", "es")],
)
def test_a_bad_selection_is_refused(langs, size, message):
    with pytest.raises(SystemExit, match=message):
        script.select(langs, size)


def test_the_requirements_pin_each_wheel_by_hash(tmp_path):
    requirements = tmp_path / "models.txt"
    names = tmp_path / "names.txt"

    script.main(
        [
            "--langs", "de",
            "--size", "md",
            "--requirements-out", str(requirements),
            "--models-out", str(names),
        ]
    )  # fmt: skip

    pin = json.load(open("bin/spacy-models.json"))["models"]["de_core_news_md"]
    assert requirements.read_text() == (
        f"de_core_news_md @ {pin['url']} --hash=sha256:{pin['sha256']}\n"
    )
    assert names.read_text() == "de_core_news_md"
