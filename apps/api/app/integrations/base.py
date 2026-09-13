from abc import ABC, abstractmethod

from pydantic import BaseModel

from app.schemas.integrations import IntegrationHealth


class IntegrationError(RuntimeError):
    """A safe, user-facing integration failure."""


class Integration(ABC):
    integration_id: str
    name: str

    @abstractmethod
    def health(self) -> IntegrationHealth:
        """Return the integration's current normalized health."""

    @abstractmethod
    def summary(self) -> BaseModel:
        """Return a normalized integration summary."""
