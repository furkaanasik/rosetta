"""Error hierarchy. Every engine error derives from RosettaError; the service decides by type."""


class RosettaError(Exception):
    """Base class for all Rosetta errors."""


class ConfigError(RosettaError):
    """``config.toml`` could not be parsed or validated."""


class ExtractionError(RosettaError):
    """A PDF page could not be extracted (no text layer, out of range, unreadable)."""


class ProviderError(RosettaError):
    """Generic translation provider failure.

    Carries the usage the provider reported for the failed call (0 when unknown), so the
    service can record what was actually spent.
    """

    def __init__(
        self, message: str, *, input_tokens: int = 0, output_tokens: int = 0, cost_usd: float = 0.0
    ) -> None:
        super().__init__(message)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost_usd = cost_usd


class ProviderUnavailableError(ProviderError):
    """The provider cannot run at all (e.g. ``claude`` not on PATH). The job stops."""


class UsageLimitError(ProviderError):
    """Subscription/rate limit hit. The job stops; no retry."""


class BudgetExceededError(ProviderError):
    """The per-call ``--max-budget-usd`` cap was hit. The job stops; no retry."""


class ProviderAuthError(ProviderError):
    """Provider is not authenticated. The job stops; the user must log in."""


class InvalidTranslationError(ProviderError):
    """Provider answered, but the payload failed validation (JSON, ids, types). Retried once."""

    def __init__(
        self,
        reason: str,
        raw: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        super().__init__(
            reason, input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd
        )
        self.reason = reason
        self.raw = raw
