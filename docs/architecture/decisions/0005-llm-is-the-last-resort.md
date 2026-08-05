# 0005 — The LLM classifier runs last, not first

**Status:** accepted
**Reverse cost:** low to reverse, high to *have* reversed — cost and stability both degrade

## Context

Transactions arrive with descriptions like `SQ *BLUE BOTTLE COFFEE 4471
CHICAGO IL 04/15`. Something has to decide that this is Dining Out.

An LLM does this well. Sending every transaction to one is also the expensive,
slow, and *non-deterministic* option — the same merchant could land in a
different category next month.

## Decision

Categorization is an ordered pipeline, cheapest and most certain first. The
LLM is the last resort:

1. **Transfer detection** — matched opposite amounts across your own accounts
   within a few days. Excluded from spend and income entirely.
2. **`CategoryRule`** — deterministic pattern → category, highest priority
   wins. `confidence = 1.0`.
3. **`MerchantCategoryMemo`** — a normalized merchant string seen and
   confirmed before.
4. **The LLM**, batched, for whatever is left.
5. **Review queue** — anything below the confidence threshold surfaces in the
   UI. Confirming writes a memo, so the same merchant is never asked about
   twice.

## Why the order matters

Recurring merchants are the bulk of transactions. Steps 2 and 3 absorb almost
all of them after the first month, which is what keeps the OpenAI bill at
roughly **$0.10–0.50/month** instead of scaling with transaction volume.

It also makes results *stable*. A merchant you have categorized once stays
categorized that way, because a memo — not a model — is answering.

And it degrades well: **with no `OPENAI_API_KEY` set at all, the app still
works.** Rules and memos still apply; everything else queues for review.

## Consequences

- The classifier sits behind a small interface in `services/categorize.py`, so
  the provider is not hardwired.
- The network call happens with **no database transaction open**. Holding one
  across a third-party call pins a connection for as long as the provider
  takes. There is a test that enforces this
  (`test_categorize.py::ClassifierIsolationTests`).
- The classifier occasionally returns a category slug that does not exist. The
  pipeline discards those rather than trusting them, and the transaction falls
  through to the review queue.
