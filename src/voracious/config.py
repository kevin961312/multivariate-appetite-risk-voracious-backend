"""Configuración de Voracious leída exclusivamente de variables de entorno ``VORACIOUS_*``."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    """Ajustes del proceso, inmutables una vez construidos.

    No se lee ningún ``.env``: el entorno (shell, Docker, orquestador) es la única fuente,
    para que local, CI y producción se configuren igual.

    Una variable definida pero vacía (``VORACIOUS_X=``) cuenta como no definida
    (``env_ignore_empty``), así la plantilla ``.env.example`` puede dejar campos sin valor.

    Attributes:
        log_level: Nivel mínimo de los logs estructurados.
        mrcd_threads: Hilos de la extensión C de ``pymrcd`` (``Qn`` y OGK) en cada ajuste MRCD.
            Parámetro de **rendimiento**, no estadístico: el ajuste es idéntico bit a bit con
            cualquier valor (``docs/metodos/mrcd-especificacion.md`` §3.12.9 e) y no se guarda en
            las versiones de la carta. ``None`` ⇒ ``pymrcd`` decide (``PYMRCD_NUM_THREADS`` o
            todos los CPU visibles). Con réplicas en procesos conviene fijarlo (procesos por hilos).
            El cableado en ``container`` llega en el Paso 3.
    """

    model_config = SettingsConfigDict(
        env_prefix="VORACIOUS_", extra="ignore", frozen=True, env_ignore_empty=True
    )

    log_level: LogLevel = "INFO"
    mrcd_threads: int | None = Field(default=None, ge=1)
