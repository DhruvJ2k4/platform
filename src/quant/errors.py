"""Exception taxonomy (doc 23): every raised platform error is one of these five kinds.

SourceError (fetch/availability of a data source), ParseError (raw file interpretation),
ContractViolation (schema or invariant breach at a validation gate), LedgerError (money-path
integrity), ConfigError (missing/invalid/ambiguous configuration). All subclass PlatformError;
bare ``except`` is forbidden repo-wide, and jobs exit nonzero on any unhandled error.
"""


class PlatformError(Exception):
    """Base class for all platform exceptions."""


class SourceError(PlatformError):
    """A data source could not be fetched or is unavailable/hostile."""


class ParseError(PlatformError):
    """A raw file could not be interpreted by its format-epoch parser."""


class ContractViolation(PlatformError):
    """A schema or invariant contract was breached at a validation gate."""


class LedgerError(PlatformError):
    """Money-path integrity failure in lots, costs, taxes, or reconciliation."""


class ConfigError(PlatformError):
    """Configuration is missing, invalid, or ambiguous; failing loudly is by design."""
