from __future__ import annotations


class AppError(Exception):
    """Base application error."""


class ParseError(AppError):
    """Raised when the input file cannot be parsed at all."""


class TournamentError(AppError):
    """Raised when tournament state transition is invalid."""
