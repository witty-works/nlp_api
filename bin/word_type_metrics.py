"""Measure the _fetch_word_type branches against corpora.

For every token the runner records which branch decided (the trace tag), what
a plain UPOS table would have said instead, and - when a UD .conllu file
provides gold part-of-speech - whether the loaded model's UPOS was right at
all. The report says, per branch: how often it fires, how often it diverges
from the naive table, and how often it fires on top of a model error. That is
the evidence for retiring a hack, keeping it, or moving it into data.

Usage:
    pdm run python -m bin.word_type_metrics --tests
    pdm run python -m bin.word_type_metrics --conllu path/to/de_gsd-ud-dev.conllu --lang de
    pdm run python -m bin.word_type_metrics --tests --conllu ... --lang de --limit 500

Needs the app context (models + rule db); runs everything through the same
pipeline the API serves.
"""

import argparse
import asyncio
import difflib
import json
import pathlib
import sys
from collections import Counter, defaultdict

from fastapi.testclient import TestClient

from app.main import app, context
from app.models import LangType

# The Phase-2 candidate: what a table-driven UPOS mapping would answer with
# no heuristics at all. Divergence from this is each branch's value-add (or
# damage) - it is not automatically wrong.
NAIVE_UPOS = {
    "NOUN": "n",
    "VERB": "v",
    "ADJ": "a",
    "ADV": "adv",
    "PRON": "pron",
    "NUM": "number",
    "CCONJ": "conj",
    "PROPN": "",
    "AUX": "",
    "DET": "",
}


NEIGHBOURS = {  # QWERTZ-ish adjacent keys, enough for realistic slips
    "a": "sq", "e": "rw", "i": "uo", "o": "ip", "u": "zi", "n": "bm",
    "r": "et", "s": "ad", "t": "rz", "l": "kö", "m": "n", "d": "sf",
}


def _pick(text: str, salt: str, count: int) -> int:
    """Deterministic pseudo-random index so runs are reproducible."""
    import hashlib

    digest = hashlib.md5((salt + text).encode()).digest()
    return int.from_bytes(digest[:4], "big") % count if count else 0


def derive(text: str, stratum: str) -> str:
    """Degrade a clean sentence into one of the corpus strata.

    partial: prefix cut mid-typing (browser-extension shape);
    typo: one keyboard slip in a content word;
    grammar: one structural slip (dropped determiner, lost capitalization,
    or swapped neighbours) - the shapes real drafts have."""
    words = text.split()
    if len(words) < 4:
        return text

    if stratum == "partial":
        cut = max(3, len(words) * 2 // 3)
        kept = words[:cut]
        kept[-1] = kept[-1][: max(2, len(kept[-1]) * 2 // 3)]  # mid-word
        return " ".join(kept)

    if stratum == "typo":
        candidates = [i for i, w in enumerate(words) if len(w) >= 5 and w.isalpha()]
        if not candidates:
            return text
        index = candidates[_pick(text, "typo", len(candidates))]
        word = words[index]
        pos = 1 + _pick(word, "pos", len(word) - 2)
        char = word[pos].lower()
        operation = _pick(word, "op", 3)
        if operation == 0 and char in NEIGHBOURS:
            replacement = NEIGHBOURS[char][_pick(word, "n", len(NEIGHBOURS[char]))]
            word = word[:pos] + replacement + word[pos + 1 :]
        elif operation == 1:
            word = word[:pos] + word[pos + 1 :]  # deletion
        else:
            word = word[:pos] + word[pos] + word[pos:]  # doubling
        words[index] = word
        return " ".join(words)

    if stratum == "grammar":
        operation = _pick(text, "gram", 3)
        articles = {"der", "die", "das", "ein", "eine", "the", "a", "an", "le", "la", "les", "un", "une"}
        article_positions = [i for i, w in enumerate(words) if w.lower() in articles]
        capitals = [
            i for i, w in enumerate(words[1:], 1) if w[:1].isupper() and w[1:].islower()
        ]
        if operation == 0 and article_positions:
            del words[article_positions[_pick(text, "art", len(article_positions))]]
        elif operation == 1 and capitals:
            index = capitals[_pick(text, "cap", len(capitals))]
            words[index] = words[index].lower()
        else:
            index = 1 + _pick(text, "swap", len(words) - 2)
            words[index], words[index + 1] = words[index + 1], words[index]
        return " ".join(words)

    return text


def parse_conllu(path: str, limit: int | None):
    sentences = []
    text, tokens = None, []
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("# text = "):
            text = line[len("# text = ") :]
        elif not line:
            if text and tokens:
                sentences.append((text, tokens))
                if limit and len(sentences) >= limit:
                    break
            text, tokens = None, []
        elif line[0].isdigit():
            cols = line.split("\t")
            if "-" in cols[0] or "." in cols[0]:
                continue  # multiword ranges and empty nodes
            tokens.append((cols[1], cols[3]))  # form, gold UPOS
    return sentences


def align(app_forms: list[str], gold_forms: list[str]):
    """Pairs of (app_index, gold_index) where the surface forms agree."""
    matcher = difflib.SequenceMatcher(a=app_forms, b=gold_forms, autojunk=False)
    pairs = []
    for block in matcher.get_matching_blocks():
        pairs += [(block.a + i, block.b + i) for i in range(block.size)]
    return pairs


class Stats:
    def __init__(self):
        self.fires = Counter()
        self.diverges = Counter()  # branch result != naive(model pos)
        self.model_pos_wrong = Counter()  # gold mode: model UPOS != gold
        self.gold_seen = Counter()
        self.examples = defaultdict(list)

    def note(self, tag, token, word_type, naive, sentence, gold_upos=None):
        self.fires[tag] += 1
        if gold_upos is not None:
            self.gold_seen[tag] += 1
            if token.pos_ != gold_upos:
                self.model_pos_wrong[tag] += 1
        if word_type != naive:
            self.diverges[tag] += 1
            if len(self.examples[tag]) < 5:
                self.examples[tag].append(
                    {
                        "token": token.text,
                        "pos": token.pos_,
                        "tag": token.tag_,
                        "gold": gold_upos,
                        "word_type": word_type,
                        "naive": naive,
                        "sentence": sentence[:90],
                    }
                )


async def sweep(lang: LangType, texts, stats: Stats, gold=None):
    model = context.model
    for index, text in enumerate(texts):
        doc = model.fetch_tokens(lang, text)
        gold_map = {}
        if gold is not None:
            pairs = align([t.text for t in doc], [f for f, _ in gold[index]])
            gold_map = {a: gold[index][b][1] for a, b in pairs}
        for token in doc:
            trace = []
            word_type = await model._fetch_word_type(lang, token, None, trace=trace)
            naive = NAIVE_UPOS.get(token.pos_, "")
            stats.note(
                trace[-1] if trace else "untraced",
                token,
                word_type,
                naive,
                text,
                gold_map.get(token.i),
            )


def report(name: str, stats: Stats):
    lines = [f"\n## {name}", "branch | fires | diverges-from-naive | model-pos-wrong"]
    total = sum(stats.fires.values())
    for tag, fires in stats.fires.most_common():
        wrong = (
            f"{stats.model_pos_wrong[tag]}/{stats.gold_seen[tag]}"
            if stats.gold_seen[tag]
            else "-"
        )
        lines.append(f"{tag} | {fires} ({fires / total:.1%}) | {stats.diverges[tag]} | {wrong}")
    print("\n".join(lines))
    return {
        "total": total,
        "branches": {
            tag: {
                "fires": stats.fires[tag],
                "diverges": stats.diverges[tag],
                "gold_seen": stats.gold_seen[tag],
                "model_pos_wrong": stats.model_pos_wrong[tag],
                "examples": stats.examples[tag],
            }
            for tag in stats.fires
        },
    }


def test_corpus_texts():
    per_lang = defaultdict(list)
    for path in sorted(pathlib.Path("tests").glob("**/input.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        text = data.get("text")
        if not text or not isinstance(text, str):
            continue
        lang = data.get("lang")
        if lang not in ("de", "en", "fr"):
            langs = context.lang_detection.predict_lang(text.replace("\n", " "))
            lang = next((l for l in langs if l in ("de", "en", "fr")), None)
        if lang:
            per_lang[LangType(lang)].append(text)
    return per_lang


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tests", action="store_true")
    parser.add_argument("--conllu")
    parser.add_argument("--lang", choices=["de", "en", "fr"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--strata", default="clean,partial,typo,grammar")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    results = {}
    if args.tests:
        for lang, texts in sorted(test_corpus_texts().items()):
            stats = Stats()
            await sweep(lang, texts, stats)
            results[f"tests-{lang}"] = report(
                f"test corpus {lang} ({len(texts)} texts)", stats
            )

    if args.conllu:
        if not args.lang:
            sys.exit("--conllu needs --lang")
        sentences = parse_conllu(args.conllu, args.limit)
        gold = [tokens for _, tokens in sentences]
        for stratum in args.strata.split(","):
            texts = [
                text if stratum == "clean" else derive(text, stratum)
                for text, _ in sentences
            ]
            stats = Stats()
            # Alignment only pairs identical surface forms, so tokens the
            # stratum altered drop out of the gold comparison on their own.
            await sweep(LangType(args.lang), texts, stats, gold=gold)
            results[f"ud-{args.lang}-{stratum}"] = report(
                f"UD {args.lang} {stratum} ({len(texts)} sentences)", stats
            )

    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(results, indent=1, ensure_ascii=False))
        print(f"\nwritten: {args.out}")


if __name__ == "__main__":
    with TestClient(app):
        asyncio.run(main())
