"""One base class for every error this tool raises on purpose.

`cli.main()` used to catch an explicit tuple of seven exception types. Twice a
new module added its own error and forgot to extend the tuple -- `CompareError`
and `CollectError` both reached the user as tracebacks while every other failure
printed one clean line. A tuple that must be edited from a distance is a bug
waiting to recur, so the CLI now catches this base instead.

Anything raised for a condition the USER can act on (missing file, bad config,
tool not found, ambiguous reference) subclasses TccError. Programming errors --
a bad argument to an internal function, an impossible state -- must NOT: those
should crash loudly with a traceback, because they are bugs and not messages.
"""

from __future__ import annotations


class TccError(Exception):
    """Base for every user-facing error. Caught once, in cli.main()."""
