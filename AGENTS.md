# Agent Guidelines — NLP API

## Ethics screening

Every change that alters behaviour is screened against the Witty Works data
ethics questions (see the [ethics board page](https://www.witty.works/ethics-board)).
Treat all submitted text as sensitive personal data: people write here about
disability, gender, sexual orientation, origin, religion and health.

A change triggers a question if it:

- **1.1 Privacy harm**: stores, logs, caches, counts or sends anywhere
  (Redis, Sentry, the LLM, LanguageTool, the remote context checker, Slack)
  anything derived from request text, emails, API keys or auth headers.
  This includes widening `store_context` and loosening the privacy filter,
  `LLM_ACCESS` or `CLIENT_CONFIG_ENABLED`.
- **1.14 Statistical proxy risk**: adds, replaces, retrains or re-thresholds a
  model or LLM prompt that decides what is flagged, or infers characteristics
  of the author or of people mentioned (gender, "refers to people",
  proficiency, …).
- **1.15 Procedural regularity risk**: makes output depend on usage history
  or on an unpinned model version, or tunes rules or thresholds automatically.

**When in doubt, raise a concern.** If you are unsure whether a change triggers a question,
treat it as a trigger. If something seems ethically off but fits none of the
three questions, raise it anyway. The board's last question is whether there
are any other ethical issues it forgot to consider. Do not settle a doubt by
yourself: tell the user what worries you and why, and let them decide.

**Record sign-offs and ethics-related steering in the PR description**: who
decided, what, and why, including design changes made for ethical reasons and
what was built or proposed and then cut. Commits stay about the code; the PR
is the transparency record and must stand on its own.

**If any of these might apply, read [docs/ethics.md](docs/ethics.md) before
writing code.** It has the full triggers, what to do (in short: stop, tell
the user, flag the PR for the board), the invariants to keep and the known
gaps you must not copy. If none apply, write "Ethics screening: no trigger" in
the PR description.
