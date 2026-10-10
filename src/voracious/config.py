"""Configuración de Voracious leída exclusivamente de variables de entorno ``VORACIOUS_*``."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
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
            todos los CPU visibles). Con réplicas en procesos conviene fijarlo (procesos por hilos):
            ``container`` lo pasa a la carta (cada ajuste MRCD) y el reparto en procesos lo fija
            en cada proceso (``PYMRCD_NUM_THREADS``).
        job_backend: Adaptador de la cola de trabajos (hoy solo ``inline``).
        repository: Adaptador de los repositorios: ``memory`` (en el proceso) o ``postgres``
            (Paso 4.2; exige ``database_url`` y ``storage=local``).
        storage: Almacenamiento de datasets: ``memory`` (en el proceso) o ``local`` (``.npy`` en
            disco con huella, mejora M6).
        storage_dir: Directorio base de ``storage=local`` (``VORACIOUS_STORAGE_DIR``);
            obligatorio con ``local``.
        replicate_processes: Procesos para repartir las réplicas bootstrap; ``None`` = en serie.
            Rendimiento: el resultado es idéntico bit a bit con cualquier valor.
        queue_workers_estimation: Hilos del carril ``estimation`` de la cola.
        queue_workers_calibration: Hilos del carril ``calibration``.
        queue_workers_light: Hilos del carril ``light``.
        queue_workers_orchestration: Hilos del carril ``orchestration``.
        max_upload_mb: Tamaño máximo del cuerpo de una subida de dataset (``POST /v1/datasets``)
            en MiB; por encima, ``413 PAYLOAD_TOO_LARGE``.
        database_url: Cadena de conexión de Postgres (``VORACIOUS_DATABASE_URL``, formato
            ``postgresql://usuario:contraseña@host:5432/base``). Secreto: ``SecretStr`` no la
            muestra en ``repr`` ni en logs. Obligatoria con ``repository=postgres``.
        database_pool_size: Conexiones máximas del pool (``VORACIOUS_DATABASE_POOL_SIZE``).
            Rendimiento, no estadístico: cubre los hilos de la cola y los de la API.
    """

    model_config = SettingsConfigDict(
        env_prefix="VORACIOUS_", extra="ignore", frozen=True, env_ignore_empty=True
    )

    log_level: LogLevel = "INFO"
    mrcd_threads: int | None = Field(default=None, ge=1)
    job_backend: Literal["inline"] = "inline"
    repository: Literal["memory", "postgres"] = "memory"
    storage: Literal["memory", "local"] = "memory"
    storage_dir: Path | None = None
    replicate_processes: int | None = Field(default=None, ge=1)
    queue_workers_estimation: int = Field(default=1, ge=1)
    queue_workers_calibration: int = Field(default=1, ge=1)
    queue_workers_light: int = Field(default=4, ge=1)
    queue_workers_orchestration: int = Field(default=2, ge=1)
    max_upload_mb: int = Field(default=50, ge=1)
    database_url: SecretStr | None = None
    database_pool_size: int = Field(default=10, ge=1)
