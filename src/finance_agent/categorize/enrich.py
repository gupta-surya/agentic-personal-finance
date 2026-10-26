"""Merchant normalization: a bank's cryptic description -> a stable merchant key.

Pure string rules, no database, no model. The same merchant should always normalize to
the same key whatever the statement wraps around it: a payment-processor prefix, a store
number, a reference id, a date, punctuation or case. Descriptions are untrusted text: they
are only ever handled as strings here (never evaluated, never formatted into SQL).
"""

import re
import unicodedata

# Processor prefixes that sit in front of the real merchant name.
_PROCESSOR_PREFIX = re.compile(r"^\s*(?:SQ\s*\*|TST\s*\*|PAYPAL\s*\*)\s*")
# "AMZN MKTP US*2K4XY7Z" is the marketplace itself, not noise in front of a merchant:
# stripping the prefix would erase the merchant, so it becomes a canonical name.
_AMAZON_MARKETPLACE = re.compile(r"^\s*AMZN\s*MKTP\b")
_AMAZON_NAME = "AMAZON MARKETPLACE"

_APOSTROPHES_AND_AMPERSAND = re.compile(r"[’‘'`´&]")
_DATE = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b\d{4}-\d{2}-\d{2}\b")
_LONG_DIGIT_RUN = re.compile(r"\b\d{5,}\b")
_HASH_NUMBER = re.compile(r"#\s*\d+")
_STORE_NUMBER = re.compile(r"\b(?:STORE|STR|LOC|LOCATION)\s*\.?\s*#?\s*\d+\b")
_TRAILING_NUMBER = re.compile(r"(?:^|\s+)\d{3,}$")
_WHITESPACE = re.compile(r"\s+")


def normalize_merchant(description: str) -> str:
    """The merchant key for ``description``; ``""`` when nothing merchant-like is left.

    Steps, in order: decompose and drop accents (so full-width and accented letters map
    to plain ones; look-alike letters from other scripts deliberately do not), upper-case,
    canonicalize the Amazon marketplace, strip a processor prefix, drop apostrophes and
    ampersands (``MCDONALD'S`` -> ``MCDONALDS``, ``AT&T`` -> ``ATT``), drop dates, long
    digit runs, ``STORE 123`` and ``#123`` numbers, turn any other punctuation into a
    space, then drop trailing numbers of three or more digits and collapse whitespace.
    """
    text = unicodedata.normalize("NFKD", description)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).upper()
    if _AMAZON_MARKETPLACE.match(text):
        return _AMAZON_NAME
    text = _PROCESSOR_PREFIX.sub("", text)
    text = _APOSTROPHES_AND_AMPERSAND.sub("", text)
    for pattern in (_DATE, _LONG_DIGIT_RUN, _STORE_NUMBER, _HASH_NUMBER):
        text = pattern.sub(" ", text)
    text = "".join(ch if ch.isalnum() else " " for ch in text)
    text = _WHITESPACE.sub(" ", text).strip()
    while (stripped := _TRAILING_NUMBER.sub("", text)) != text:
        text = stripped
    return text
