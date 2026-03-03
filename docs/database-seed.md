# Database seed: dump.sql

## Table of Contents

- [How it's used](#how-its-used)
- [What's inside](#whats-inside)
- [Source of truth for rules](#source-of-truth-for-rules)
- [Regenerating dump.sql](#regenerating-dumpsql)
- [Verifying changes](#verifying-changes)
- [Where to look in code](#where-to-look-in-code)

---

The application seeds its in-memory SQLite database from [database/dump.sql](../database/dump.sql) by default. This file contains the bulk of the inclusive language rules used by the NLP API.

## How it's used

- On boot, when `IMPORT_FROM_DUMP=true` (default in Core settings), [app/db.py](../app/db.py) loads [database/dump.sql](../database/dump.sql) into an in-memory SQLite instance.
- If `IMPORT_FROM_DUMP=false`, the app falls back to copying from [database/db.sqlite3](../database/db.sqlite3) instead.

- A pruned SQLite dump containing only the tables needed by the rule engine (e.g., `rules_rule`, `rules_alternative`, `rules_falsepositive`, `rules_lemmatization`, language declensions tables, and sources).
- Inactive rules and alternatives are removed to keep the dataset lean.

## Source of truth for rules

- The original rules SQLite database is maintained and edited in the Witty Works Rule Editor: https://github.com/witty-works/rule-editor
- When rules change there, export or copy the updated SQLite file from the Rule Editor and use it as input for the sync step below.

## Regenerating dump.sql

- When you update the source SQLite database (for example, new rules) regenerate the dump and supporting lookup files.
- Use the helper script:

```bash
# Replace path/to/source.sqlite3 with your updated rules database
# (e.g., the SQLite file exported from the Rule Editor)

pdm run python -m bin.sync_sqlite_data -f path/to/source.sqlite3
```

- The script will:
  - Copy the file to [database/db.sqlite3](../database/db.sqlite3)
  - Drop unused tables and columns (`created_at`, `updated_at`, `comment`)
  - Delete inactive rules/alternatives
  - Rebuild [training_data/lookup.json](../training_data/lookup.json) and [training_data/lemma_plural_lookup.json](../training_data/lemma_plural_lookup.json)
  - Write the cleaned SQL dump to [database/dump.sql](../database/dump.sql)

## Verifying changes

- Start the API locally and check `/health` or run a small `/v2.4/check` request from the examples in [API Endpoints](./api.md).
- In CI and containers, using `dump.sql` typically yields faster, more reproducible startups compared to bundling a binary SQLite file.

## Where to look in code

- Loader logic: [app/db.py](../app/db.py)
- Sync/cleanup script: [bin/sync_sqlite_data.py](../bin/sync_sqlite_data.py)

---

## See Also

- [Configuration & Environment Variables](./configuration.md) - `IMPORT_FROM_DUMP` setting details
- [Training Data & Lookups](./training-data.md) - Language resources and lookup files
- [Technical Notes](./technical-notes.md) - Data initialization details
- Back to [📋 Documentation Index](../README.md#documentation-index)
