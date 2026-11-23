# ADR: Serialized exports as the rules data exchange contract

Status: proposed. Date: 2026-08-12. Scope: rule editor and NLP API; recorded here because the API side carries the consuming half and the migration is verifiable against this repo's test suite.

## Decision

The rule editor's serialized export format (`export_rules_db` / `export_rule`) becomes the only data contract between the rule editor and the NLP API, replacing the download-the-sqlite-file workflow that sqlite was originally chosen to serve.

- The export becomes self-describing: `schema_version`, DDL generated from the editor's models for exactly the exported fields, then the data. Schema and data are versioned together and can never drift apart; neither side hand-maintains a second schema.
- The editor publishes stamped release artifacts rather than ad-hoc file copies: an export runs after an evaluation pass and embeds the editor revision plus the evaluation-run stamp, so any deployment can state which validated dataset it serves. Two flavors: full (deployments; includes the linguistic declension tables) and shareable (`--exclude-linguistic-data`; safe for public distribution while the verbformen/Netzverb permission covers only our own use - see docs/spacy-feedback item 5 and the data-provenance record).
- The NLP API pins a dataset version in a small manifest (URL + hash + version) and fetches at build/startup - the same pattern CI already uses for `lid.176.bin` - then materializes its in-memory sqlite by executing the bundled DDL and loading the data. `database/dump.sql` (~8 MB) and `database/db.sqlite3` (26 MB) leave the repository; `IMPORT_FROM_DUMP` becomes `IMPORT_FROM_EXPORT`.
- The editor's own storage becomes a private implementation detail; once nothing downstream reads its sqlite file, the editor is free to move to a database suited for parallel writes (the versioned evaluation runs now write thousands of rows concurrently with editing sessions).
- Community/upstream contribution of individual rules uses the already-built selective path: `export_rule --id/--lemma/--text-id/--full` on the contributing installation, `import_rule` plus the editor's validation and evaluation gates on ours. Authoring authority stays in the editor; nothing imports into the API directly.

Rollout in three independently shippable steps, each leaving behavior identical and snapshot-verifiable: (1) define the self-describing export and switch `bin/sync_sqlite_data.py` to consume it instead of a sqlite path; (2) editor publishes stamped releases, API pins them via the manifest and drops the committed database files; (3) editor migrates its storage to Postgres when write contention warrants it - invisible to everything downstream by then.

## Consequences

Positive:

- The API decouples from the editor's Django schema. Today `query_definitions.py`, `db.py` and `dump.sql` silently track editor migrations; after step 1 the contract is explicit and versioned, and an incompatible change fails loudly at import with a version mismatch instead of corrupting behavior quietly.
- Rule-data updates become reviewable. A dataset bump is a one-line manifest PR pointing at a stamped release, instead of a 947-line SQL blob diff (the shape the spaCy-3.8 rule corrections arrived in).
- Version stamping extends end to end: dataset releases carry the evaluation run they were validated by, closing the loop the rule editor's versioned evaluation started.
- License and provenance hygiene improves over the status quo: the public artifact excludes the verbformen-derived declension tables (today's committed `dump.sql` ships them wherever the repo goes), and the dataset location carries the LICENSE/NOTICE story per source (CC0 vs CC BY-NC-SA vs permission-gated).
- The repository loses ~34 MB of committed binary/blob data.
- Owning the materialization step allows indexes built for the API's actual query patterns (the code review found unindexable `COLLATE NOCASE` scans over the declension columns), and lets startup-built lookups (surface-form sets, `word_type_lemmas`) load straight from the export without touching sqlite at all.
- The editor's Postgres option is unlocked without any downstream coordination.

Negative / costs:

- An API-side importer must be built and maintained (roughly `sync_sqlite_data.py` inverted); the transition runs both paths until step 2 completes.
- Format versioning becomes a discipline forever: the export format is a public contract, changes need a version bump and importer support.
- Build/startup gains a fetch dependency (mitigated by the manifest hash, CI caching, and the option to vendor the artifact in an image build).
- Two artifact flavors mean the deployment path and the sharing path must not be confused; the full flavor's distribution must stay within what the Netzverb permission covers until a public grant exists.
- The in-memory sqlite queries initially require the importer to reproduce today's table shapes; diverging from them (better indexes, fewer tables) is deliberate follow-up work, not free.
- Materialization recurs at startup once no prebuilt database file is committed - but that is already the default today, and measured on the real data (36k rows) the cost class is identical: dump.sql `executescript` 0.90s vs JSON parse + per-table `executemany` 0.76s (one prepared statement per table instead of ~36k individually parsed INSERTs) vs ~0.00s for opening a prebuilt file - all noise against ~30-40s of spaCy model loading. Where materialization happens is a deployment choice, not a contract property: materialize at image build (the image ships a warm read-only sqlite file; runtime startup becomes faster than today, and workers can share one read-only file instead of per-worker memory copies) or into a manifest-hash-keyed local cache for bare-metal and development.

## Options considered

### A. Status quo: download the editor's sqlite, commit dump.sql + db.sqlite3

Pro: zero new code; schema arrives for free inside the dump; offline and reproducible once cloned. Con: API is coupled to the editor's internal Django schema and migration history; data updates are unreviewable blob diffs; 34 MB of committed artifacts; sqlite-as-transport forces sqlite-as-editor-storage, which the evaluation write load has outgrown; the committed dump publicly ships verbformen-derived data wherever the repo is visible.

### B. Serialized export as contract, manifest-pinned stamped releases (chosen)

Pro: explicit versioned contract; reviewable one-line dataset bumps; evaluation-stamped provenance; two license-appropriate flavors; repo slimming; frees the editor's storage choice; matches the existing fetch-and-cache CI pattern; every step behavior-identical and testable. Con: importer to build; format discipline forever; fetch dependency at build/startup.

### C. Git submodule pointing at the rule-editor repository

Pro: git-native version pinning; no artifact hosting needed. Con: pulls application code into a data dependency; breaks public clones and CI of this repo if the editor repo is private; submodule ergonomics (recursive clones, Docker builds); couples dataset versions to editor-repo commits rather than validated releases.

### D. Git submodule pointing at a dedicated data-only repository

Pro: git-native pinning of exactly the data; public repo can carry the shareable flavor and the license story. Con: a third repository to operate; submodule ergonomics remain; the full (permission-gated) flavor still needs a non-public channel, so the artifact split exists anyway; offers little over the manifest once releases are stamped.

### E. Schema handling sub-options

Hand-maintained DDL in the API (pro: full control; con: a second schema to keep in sync - though the API already maintains this knowledge implicitly in `query_definitions.py`). Schema derived generically from fixture metadata at import (pro: no DDL anywhere; con: type/index intent is lost, and sqlite type affinity papering over it hides bugs). Self-describing export with editor-generated DDL (chosen: single-sourced in the editor's models, versioned with the data, zero hand maintenance on either side).
