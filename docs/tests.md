# Tests

## Table of Contents

- [Run all tests](#run-all-tests)
- [Run last failing tests](#run-last-failing-tests)
- [Update snapshot fixtures](#update-snapshot-fixtures)

---

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
