# Demo corpus — entirely fictional

Synthetic documents for demos, screenshots and the walkthrough video. **Every
name, client, matter number, address and figure here is invented.** No real
person, firm or file appears.

It exists because the screenshots that shipped on ragvault.net from December 2025
were captured against the author's own archive and exposed a personal email
address, employment history and the names of real third parties. Demo material
must never be captured against real data again — index this instead.

The corpus is written to support two demo queries:

- **Literal identifier:** `RW-2024-0187` — appears in exactly three documents,
  showing exact-token retrieval.
- **Semantic, no keyword overlap:** "how long do we keep client records before
  destroying them" — the answering document (`policy_records_retention.md`)
  never uses the words "how long" or "destroying".

## Verified 2026-09-09

Indexed into a clean instance (v2.17.1 image, 9 documents, 40 chunks) and the
demo queries were run. These are measured results, not intentions:

| Query | Top hit | Score |
|---|---|---|
| "how long do we keep client records before destroying them" | `policy_records_retention.md` | 0.636 |
| "RW-2024-0187" | `matter_RW-2024-0187_file_note.md`, then the engagement letter | 0.450 / 0.329 |
| "can I put a client file into ChatGPT to summarise it" | `policy_information_security.md` | 0.310 |

The first shows semantic retrieval: the answering policy contains neither "how
long" nor "destroying". The second shows exact-identifier retrieval spanning two
documents. The third is the strongest one to demo, because it is the product's
own sales argument being answered out of the corpus.

**Index `documents/` only, never the corpus root.** An earlier version kept this
README beside the documents; it describes the demo queries verbatim, so it
outranked the real answers and returned itself for every query. Verified again
after moving it.
