# 06 - memory_zone docs: the async-service caveat

**Venue:** docs PR via the website README process in explosion/spaCy.
**Status:** draft.

## Evidence

`Language.memory_zone()` works exactly as advertised through our full e2e
suite - but only after serializing access per language with an asyncio
lock. Zones are process-global on the vocab: in an async server
(FastAPI/uvicorn - a very common serving shape), requests interleave at
await points, and one request's zone exit evicts strings another in-flight
request still references.

## Ask

One docs paragraph on the interleaving hazard plus the lock pattern:

```python
@asynccontextmanager
async def nlp_session(nlp, lock):
    async with lock:                # zones are process-global on the vocab
        with nlp.memory_zone():
            yield
# Extract plain data before leaving the zone; a Doc must not outlive it.
```

Our working implementation is `Model.nlp_session()` in this repo (positive
report otherwise: with the lock, bounded memory held across the whole
suite).
