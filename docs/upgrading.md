# Upgrading

What an operator has to change, or check, when moving a deployment to a newer
release of the API. Each release lists the changes that need action, with
what to set or run. Changes that need nothing from the operator are not
listed; the git history has them.

## 4.0.0

- **`ENVIRONMENT_TYPE` defaults to `production`.** A deployment that never set
  it now hides the development helpers (`/debug/*`, `/lemmatize`, `/tokenize`,
  `/parse-word-types`, `/save_openapi_json` answer `404`) and `/` no longer
  redirects to `/docs`. Set `ENVIRONMENT_TYPE=development` where you want
  them, for local work only.
- **`LANGUAGETOOL_API` defaults to empty.** A deployment that never set it
  used LanguageTool's hosted API and sent it the text being checked; now it
  makes no spelling and grammar checks. To keep them, set `LANGUAGETOOL_API`
  to your LanguageTool server (or, knowing that it sends the text to
  LanguageTool, to `https://api.languagetoolplus.com/v2`).
- **Production refuses to start with API keys stored as written.** If Redis
  holds an API key as written (any key minted, synced or set as
  `DEFAULT_API_KEY` while `API_KEY_HMAC_KEY` was empty), a production start
  stops with a message saying how many. Set `API_KEY_HMAC_KEY` to a random
  secret, run `python -m bin.api_key rehash` against the deployment's Redis
  with it, then start; see [API keys](./setup.md#api-keys).
- **Production refuses to start with `TESTING` on or
  `MANAGEMENT_AUTH_ENABLED` off.** Both are for tests and local work: the
  first lets a request name its user, the second opens the management
  endpoints. Change them back, or set `ENVIRONMENT_TYPE=development` where you
  run tests.
- **`SLACK_ENABLED` needs its credentials.** With Slack on and
  `SLACK_SIGNING_SECRET` or `SLACK_BOT_TOKEN` empty, the start is refused;
  it used to serve `/slack/commands` with a placeholder signing secret.
- **Dashboard tokens need an issuer and a verified email.** With
  `DASHBOARD_CLIENT_ID` set, `DASHBOARD_ISSUER` is required (the start is
  refused without it) and every dashboard token is checked for that `iss`. A
  dashboard token is accepted only with `email_verified: true`. Deploy, in
  this order: first the dashboard release that puts `iss` and
  `email_verified` in its tokens, then this API with `DASHBOARD_ISSUER` set.
  Tokens the dashboard issued before carry neither and are refused, so users
  sign in again.
- **Refused tokens are answered with `401`, not `403`.** An invalid or
  expired token, an unknown `x-key` at `/v2.0/auth` and a request there
  with no credential now get `401` (with
  `WWW-Authenticate: Bearer error="invalid_token"` for a token); a failure
  to fetch the issuer's keys gets `503`, where it got `400`. `403` is left
  for a valid credential whose user is not let in. Clients that only
  refreshed a token on `403` need to do so on `401`; the browser extension
  already does.
- **The per-user request log is gone.** `REDIS_LOG_EMAILS` and
  `GET /user/logs` no longer exist; the API no longer stores the text and
  `Authorization` header of requests from the listed emails. What earlier
  versions stored stays in Redis until deleted, with no expiry:

  ```bash
  redis-cli DEL debug_emails
  redis-cli --scan --pattern 'log-dashboard-user-email:*' | xargs -r redis-cli DEL
  ```

- **Organisation configs move to a prefixed Redis key.** They are stored
  under `dashboard-organization:<id>` instead of the bare id. Configs stored
  under the bare id are still read, so nothing breaks on upgrade; move them
  once with the migration, which touches only JSON objects naming their own
  key as `id`:

  ```bash
  uv run python -m bin.migrate_organization_keys --dry-run
  uv run python -m bin.migrate_organization_keys
  ```
- **LLM provider adapters (`LLM_PROVIDER`).** Nothing changes without it:
  the default `openai-compatible` behaves as before, including the `422`
  for a LiteLLM proxy's guardrail refusals. Behind a LiteLLM proxy, set
  `LLM_PROVIDER=litellm-proxy` so the API learns which model answered. New
  optional settings: `LLM_TASK_EXTRA_BODY`, `LLM_SERVED_MODEL_HEADER`,
  `LLM_EXPECTED_MODEL` and `LLM_MODEL_MISMATCH` (`warn` by default); an
  unknown `LLM_PROVIDER` stops the start. See
  [Choosing a language model](./llm-models.md).
- **Rephrasings are checked before they reach the user.** A rephrasing that
  undoes the swap, brings the flagged words back, changes another
  occurrence of them, rewrites the sentence or adds a word Witty flags is
  dropped, and the client offers the plain alternative. Drops are logged by
  the check's name and counted in `rephrase_dropped` with `LOG_METRICS`.
  `bin/llm_check.py` tests the configured model on known cases.
- **Rephrase and write answers name the model.** `/v1.0/rephrase` and
  `/v1.0/write` answers carry `model`: the model that answered, as the
  provider reported it, else `LLM_MODEL`. `/health` reports the same under
  `llm`, for information only; it never makes `/health` fail. Clients that
  ignore unknown fields need no change.
- **Bedrock credentials use the standard AWS names.** `AWS_KEY` and
  `AWS_SECRET_KEY` are no longer read, and setting either stops the start.
  Set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` instead, or use an AWS
  profile or instance role; LiteLLM finds them itself. `AWS_REGION_NAME` is
  unchanged.

---

## See Also

- [Configuration & Environment Variables](./configuration.md)
- [Setup & Deployment](./setup.md)
- Back to [📋 Documentation Index](../README.md#documentation-index)
