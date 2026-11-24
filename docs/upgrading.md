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

---

## See Also

- [Configuration & Environment Variables](./configuration.md)
- [Setup & Deployment](./setup.md)
- Back to [📋 Documentation Index](../README.md#documentation-index)
