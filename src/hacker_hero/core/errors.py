"""Custom exceptions."""


class ScoresCodecError(ValueError):
    """Raised when scores blob cannot be decoded/encoded."""


class DocumentError(Exception):
    """Raised for document-level errors (missing section, IO, etc.)."""


class ValidationError(ValueError):
    """Raised for invalid field values (e.g. non-latin-1 name)."""
