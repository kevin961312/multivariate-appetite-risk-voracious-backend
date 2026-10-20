"""Configuración de Voracious leída exclusivamente de variables de entorno ``VORACIOUS_*``."""

import ipaddress
import re
from pathlib import Path
from typing import Annotated, Final, Literal
from urllib.parse import urlsplit

from pydantic import Field, IPvAnyNetwork, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

JwtAlgorithm = Literal["EdDSA", "ES256", "RS256", "PS256"]
"""Algoritmos de firma asimétrica admitidos (D2). Nunca ``none`` ni ``HS*``: una llave
compartida permitiría firmar a quien solo debe verificar."""

CORS_ANY_ORIGIN: Final = "*"
"""Valor de ``VORACIOUS_CORS_ALLOWED_ORIGINS`` que admite cualquier origen (va solo, sin otros).

Es seguro porque la API autentica con ``Authorization: Bearer`` y sin credenciales de CORS: el
navegador nunca manda el token por su cuenta (no hay cookies), así que un origen ajeno no puede
llamar en nombre del usuario (dueño, 2026-10-20)."""

_LOOPBACK_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "::1"})
"""Únicos hosts con los que un origen CORS puede ser ``http``: todo origen público va por TLS."""

_DNS_LABEL: Final = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
"""Etiqueta DNS en minúsculas (un nombre internacional se escribe en punycode, como lo envía el
navegador en ``Origin``)."""


def _split_commas(value: object) -> object:
    """Admite ``a, b,c`` en una variable de entorno (sin JSON).

    Args:
        value: Valor crudo (cadena desde el entorno o secuencia desde el código).

    Returns:
        La secuencia de elementos, sin espacios ni elementos vacíos; cualquier otro valor, intacto.
    """
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    return value


def _valid_host(host: str) -> bool:
    """Indica si ``host`` es una IP o un nombre DNS escrito como lo serializa el navegador.

    Args:
        host: Host en minúsculas, sin corchetes.

    Returns:
        ``True`` si es una IPv4, una IPv6 en forma comprimida o un nombre DNS válido.
    """
    try:
        return str(ipaddress.ip_address(host)) == host
    except ValueError:
        pass
    if re.fullmatch(r"[0-9.]+", host) or len(host) > 253:
        # Solo dígitos y puntos sin ser una IPv4 canónica (``127.1``): el navegador la reescribe.
        return False
    return all(_DNS_LABEL.fullmatch(label) for label in host.split("."))


def _normalize_origin(raw: str) -> str:
    """Valida y normaliza un origen CORS (``esquema://host[:puerto]``).

    Args:
        raw: Origen tal como viene de la configuración.

    Returns:
        El origen en minúsculas, exactamente como lo envía un navegador en ``Origin``.

    Raises:
        ValueError: Si es ``*`` o un comodín, ``null``, lleva ruta (también la barra final),
            query, fragmento o credenciales, el esquema no es ``http``/``https``, el puerto es
            inválido o el de por defecto, o es ``http`` fuera de ``localhost``, ``127.0.0.1`` y
            ``[::1]``.
    """
    origin = raw.strip().lower()
    if "*" in origin:
        msg = (
            f"origen CORS {raw!r}: no se admiten comodines parciales; usa '*' solo (cualquier "
            "origen) o lista cada origen"
        )
        raise ValueError(msg)
    if origin == "null":
        msg = "origen CORS 'null': no se admite (lo envían documentos sin origen propio)"
        raise ValueError(msg)
    parts = urlsplit(origin)
    if parts.scheme not in {"http", "https"}:
        msg = f"origen CORS {raw!r}: el esquema debe ser http o https"
        raise ValueError(msg)
    host = parts.hostname or ""
    try:
        port = parts.port
    except ValueError:
        port = 0
    default_port = 443 if parts.scheme == "https" else 80
    if not _valid_host(host) or port == 0 or port == default_port:
        msg = (
            f"origen CORS {raw!r}: debe ser exactamente esquema://host[:puerto], sin puerto "
            "por defecto"
        )
        raise ValueError(msg)
    netloc = f"[{host}]" if ":" in host else host
    canonical = f"{parts.scheme}://{netloc}" + (f":{port}" if port is not None else "")
    if origin != canonical:
        msg = (
            f"origen CORS {raw!r}: debe ser exactamente esquema://host[:puerto] (sin ruta ni barra "
            "final, query, fragmento ni credenciales)"
        )
        raise ValueError(msg)
    if parts.scheme == "http" and host not in _LOOPBACK_HOSTS:
        msg = f"origen CORS {raw!r}: un origen público debe ser https"
        raise ValueError(msg)
    return canonical


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
        database_url_file: Fichero con la cadena de conexión (``VORACIOUS_DATABASE_URL_FILE``):
            el secreto de Compose montado en ``/run/secrets/database_url``. Excluyente con
            ``database_url`` (que queda para desarrollo, CI y tests); ``container`` lo lee, quita
            los espacios de los extremos y exige que no quede vacío.
        database_pool_size: Conexiones máximas del pool (``VORACIOUS_DATABASE_POOL_SIZE``).
            Rendimiento, no estadístico: cubre los hilos de la cola y los de la API.
        jwt_jwks_file: JWKS con las llaves **públicas** que verifican los tokens
            (``VORACIOUS_JWT_JWKS_FILE``); cada llave con ``kid`` y ``alg``. Sin él la API no
            arranca. La llave privada nunca entra en la configuración (D11).
        jwt_issuer: Emisor exigido, comparado entero (claim ``iss``; ``VORACIOUS_JWT_ISSUER``).
        jwt_audience: Audiencia exigida, comparada entera (claim ``aud``;
            ``VORACIOUS_JWT_AUDIENCE``).
        jwt_algorithms: Algoritmos admitidos (``VORACIOUS_JWT_ALGORITHMS``, separados por comas;
            ``EdDSA`` por defecto). Al menos uno; solo asimétricos.
        jwt_leeway_seconds: Margen de reloj en segundos al comprobar ``exp``, ``nbf`` e ``iat``
            (``VORACIOUS_JWT_LEEWAY_SECONDS``, 0 a 300; 30 por defecto).
        trusted_proxies: IP o redes CIDR de los proxies cuyo ``X-Forwarded-For`` y
            ``X-Forwarded-Proto`` se creen (``VORACIOUS_TRUSTED_PROXIES``, separadas por comas;
            ``()`` por defecto: no se cree a nadie). Se validan al arrancar: ``*``, ``/0``, un
            nombre de host o una IP mal escrita fallan (nunca un literal que no coincide, mudo).
        rate_limit_per_minute: Peticiones por minuto y por IP de cliente
            (``VORACIOUS_RATE_LIMIT_PER_MINUTE``; 600 por defecto). Operativo, no estadístico.
        rate_limit_burst: Ráfaga admitida por IP de cliente, capacidad del cubo de fichas
            (``VORACIOUS_RATE_LIMIT_BURST``; 120 por defecto). Operativo, no estadístico.
        cors_allowed_origins: Orígenes de navegador admitidos por CORS
            (``VORACIOUS_CORS_ALLOWED_ORIGINS``, separados por comas; ``()`` por defecto: CORS
            cerrado). ``*`` solo (``CORS_ANY_ORIGIN``) admite cualquier origen; si no, cada uno
            exactamente ``esquema://host[:puerto]``, en minúsculas y sin repetidos; ``http`` solo
            en ``localhost``, ``127.0.0.1`` y ``[::1]``.
        api_docs: Sirve ``/docs``, ``/redoc`` y ``/openapi.json`` (``VORACIOUS_API_DOCS``; ``True``
            por defecto). Con ``False`` no existen y solo ``/health`` y ``/ready`` son públicas.
        max_active_jobs_per_tenant: Trabajos de cómputo en cola o en curso por tenant
            (``VORACIOUS_MAX_ACTIVE_JOBS_PER_TENANT``; 4 por defecto); por encima,
            ``429 TOO_MANY_JOBS``. Operativo, no estadístico.
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
    database_url_file: Path | None = None
    database_pool_size: int = Field(default=10, ge=1)
    jwt_jwks_file: Path | None = None
    jwt_issuer: str | None = Field(default=None, min_length=1, max_length=256)
    jwt_audience: str | None = Field(default=None, min_length=1, max_length=256)
    jwt_algorithms: Annotated[tuple[JwtAlgorithm, ...], NoDecode] = Field(
        default=("EdDSA",), min_length=1
    )
    jwt_leeway_seconds: int = Field(default=30, ge=0, le=300)
    trusted_proxies: Annotated[tuple[IPvAnyNetwork, ...], NoDecode] = ()
    rate_limit_per_minute: int = Field(default=600, ge=1)
    rate_limit_burst: int = Field(default=120, ge=1)
    cors_allowed_origins: Annotated[tuple[str, ...], NoDecode] = ()
    api_docs: bool = True
    max_active_jobs_per_tenant: int = Field(default=4, ge=1)

    @field_validator("jwt_algorithms", "trusted_proxies", "cors_allowed_origins", mode="before")
    @classmethod
    def _split_lists(cls, value: object) -> object:
        """Admite listas separadas por comas en la variable de entorno (sin JSON).

        Args:
            value: Valor crudo (cadena desde el entorno o secuencia desde el código).

        Returns:
            La secuencia de elementos, sin espacios ni elementos vacíos.
        """
        return _split_commas(value)

    @field_validator("trusted_proxies")
    @classmethod
    def _no_catch_all_proxy(cls, value: tuple[IPvAnyNetwork, ...]) -> tuple[IPvAnyNetwork, ...]:
        """Rechaza ``0.0.0.0/0`` y ``::/0``: confiar en todo el mundo equivale a ``*``.

        Args:
            value: Redes ya validadas.

        Returns:
            Las mismas redes.

        Raises:
            ValueError: Si alguna tiene prefijo 0.
        """
        if any(network.prefixlen == 0 for network in value):
            msg = "VORACIOUS_TRUSTED_PROXIES no admite /0: cualquiera podría falsificar su IP"
            raise ValueError(msg)
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def _normalize_origins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Valida cada origen, lo pasa a minúsculas y quita los repetidos (conserva el orden).

        Args:
            value: Orígenes crudos.

        Returns:
            ``("*",)`` si es ``*`` solo; si no, los orígenes normalizados.

        Raises:
            ValueError: Si ``*`` va con otros valores o algún origen no es válido.
        """
        if CORS_ANY_ORIGIN in value:
            if value != (CORS_ANY_ORIGIN,):
                msg = "VORACIOUS_CORS_ALLOWED_ORIGINS: '*' (cualquier origen) va solo, sin otros"
                raise ValueError(msg)
            return value
        return tuple(dict.fromkeys(_normalize_origin(origin) for origin in value))
