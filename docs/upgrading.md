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

---

## See Also

- [Configuration & Environment Variables](./configuration.md)
- [Setup & Deployment](./setup.md)
- Back to [📋 Documentation Index](../README.md#documentation-index)
