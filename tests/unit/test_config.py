from pathlib import Path

import pytest
from pydantic import ValidationError

from voracious.config import Settings


def test_log_level_default_is_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VORACIOUS_LOG_LEVEL", raising=False)
    assert Settings().log_level == "INFO"


def test_log_level_is_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORACIOUS_LOG_LEVEL", "DEBUG")
    assert Settings().log_level == "DEBUG"


def test_invalid_log_level_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORACIOUS_LOG_LEVEL", "VERBOSE")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_are_frozen() -> None:
    assert Settings.model_config.get("frozen") is True


def test_mrcd_threads_default_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VORACIOUS_MRCD_THREADS", raising=False)
    assert Settings().mrcd_threads is None


def test_mrcd_threads_empty_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORACIOUS_MRCD_THREADS", "")
    assert Settings().mrcd_threads is None


def test_mrcd_threads_is_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORACIOUS_MRCD_THREADS", "4")
    assert Settings().mrcd_threads == 4


@pytest.mark.parametrize("value", ["0", "-1", "dos"])
def test_invalid_mrcd_threads_raises(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("VORACIOUS_MRCD_THREADS", value)
    with pytest.raises(ValidationError):
        Settings()


def test_paso3_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "JOB_BACKEND",
        "REPOSITORY",
        "STORAGE",
        "REPLICATE_PROCESSES",
        "QUEUE_WORKERS_LIGHT",
        "MAX_UPLOAD_MB",
    ):
        monkeypatch.delenv(f"VORACIOUS_{name}", raising=False)
    s = Settings()
    assert (s.job_backend, s.repository, s.storage) == ("inline", "memory", "memory")
    assert s.replicate_processes is None
    assert (
        s.queue_workers_estimation,
        s.queue_workers_calibration,
        s.queue_workers_light,
        s.queue_workers_orchestration,
    ) == (1, 1, 4, 2)
    assert s.max_upload_mb >= 1


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("JOB_BACKEND", "celery"),
        ("REPOSITORY", "mongo"),
        ("DATABASE_POOL_SIZE", "0"),
        ("STORAGE", "s3"),
        ("REPLICATE_PROCESSES", "0"),
        ("QUEUE_WORKERS_LIGHT", "0"),
        ("MAX_UPLOAD_MB", "0"),
    ],
)
def test_invalid_paso3_values_fail(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(f"VORACIOUS_{name}", value)
    with pytest.raises(ValidationError):
        Settings()


def test_replicate_processes_is_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORACIOUS_REPLICATE_PROCESSES", "3")
    assert Settings().replicate_processes == 3


def test_storage_dir_is_read_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VORACIOUS_STORAGE", "local")
    monkeypatch.setenv("VORACIOUS_STORAGE_DIR", str(tmp_path))
    s = Settings()
    assert (s.storage, s.storage_dir) == ("local", tmp_path)
    assert Settings.model_construct().storage_dir is None


def test_database_url_is_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "postgresql://usuario:clave-muy-secreta@db:5432/voracious"
    monkeypatch.setenv("VORACIOUS_REPOSITORY", "postgres")
    monkeypatch.setenv("VORACIOUS_DATABASE_URL", url)
    monkeypatch.setenv("VORACIOUS_DATABASE_POOL_SIZE", "3")
    settings = Settings()
    assert settings.repository == "postgres"
    assert settings.database_pool_size == 3
    assert settings.database_url is not None
    assert settings.database_url.get_secret_value() == url
    assert "clave-muy-secreta" not in repr(settings)
    assert "clave-muy-secreta" not in str(settings)


# --- seguridad mínima: JWT y URL en fichero ---------------------------------------------------


def test_auth_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "JWT_JWKS_FILE",
        "JWT_ISSUER",
        "JWT_AUDIENCE",
        "JWT_ALGORITHMS",
        "JWT_LEEWAY_SECONDS",
        "DATABASE_URL_FILE",
    ):
        monkeypatch.delenv(f"VORACIOUS_{name}", raising=False)
    s = Settings()
    assert (s.jwt_jwks_file, s.jwt_issuer, s.jwt_audience, s.database_url_file) == (
        None,
        None,
        None,
        None,
    )
    assert s.jwt_algorithms == ("EdDSA",)
    assert s.jwt_leeway_seconds == 30


def test_auth_is_read_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VORACIOUS_JWT_JWKS_FILE", str(tmp_path / "jwks.json"))
    monkeypatch.setenv("VORACIOUS_JWT_ISSUER", "voracious-demo")
    monkeypatch.setenv("VORACIOUS_JWT_AUDIENCE", "voracious-api")
    monkeypatch.setenv("VORACIOUS_JWT_ALGORITHMS", "EdDSA, ES256,RS256,PS256")
    monkeypatch.setenv("VORACIOUS_JWT_LEEWAY_SECONDS", "0")
    monkeypatch.setenv("VORACIOUS_DATABASE_URL_FILE", "/run/secrets/database_url")
    s = Settings()
    assert s.jwt_jwks_file == tmp_path / "jwks.json"
    assert (s.jwt_issuer, s.jwt_audience) == ("voracious-demo", "voracious-api")
    assert s.jwt_algorithms == ("EdDSA", "ES256", "RS256", "PS256")
    assert s.jwt_leeway_seconds == 0
    assert s.database_url_file == Path("/run/secrets/database_url")


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("JWT_ALGORITHMS", "HS256"),
        ("JWT_ALGORITHMS", "none"),
        ("JWT_ALGORITHMS", "EdDSA,HS512"),
        ("JWT_ALGORITHMS", " , "),
        ("JWT_LEEWAY_SECONDS", "-1"),
        ("JWT_LEEWAY_SECONDS", "301"),
        ("JWT_ISSUER", "x" * 257),
    ],
)
def test_invalid_auth_values_fail(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(f"VORACIOUS_{name}", value)
    with pytest.raises(ValidationError):
        Settings()


def test_empty_auth_variables_count_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORACIOUS_JWT_ISSUER", "")
    monkeypatch.setenv("VORACIOUS_JWT_ALGORITHMS", "")
    s = Settings()
    assert s.jwt_issuer is None
    assert s.jwt_algorithms == ("EdDSA",)
    assert Settings(jwt_algorithms=("RS256",)).jwt_algorithms == ("RS256",)


# --- paso E: proxy, límite de peticiones, CORS, documentación y cupo por tenant ---------------


def test_paso_e_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "TRUSTED_PROXIES",
        "RATE_LIMIT_PER_MINUTE",
        "RATE_LIMIT_BURST",
        "CORS_ALLOWED_ORIGINS",
        "API_DOCS",
        "MAX_ACTIVE_JOBS_PER_TENANT",
    ):
        monkeypatch.delenv(f"VORACIOUS_{name}", raising=False)
    s = Settings()
    assert s.trusted_proxies == ()
    assert (s.rate_limit_per_minute, s.rate_limit_burst) == (600, 120)
    assert s.cors_allowed_origins == ()
    assert s.api_docs is True
    assert s.max_active_jobs_per_tenant == 4


def test_paso_e_values_are_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORACIOUS_TRUSTED_PROXIES", "172.29.80.10, 10.0.0.0/8,fd00::/8")
    monkeypatch.setenv("VORACIOUS_RATE_LIMIT_PER_MINUTE", "60")
    monkeypatch.setenv("VORACIOUS_RATE_LIMIT_BURST", "5")
    monkeypatch.setenv(
        "VORACIOUS_CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000"
    )
    monkeypatch.setenv("VORACIOUS_API_DOCS", "false")
    monkeypatch.setenv("VORACIOUS_MAX_ACTIVE_JOBS_PER_TENANT", "1")
    s = Settings()
    assert [str(n) for n in s.trusted_proxies] == ["172.29.80.10/32", "10.0.0.0/8", "fd00::/8"]
    assert (s.rate_limit_per_minute, s.rate_limit_burst) == (60, 5)
    assert s.cors_allowed_origins == ("http://localhost:5173", "http://localhost:3000")
    assert s.api_docs is False
    assert s.max_active_jobs_per_tenant == 1


def test_empty_paso_e_lists_are_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORACIOUS_TRUSTED_PROXIES", "")
    monkeypatch.setenv("VORACIOUS_CORS_ALLOWED_ORIGINS", " , ")
    s = Settings()
    assert (s.trusted_proxies, s.cors_allowed_origins) == ((), ())


@pytest.mark.parametrize(
    "value",
    ["*", "proxy", "api.voracious.cloud", "172.29.80.300", "10.0.0.1/8", "0.0.0.0/0", "::/0"],
)
def test_invalid_trusted_proxies_fail(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Nunca un literal que no coincide sin avisar (uvicorn convierte lo que no es IP en texto)."""
    monkeypatch.setenv("VORACIOUS_TRUSTED_PROXIES", f"172.29.80.10,{value}")
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RATE_LIMIT_PER_MINUTE", "0"),
        ("RATE_LIMIT_BURST", "0"),
        ("MAX_ACTIVE_JOBS_PER_TENANT", "0"),
        ("API_DOCS", "quizá"),
    ],
)
def test_invalid_paso_e_values_fail(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(f"VORACIOUS_{name}", value)
    with pytest.raises(ValidationError):
        Settings()


def test_cors_origins_are_lowercased_and_deduplicated() -> None:
    s = Settings(
        cors_allowed_origins=(
            "HTTPS://Voracious.Cloud",
            "https://voracious.cloud",
            "http://[::1]:5173",
            "http://127.0.0.1:8080",
            "https://front.voracious.cloud:8443",
        )
    )
    assert s.cors_allowed_origins == (
        "https://voracious.cloud",
        "http://[::1]:5173",
        "http://127.0.0.1:8080",
        "https://front.voracious.cloud:8443",
    )


@pytest.mark.parametrize("value", ["*", " * ", ("*",)])
def test_a_lone_star_allows_any_origin(value: str | tuple[str, ...]) -> None:
    """Decisión del dueño (2026-10-20): cualquier front; la barrera es el token portador."""
    assert Settings(cors_allowed_origins=value).cors_allowed_origins == ("*",)


@pytest.mark.parametrize(
    "value", ["*,https://voracious.cloud", "http://localhost:5173, *", "*,*", "*,null"]
)
def test_the_star_mixed_with_other_origins_fails(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("VORACIOUS_CORS_ALLOWED_ORIGINS", value)
    with pytest.raises(ValidationError, match="va solo"):
        Settings()


@pytest.mark.parametrize(
    "origin",
    [
        "**",
        "https://*",
        "https://*.voracious.cloud",
        "null",
        "https://voracious.cloud/",
        "https://voracious.cloud/app",
        "https://voracious.cloud?x=1",
        "https://voracious.cloud?",
        "https://voracious.cloud#f",
        "https://user:pass@voracious.cloud",
        "https://user@voracious.cloud",
        "ftp://voracious.cloud",
        "voracious.cloud",
        "//voracious.cloud",
        "http://voracious.cloud",  # público sin TLS
        "http://192.168.1.10:5173",
        "https://voracious.cloud:443",  # puerto por defecto: el navegador no lo envía
        "http://localhost:80",
        "https://voracious.cloud:",
        "https://voracious.cloud:0",
        "https://voracious.cloud:99999",
        "https://voracious.cloud:08443",
        "https://127.1",
        "https://[0:0:0:0:0:0:0:1]",
        "https://voracious..cloud",
        "https://voracious.cloud.",
        "https://-voracious.cloud",
        "https://vorácious.cloud",
        "https://vora cious.cloud",
        "https://",
    ],
)
def test_invalid_cors_origins_fail(monkeypatch: pytest.MonkeyPatch, origin: str) -> None:
    monkeypatch.setenv("VORACIOUS_CORS_ALLOWED_ORIGINS", f"http://localhost:5173,{origin}")
    with pytest.raises(ValidationError):
        Settings()
