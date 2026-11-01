# 07 - requires-python ceiling vs cross-platform lockers

**Venue:** discussion (not the tracker).
**Status:** note.

spacy 3.8.14 declares `python <3.15`; projects with an unbounded
`requires-python` get an opaque cross-platform lock failure (pdm rejects
the candidate with only a debug-log explanation). Not spaCy's bug alone -
but a floor/ceiling note in the install docs would save resolver
archaeology.
