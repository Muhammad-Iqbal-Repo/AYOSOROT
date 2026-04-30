# agent/exceptions.py
"""
Typed exceptions for every failure mode the agent can encounter.
Each maps to a distinct, user-friendly message in app.py.
"""


class AgentError(Exception):
    """Base class for all agent errors."""


class ConfigurationError(AgentError):
    """Missing or invalid API key / environment config."""


class EmptyResponseError(AgentError):
    """Gemini returned an empty or whitespace-only response."""


class SafetyBlockError(AgentError):
    """Gemini refused the request due to safety filters."""


class ParseError(AgentError):
    """Response was received but could not be parsed into a PersonProfile."""


class QuotaExceededError(AgentError):
    """API quota or rate limit has been hit."""


class ApiError(AgentError):
    """Catch-all for unexpected HTTP/SDK errors from the Gemini API."""


class ModelNotAvailableError(AgentError):
    """Configured model is not available for this API key."""
