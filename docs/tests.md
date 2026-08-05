# Tests

## Table of Contents

- [Run all tests](#run-all-tests)
- [Run last failing tests](#run-last-failing-tests)
- [Update snapshot fixtures](#update-snapshot-fixtures)

---

## LanguageTool

The snapshots include LanguageTool findings, so they only hold still if
LanguageTool does. Run it locally before the suite:

```bash
docker compose up -d languagetool
LANGUAGETOOL_API="http://127.0.0.1:8210/v2" pdm run pytest -q
```

Without it the tests call the hosted API, which is a different version. It moved
from 6.8 to 6.9-SNAPSHOT during this project and stopped reporting
`COMMA_COMPOUND_SENTENCE`, so a snapshot changed with no change here. It is also
reachable over the network, which failed five times in one afternoon and once
took a dozen unrelated tests down with it.

The image is pinned for the same reason `latest` is not: it would drift too. The
heap is set because the default runs out part way through the suite and the
container exits, which surfaces as every remaining test failing to connect.

Use `127.0.0.1` rather than `localhost`. If anything else on the machine listens
on the IPv6 loopback for that port, `localhost` resolves there first and the
requests never reach the container, which looks like LanguageTool returning 404.

## Run all tests

To run the entire test suite:

```bash
pdm run pytest -vv
```

## Run last failing tests

To only run the last failing tests:

```bash
pdm run pytest -vv --lf
```

## Update snapshot fixtures

To update the fixtures with the current API responses:

```bash
pdm run pytest --snapshot-update
```

Make sure to review the changes if they are indeed intended before committing!

---

## See Also

- [Setup & Deployment](./setup.md) - Installation and running locally
- [Configuration & Environment Variables](./configuration.md) - Testing environment variables
- [API Endpoints](./api.md) - API examples for manual testing
- Back to [📋 Documentation Index](../README.md#documentation-index)
