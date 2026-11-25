"""Offsets as JavaScript clients count them: in UTF-16 code units, where a
character outside the Basic Multilingual Plane (most emoji) counts twice.
No imports, so models and helpers alike can use it."""


def utf16_units(text: str) -> int:
    """The length of `text` in UTF-16 code units."""
    return sum(2 if ord(char) > 0xFFFF else 1 for char in text)


def python_index(text: str, utf16_offset: int) -> int:
    """The Python index of a UTF-16 code-unit offset into `text`."""
    units = 0
    for index, char in enumerate(text):
        if units >= utf16_offset:
            return index
        units += 2 if ord(char) > 0xFFFF else 1
    return len(text)
