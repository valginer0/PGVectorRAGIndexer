# Search Eval Fixture Corpus

This fixture set supports repeatable search-quality evaluation.

It is intentionally synthetic. The documents are small enough to inspect by
hand, but they cover several behaviors that have produced or could produce
search bugs:

- short literal identifiers such as `EV6`
- contextual/vector matches where the query wording differs from the document
- hybrid literal plus semantic queries
- extension filters
- chunk crowding from one source file
- unrelated negative-control documents

The first evaluator implementation should index every file under `corpus/`
using the metadata in `manifest.yaml`, then run `queries.yaml`.

All files should be indexed with:

```yaml
namespace: search_eval_v0
category: search_eval
```

This namespace lets the evaluator clean up and query only its own documents.

## Validation

Run the fixture integrity test after editing the corpus, manifest, or query set:

```bash
venv/bin/python -m pytest tests/test_search_eval_fixtures.py -q
```

The test checks that:

- every manifest document exists and is non-empty
- query IDs are unique
- query classes are known
- query file references are listed in the manifest
- extension-filter expectations match expected files
- literal and negative-control fixtures preserve their intended contracts

## Next Step

Build the first evaluator CLI around these fixtures. It should index the corpus,
run `queries.yaml`, de-duplicate returned chunks by `source_uri`, and report both
backend chunk metrics and displayed unique-file metrics.
