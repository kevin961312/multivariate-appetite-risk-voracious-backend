"""Configuración de Voracious leída exclusivamente de variables de entorno ``VORACIOUS_*``."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    """Ajustes del proceso, inmutables una vez construidos.

    No se lee ningún ``.env``: el entorno (shell, Docker, orquestador) es la única fuente,
    para que local, CI y producción se configuren igual.

    Attributes:
        log_level: Nivel mínimo de los logs estructurados.
    """

    model_config = SettingsConfigDict(env_prefix="VORACIOUS_", extra="ignore", frozen=True)

    log_level: LogLevel = "INFO"
