"""Source adapters: one module per data source.

Each adapter knows WHAT to download. PoliteFetcher (how to ask) and RawStore (how to keep it)
do the rest.
"""


class UnexpectedResponseError(Exception):
    """A source answered, but not in the expected shape: stop rather than store junk (ADR 0004)."""
