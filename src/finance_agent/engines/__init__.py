"""Deterministic calculators over query results. No SQL, no model.

An engine takes ``QueryResult``s and returns a ``QueryResult``: the numbers it
produces carry their own ``result_id``, which names the source ids it consumed, so
the verifier traces a derived figure exactly like a queried one.
"""
