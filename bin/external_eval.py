"""Evaluate the checker against external gender-inclusive corpora.

Two complementary measurements per corpus of (exclusive, inclusive) pairs:

- detection: the exclusive side should produce at least one
  gender-orientation finding (recall proxy), and the inclusive side should
  produce none (false-positive rate on already-inclusive text - the
  should-not-flag contract).
- suggestions: where the exclusive side is flagged, do our alternatives
  contain the gold inclusive rewrite of the changed span (normalized)?

LanguageTool is deliberately disabled (LANGUAGETOOL_API=""): the external
gold covers inclusive language, not spelling, and the comparison should not
ride on a spell checker.

Usage:
    TESTING=True MANAGEMENT_AUTH_ENABLED=False LANGUAGETOOL_API="" \
        pdm run python -m bin.external_eval --pairs file.tsv --lang fr --limit 500
"""

import argparse
import ast
import asyncio
import csv
import json
import pathlib
import re
import sys
import unicodedata
from collections import Counter

from fastapi.testclient import TestClient

from app.main import app, context
from app.config_manager import parse_term_replacements

EMAIL = "external-eval@example.org"


def seed_user():
    user = {
        "id": "external-eval",
        "email": EMAIL,
        "plan": "witty_teams",
        "organization_id": "external-eval-org",
        "name": "External Eval",
        "config": {"categories": {}},
        "false_positives": [],
        "term_replacements": {},
        "domains": None,
        "notifications": 0,
        "config_hash": None,
    }
    user["term_replacements"] = parse_term_replacements(
        user["term_replacements"], context
    )
    context.redis.db.set(context.redis.get_user_id(user["email"]), json.dumps(user))
    org = {
        "id": user["organization_id"],
        "name": "External Eval",
        "plan": "witty_teams",
        "trial_ends_at": None,
        "config": {},
        "false_positives": [],
        "term_replacements": {},
        "domains": None,
        "config_hash": None,
    }
    context.redis.db.set(org["id"], json.dumps(org))


def normalize(text: str) -> str:
    """Fold the gender separators (:, *, interpunct, _, intra-word period -
    INCLURE's gold writes 'participant.e.s') so rewrites compare across
    separator conventions."""
    text = unicodedata.normalize("NFC", text.strip().lower())
    text = re.sub(r"(?<=\w)\.(?=\w)", "·", text)
    for separator in ":*_":
        text = text.replace(separator, "·")
    # fold '·e·s' / '·rice·s' morpheme spelling onto '·es' / '·rices'
    text = re.sub(r"·([a-zà-ÿ]{1,6})·(s|x)\b", r"·\1\2", text)
    # fold leading articles: 'les agent·es' should equal 'agent·es'
    text = re.sub(
        r"^(les?|la|l'|un|une|des|die|der|das|den|dem|ein|eine|einen)\s+",
        "", text
    )
    return text.rstrip(".")


def gender_findings(client, text: str, lang: str, config: dict) -> list[dict]:
    response = client.post(
        "/v2.4/check",
        json={"text": text, "lang": lang, "config": config},
        headers={"X-TESTING-AUTH": EMAIL},
    )
    response.raise_for_status()
    return [
        result
        for result in response.json()["results"]
        if result["category"] == "gender-orientation"
    ]


def changed_spans(exclusive: str, inclusive: str) -> list[tuple[str, str]]:
    """Word-level (exclusive, inclusive) replacements between the pair."""
    import difflib

    a, b = exclusive.split(), inclusive.split()
    spans = []
    for op, a0, a1, b0, b1 in difflib.SequenceMatcher(a=a, b=b).get_opcodes():
        if op == "replace":
            spans.append((" ".join(a[a0:a1]), " ".join(b[b0:b1])))
    return spans


async def evaluate_pairs(pairs, lang: str, config: dict, label: str):
    stats = Counter()
    misses, false_positives, suggestion_misses = [], [], []
    with TestClient(app) as client:
        seed_user()
        # Person-noun surface forms from the rules DB decide which gold
        # targets are in the product's scope (role nouns) versus out of it
        # (pronouns, participles, adjectives INCLURE also rewrites).
        from app.query_definitions import declensions_config
        from app.models import BasicWordType, LangType as LT

        noun_config = declensions_config[LT(lang)][BasicWordType.NOUN]
        rows = await context.db.fetch_rows(
            f"SELECT {', '.join(noun_config['columns'])} FROM {noun_config['name']}"
        )
        noun_forms = {
            str(value).lower() for row in rows for value in row if value
        }
        for exclusive, inclusive in pairs:
            spans = changed_spans(exclusive, inclusive)
            target_words = {
                normalize(w) for span, _ in spans for w in span.split()
            }
            in_scope = any(
                word in noun_forms
                for span, _ in spans
                for word in span.lower().split()
            )
            stats["in_scope" if in_scope else "out_of_scope"] += 1
            findings = gender_findings(client, exclusive, lang, config)
            stats["pairs"] += 1
            on_target = [
                f for f in findings
                if target_words & {normalize(w) for w in f["text"].split()}
            ]
            if findings:
                stats["detected_any"] += 1
            if on_target:
                stats["detected_target"] += 1
                if in_scope:
                    stats["detected_in_scope"] += 1
                gold = {normalize(g) for _, g in spans}
                gold_stems = {g.split("·")[0] for g in gold if "·" in g}
                ours = {
                    normalize(alternative["text"])
                    for finding in on_target
                    for alternative in finding["alternatives"]
                    if alternative.get("text")
                }
                if gold & ours:
                    stats["suggestion_exact"] += 1
                elif gold_stems and any(
                    o.split("·")[0] in gold_stems for o in ours if "·" in o
                ):
                    stats["suggestion_same_lemma"] += 1
                else:
                    stats["suggestion_miss"] += 1
                    if len(suggestion_misses) < 15:
                        suggestion_misses.append(
                            {"text": exclusive[:90], "gold": sorted(gold),
                             "ours": sorted(ours)[:6]}
                        )
            else:
                stats["missed_target"] += 1
                if in_scope and len(misses) < 25:
                    misses.append(
                        {"text": exclusive[:100],
                         "target": [s for s, _ in spans][:3]}
                    )

            inclusive_changed = {
                normalize(w) for _, span in spans for w in span.split()
            }
            inclusive_findings = gender_findings(client, inclusive, lang, config)
            rewrite_flagged = [
                f for f in inclusive_findings
                if inclusive_changed & {normalize(w) for w in f["text"].split()}
            ]
            if rewrite_flagged:
                # we flagged the very words the gold rewrite made inclusive
                stats["rewrite_flagged"] += 1
                if len(false_positives) < 25:
                    false_positives.append(
                        {"text": inclusive[:90],
                         "flagged": [f["text"] for f in rewrite_flagged][:4]}
                    )
            if len(inclusive_findings) > len(rewrite_flagged):
                # other findings on the inclusive side: usually residual
                # generic masculines the minimal gold pair left untouched
                stats["residual_flagged"] += 1

    total = max(stats["pairs"], 1)
    print(f"\n## {label} ({stats['pairs']} pairs, lang={lang})")
    print(f"target span detected: {stats['detected_target']}/{total}"
          f" ({stats['detected_target'] / total:.1%})"
          f"   [any finding: {stats['detected_any'] / total:.1%}]")
    print(f"gold rewrite re-flagged (true FP): {stats['rewrite_flagged']}/{total}"
          f" ({stats['rewrite_flagged'] / total:.1%})")
    if stats["in_scope"]:
        print(f"in-scope targets (role nouns): {stats['in_scope']}/{total}"
              f" - detected {stats['detected_in_scope']}/{stats['in_scope']}"
              f" ({stats['detected_in_scope'] / stats['in_scope']:.1%})")
    print(f"residual masculines flagged on inclusive side: "
          f"{stats['residual_flagged']}/{total} ({stats['residual_flagged'] / total:.1%})")
    tries = (stats["suggestion_exact"] + stats["suggestion_same_lemma"]
             + stats["suggestion_miss"])
    if tries:
        print(f"suggestions vs gold: exact {stats['suggestion_exact']}/{tries}"
              f", same-lemma inclusive {stats['suggestion_same_lemma']}/{tries}"
              f", neither {stats['suggestion_miss']}/{tries}")
    return {
        "stats": dict(stats),
        "missed_examples": misses,
        "false_positive_examples": false_positives,
        "suggestion_miss_examples": suggestion_misses,
    }


def load_pairs(path: str, limit: int | None):
    """Two formats: INCLURE csv (one 'translation' column holding a python
    dict literal with fr/fri) or plain TSV exclusive<TAB>inclusive."""
    pairs = []
    if path.endswith(".csv"):
        with open(path, encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                record = ast.literal_eval(row["translation"])
                exclusive = record["fr"].strip()
                inclusive = record["fri"].strip()
                if exclusive and inclusive and exclusive != inclusive:
                    pairs.append((exclusive, inclusive))
                    if limit and len(pairs) >= limit:
                        return pairs
        return pairs
    for line in open(path, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 2 and parts[0] and parts[1]:
            pairs.append((parts[0], parts[1]))
            if limit and len(pairs) >= limit:
                break
    return pairs


async def evaluate_dictionary(path: str, lang: str, config: dict, limit: int | None):
    """diversifix unified.csv: exclusive,inclusive,type,source rows.

    Each exclusive term is embedded in a template sentence; detection means
    a gender-orientation finding on the term. Suggestion overlap compares
    our alternatives with all of the dictionary's inclusive alternatives
    for that term. Inclusive-side templates are only expected to stay
    unflagged for neutral rewrites (type 1/2) - a bare feminine form
    (type 0) may legitimately be flagged toward a pair form."""
    entries = {}
    with open(path, encoding="utf-8") as handle:
        for row in csv.reader(handle):
            if len(row) < 4:
                continue
            term, alternative, kind, source = row[0], row[1], row[2], row[3]
            record = entries.setdefault(
                term, {"alternatives": set(), "neutral": set(), "sources": set()}
            )
            record["alternatives"].add(alternative)
            if kind in ("1", "2"):
                record["neutral"].add(alternative)
            record["sources"].add(source)

    terms = sorted(entries)
    if limit and len(terms) > limit:
        step = len(terms) / limit
        terms = [terms[int(i * step)] for i in range(limit)]

    template = "Die {} in unserem Unternehmen sind uns wichtig."
    stats = Counter()
    misses, neutral_flagged, suggestion_hits = [], [], Counter()
    with TestClient(app) as client:
        seed_user()
        from app.query_definitions import declensions_config
        from app.models import BasicWordType, LangType as LT

        noun_config = declensions_config[LT(lang)][BasicWordType.NOUN]
        rows = await context.db.fetch_rows(
            f"SELECT {', '.join(noun_config['columns'])} FROM {noun_config['name']}"
        )
        noun_forms = {str(v).lower() for row in rows for v in row if v}

        for term in terms:
            record = entries[term]
            in_scope = term.lower() in noun_forms
            stats["terms"] += 1
            stats["in_scope" if in_scope else "out_of_scope"] += 1
            findings = gender_findings(client, template.format(term), lang, config)
            on_term = [
                f for f in findings
                if normalize(term) in {normalize(w) for w in f["text"].split()}
                or normalize(f["text"]) == normalize(term)
            ]
            if on_term:
                stats["detected"] += 1
                if in_scope:
                    stats["detected_in_scope"] += 1
                gold = {normalize(a) for a in record["alternatives"]}
                ours = {
                    normalize(a["text"])
                    for f in on_term
                    for a in f["alternatives"]
                    if a.get("text")
                }
                if gold & ours:
                    stats["suggestion_overlap"] += 1
                    for source in record["sources"]:
                        suggestion_hits[source] += 1
            else:
                stats["missed"] += 1
                if not in_scope:
                    stats["missed_out_of_scope"] += 1
                misses.append({"term": term, "sources": sorted(record["sources"]),
                               "in_scope": in_scope,
                               "alternatives": sorted(record["alternatives"])[:4]})

            for alternative in sorted(record["neutral"])[:1]:
                neutral = gender_findings(
                    client, template.format(alternative), lang, config
                )
                stats["neutral_checked"] += 1
                if any(
                    normalize(alternative) in {normalize(w) for w in f["text"].split()}
                    for f in neutral
                ):
                    stats["neutral_flagged"] += 1
                    if len(neutral_flagged) < 20:
                        neutral_flagged.append(alternative)

    total = max(stats["terms"], 1)
    print(f"\n## diversifix dictionary ({stats['terms']} terms, lang={lang})")
    print(f"detected: {stats['detected']}/{total} ({stats['detected'] / total:.1%})")
    if stats["in_scope"]:
        print(f"in-scope (rules-DB nouns): {stats['in_scope']}/{total}"
              f" - detected {stats['detected_in_scope']}/{stats['in_scope']}"
              f" ({stats['detected_in_scope'] / stats['in_scope']:.1%})")
    if stats["detected"]:
        print(f"suggestion overlap with their alternatives: "
              f"{stats['suggestion_overlap']}/{stats['detected']}"
              f" ({stats['suggestion_overlap'] / stats['detected']:.1%})")
    if stats["neutral_checked"]:
        print(f"neutral rewrites flagged (should be 0): "
              f"{stats['neutral_flagged']}/{stats['neutral_checked']}")
    return {
        "stats": dict(stats),
        "missed_terms": misses,
        "neutral_flagged": neutral_flagged,
        "suggestion_hits_by_source": dict(suggestion_hits),
    }


async def evaluate_ifc(directory: str, lang: str, config: dict, limit: int | None):
    """Grouin's IFC corpus, inclusive versions (VFI): sentences containing
    inclusive forms must stay unflagged by gender rules - a should-not-flag
    sanity set of real published inclusive French."""
    inclusive_shape = re.compile(r"\w(·|\(e\)|\.e\.|/-?e\b|\w·\w)")
    sentences = []
    for path in sorted(pathlib.Path(directory).glob("vfi/*.txt")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            sentence = " ".join(sentence.split())
            if 20 < len(sentence) < 600 and inclusive_shape.search(sentence):
                sentences.append(sentence)
                if limit and len(sentences) >= limit:
                    break
        if limit and len(sentences) >= limit:
            break

    stats = Counter()
    flagged = []
    with TestClient(app) as client:
        seed_user()
        for sentence in sentences:
            stats["sentences"] += 1
            findings = gender_findings(client, sentence, lang, config)
            hits = [
                f for f in findings
                if inclusive_shape.search(f["text"])
            ]
            if hits:
                stats["inclusive_span_flagged"] += 1
                if len(flagged) < 20:
                    flagged.append({"text": sentence[:90],
                                    "flagged": [f["text"] for f in hits][:3]})
            if findings and not hits:
                stats["other_findings"] += 1

    total = max(stats["sentences"], 1)
    print(f"\n## IFC VFI inclusive sentences ({stats['sentences']}, lang={lang})")
    print(f"inclusive spans flagged (should be 0): "
          f"{stats['inclusive_span_flagged']}/{total}"
          f" ({stats['inclusive_span_flagged'] / total:.1%})")
    print(f"other gender findings in the same sentences: {stats['other_findings']}/{total}")
    return {"stats": dict(stats), "flagged_examples": flagged}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs")
    parser.add_argument("--dict")
    parser.add_argument("--ifc")
    parser.add_argument("--lang", choices=["de", "fr"], required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--label", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    config = (
        {"german_gender_ending": ":in", "gendered_roles_format": "inclusive_gender"}
        if args.lang == "de"
        else {"french_gender_separator": "·", "gendered_roles_format": "inclusive_gender"}
    )
    if args.dict:
        result = await evaluate_dictionary(args.dict, args.lang, config, args.limit)
    elif args.ifc:
        result = await evaluate_ifc(args.ifc, args.lang, config, args.limit)
    else:
        if not args.pairs:
            sys.exit("need --pairs or --dict")
        pairs = load_pairs(args.pairs, args.limit)
        if not pairs:
            sys.exit(f"no pairs loaded from {args.pairs}")
        result = await evaluate_pairs(
            pairs, args.lang, config, args.label or pathlib.Path(args.pairs).stem
        )
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(result, indent=1, ensure_ascii=False)
        )
        print(f"written: {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
