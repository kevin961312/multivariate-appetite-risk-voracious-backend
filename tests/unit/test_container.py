import dataclasses
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import structlog

from voracious.application.auth import AuthenticationError, AuthFailure, Role
from voracious.application.errors import FitNotFoundError
from voracious.application.ports import JobKind, JobRequest
from voracious.application.use_cases import RunFitJob, RunLimitsJob
from voracious.config import Settings
from voracious.container import (
    ConfigurationError,
    Container,
    build_container,
    generate_signing_key,
    issue_token,
    oversubscribed,
)
from voracious.domain.common import SerialTaskMapper
from voracious.infrastructure.auth import JwtTokenVerifier
from voracious.infrastructure.clock import SystemClock
from voracious.infrastructure.ids import UuidIdGenerator
from voracious.infrastructure.memory import InMemoryDatasetStorage
from voracious.infrastructure.parallel import ProcessPoolTaskMapper
from voracious.infrastructure.storage import LocalDatasetStorage


@pytest.fixture(autouse=True)
def _reset_structlog() -> None:
    structlog.reset_defaults()


def test_build_container_uses_given_settings() -> None:
    settings = Settings(log_level="WARNING")
    assert build_container(settings).settings is settings


def test_build_container_reads_env_when_no_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORACIOUS_LOG_LEVEL", "ERROR")
    assert build_container().settings.log_level == "ERROR"


def test_container_wires_use_cases_and_handlers() -> None:
    container = build_container(Settings())
    try:
        assert set(container.charts) == {"t2mrcd"}
        assert set(container.handlers) == {
            JobKind.MRCD_FIT,
            JobKind.LIMITS,
            JobKind.EXCLUSION,
            JobKind.MODEL_ASSEMBLY,
            JobKind.PIPELINE,
            JobKind.SCORE,
            JobKind.VERSION_PROPOSAL,
        }
        assert isinstance(container.use_cases.request_fit.ids, UuidIdGenerator)
        assert isinstance(container.use_cases.status.clock, SystemClock)
    finally:
        container.shutdown()


def test_job_admission_is_shared_and_uses_the_configured_quota() -> None:
    default = build_container(Settings())
    custom = build_container(Settings(max_active_jobs_per_tenant=7))
    try:
        assert default.use_cases.request_fit.admission.max_active == 4
        uc = custom.use_cases
        admissions = [
            uc.request_fit.admission,
            uc.request_limits.admission,
            uc.request_pipeline.admission,
            uc.request_recalibration.admission,
        ]
        assert all(a is admissions[0] for a in admissions)  # un solo cupo por proceso
        assert admissions[0].max_active == 7
        assert admissions[0].fits is uc.request_fit.fits
        assert admissions[0].limits is uc.request_limits.limits
        assert admissions[0].pipelines is uc.request_pipeline.pipelines
    finally:
        default.shutdown()
        custom.shutdown()


def test_mapper_is_serial_or_processes() -> None:
    serial = build_container(Settings())
    procs = build_container(Settings(replicate_processes=2, mrcd_threads=1))
    try:
        assert isinstance(_mapper_of(serial), SerialTaskMapper)
        mapper = _mapper_of(procs)
        assert isinstance(mapper, ProcessPoolTaskMapper)
        assert (mapper.max_workers, mapper.mrcd_threads) == (2, 1)
    finally:
        serial.shutdown()
        procs.shutdown()


def _mapper_of(container: Container) -> object:
    handler = container.handlers[JobKind.LIMITS]
    run = getattr(handler, "__self__", None)
    assert isinstance(run, RunLimitsJob)
    return run.mapper


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("job_backend", "celery", "JOB_BACKEND"),
        ("repository", "mongo", "REPOSITORY"),
        ("storage", "s3", "STORAGE"),
    ],
)
def test_unknown_adapter_fails_at_startup(field: str, value: str, match: str) -> None:
    settings = Settings.model_construct(**{**Settings().model_dump(), field: value})
    with pytest.raises(ConfigurationError, match=match):
        build_container(settings)


def test_oversubscription_warns(capsys: pytest.CaptureFixture[str]) -> None:
    assert not oversubscribed(Settings(), 8)
    assert not oversubscribed(Settings(replicate_processes=2), None)
    assert oversubscribed(Settings(replicate_processes=2), 8)  # hilos = todos los núcleos
    assert not oversubscribed(Settings(replicate_processes=2, mrcd_threads=4), 8)
    assert oversubscribed(Settings(replicate_processes=4, mrcd_threads=4), 8)
    # build_container configura structlog (JSON a stdout), así que se lee la salida.
    build_container(Settings(replicate_processes=64, mrcd_threads=64)).shutdown()
    assert '"event": "replicate_oversubscription"' in capsys.readouterr().out


def test_handle_dispatches_and_rejects_unknown_kind() -> None:
    container = build_container(Settings())
    try:
        with pytest.raises(FitNotFoundError):
            container.handle(JobRequest(JobKind.MRCD_FIT, "t", "t2mrcd", "nope"))
        without = dataclasses.replace(container, handlers={})
        with pytest.raises(ValueError, match="manejador"):
            without.handle(JobRequest(JobKind.MRCD_FIT, "t", "t2mrcd", "x"))
    finally:
        container.shutdown()


def test_charts_receive_mrcd_threads_and_repositories_encode_models() -> None:
    from voracious.infrastructure.memory import ModelRecordCodec

    container = build_container(Settings(mrcd_threads=2))
    try:
        chart = container.charts["t2mrcd"]
        assert getattr(chart, "mrcd_threads", None) == 2
        handler = container.handlers[JobKind.MRCD_FIT]
        run = getattr(handler, "__self__", None)
        assert isinstance(run, RunFitJob)
        assert getattr(run.steps["t2mrcd"], "chart", None) is chart
        model_store = getattr(container.use_cases.get_model.models, "_store", None)
        assert isinstance(getattr(model_store, "codec", None), ModelRecordCodec)
    finally:
        container.shutdown()


def test_local_storage_needs_a_directory(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="STORAGE_DIR"):
        build_container(Settings(storage="local"))
    container = build_container(Settings(storage="local", storage_dir=tmp_path / "ds"))
    try:
        storage = container.use_cases.upload_dataset.datasets
        assert isinstance(storage, LocalDatasetStorage)
        assert storage.base_dir == tmp_path / "ds"
    finally:
        container.shutdown()


def test_memory_storage_by_default() -> None:
    container = build_container(Settings())
    try:
        assert isinstance(container.use_cases.upload_dataset.datasets, InMemoryDatasetStorage)
    finally:
        container.shutdown()


def test_postgres_needs_url_and_local_storage(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        build_container(Settings(repository="postgres"))
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        build_container(Settings(repository="postgres", database_url=""))
    with pytest.raises(ConfigurationError, match="STORAGE=local"):
        build_container(Settings(repository="postgres", database_url="postgresql://x@h/db"))


def test_memory_container_has_no_database_check(tmp_path: Path) -> None:
    memory = build_container(Settings())
    local = build_container(Settings(storage="local", storage_dir=tmp_path))
    try:
        assert memory.check_readiness() == {}
        assert local.check_readiness() == {"storage": True}
        assert memory.startup() == dict.fromkeys(
            (
                "fits",
                "limits",
                "exclusions",
                "pipelines",
                "models",
                "scores",
                "recalibrations",
                "versions",
            ),
            0,
        )
    finally:
        memory.shutdown()
        local.shutdown()


# --- seguridad mínima: URL en fichero, verificador y CLI ----------------------------------------


def test_database_url_file_is_read_and_stripped(tmp_path: Path) -> None:
    secret = tmp_path / "database_url"
    secret.write_text("  postgresql://u:muy-secreta@127.0.0.1:1/db\n", encoding="utf-8")
    # La URL se acepta (el error siguiente es de almacenamiento, no de la URL).
    with pytest.raises(ConfigurationError, match="STORAGE=local"):
        build_container(Settings(repository="postgres", database_url_file=secret))
    built = build_container(
        Settings(
            repository="postgres",
            database_url_file=secret,
            storage="local",
            storage_dir=tmp_path / "ds",
        )
    )
    built.shutdown(wait=False)


def test_database_url_and_its_file_are_exclusive_and_errors_hide_the_content(
    tmp_path: Path,
) -> None:
    secret = tmp_path / "database_url"
    secret.write_text("postgresql://u:muy-secreta@h/db", encoding="utf-8")
    both = Settings(
        repository="postgres", database_url="postgresql://x@h/db", database_url_file=secret
    )
    with pytest.raises(ConfigurationError, match="excluyentes") as info:
        build_container(both)
    assert "muy-secreta" not in str(info.value)
    blank = tmp_path / "blank"
    blank.write_text(" \n\t\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="vacío") as info:
        build_container(Settings(repository="postgres", database_url_file=blank))
    assert str(blank) in str(info.value)
    missing = tmp_path / "no-existe"
    with pytest.raises(ConfigurationError, match="no se puede leer") as info:
        build_container(Settings(repository="postgres", database_url_file=missing))
    assert str(missing) in str(info.value)
    with pytest.raises(ConfigurationError, match="no se puede leer"):
        build_container(Settings(repository="postgres", database_url_file=tmp_path))


def test_without_jwks_there_is_no_verifier() -> None:
    container = build_container(Settings())
    try:
        assert container.token_verifier is None
    finally:
        container.shutdown()


def test_jwks_configuration_errors(tmp_path: Path) -> None:
    from support.auth import JWKS_FILE, PUBLIC_JWK

    with pytest.raises(ConfigurationError, match="VORACIOUS_JWT_ISSUER"):
        build_container(Settings(jwt_jwks_file=JWKS_FILE, jwt_audience="a"))
    with pytest.raises(ConfigurationError, match="VORACIOUS_JWT_ISSUER"):
        build_container(Settings(jwt_jwks_file=JWKS_FILE, jwt_issuer="i"))
    missing = tmp_path / "jwks.json"
    with pytest.raises(ConfigurationError, match="no se puede leer") as info:
        build_container(Settings(jwt_jwks_file=missing, jwt_issuer="i", jwt_audience="a"))
    assert str(missing) in str(info.value)
    leaked = tmp_path / "leaked.json"
    leaked.write_text(json.dumps({"keys": [{**PUBLIC_JWK, "d": "PRIVADO"}]}), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="privados") as info:
        build_container(Settings(jwt_jwks_file=leaked, jwt_issuer="i", jwt_audience="a"))
    assert "PRIVADO" not in str(info.value)
    with pytest.raises(ConfigurationError, match="'alg' permitido"):
        build_container(
            Settings(
                jwt_jwks_file=JWKS_FILE,
                jwt_issuer="i",
                jwt_audience="a",
                jwt_algorithms=("RS256",),
            )
        )


def test_jwks_gives_a_verifier() -> None:
    from support.auth import auth_settings, token

    container = build_container(auth_settings())
    try:
        assert isinstance(container.token_verifier, JwtTokenVerifier)
        assert container.token_verifier.verify(token("t-1")).tenant_id == "t-1"
    finally:
        container.shutdown()


def test_issue_token_uses_the_configured_issuer_and_checks_the_jwks() -> None:
    from support.auth import OTHER_KEY_PEM, PRIVATE_KEY_PEM, TEST_KID, auth_settings

    settings = auth_settings()
    kwargs: dict[str, Any] = {
        "subject": "ana",
        "tenant_id": "demo",
        "roles": (Role.ANALYST,),
        "ttl": timedelta(hours=1),
    }
    raw = issue_token(PRIVATE_KEY_PEM, kid=TEST_KID, settings=settings, **kwargs)
    verifier = build_container(settings).token_verifier
    assert verifier is not None
    assert verifier.verify(raw).subject == "ana"
    with pytest.raises(AuthenticationError) as info:
        issue_token(PRIVATE_KEY_PEM, kid="otro-kid", settings=settings, **kwargs)
    assert info.value.reason is AuthFailure.UNKNOWN_KEY
    with pytest.raises(AuthenticationError) as info:
        issue_token(OTHER_KEY_PEM, kid=TEST_KID, settings=settings, **kwargs)
    assert info.value.reason is AuthFailure.BAD_SIGNATURE
    # Sin JWKS se emite igual (no hay con qué comprobarlo).
    plain = Settings(jwt_issuer="i", jwt_audience="a")
    assert issue_token(PRIVATE_KEY_PEM, kid="cualquiera", settings=plain, **kwargs).count(".") == 2
    with pytest.raises(ConfigurationError, match="VORACIOUS_JWT_ISSUER"):
        issue_token(PRIVATE_KEY_PEM, kid=TEST_KID, settings=Settings(), **kwargs)
    with pytest.raises(ValueError, match="vida"):
        issue_token(
            PRIVATE_KEY_PEM, kid=TEST_KID, settings=settings, **{**kwargs, "ttl": timedelta(days=8)}
        )


def test_issue_token_reports_invalid_variables_as_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from support.auth import PRIVATE_KEY_PEM

    monkeypatch.setenv("VORACIOUS_JWT_ALGORITHMS", "HS256")
    with pytest.raises(ConfigurationError, match="jwt_algorithms"):
        issue_token(
            PRIVATE_KEY_PEM,
            kid="k",
            subject="s",
            tenant_id="t",
            roles=(Role.ADMIN,),
            ttl=timedelta(hours=1),
        )


def test_generate_signing_key_extends_the_jwks() -> None:
    pem, first = generate_signing_key("k1", None)
    assert pem.startswith(b"-----BEGIN PRIVATE KEY-----")
    _, second = generate_signing_key("k2", first)
    assert [k["kid"] for k in json.loads(second)["keys"]] == ["k1", "k2"]
    assert "PRIVATE" not in second
    with pytest.raises(ValueError, match="ya está"):
        generate_signing_key("k1", second)
