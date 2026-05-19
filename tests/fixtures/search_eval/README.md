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

The Niro service bulletin is a true non-EV6 distractor: it should remain
semantically close to EV service content without containing the literal `EV6`
token.

The first evaluator implementation should index every file under `corpus/`
using the metadata in `manifest.yaml`, then run `queries.yaml`.

All files should be indexed with:

```yaml
namespace: search_eval_v0
category: search_eval
```

This namespace lets the evaluator clean up and query only its own documents.

## Validation

Run the fixture integrity and evaluator CLI tests after editing the corpus,
manifest, query set, or evaluator:

```bash
venv/bin/python -m pytest tests/test_search_eval_fixtures.py tests/test_search_eval_cli.py -q
```

The test checks that:

- every manifest document exists and is non-empty
- query IDs are unique
- query classes are known
- query file references are listed in the manifest
- extension-filter expectations match expected files
- literal and negative-control fixtures preserve their intended contracts

The evaluator skeleton can also validate and print the planned query executions:

```bash
venv/bin/python scripts/search_eval.py validate
venv/bin/python scripts/search_eval.py plan
venv/bin/python scripts/search_eval.py plan --json
venv/bin/python scripts/search_eval.py run --output-json docs/internal/SEARCH_EVAL_BASELINE_V0.json
venv/bin/python scripts/search_eval.py run --skip-cleanup --skip-index --query-id literal_ev6_txt
```

## Next Step

After corpus or query edits, run the live evaluator against a branch-local API
and refresh the private baseline artifacts in `docs/internal/`. The live runner
indexes the corpus through `/upload-and-index`, de-duplicates returned chunks by
`source_uri`, and writes backend chunk, displayed unique-file, assertion, and
top-file diagnostic metrics.
