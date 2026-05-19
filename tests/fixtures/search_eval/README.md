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
