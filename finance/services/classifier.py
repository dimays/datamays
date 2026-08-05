"""The LLM step of categorization, kept behind a small interface.

Only reached for merchants that no rule and no remembered decision covers, so
in steady state this runs on a handful of genuinely new merchants a week
rather than on every transaction. That is what keeps it costing pennies.

The provider sits behind `Classifier` so swapping models — or dropping the LLM
entirely — does not touch the pipeline.
"""

import json
import logging
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger(__name__)

BATCH_SIZE = 40

# Without this the client waits indefinitely. The categorizer runs from the
# hourly chain, so a hung request would stall every later step behind it.
REQUEST_TIMEOUT_SECONDS = 45

SYSTEM_PROMPT = """You categorize personal bank transactions for a two-person household.

You will get a list of merchant descriptions and a list of allowed categories.
Assign each merchant exactly one category slug from the list.

Rules:
- Use only slugs from the provided list. Never invent one.
- Judge by the merchant, not the amount.
- Prefer the most specific category that clearly fits.
- When genuinely unsure between categories, pick the closest and lower your
  confidence. When you have no real idea, use "uncategorized" with a low
  confidence rather than guessing something plausible-sounding.
- confidence is 0.0 to 1.0 and should reflect real uncertainty. A well-known
  national merchant is high confidence; an ambiguous abbreviation is not.

Respond with a single JSON object matching the given response_shape."""


@dataclass(frozen=True)
class Classification:
    merchant_key: str
    category_slug: str
    confidence: float


class Classifier:
    """Base interface. Subclasses talk to a specific provider."""

    def classify(self, merchant_keys, categories) -> list[Classification]:
        raise NotImplementedError


class NullClassifier(Classifier):
    """Used when no API key is configured.

    Returns nothing rather than failing, so the deterministic parts of the
    pipeline keep working and unmatched transactions simply queue for review.
    """

    def classify(self, merchant_keys, categories):
        return []


class OpenAIClassifier(Classifier):
    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or getattr(settings, "OPENAI_API_KEY", "")
        self.model = model or getattr(settings, "FINANCE_CATEGORIZER_MODEL", "gpt-4o-mini")

    def classify(self, merchant_keys, categories):
        if not merchant_keys or not self.api_key:
            return []

        results = []

        for start in range(0, len(merchant_keys), BATCH_SIZE):
            batch = merchant_keys[start : start + BATCH_SIZE]

            try:
                results.extend(self._classify_batch(batch, categories))
            except Exception:  # noqa: BLE001
                # A classifier outage must not fail the sync. The affected
                # transactions stay uncategorized and land in the review queue.
                logger.exception("Classifier batch failed; leaving %d for review", len(batch))

        return results

    def _classify_batch(self, merchant_keys, categories):
        from openai import OpenAI

        client = OpenAI(
            api_key=self.api_key,
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=2,
        )
        allowed = {category["slug"] for category in categories}

        response = client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "categories": categories,
                            "merchants": merchant_keys,
                            "response_shape": {
                                "results": [
                                    {"merchant": "string", "category": "slug", "confidence": 0.0}
                                ]
                            },
                        }
                    ),
                },
            ],
        )

        payload = json.loads(response.choices[0].message.content or "{}")

        return list(self._parse(payload, merchant_keys, allowed))

    def _parse(self, payload, merchant_keys, allowed):
        requested = set(merchant_keys)

        for item in payload.get("results") or []:
            merchant = str(item.get("merchant") or "").strip()
            slug = str(item.get("category") or "").strip()

            # Guard against a hallucinated slug or a merchant we never asked
            # about: either would write a wrong category into the ledger.
            if merchant not in requested or slug not in allowed:
                logger.warning("Discarding classification %r → %r", merchant, slug)
                continue

            try:
                confidence = float(item.get("confidence", 0))
            except (TypeError, ValueError):
                confidence = 0.0

            yield Classification(
                merchant_key=merchant,
                category_slug=slug,
                confidence=max(0.0, min(1.0, confidence)),
            )


def get_classifier() -> Classifier:
    if getattr(settings, "OPENAI_API_KEY", ""):
        return OpenAIClassifier()

    return NullClassifier()
