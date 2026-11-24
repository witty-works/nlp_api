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

---

## See Also

- [Configuration & Environment Variables](./configuration.md)
- [Setup & Deployment](./setup.md)
- Back to [📋 Documentation Index](../README.md#documentation-index)
