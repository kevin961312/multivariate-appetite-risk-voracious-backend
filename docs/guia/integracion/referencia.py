"""Sección «Referencia de la API» de la guía de integración, generada desde el OpenAPI.

Uso (desde ``build.py`` u otro script; solo biblioteca estándar)::

    import json
    from referencia import referencia_html

    openapi = json.loads(Path("docs/guia/integracion/openapi.json").read_text(encoding="utf-8"))
    html = referencia_html(openapi)  # va dentro de <h1 id="referencia">…</h1>, sin el h1

El contrato (rutas, parámetros, cuerpos, esquemas y roles) sale del OpenAPI que escribe
``exportar_openapi.py``; los textos en español y los ejemplos se redactan aquí leyendo los routers
y los casos de uso. Los valores por defecto de la carta se leen del código fuente (``ast``, sin
importar ``voracious``) para que la guía no se desincronice de ``src/``. Cada ejemplo de petición
y de respuesta se **valida contra su esquema** antes de escribirse: si la API cambia y un ejemplo
deja de cumplirlo, la generación falla en lugar de publicar un ejemplo falso.
"""

import ast
import json
import re
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import cache
from html import escape
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parents[3] / "src" / "voracious"
"""Código fuente del backend (de él se leen los valores por defecto)."""

METODOS = ("get", "post", "put", "patch", "delete")
EXTENSION_ROLES = "x-voracious-roles"
PREFIJO_CARTA = "/v1/charts/t2mrcd"
MODELO = PREFIJO_CARTA + "/models/{model_id}"
ENTIDADES = re.compile(r"&amp;(times|minus|alpha|le|ge|middot|rarr|hellip|nbsp);")
"""Entidades HTML que los textos de este módulo pueden usar (se conservan tras escapar)."""


# --- valores por defecto, leídos del código fuente ------------------------------------------------


def _asignaciones(cuerpo: Sequence[ast.stmt]) -> Iterator[tuple[str, ast.expr]]:
    """Asignaciones simples (``X = v`` o ``X: T = v``) de un bloque de código.

    Args:
        cuerpo: Sentencias del módulo o de la clase.

    Yields:
        Pares (nombre, expresión del valor).
    """
    for nodo in cuerpo:
        if isinstance(nodo, ast.Assign) and len(nodo.targets) == 1:
            objetivo = nodo.targets[0]
            if isinstance(objetivo, ast.Name):
                yield objetivo.id, nodo.value
        elif (
            isinstance(nodo, ast.AnnAssign)
            and isinstance(nodo.target, ast.Name)
            and nodo.value is not None
        ):
            yield nodo.target.id, nodo.value


def _modulo(relativa: str) -> ast.Module:
    """Árbol sintáctico de un módulo de ``src/voracious``.

    Args:
        relativa: Ruta del módulo relativa a ``src/voracious``.

    Returns:
        El árbol.
    """
    return ast.parse((SRC / relativa).read_text(encoding="utf-8"))


def _literal(expresion: ast.expr, contexto: Mapping[str, ast.expr]) -> object:
    """Evalúa un literal, resolviendo un nombre de constante del mismo módulo y ``Field(default=)``.

    Args:
        expresion: Expresión del valor.
        contexto: Asignaciones de nivel de módulo (para resolver nombres).

    Returns:
        El valor.

    Raises:
        ValueError: Si la expresión no es un literal resoluble.
    """
    if isinstance(expresion, ast.Name) and expresion.id in contexto:
        return _literal(contexto[expresion.id], contexto)
    if isinstance(expresion, ast.Call):
        for palabra in expresion.keywords:
            if palabra.arg == "default":
                return _literal(palabra.value, contexto)
        msg = f"llamada sin default literal: {ast.unparse(expresion)}"
        raise ValueError(msg)
    return ast.literal_eval(expresion)


def constante(relativa: str, nombre: str, clase: str | None = None) -> object:
    """Valor por defecto declarado en el código fuente, sin importar el módulo.

    Args:
        relativa: Ruta del módulo relativa a ``src/voracious``.
        nombre: Constante de módulo o campo de ``clase``.
        clase: Clase que declara el campo (``None``: constante de módulo).

    Returns:
        El valor literal.

    Raises:
        LookupError: Si la constante o el campo no existen.
    """
    arbol = _modulo(relativa)
    contexto = dict(_asignaciones(arbol.body))
    cuerpo: Sequence[ast.stmt] = arbol.body
    if clase is not None:
        clases = [n for n in arbol.body if isinstance(n, ast.ClassDef) and n.name == clase]
        if not clases:
            msg = f"no existe la clase {clase} en {relativa}"
            raise LookupError(msg)
        cuerpo = clases[0].body
    for objetivo, valor in _asignaciones(cuerpo):
        if objetivo == nombre:
            return _literal(valor, contexto)
    msg = f"no existe {nombre} en {relativa}"
    raise LookupError(msg)


@dataclass(frozen=True)
class Defectos:
    """Valores por defecto de la carta y de la API, con el archivo de donde salen.

    Attributes:
        mrcd_alpha: ``alpha`` de MRCD bajo la carta.
        maxcsteps: Máximo de C-steps (``rrcov``).
        target: Matriz objetivo (``rrcov``).
        maxcond: Número de condición objetivo (``rrcov``).
        n_replicates: Réplicas bootstrap B.
        alpha_limit: Nivel del límite de Fase I.
        phase2_alpha_limit: Nivel del límite de Fase II.
        min_observations: Mínimo de observaciones nuevas de una recalibración.
        revalidate_every_months: Meses de la revalidación periódica.
        max_upload_mb: Máximo del cuerpo de una subida (MiB).
    """

    mrcd_alpha: object
    maxcsteps: object
    target: object
    maxcond: object
    n_replicates: object
    alpha_limit: object
    phase2_alpha_limit: object
    min_observations: object
    revalidate_every_months: object
    max_upload_mb: object


@cache
def defectos() -> Defectos:
    """Lee los valores por defecto del código fuente (una sola vez).

    Returns:
        Los valores.
    """
    carta = "domain/charts/t2mrcd/params.py"
    mrcd = "domain/estimators/mrcd/params.py"
    return Defectos(
        mrcd_alpha=constante(carta, "T2MRCD_MRCD_ALPHA"),
        maxcsteps=constante(mrcd, "maxcsteps", "MRCDParams"),
        target=constante(mrcd, "target", "MRCDParams"),
        maxcond=constante(mrcd, "maxcond", "MRCDParams"),
        n_replicates=constante(carta, "DEFAULT_N_REPLICATES"),
        alpha_limit=constante(carta, "DEFAULT_ALPHA_LIMIT"),
        phase2_alpha_limit=constante(carta, "DEFAULT_PHASE2_ALPHA_LIMIT"),
        min_observations=constante(
            "domain/charts/t2mrcd/revalidation.py", "DEFAULT_MIN_OBSERVATIONS"
        ),
        revalidate_every_months=constante(
            "application/records.py", "DEFAULT_REVALIDATE_EVERY_MONTHS"
        ),
        max_upload_mb=constante("config.py", "max_upload_mb", "Settings"),
    )


def _defectos_de_campo() -> dict[str, str]:
    """Columna «Por defecto» de los campos cuyo valor por defecto decide la carta.

    Returns:
        Texto por campo calificado (``Esquema.campo``).
    """
    d = defectos()
    vigilancia = f"cada {d.revalidate_every_months} meses; sin criterio por número de observaciones"
    return {
        "FitRequest.mrcd": "los de la carta",
        "T2MRCDParamsIn.mrcd": "los de la carta",
        "MRCDIn.alpha": f"{d.mrcd_alpha} (carta)",
        "MRCDIn.h": "según alpha",
        "MRCDIn.maxcsteps": str(d.maxcsteps),
        "MRCDIn.rho": "automática",
        "MRCDIn.target": str(d.target),
        "MRCDIn.maxcond": f"{d.maxcond:g}" if isinstance(d.maxcond, float) else str(d.maxcond),
        "BootstrapIn.n_replicates": str(d.n_replicates),
        "BootstrapIn.alpha_limit": str(d.alpha_limit),
        "BootstrapIn.phase2_alpha_limit": str(d.phase2_alpha_limit),
        "RecalibrationParamsIn.min_observations": str(d.min_observations),
        "LifecyclePolicyIn.revalidate_every_months": str(d.revalidate_every_months),
        "LifecyclePolicyIn.revalidate_every_observations": "desactivado",
        "ModelFromRefsRequest.lifecycle_policy": vigilancia,
        "Phase1PipelineRequest.lifecycle_policy": vigilancia,
        "ExclusionRequest.assignable_cause": "[]",
        "Phase1PipelineRequest.assignable_cause": "[]",
        "ApproveRequest.effective_from": "el instante de la aprobación",
    }


# --- textos curados -------------------------------------------------------------------------------

CAMPOS: dict[str, str] = {
    "DatasetUploadIn.data": "Matriz n &times; p por filas (n observaciones, p variables); "
    "números finitos.",
    "DatasetUploadIn.variables": "Nombre de cada columna: p nombres distintos y no vacíos.",
    "DatasetUploadIn.observed_at": "Fecha de cada fila con zona horaria (n fechas). Solo "
    "trazabilidad: ningún cálculo la usa.",
    "FitRequest.dataset_id": "Dataset a ajustar: el subido, la salida de su exclusión humana o, "
    "en una recalibración, el dataset de extensión o las filas nuevas conservadas.",
    "FitRequest.mrcd": "Parámetros de MRCD; lo omitido toma el valor de la carta.",
    "MRCDIn.alpha": "Proporción de observaciones del subconjunto MRCD; fija su tamaño h.",
    "MRCDIn.h": "Tamaño del subconjunto; si se envía, prevalece sobre `alpha`.",
    "MRCDIn.maxcsteps": "Máximo de C-steps por subconjunto inicial.",
    "MRCDIn.rho": "Regularización fija; omitida, se elige por el número de condición `maxcond`.",
    "MRCDIn.target": "Matriz objetivo de la regularización.",
    "MRCDIn.maxcond": "Número de condición objetivo con el que se elige `rho`.",
    "LimitsRequest.fit_id": "Ajuste `succeeded` sobre el que se calibran los límites.",
    "LimitsRequest.params": "Parámetros de la carta. Obligatorio en la Fase I; no se envía junto "
    "con `recalibration_id`.",
    "LimitsRequest.recalibration_id": "Recalibración a la que pertenece el dataset del ajuste: "
    "hereda los parámetros de la versión base con la semilla de la recalibración. Excluyente "
    "con `params`.",
    "T2MRCDParamsIn.bootstrap": "Bootstrap de los límites de control.",
    "T2MRCDParamsIn.mrcd": "Parámetros de MRCD de la carta; deben coincidir con los del ajuste "
    "(`T2MRCD_FIT_PARAMS_MISMATCH`).",
    "BootstrapIn.seed": "Semilla raíz del bootstrap: con la misma semilla y los mismos datos el "
    "resultado es idéntico bit a bit.",
    "BootstrapIn.n_replicates": "Número de réplicas bootstrap B.",
    "BootstrapIn.alpha_limit": "Nivel &alpha; del límite de Fase I (cuantil 1 &minus; &alpha; "
    "del T² de las réplicas).",
    "BootstrapIn.phase2_alpha_limit": "Nivel &alpha; del límite de Fase II (T² de las filas "
    "fuera de la muestra de cada réplica).",
    "ExclusionRequest.dataset_id": "Dataset del que se quitan filas: el subido (Fase I) o el de "
    "candidatas de una recalibración.",
    "ExclusionRequest.assignable_cause": "Filas con causa asignable. Obligatorio y no vacío en "
    "la Fase I; vacío u omitido sobre las candidatas de una recalibración (las filas salen de "
    "las anotaciones).",
    "AssignableCauseIn.row": "Índice de la fila en el dataset (base 0).",
    "AssignableCauseIn.cause": "Causa asignable identificada (texto libre).",
    "ModelFromRefsRequest.fit_id": "Ajuste `succeeded` del dataset subido o de su exclusión "
    "humana.",
    "ModelFromRefsRequest.limits_id": "Límites `succeeded` calibrados sobre ese mismo ajuste.",
    "ModelFromRefsRequest.lifecycle_policy": "Política de revalidación periódica del modelo.",
    "LifecyclePolicyIn.revalidate_every_months": "Meses desde la aprobación de la versión "
    "vigente tras los que la carta avisa `revalidation_due`; `null` desactiva el criterio.",
    "LifecyclePolicyIn.revalidate_every_observations": "Observaciones puntuadas con la versión "
    "vigente tras las que se avisa; `null` desactiva el criterio.",
    "Phase1PipelineRequest.dataset_id": "Dataset raíz subido con `POST /v1/datasets`.",
    "Phase1PipelineRequest.params": "Parámetros de la carta (`bootstrap.seed` es obligatorio).",
    "Phase1PipelineRequest.assignable_cause": "Filas del dataset con causa asignable; si hay "
    "alguna, la tubería empieza por la exclusión humana.",
    "Phase1PipelineRequest.lifecycle_policy": "Política de revalidación del modelo resultante.",
    "ScoreRequest.observations": "Observaciones del lote, cada una con su fecha y sus p valores.",
    "ScoreRequest.batch_label": "Etiqueta libre del lote (p. ej. el cierre al que corresponde).",
    "ScoreRequest.variables": "Nombre de cada columna de `values`. Si el modelo tiene nombres "
    "(los de su dataset raíz), deben ser los mismos y en el mismo orden "
    "(`VARIABLES_MISMATCH`).",
    "ObservationIn.observed_at": "Fecha de la observación con zona horaria; decide qué versión "
    "la puntúa.",
    "ObservationIn.values": "Valores de las p variables, en el orden del modelo; finitos.",
    "AnnotationRequest.assignable_cause": "`true` si se confirmó una causa asignable: la señal "
    "se excluirá de la base al recalibrar.",
    "AnnotationRequest.cause": "Causa identificada.",
    "AnnotationRequest.action": "Acción tomada.",
    "StructuralEventRequest.occurred_at": "Cuándo ocurrió el cambio estructural (con zona "
    "horaria).",
    "StructuralEventRequest.description": "Descripción del cambio.",
    "ApproveRequest.effective_from": "Desde cuándo rige la versión (con zona horaria); no puede "
    "ser retroactivo.",
    "ApproveRequest.note": "Nota de la aprobación.",
    "RejectRequest.note": "Motivo del rechazo.",
    "RecalibrationRequest.range_from": "Inicio del rango de observaciones candidatas "
    "(inclusivo, con zona horaria).",
    "RecalibrationRequest.range_to": "Fin del rango (inclusivo, con zona horaria).",
    "RecalibrationRequest.params": "Parámetros de la recalibración.",
    "RecalibrationRequest.force_replace": "`true` reemplaza la base por las filas nuevas "
    "(REPLACE); por defecto se amplía (EXTEND), salvo evento estructural sin resolver.",
    "RecalibrationRequest.mode": "`pipeline` encola la recalibración completa (`202`); "
    "`stepwise` abre la sesión para encadenar los pasos (`201`).",
    "RecalibrationParamsIn.seed": "Semilla de la recalibración (sustituye a la de la versión "
    "base en los parámetros heredados).",
    "RecalibrationParamsIn.min_observations": "Mínimo de observaciones nuevas conservadas; por "
    "debajo, la recalibración termina `insufficient`.",
    "ExtensionRequest.dataset_id": "Filas nuevas conservadas: el dataset de candidatas (si "
    "ninguna tiene causa asignable) o la salida de su exclusión humana.",
    "VersionProposalRequest.recalibration_id": "Recalibración paso a paso en curso.",
    "VersionProposalRequest.fit_id": "Ajuste final: el del dataset de extensión (EXTEND) o el de "
    "las filas nuevas conservadas (REPLACE).",
    "VersionProposalRequest.limits_id": "Límites calibrados sobre ese ajuste (con "
    "`recalibration_id`).",
}
"""Descripción de cada campo de cuerpo (sustituye a la del docstring del schema)."""

PARAMETROS: dict[str, str] = {
    "dataset_id": "Identificador del dataset.",
    "fit_id": "Identificador del ajuste.",
    "limits_id": "Identificador de los límites.",
    "exclusion_id": "Identificador de la exclusión.",
    "model_id": "Identificador del modelo.",
    "pipeline_id": "Identificador de la tubería.",
    "score_id": "Identificador de la puntuación (el `id` del `202`).",
    "observation_id": "Identificador de la observación con señal.",
    "recalibration_id": "Identificador de la recalibración.",
    "number": "Número de la versión (la 0 es la de la Fase I).",
    "include": "Partes grandes opcionales que se añaden a la respuesta. Repetible: "
    "`?include=a&include=b`.",
    "date_column": "Columna de la cabecera del CSV con la fecha de cada fila (se ignora en JSON).",
    "from": "Inicio del rango de `observed_at` (inclusivo, ISO 8601 con zona horaria).",
    "to": "Fin del rango de `observed_at` (inclusivo, ISO 8601 con zona horaria).",
    "signals_only": "`true` devuelve solo las observaciones que dieron señal.",
}
"""Descripción de los parámetros de ruta y de consulta."""

SIGNIFICADO: dict[int, str] = {
    200: "Correcto.",
    201: "Creado.",
    202: "Aceptado: el trabajo quedó en cola (`status: queued`).",
    401: "Falta el token o no es válido (`details.reason`; con `WWW-Authenticate`).",
    403: "El token es válido pero sus roles no permiten la operación (`details.required_roles`).",
    404: "El recurso no existe o es de otro tenant.",
    405: "Método no admitido en la ruta.",
    409: "El estado del recurso no permite la operación.",
    413: "El cuerpo supera el máximo de subida.",
    415: "Tipo de contenido no admitido.",
    422: "La petición no es válida.",
    500: "Error interno (el detalle queda en el registro del servidor).",
    503: "El servicio no está disponible.",
}
"""Significado genérico de cada estado HTTP."""

ROLES_DE_GRUPO: dict[frozenset[str], str] = {
    frozenset({"analyst", "approver", "admin"}): "lectura",
    frozenset({"analyst", "admin"}): "operación",
    frozenset({"approver", "admin"}): "decisión",
}
"""Nombre del grupo de roles de ``voracious.api.auth`` (``Reader``, ``Operator``, ``Decider``)."""

FALLOS_DE_TRABAJO = (
    "Si el trabajo falla, el `GET` responde `200` con `status: failed` y `error` en el formato "
    "uniforme; `JOB_INTERRUPTED` indica que el servicio se reinició con el trabajo en curso y hay "
    "que volver a pedirlo."
)


# --- ejemplos -------------------------------------------------------------------------------------


def _uuid(nombre: str) -> str:
    """UUID estable y verosímil para un recurso de los ejemplos.

    Args:
        nombre: Nombre del recurso.

    Returns:
        El UUID en texto.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://voracious.example/guia/{nombre}"))


IDS: dict[str, str] = {
    nombre: _uuid(nombre)
    for nombre in (
        "dataset",
        "dataset_exclusion",
        "dataset_candidatas",
        "dataset_candidatas_cancelada",
        "dataset_conservadas",
        "dataset_extension",
        "fit",
        "fit_recalibracion",
        "limits",
        "limits_recalibracion",
        "exclusion",
        "model",
        "pipeline",
        "score",
        "observation",
        "observation_sin_senal",
        "annotation",
        "event",
        "recalibration",
        "recalibration_pipeline",
        "recalibration_cancelada",
    )
}
"""Identificadores de los ejemplos (los mismos en toda la guía).

Los ejemplos cuentan un mismo caso: el histórico ``dataset`` (``N_FILAS`` cierres diarios) pasa
por la tubería de Fase I ``pipeline``, que excluye la fila ``FILA_EXCLUIDA`` (``exclusion``),
ajusta ``fit``, calibra ``limits`` y ensambla ``model``. En la Fase II se puntúa el lote
``score``: ``observation_sin_senal`` (sin señal) y ``observation`` (señal anotada con causa
asignable). La recalibración paso a paso ``recalibration`` amplía la base y propone la versión 1;
antes se abrió y canceló ``recalibration_cancelada``, y ``recalibration_pipeline`` es el ``id``
que daría la misma petición con ``mode: pipeline``.
"""

HUELLA = "sha256:62a5e82308ed652f2b147ef6091daeef5df56177cd1d56c2e832f34cda17be1c"
HUELLA_BASE_V0 = "sha256:a6b8b34c9f7ba34d204d762216c4b518fde7cae287e2bf655a10ac1248183933"
HUELLA_BASE = "sha256:39981e8639d5f9f0c5f47fb039dfc3dcfdde25683177e3c22a68f6108dbe6c6f"
VARIABLES = ["rentabilidad", "volatilidad", "var_95"]
REFERENCIA_T2 = (
    "Pineda Jaramillo, K. S. (2026). Carta de control robusta para observaciones individuales en "
    "fase I para procesos de alta dimensionalidad. Tesis de maestría, Universidad Nacional de "
    "Colombia. https://repositorio.unal.edu.co/handle/unal/90389"
)
N_FILAS = 250
"""Filas del histórico subido (cierres diarios del 2025-10-24 al 2026-06-30)."""
FILA_EXCLUIDA = 17
N_BASE = N_FILAS - 1
"""Base de la versión 0: el histórico sin la fila con causa asignable."""
N_NUEVAS = 92
"""Candidatas de la recalibración: cierres diarios del 2026-07-01 al 2026-09-30."""
N_EXCLUIDAS = 1
"""Candidatas con causa asignable anotada (la señal ``observation``)."""
N_BASE_V1 = N_BASE + N_NUEVAS - N_EXCLUIDAS
FILAS_MOSTRADAS = 3
"""Filas que muestran los ejemplos de listas largas (el resto se abrevia con «…»)."""
FILAS_HISTORICO = (
    (0.0123, 0.1810, 0.0342),
    (0.0098, 0.1764, 0.0311),
    (0.0141, 0.1852, 0.0367),
)
"""Primeras ``FILAS_MOSTRADAS`` filas del histórico (en JSON y en CSV)."""
NOTA_APROBACION = "Aprobada por el comité de riesgos"
NOTA_RECHAZO = "Los cierres de septiembre aún no están conciliados"


class Abreviada(list[object]):
    """Lista de un ejemplo mostrada en parte: el HTML añade una línea «… N … más».

    Se valida contra el esquema como cualquier lista; solo cambia cómo se escribe.

    Attributes:
        omitidos: Elementos que no se muestran.
        unidad: Nombre de los elementos omitidos (``filas``, ``fechas``…).
    """

    def __init__(self, elementos: Sequence[object], total: int, unidad: str) -> None:
        """Crea la lista.

        Args:
            elementos: Elementos que se muestran.
            total: Número de elementos de la lista completa.
            unidad: Nombre de los elementos omitidos.
        """
        super().__init__(elementos)
        self.omitidos = total - len(elementos)
        self.unidad = unidad


def _cierres(desde: str, n: int = FILAS_MOSTRADAS) -> list[str]:
    """Fechas de ``n`` cierres diarios consecutivos (a las 21:00 UTC).

    Args:
        desde: Primer día (``AAAA-MM-DD``).
        n: Número de días.

    Returns:
        Las fechas en ISO 8601.
    """
    inicio = date.fromisoformat(desde)
    return [f"{inicio + timedelta(days=i)}T21:00:00Z" for i in range(n)]


def _parametros_mrcd() -> dict[str, object]:
    """Parámetros de MRCD tal como los devuelve la API con los valores por defecto.

    Returns:
        Los parámetros.
    """
    d = defectos()
    return {
        "alpha": d.mrcd_alpha,
        "h": None,
        "maxcsteps": d.maxcsteps,
        "rho": None,
        "target": d.target,
        "maxcond": d.maxcond,
    }


def _parametros_carta(semilla: int) -> dict[str, object]:
    """Parámetros de la carta tal como los devuelve la API con los valores por defecto.

    Args:
        semilla: Semilla del bootstrap.

    Returns:
        Los parámetros.
    """
    d = defectos()
    return {
        "bootstrap": {
            "n_replicates": d.n_replicates,
            "seed": semilla,
            "alpha_limit": d.alpha_limit,
            "clean_criterion": "best_subset",
            "aggregation": "pooled_quantile",
            "phase2_alpha_limit": d.phase2_alpha_limit,
            "phase2_aggregation": "pooled_quantile",
        },
        "mrcd": _parametros_mrcd(),
    }


def _modelo_recalibrado() -> dict[str, object]:
    """Modelo de la versión 1 de los ejemplos (base ampliada, límite de Fase II).

    Returns:
        El modelo tal como lo devuelve ``GET …/versions/{number}``.
    """
    d = defectos()
    n_base = N_BASE_V1
    return {
        "n_features": len(VARIABLES),
        "n_base": n_base,
        "limit_regime": "phase2",
        "operative_limit": 15.67,
        "limits": {
            "phase1_limit": 15.21,
            "phase2_limit": 15.67,
            "n_replicates": d.n_replicates,
            "seed": 2027,
            "n_clean": 255,
            "alpha_limit": d.alpha_limit,
            "phase2_alpha_limit": d.phase2_alpha_limit,
            "oob_size_min": 76,
            "oob_size_mean": 93.8,
            "phase1_mc_error": 0.29,
            "phase2_mc_error": 0.31,
            "estimator_name": "mrcd",
            "sampler_name": "bootstrap_oob",
        },
        "mrcd": {
            "alpha": d.mrcd_alpha,
            "h": 255,
            "rho": 0.0377,
            "cnp2": 1.3089,
            "crit": -14.4102,
            "n_obs": n_base,
            "center": None,
            "cov": None,
        },
        "pymrcd_version": "0.1.0",
        "seed": 2027,
        "statistic_reference": REFERENCIA_T2,
        "historical_t2": None,
        "historical_outlier": None,
    }


def _ajuste_con_covarianza() -> dict[str, object]:
    """Resumen MRCD del ajuste de la Fase I con ``include=covariance`` (centro y dispersión).

    Returns:
        El ``result`` de ``GET …/fits/{fit_id}?include=covariance``.
    """
    return {
        "alpha": defectos().mrcd_alpha,
        "h": 187,
        "rho": 0.0412,
        "cnp2": 1.3127,
        "crit": -14.2873,
        "n_obs": N_BASE,
        "center": [0.0116, 0.1795, 0.0341],
        "cov": [
            [4.20e-06, -1.01e-06, 9.13e-07],
            [-1.01e-06, 1.53e-05, -1.73e-06],
            [9.13e-07, -1.73e-06, 6.86e-06],
        ],
    }


def _version_0() -> dict[str, object]:
    """Resumen de la versión 0 (la de la Fase I, vigente mientras la 1 está propuesta).

    Returns:
        El elemento de ``GET …/versions`` para la versión 0.
    """
    return {
        "number": 0,
        "status": "active",
        "decision": "initial",
        "justification": "initial_fit",
        "created_at": "2026-07-01T14:08:32Z",
        "effective_from": None,
        "approved_at": "2026-07-01T14:08:32Z",
        "rejected_at": None,
        "decided_by": None,
        "decision_note": None,
        "recalibration_id": None,
        "structural_event_id": None,
        "previous_number": None,
        "base_hash": HUELLA_BASE_V0,
        "n_base": N_BASE,
        "n_exclusions": 1,
    }


def _valores() -> dict[str, object]:
    """Valores de ejemplo por campo (``campo`` o ``Esquema.campo``, que tiene prioridad).

    Un valor que no cumple el esquema del campo se ignora si la clave no está calificada (el
    nombre se comparte entre esquemas de tipos distintos); si está calificada, es un error. Las
    fechas siguen el caso de ``IDS``: Fase I el 2026-07-01 (la tubería tarda unos 6 minutos, casi
    todos de la calibración de los límites), Fase II diaria desde julio, recalibración el
    2026-10-01, aprobación el 2026-10-02 y evento estructural el 2026-10-16.

    Returns:
        Los valores.
    """
    d = defectos()
    n_kept = N_NUEVAS - N_EXCLUIDAS
    antes = {
        "phase1_limit": 15.84,
        "phase2_limit": 16.27,
        "phase1_mc_error": 0.38,
        "phase2_mc_error": 0.44,
        "regime": "phase1_provisional",
        "operative_limit": 15.84,
        "n_base": N_BASE,
    }
    despues = {
        "phase1_limit": 15.21,
        "phase2_limit": 15.67,
        "phase1_mc_error": 0.29,
        "phase2_mc_error": 0.31,
        "regime": "phase2",
        "operative_limit": 15.67,
        "n_base": N_BASE_V1,
    }
    return {
        # Identificadores.
        "dataset_id": IDS["dataset"],
        "fit_id": IDS["fit"],
        "limits_id": IDS["limits"],
        "model_id": IDS["model"],
        "score_id": IDS["score"],
        "observation_id": IDS["observation"],
        "recalibration_id": IDS["recalibration"],
        "root_dataset_id": IDS["dataset"],
        "output_dataset_id": IDS["dataset_exclusion"],
        "candidates_dataset_id": IDS["dataset_candidatas"],
        "kept_dataset_id": IDS["dataset_conservadas"],
        "extension_dataset_id": IDS["dataset_extension"],
        "annotation_id": None,
        "structural_event_id": None,
        "unresolved_event_id": None,
        "parent_id": None,
        "origin_ref": None,
        "observation_ids": [IDS["observation_sin_senal"], IDS["observation"]],
        "FitRequest.dataset_id": IDS["dataset_exclusion"],
        "FitResponse.dataset_id": IDS["dataset_exclusion"],
        "FitResponse.id": IDS["fit"],
        "LimitsResponse.id": IDS["limits"],
        "ExclusionResponse.id": IDS["exclusion"],
        "ModelResponse.id": IDS["model"],
        "PipelineResponse.id": IDS["pipeline"],
        "ScoreResponse.id": IDS["score"],
        "ObservationOut.id": IDS["observation"],
        "AnnotationOut.id": IDS["annotation"],
        "StructuralEventOut.id": IDS["event"],
        "RecalibrationResponse.id": IDS["recalibration"],
        "RecalibrationResponse.pipeline_id": None,
        "LimitsResponse.recalibration_id": None,
        "PipelineResponse.recalibration_id": None,
        "ProvenanceOut.exclusion_id": IDS["exclusion"],
        "ExtensionRequest.dataset_id": IDS["dataset_conservadas"],
        "ExtensionOut.dataset_id": IDS["dataset_extension"],
        "VersionProposalRequest.fit_id": IDS["fit_recalibracion"],
        "VersionProposalRequest.limits_id": IDS["limits_recalibracion"],
        "ProposalOut.fit_id": IDS["fit_recalibracion"],
        "ProposalOut.limits_id": IDS["limits_recalibracion"],
        "PipelineResponse.steps": [
            {"kind": "exclusion", "id": IDS["exclusion"]},
            {"kind": "fit", "id": IDS["fit"]},
            {"kind": "limits", "id": IDS["limits"]},
            {"kind": "model", "id": IDS["model"]},
        ],
        # Fechas (ISO 8601 en UTC): Fase I el 2026-07-01.
        "DatasetResponse.created_at": "2026-07-01T13:58:04Z",
        "PipelineResponse.created_at": "2026-07-01T14:02:09Z",
        "PipelineResponse.started_at": "2026-07-01T14:02:10Z",
        "PipelineResponse.finished_at": "2026-07-01T14:08:33Z",
        "ExclusionResponse.created_at": "2026-07-01T14:02:10Z",
        "ExclusionResponse.started_at": "2026-07-01T14:02:10Z",
        "ExclusionResponse.finished_at": "2026-07-01T14:02:11Z",
        "FitResponse.created_at": "2026-07-01T14:02:11Z",
        "FitResponse.started_at": "2026-07-01T14:02:12Z",
        "FitResponse.finished_at": "2026-07-01T14:02:20Z",
        "LimitsResponse.created_at": "2026-07-01T14:02:20Z",
        "LimitsResponse.started_at": "2026-07-01T14:02:21Z",
        "LimitsResponse.finished_at": "2026-07-01T14:08:30Z",
        "ModelResponse.created_at": "2026-07-01T14:08:30Z",
        "ModelResponse.started_at": "2026-07-01T14:08:31Z",
        "ModelResponse.finished_at": "2026-07-01T14:08:32Z",
        "revalidation_due_at": "2027-01-01T14:08:32Z",
        # Fase II: el lote de los cierres del 14 y el 15 de septiembre, puntuado el 16.
        "ScoreResponse.created_at": "2026-09-16T07:30:02Z",
        "ScoreResponse.started_at": "2026-09-16T07:30:02Z",
        "ScoreResponse.finished_at": "2026-09-16T07:30:03Z",
        "observed_at": "2026-09-15T21:00:00Z",
        "recorded_at": "2026-09-16T07:30:03Z",
        "AnnotationOut.created_at": "2026-09-16T09:12:45Z",
        "occurred_at": "2026-10-15T00:00:00Z",
        "registered_at": "2026-10-16T08:20:40Z",
        # Recalibración paso a paso del 2026-10-01 y aprobación del 2026-10-02.
        "RecalibrationResponse.created_at": "2026-10-01T09:10:05Z",
        "RecalibrationResponse.started_at": "2026-10-01T09:10:05Z",
        "RecalibrationResponse.finished_at": "2026-10-01T09:21:49Z",
        "requested_at": "2026-10-01T09:21:48Z",
        "range_from": "2026-07-01T00:00:00Z",
        "range_to": "2026-09-30T23:59:59Z",
        "VersionSummary.created_at": "2026-10-01T09:21:49Z",
        "ApproveRequest.effective_from": "2026-10-03T00:00:00Z",
        "approved_at": None,
        "rejected_at": None,
        "DatasetResponse.observed_at": Abreviada(_cierres("2025-10-24"), N_FILAS, "fechas"),
        "ModelResponse.observed_at": None,
        "DatasetUploadIn.observed_at": Abreviada(_cierres("2025-10-24"), N_FILAS, "fechas"),
        # Datasets.
        "n": N_FILAS,
        "p": len(VARIABLES),
        "n_rows": N_FILAS,
        "n_features": len(VARIABLES),
        "content_hash": HUELLA,
        "base_hash": HUELLA_BASE,
        "variables": VARIABLES,
        "has_observed_at": True,
        "source": "upload",
        "lineage": [
            {"dataset_id": IDS["dataset"], "source": "upload", "n": N_FILAS, "origin_ref": None}
        ],
        "DatasetUploadIn.data": Abreviada([list(f) for f in FILAS_HISTORICO], N_FILAS, "filas"),
        "data": None,
        "rows": None,
        # Ajuste MRCD y límites de la Fase I (h = 187 de 249 filas con alpha 0.75).
        "alpha": d.mrcd_alpha,
        "h": 187,
        "rho": 0.0412,
        "cnp2": 1.3127,
        "crit": -14.2873,
        "n_obs": N_BASE,
        "center": None,
        "cov": None,
        "FitResponse.params": _parametros_mrcd(),
        "FitResponse.result": _ajuste_con_covarianza(),
        "LimitsResponse.params": _parametros_carta(2026),
        "ModelResponse.params": _parametros_carta(2026),
        "PipelineResponse.params": _parametros_carta(2026),
        "RecalibrationResponse.params": {"seed": 2027, "min_observations": d.min_observations},
        "inherited_params": _parametros_carta(2027),
        "phase1_limit": 15.84,
        "phase2_limit": 16.27,
        "operative_limit": 15.84,
        "limit_regime": "phase1_provisional",
        "n_replicates": d.n_replicates,
        "seed": 2026,
        "n_clean": 187,
        "alpha_limit": d.alpha_limit,
        "phase2_alpha_limit": d.phase2_alpha_limit,
        "oob_size_min": 55,
        "oob_size_mean": 68.8,
        "phase1_mc_error": 0.38,
        "phase2_mc_error": 0.44,
        "estimator_name": "mrcd",
        "sampler_name": "bootstrap_oob",
        "stage_kind": "phase1",
        "spawn_key": [0, 0],
        "clean_rows": None,
        "pymrcd_version": "0.1.0",
        "statistic_reference": REFERENCIA_T2,
        "historical_t2": None,
        "historical_outlier": None,
        "training_data": None,
        "n_base": N_BASE,
        "kind": "phase1",
        "lifecycle_policy": {
            "revalidate_every_months": d.revalidate_every_months,
            "revalidate_every_observations": None,
        },
        # Exclusión humana de la Fase I.
        "row": FILA_EXCLUIDA,
        "cause": "Precio erróneo del proveedor de mercado",
        "insufficient": False,
        "n_kept": N_BASE,
        "n_excluded_assignable_cause": 1,
        "row_disposition": None,
        # Fase II.
        "batch_label": "cierres-2026-09-14-y-15",
        "n_observations": 2,
        "version_numbers": [0, 0],
        "n_signals": 1,
        "values": [0.0412, 0.2930, 0.0811],
        "t2": 23.71,
        "limit": 15.84,
        "limit_kind": "phase1_provisional",
        "version_number": 0,
        "signal": True,
        "action": "Se corrigió la serie y se reprocesó el cierre",
        "actor": "ana.gomez",
        "description": "Cambio de metodología del VaR: de histórico a Monte Carlo",
        "ScoreRequest.observations": [
            {"observed_at": "2026-09-14T21:00:00Z", "values": [0.0117, 0.1798, 0.0339]},
            {"observed_at": "2026-09-15T21:00:00Z", "values": [0.0412, 0.2930, 0.0811]},
        ],
        # Estado de la carta el 2026-09-16, tras puntuar el lote (77 cierres desde julio).
        "ChartStatusOut.status": "startup",
        "active_version": 0,
        "proposed_version": None,
        "revalidation_due": False,
        "observations_since_active": 77,
        "notices": [],
        # Recalibración.
        "mode": "stepwise",
        "force_replace": False,
        "base_version_number": 0,
        "outcome": "extend",
        "RecalibrationResponse.proposed_version": 1,
        "n_candidates": N_NUEVAS,
        "n_already_in_base": 0,
        "decision": "extend",
        "n_new": N_NUEVAS,
        "n_kept_new": n_kept,
        "min_observations": d.min_observations,
        "RecalibrationParamsIn.seed": 2027,
        "RecalibrationReportOut.n_excluded_assignable_cause": N_EXCLUIDAS,
        "RecalibrationReportOut.before": antes,
        "RecalibrationReportOut.after": despues,
        "phase2_exceeds_phase1": True,
        # Versiones.
        "number": 1,
        "VersionSummary.status": "proposed",
        "VersionSummary.n_base": N_BASE_V1,
        "justification": "default_extend",
        "previous_number": 0,
        "n_exclusions": N_EXCLUIDAS,
        "decided_by": None,
        "decision_note": None,
        "ApproveRequest.note": NOTA_APROBACION,
        "RejectRequest.note": NOTA_RECHAZO,
        "VersionSummary.recalibration_id": IDS["recalibration"],
        "VersionSummary.effective_from": None,
        "VersionDetail.exclusions": [
            {
                "source": "observation",
                "ref": IDS["observation"],
                "reason": "assignable_cause",
                "annotation_id": IDS["annotation"],
                "observed_at": "2026-09-15T21:00:00Z",
            }
        ],
        "VersionDetail.base_refs": Abreviada(
            [
                {"source": "training", "ref": str(i), "observed_at": fecha}
                for i, fecha in enumerate(_cierres("2025-10-24"))
            ],
            N_BASE_V1,
            "filas",
        ),
        "base_data": None,
        # Errores y salud.
        "error": None,
        "checks": {"database": "ok", "storage": "ok"},
    }


ALIAS_DE_ESQUEMA = {"VersionDetail": "VersionSummary"}
"""Esquemas que comparten valores de ejemplo con otro (``VersionDetail`` amplía el resumen)."""

INCLUIR_EN_PETICION = frozenset(
    {
        "DatasetUploadIn.variables",
        "DatasetUploadIn.observed_at",
        "FitRequest.mrcd",
        "MRCDIn.alpha",
        "LimitsRequest.params",
        "T2MRCDParamsIn.mrcd",
        "BootstrapIn.n_replicates",
        "BootstrapIn.alpha_limit",
        "BootstrapIn.phase2_alpha_limit",
        "ExclusionRequest.assignable_cause",
        "AssignableCauseIn.cause",
        "ModelFromRefsRequest.lifecycle_policy",
        "LifecyclePolicyIn.revalidate_every_months",
        "Phase1PipelineRequest.assignable_cause",
        "ScoreRequest.batch_label",
        "ScoreRequest.variables",
        "AnnotationRequest.cause",
        "AnnotationRequest.action",
        "ApproveRequest.effective_from",
        "ApproveRequest.note",
        "RejectRequest.note",
        "RecalibrationParamsIn.min_observations",
        "RecalibrationRequest.force_replace",
        "RecalibrationRequest.mode",
    }
)
"""Campos opcionales que aparecen en los ejemplos de petición (los obligatorios siempre)."""


def _error(
    codigo: str, mensaje: str, detalles: Mapping[str, object] | None = None
) -> dict[str, object]:
    """Cuerpo de error con el formato uniforme de la API (``api/errors.py``).

    Args:
        codigo: Código del catálogo.
        mensaje: Mensaje legible (el que da el servidor).
        detalles: Datos adicionales.

    Returns:
        ``{"code", "message", "details"}``.
    """
    return {"code": codigo, "message": mensaje, "details": dict(detalles or {})}


# --- operaciones ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Operacion:
    """Contenido redactado de una operación (lo que el OpenAPI no dice o dice en inglés).

    Attributes:
        titulo: Nombre de la operación (encabezado h3).
        descripcion: Párrafos; el texto entre comillas invertidas se escribe como código.
        errores: Códigos de error que puede devolver, por estado HTTP. ``401`` y ``403`` se
            añaden solos a toda operación protegida.
        ko: Ejemplo de respuesta de error: estado y cuerpo (``None``: sin ejemplo).
        recurso: Clave de ``IDS`` del recurso que crea (el ``id`` de un ``202``).
        consulta: Parámetros de consulta del ejemplo de petición.
        ruta: Identificadores de la ruta del ejemplo que no son los de siempre (parámetro →
            valor).
        ok: Estados con ejemplo de respuesta correcta (vacío: el primer 2xx del OpenAPI).
        cambios_ok: Valores del ejemplo de respuesta correcta (campo de primer nivel → valor).
        previos_ok: Elementos que preceden al generado en un ejemplo de respuesta que es una
            lista (p. ej. la versión 0 antes de la 1).
        significado: Significado de un estado, en lugar del genérico.
        esquema: Etiqueta del esquema de un estado, en lugar de la del OpenAPI.
        nota: Caja tras la descripción: (clase de la caja, etiqueta, texto).
        sin_cuerpo: La operación no lleva cuerpo aunque sea ``POST``.
    """

    titulo: str
    descripcion: tuple[str, ...]
    errores: Mapping[int, tuple[str, ...]] = field(default_factory=dict)
    ko: tuple[int, Mapping[str, object]] | None = None
    recurso: str | None = None
    consulta: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    ruta: Mapping[str, str] = field(default_factory=dict)
    ok: tuple[int, ...] = ()
    cambios_ok: Mapping[str, object] = field(default_factory=dict)
    previos_ok: tuple[Mapping[str, object], ...] = ()
    significado: Mapping[int, str] = field(default_factory=dict)
    esquema: Mapping[int, str] = field(default_factory=dict)
    nota: tuple[str, str, str] | None = None
    sin_cuerpo: bool = False


@dataclass(frozen=True)
class Grupo:
    """Grupo de operaciones (un h2 de la referencia).

    Attributes:
        ancla: ``id`` del h2.
        titulo: Título.
        introduccion: Párrafos de introducción.
        operaciones: Operaciones (método, plantilla) en el orden en que se documentan.
    """

    ancla: str
    titulo: str
    introduccion: tuple[str, ...]
    operaciones: tuple[tuple[str, str], ...]


def _operaciones() -> dict[tuple[str, str], Operacion]:
    """Textos, errores y ejemplos de cada operación, leídos de los routers y casos de uso.

    Returns:
        Las operaciones por (método, plantilla).
    """
    d = defectos()
    m = MODELO
    c = PREFIJO_CARTA
    trabajo = FALLOS_DE_TRABAJO
    return {
        ("POST", "/v1/datasets"): Operacion(
            titulo="Subir un dataset",
            descripcion=(
                "Guarda un histórico n &times; p (n observaciones, p variables) y devuelve su "
                "identificador, su forma y su huella `content_hash` (SHA-256 del contenido). Es "
                "síncrona: responde `201` con el dataset ya creado. El dataset no pertenece a "
                "ninguna carta; los pasos lo referencian por `dataset_id`.",
                "Admite tres formatos según `Content-Type`: JSON, CSV (`text/csv`) y "
                "`multipart/form-data` con el CSV en la parte `file`. El CSV usa coma como "
                "separador, debe estar en UTF-8 y puede llevar cabecera: si alguna celda de la "
                "primera fila no es numérica, esa fila da los nombres de las variables, y la "
                "columna `date_column` (por defecto `observed_at`) da la fecha de cada fila "
                "(ISO 8601 con zona horaria), que no cuenta como variable. Las líneas vacías se "
                "ignoran.",
                "La matriz debe ser no vacía y finita (sin NaN ni infinitos); `variables` lleva "
                "un nombre distinto por columna y `observed_at` una fecha por fila. El cuerpo no "
                f"puede superar `VORACIOUS_MAX_UPLOAD_MB` ({d.max_upload_mb} MiB por defecto).",
            ),
            errores={
                413: ("PAYLOAD_TOO_LARGE",),
                415: ("UNSUPPORTED_MEDIA_TYPE",),
                422: ("INVALID_INPUT",),
            },
            ko=(
                422,
                _error(
                    "INVALID_INPUT",
                    "'variables' debe tener un nombre por columna",
                    {"input": "variables", "columns": 3, "names": 2},
                ),
            ),
        ),
        ("GET", "/v1/datasets/{dataset_id}"): Operacion(
            titulo="Consultar un dataset",
            descripcion=(
                "Devuelve el resumen del dataset (forma, huella, origen, fecha de creación y "
                "nombres de variables) y su linaje: la cadena de datasets desde la raíz subida "
                "hasta él, con el origen de cada uno (`upload`, `exclusion_output`, "
                "`recalibration_candidates` o `recalibration_extension`).",
                "Las partes grandes solo se devuelven si se piden con `include`: `data` (la "
                "matriz), `rows` (índices de sus filas en el dataset padre) y `observed_at` (la "
                "fecha de cada fila).",
            ),
            errores={404: ("DATASET_NOT_FOUND",), 422: ("INVALID_INPUT",)},
            ko=(
                404,
                _error(
                    "DATASET_NOT_FOUND",
                    f"el dataset '{IDS['dataset']}' no existe",
                    {"dataset_id": IDS["dataset"]},
                ),
            ),
            consulta={"include": ("observed_at",)},
        ),
        ("POST", f"{c}/fits"): Operacion(
            titulo="Pedir un ajuste MRCD",
            descripcion=(
                "Valida el dataset y encola su ajuste con el estimador MRCD (port fiel de "
                "`rrcov::CovMrcd`) bajo la carta T²MRCD, en el carril `estimation`. Lo omitido "
                f"en `mrcd` toma el valor de la carta: `alpha` {d.mrcd_alpha} y los valores por "
                "defecto de `rrcov` para el resto.",
                "Sobre un dataset de una recalibración, el ajuste debe ser el de la operación de "
                "la sesión: el dataset de extensión si la recalibración amplía la base o las "
                "filas nuevas conservadas si la reemplaza (`details.reason`).",
            ),
            errores={
                404: ("DATASET_NOT_FOUND",),
                409: ("RECALIBRATION_NOT_IN_PROGRESS",),
                422: ("INVALID_INPUT",),
            },
            ko=(
                404,
                _error(
                    "DATASET_NOT_FOUND",
                    f"el dataset '{IDS['dataset_exclusion']}' no existe",
                    {"dataset_id": IDS["dataset_exclusion"]},
                ),
            ),
            recurso="fit",
            significado={
                202: "Aceptado: el ajuste quedó en cola; se consulta con `GET …/fits/{fit_id}`."
            },
        ),
        ("GET", f"{c}/fits/{{fit_id}}"): Operacion(
            titulo="Consultar un ajuste",
            descripcion=(
                "Estado del ajuste y, si terminó bien, su resumen en `result`: `alpha`, tamaño "
                "del subconjunto `h`, regularización `rho` elegida, factor de consistencia "
                "`cnp2`, criterio `crit` y número de observaciones `n_obs`. El centro y la "
                "matriz de dispersión (`center`, `cov`) solo se devuelven con "
                "`include=covariance`.",
                f"{trabajo} Fallo propio del paso: `MRCD_FIT_FAILED`.",
            ),
            errores={404: ("FIT_NOT_FOUND",), 422: ("INVALID_INPUT",)},
            ko=(
                404,
                _error(
                    "FIT_NOT_FOUND",
                    f"el ajuste '{IDS['fit']}' no existe",
                    {"fit_id": IDS["fit"]},
                ),
            ),
            consulta={"include": ("covariance",)},
        ),
        ("POST", f"{c}/limits"): Operacion(
            titulo="Pedir la calibración de los límites",
            descripcion=(
                "Valida el ajuste y encola, en el carril `calibration`, la calibración bootstrap "
                "de los dos límites de control, que comparten réplicas: el de Fase I (T² de la "
                "muestra de cada réplica) y el de Fase II (T² de las filas fuera de la muestra, "
                "OOB). Cada uno es el cuantil 1 &minus; &alpha; del conjunto de T² de todas las "
                "réplicas, y solo se remuestrean las observaciones limpias del ajuste.",
                "Se pide de una de dos formas: `{fit_id, params}` en la Fase I (con "
                "`params.bootstrap.seed` siempre) o `{fit_id, recalibration_id}` sobre un dataset "
                "de una recalibración, que hereda los parámetros de la versión base con la "
                "semilla de la recalibración. Enviar las dos responde `422`. Los parámetros de "
                "MRCD de la carta deben ser los del ajuste. Todo se comprueba antes de encolar.",
            ),
            errores={
                404: ("FIT_NOT_FOUND",),
                409: ("FIT_NOT_READY", "RECALIBRATION_NOT_IN_PROGRESS"),
                422: (
                    "INVALID_INPUT",
                    "T2MRCD_FIT_PARAMS_MISMATCH",
                    "RECALIBRATION_MISMATCH",
                    "T2MRCD_DECISION_PENDING",
                ),
            },
            ko=(
                409,
                _error(
                    "FIT_NOT_READY",
                    f"el ajuste '{IDS['fit']}' no está listo",
                    {"fit_id": IDS["fit"], "status": "running"},
                ),
            ),
            recurso="limits",
            significado={
                202: "Aceptado: la calibración quedó en cola; se consulta con "
                "`GET …/limits/{limits_id}`."
            },
        ),
        ("GET", f"{c}/limits/{{limits_id}}"): Operacion(
            titulo="Consultar unos límites",
            descripcion=(
                "Estado de la calibración y, si terminó bien, los límites en `result`: "
                "`phase1_limit` y `phase2_limit` con su error de Monte Carlo, las réplicas, las "
                "observaciones limpias remuestreadas (`n_clean`) y el tamaño de las muestras OOB. "
                "`stage_kind` dice la operación (`phase1`, `new_rows` o `extension`). Con "
                "`include=clean_rows` devuelve la máscara de filas limpias.",
                f"{trabajo} Fallos propios del paso: `BOOTSTRAP_REPLICATE_FAILED`, "
                "`BOOTSTRAP_OOB_EMPTY`, `BOOTSTRAP_LIMIT_NOT_FINITE`, "
                "`T2MRCD_NO_CLEAN_OBSERVATIONS` y `MRCD_FIT_FAILED`.",
            ),
            errores={404: ("LIMITS_NOT_FOUND",), 422: ("INVALID_INPUT",)},
            ko=(
                404,
                _error(
                    "LIMITS_NOT_FOUND",
                    f"los límites '{IDS['limits']}' no existen",
                    {"limits_id": IDS["limits"]},
                ),
            ),
        ),
        ("POST", f"{c}/exclusions"): Operacion(
            titulo="Pedir una exclusión humana",
            descripcion=(
                "Encola, en el carril `light`, la exclusión de las filas en las que una persona "
                "identificó una causa asignable, antes de ajustar nada. Es el único filtro de "
                "filas: no hay depuración automática. El resultado es un dataset derivado "
                "(`output_dataset_id`) que se ajusta después con `/fits`.",
                "En la Fase I solo se admite sobre el dataset subido, con al menos una fila en "
                "`assignable_cause` y sin quitarlas todas. Sobre las candidatas de una "
                "recalibración se envía solo `{dataset_id}`: las filas salen de las anotaciones "
                "con causa asignable confirmada.",
            ),
            errores={
                404: ("DATASET_NOT_FOUND",),
                409: ("RECALIBRATION_NOT_IN_PROGRESS",),
                422: ("INVALID_INPUT",),
            },
            ko=(
                422,
                _error(
                    "INVALID_INPUT",
                    "la exclusión humana solo se admite al principio, sobre el dataset subido",
                    {
                        "dataset_id": IDS["dataset_exclusion"],
                        "reason": "human_exclusion_only_at_start",
                    },
                ),
            ),
            recurso="exclusion",
        ),
        ("GET", f"{c}/exclusions/{{exclusion_id}}"): Operacion(
            titulo="Consultar una exclusión",
            descripcion=(
                "Estado de la exclusión y, si terminó bien, el dataset resultante "
                "(`output_dataset_id`), cuántas filas quedan (`n_kept`) y cuántas se quitaron "
                "(`n_excluded_assignable_cause`). En una recalibración, `insufficient` es `true` "
                "si quedan menos observaciones que el mínimo. Con `include=row_disposition` "
                "devuelve el destino de cada fila.",
                trabajo,
            ),
            errores={404: ("EXCLUSION_NOT_FOUND",), 422: ("INVALID_INPUT",)},
            ko=(
                404,
                _error(
                    "EXCLUSION_NOT_FOUND",
                    f"la exclusión '{IDS['exclusion']}' no existe",
                    {"exclusion_id": IDS["exclusion"]},
                ),
            ),
        ),
        ("POST", f"{c}/models"): Operacion(
            titulo="Ensamblar un modelo",
            descripcion=(
                "Encola el ensamblado del modelo de Fase I a partir de un ajuste y de sus "
                "límites, ya terminados, sin datos ni cómputo nuevo. El modelo nace con su "
                "versión 0 vigente, que vigila con el límite de Fase I (provisional).",
                "`lifecycle_policy` fija la revalidación periódica: un campo omitido toma su "
                "valor por defecto y `null` lo desactiva.",
            ),
            errores={
                404: ("FIT_NOT_FOUND", "LIMITS_NOT_FOUND"),
                409: ("FIT_NOT_READY", "LIMITS_NOT_READY"),
                422: ("INVALID_INPUT", "LIMITS_FIT_MISMATCH", "RECALIBRATION_MISMATCH"),
            },
            ko=(
                422,
                _error(
                    "LIMITS_FIT_MISMATCH",
                    f"los límites '{IDS['limits_recalibracion']}' no se calibraron sobre el "
                    f"ajuste '{IDS['fit']}'",
                    {
                        "limits_id": IDS["limits_recalibracion"],
                        "fit_id": IDS["fit"],
                        "limits_fit_id": IDS["fit_recalibracion"],
                    },
                ),
            ),
            recurso="model",
            significado={
                202: "Aceptado: el ensamblado quedó en cola; se consulta con "
                "`GET …/models/{model_id}`."
            },
        ),
        ("GET", f"{m}"): Operacion(
            titulo="Consultar un modelo",
            descripcion=(
                "Estado del ensamblado y, si terminó bien, el modelo en `result`: número de "
                "variables, tamaño de la base, régimen y valor del límite operativo, límites, "
                "resumen MRCD, versión de `pymrcd`, semilla y referencia de la estadística T². "
                "`provenance` dice de qué dataset, ajuste, límites y exclusión se ensambló.",
                "Con `include` añade `training_data` (el histórico), `observed_at` (sus fechas), "
                "`covariance` (centro y dispersión MRCD) e `historical` (T² y marca de atípico "
                "de cada fila del histórico).",
            ),
            errores={404: ("MODEL_NOT_FOUND",), 422: ("INVALID_INPUT",)},
            ko=(
                404,
                _error(
                    "MODEL_NOT_FOUND",
                    f"el modelo '{IDS['model']}' no existe",
                    {"model_id": IDS["model"]},
                ),
            ),
        ),
        ("GET", f"{m}/status"): Operacion(
            titulo="Consultar el estado de la carta",
            descripcion=(
                "Estado de la carta por precedencia: `requires_new_base` (hay un evento "
                "estructural sin resolver), `proposal_pending` (hay una propuesta sin decidir), "
                "`revalidation_due` (venció la revalidación periódica), `startup` (vigila la "
                "versión 0 con el límite provisional de Fase I) o `active` (vigila una versión "
                "recalibrada con el límite de Fase II).",
                "Incluye la versión vigente y la propuesta, cuándo vence la revalidación, las "
                "observaciones puntuadas desde la versión vigente y los avisos activos "
                "(`notices`).",
            ),
            errores={404: ("MODEL_NOT_FOUND",), 409: ("MODEL_NOT_READY",)},
            ko=(
                409,
                _error(
                    "MODEL_NOT_READY",
                    f"el modelo '{IDS['model']}' no está listo",
                    {"model_id": IDS["model"], "status": "queued"},
                ),
            ),
        ),
        ("POST", f"{c}/pipelines/phase1"): Operacion(
            titulo="Ejecutar la Fase I completa",
            descripcion=(
                "Encola la Fase I completa como orquestación de los mismos pasos: exclusión "
                "humana (si `assignable_cause` no está vacío), ajuste, límites y modelo. Da el "
                "mismo modelo, bit a bit, que encadenar los pasos a mano.",
                "`GET …/pipelines/{pipeline_id}` informa de cada paso lanzado y, al terminar, "
                "del `model_id`.",
            ),
            errores={404: ("DATASET_NOT_FOUND",), 422: ("INVALID_INPUT",)},
            ko=(
                404,
                _error(
                    "DATASET_NOT_FOUND",
                    f"el dataset '{IDS['dataset']}' no existe",
                    {"dataset_id": IDS["dataset"]},
                ),
            ),
            recurso="pipeline",
            significado={
                202: "Aceptado: la tubería quedó en cola; se consulta con "
                "`GET …/pipelines/{pipeline_id}`."
            },
        ),
        ("GET", f"{c}/pipelines/{{pipeline_id}}"): Operacion(
            titulo="Consultar una tubería",
            descripcion=(
                "Estado de una tubería de Fase I (`kind: phase1`) o de recalibración "
                "(`kind: recalibration`), con los pasos lanzados (`steps`: tipo e id de cada "
                "recurso, que se pueden consultar uno a uno) y, al terminar bien, el `model_id`.",
                "Si un paso falla, la tubería queda `failed` y `error.details` indica el paso "
                "(`step`, `step_id`).",
            ),
            errores={404: ("PIPELINE_NOT_FOUND",)},
            ko=(
                404,
                _error(
                    "PIPELINE_NOT_FOUND",
                    f"la tubería '{IDS['pipeline']}' no existe",
                    {"pipeline_id": IDS["pipeline"]},
                ),
            ),
        ),
        ("GET", f"{c}/pipelines/phase1/{{pipeline_id}}"): Operacion(
            titulo="Consultar una tubería (alias)",
            descripcion=(
                "Alias de `GET /v1/charts/t2mrcd/pipelines/{pipeline_id}`, que se mantiene por "
                "compatibilidad: devuelve exactamente la misma respuesta.",
            ),
            errores={404: ("PIPELINE_NOT_FOUND",)},
            ko=(
                404,
                _error(
                    "PIPELINE_NOT_FOUND",
                    f"la tubería '{IDS['pipeline']}' no existe",
                    {"pipeline_id": IDS["pipeline"]},
                ),
            ),
        ),
        ("POST", f"{m}/scores"): Operacion(
            titulo="Puntuar un lote",
            descripcion=(
                "Valida y encola la puntuación de un lote de observaciones con fecha. Cada "
                "observación se puntúa con la versión aprobada que rige en su `observed_at` y "
                "queda registrada con su T², el límite aplicado y si es señal (T² mayor que el "
                "límite).",
                "La validación es síncrona: un número de variables distinto del modelo o "
                "nombres de `variables` distintos (en número o en orden) se rechazan antes de "
                "encolar.",
            ),
            errores={
                404: ("MODEL_NOT_FOUND",),
                409: ("MODEL_NOT_READY",),
                422: ("INVALID_INPUT", "VARIABLES_MISMATCH", "OBSERVATION_BEFORE_FIRST_VERSION"),
            },
            ko=(
                422,
                _error(
                    "VARIABLES_MISMATCH",
                    "las variables no son las del modelo (mismos nombres y en el mismo orden)",
                    {
                        "input": "scores",
                        "expected": VARIABLES,
                        "received": ["volatilidad", "rentabilidad", "var_95"],
                    },
                ),
            ),
            recurso="score",
            significado={
                202: "Aceptado: la puntuación quedó en cola; se consulta con "
                "`GET …/scores/{score_id}`."
            },
        ),
        ("GET", f"{m}/scores/{{score_id}}"): Operacion(
            titulo="Consultar una puntuación",
            descripcion=(
                "Estado de la puntuación y, si terminó bien, los identificadores de las "
                "observaciones registradas (en el orden del lote), la versión con la que se "
                "puntuó cada una y el número de señales. El detalle de cada observación se "
                "consulta con `GET …/observations`.",
                trabajo,
            ),
            errores={404: ("MONITORING_NOT_FOUND",)},
            ko=(
                404,
                _error(
                    "MONITORING_NOT_FOUND",
                    f"el monitoreo '{IDS['score']}' no existe",
                    {"model_id": IDS["model"], "monitoring_id": IDS["score"]},
                ),
            ),
        ),
        ("GET", f"{m}/observations"): Operacion(
            titulo="Listar observaciones",
            descripcion=(
                "Observaciones registradas del modelo en un rango de fechas inclusivo (`from` y "
                "`to`, con zona horaria; ambos opcionales), con su T², el límite y su régimen, "
                "la versión aplicada, si es señal y su anotación vigente (la más reciente). "
                "`signals_only=true` devuelve solo las señales.",
            ),
            errores={404: ("MODEL_NOT_FOUND",), 422: ("INVALID_INPUT",)},
            ko=(
                422,
                _error(
                    "INVALID_INPUT",
                    "la petición no cumple el schema",
                    {
                        "errors": [
                            {
                                "loc": ["query", "from"],
                                "msg": "Input should be a valid datetime or date, input is "
                                "too short",
                                "type": "datetime_from_date_parsing",
                            }
                        ]
                    },
                ),
            ),
            consulta={
                "from": ("2026-09-01T00:00:00Z",),
                "to": ("2026-09-30T23:59:59Z",),
                "signals_only": ("true",),
            },
        ),
        ("POST", f"{m}/observations/{{observation_id}}/annotations"): Operacion(
            titulo="Anotar una señal",
            descripcion=(
                "Añade una anotación a una observación que dio señal: si se confirmó una causa "
                "asignable, cuál fue y qué acción se tomó. Las anotaciones no se editan ni se "
                "borran: vale la más reciente. Quien anota es el `sub` del token (enviar "
                "`actor` responde `422`).",
                "Las señales con causa asignable confirmada se excluyen de la base en la "
                "siguiente recalibración.",
            ),
            errores={
                404: ("OBSERVATION_NOT_FOUND",),
                409: ("NOT_A_SIGNAL",),
                422: ("INVALID_INPUT",),
            },
            ko=(
                409,
                _error(
                    "NOT_A_SIGNAL",
                    "solo se anotan observaciones con señal",
                    {"observation_id": IDS["observation_sin_senal"]},
                ),
            ),
        ),
        ("POST", f"{m}/structural-events"): Operacion(
            titulo="Registrar un evento estructural",
            descripcion=(
                "Registra un cambio estructural del proceso (p. ej. de metodología o de mandato) "
                "que obliga a una base nueva. La carta pasa a `requires_new_base` hasta que se "
                "apruebe una versión que lo resuelva, y la siguiente recalibración reemplaza la "
                "base (REPLACE) y solo admite observaciones posteriores al evento.",
                "Si había una propuesta pendiente, se rechaza automáticamente. Quien lo "
                "registra es el `sub` del token.",
            ),
            errores={
                404: ("MODEL_NOT_FOUND",),
                409: ("MODEL_NOT_READY",),
                422: ("INVALID_INPUT",),
            },
            ko=(
                409,
                _error(
                    "MODEL_NOT_READY",
                    f"el modelo '{IDS['model']}' no está listo",
                    {"model_id": IDS["model"], "status": "running"},
                ),
            ),
        ),
        ("GET", f"{m}/structural-events"): Operacion(
            titulo="Listar eventos estructurales",
            descripcion=("Eventos estructurales del modelo, ordenados por `occurred_at`.",),
            errores={404: ("MODEL_NOT_FOUND",)},
            ko=(
                404,
                _error(
                    "MODEL_NOT_FOUND",
                    f"el modelo '{IDS['model']}' no existe",
                    {"model_id": IDS["model"]},
                ),
            ),
        ),
        ("POST", f"{m}/recalibrations"): Operacion(
            titulo="Pedir una recalibración",
            descripcion=(
                "Valida la petición de forma síncrona y abre la sesión: fija las observaciones "
                "candidatas del rango (las que ya están en la base vigente quedan aparte), "
                "hereda los parámetros de la carta de la versión base con la semilla "
                "`params.seed` y crea el dataset de candidatas.",
                "Con `mode: pipeline` (por defecto) encola la recalibración completa y responde "
                "`202`; se consulta con `GET …/recalibrations/{recalibration_id}`. Con "
                "`mode: stepwise` responde `201` con la sesión abierta (`recalibration_id`, "
                "`candidates_dataset_id`) para encadenar los pasos.",
            ),
            errores={
                404: ("MODEL_NOT_FOUND",),
                409: ("MODEL_NOT_READY", "PROPOSAL_PENDING", "RECALIBRATION_IN_PROGRESS"),
                422: (
                    "INVALID_INPUT",
                    "RANGE_BEFORE_STRUCTURAL_EVENT",
                    "RECALIBRATION_INSUFFICIENT_OBSERVATIONS",
                    "VARIABLES_MISMATCH",
                ),
            },
            ko=(
                409,
                _error(
                    "RECALIBRATION_IN_PROGRESS",
                    "ya hay una recalibración en curso",
                    {"recalibration_id": IDS["recalibration_cancelada"]},
                ),
            ),
            recurso="recalibration_pipeline",
            ok=(201, 202),
            significado={
                201: "Creada: sesión paso a paso abierta (`mode: stepwise`).",
                202: "Aceptada: recalibración completa en cola (`mode: pipeline`; el ejemplo da "
                "el `id` que tendría la misma petición en ese modo).",
            },
            esquema={202: "AcceptedJob"},
        ),
        ("GET", f"{m}/recalibrations/{{recalibration_id}}"): Operacion(
            titulo="Consultar una recalibración",
            descripcion=(
                "Estado de la recalibración y de su sesión: modo, rango, parámetros heredados, "
                "candidatas (`n_candidates`, `n_already_in_base`), datasets de la sesión "
                "(`candidates_dataset_id`, `kept_dataset_id`, `extension_dataset_id`), tubería "
                "(`pipeline_id`) y propuesta pedida (`proposal`). En modo paso a paso es también "
                "el trabajo de `POST …/versions`.",
                "Al terminar bien, `outcome` da la decisión (`extend`, `replace` o "
                "`insufficient`), `proposed_version` el número de la versión propuesta y `report` "
                "el informe antes y después (límites, tamaños de base y filas excluidas). Con "
                "`include=row_disposition` añade el destino de cada candidata.",
                trabajo,
            ),
            errores={404: ("RECALIBRATION_NOT_FOUND",), 422: ("INVALID_INPUT",)},
            ko=(
                404,
                _error(
                    "RECALIBRATION_NOT_FOUND",
                    f"la recalibración '{IDS['recalibration']}' no existe",
                    {"model_id": IDS["model"], "recalibration_id": IDS["recalibration"]},
                ),
            ),
        ),
        ("POST", f"{m}/recalibrations/{{recalibration_id}}/extension"): Operacion(
            titulo="Construir la base ampliada",
            descripcion=(
                "Paso síncrono de una recalibración paso a paso que amplía la base (EXTEND): "
                "crea el dataset de extensión con la base vigente seguida de las observaciones "
                "nuevas conservadas. Ese dataset se ajusta con `/fits` y se calibra con "
                "`/limits` (con `recalibration_id`).",
                "Es idempotente: repetirlo con el mismo `dataset_id` devuelve la misma "
                "extensión. En un reemplazo (REPLACE) no hay extensión y responde `422`.",
            ),
            errores={
                404: ("RECALIBRATION_NOT_FOUND", "DATASET_NOT_FOUND"),
                409: ("RECALIBRATION_NOT_IN_PROGRESS",),
                422: ("INVALID_INPUT", "RECALIBRATION_MISMATCH"),
            },
            ko=(
                422,
                _error(
                    "INVALID_INPUT",
                    "hay candidatas con causa asignable: primero la exclusión humana",
                    {
                        "dataset_id": IDS["dataset_candidatas"],
                        "reason": "human_exclusion_required",
                    },
                ),
            ),
        ),
        ("POST", f"{m}/versions"): Operacion(
            titulo="Proponer la versión",
            descripcion=(
                "Último paso de una recalibración paso a paso: valida y encola, en el carril "
                "`light`, la propuesta de versión con el ajuste y los límites finales (los del "
                "dataset de extensión en EXTEND o los de las filas nuevas conservadas en "
                "REPLACE).",
                "El trabajo es la propia recalibración: el `id` del `202` es el "
                "`recalibration_id`, y `GET …/recalibrations/{recalibration_id}` trae al "
                "terminar `proposed_version`. La versión queda `proposed` hasta que una persona "
                "la apruebe o la rechace.",
            ),
            errores={
                404: ("RECALIBRATION_NOT_FOUND", "FIT_NOT_FOUND", "LIMITS_NOT_FOUND"),
                409: (
                    "RECALIBRATION_NOT_IN_PROGRESS",
                    "PROPOSAL_PENDING",
                    "FIT_NOT_READY",
                    "LIMITS_NOT_READY",
                ),
                422: ("INVALID_INPUT", "LIMITS_FIT_MISMATCH", "VERSION_INPUTS_MISMATCH"),
            },
            ko=(
                422,
                _error(
                    "VERSION_INPUTS_MISMATCH",
                    "los pasos pedidos no son los que exige la decisión de la recalibración",
                    {"reason": "limits_not_of_recalibration", "limits_id": IDS["limits"]},
                ),
            ),
            recurso="recalibration",
            significado={
                202: "Aceptado: la propuesta quedó en cola; se consulta con "
                "`GET …/recalibrations/{recalibration_id}`."
            },
        ),
        ("POST", f"{m}/recalibrations/{{recalibration_id}}/cancel"): Operacion(
            titulo="Cancelar una recalibración",
            descripcion=(
                "Cancela una recalibración paso a paso que sigue `running` y aún no ha pedido su "
                "propuesta, y deja libre el modelo para otra recalibración. Responde con la "
                "recalibración en estado `cancelled`. No lleva cuerpo.",
            ),
            errores={
                404: ("RECALIBRATION_NOT_FOUND",),
                409: ("RECALIBRATION_NOT_IN_PROGRESS",),
            },
            ko=(
                409,
                _error(
                    "RECALIBRATION_NOT_IN_PROGRESS",
                    f"la recalibración '{IDS['recalibration_cancelada']}' no se puede cancelar",
                    {
                        "recalibration_id": IDS["recalibration_cancelada"],
                        "mode": "stepwise",
                        "status": "cancelled",
                        "proposal_requested": False,
                    },
                ),
            ),
            ruta={"recalibration_id": IDS["recalibration_cancelada"]},
            cambios_ok={
                "id": IDS["recalibration_cancelada"],
                "status": "cancelled",
                "created_at": "2026-10-01T09:02:11Z",
                "started_at": "2026-10-01T09:02:11Z",
                "finished_at": "2026-10-01T09:04:37Z",
                "outcome": None,
                "proposed_version": None,
                "candidates_dataset_id": IDS["dataset_candidatas_cancelada"],
                "proposal": None,
                "kept_dataset_id": None,
                "extension_dataset_id": None,
                "report": None,
            },
            sin_cuerpo=True,
        ),
        ("GET", f"{m}/versions"): Operacion(
            titulo="Listar versiones",
            descripcion=(
                "Versiones del modelo ordenadas por número, en resumen (sin el modelo ni la "
                "base): estado, decisión (`initial`, `extend` o `replace`) y su justificación, "
                "fechas, quién decidió, recalibración y evento estructural de origen, huella y "
                "tamaño de la base.",
            ),
            previos_ok=(_version_0(),),
            errores={404: ("MODEL_NOT_FOUND",)},
            ko=(
                404,
                _error(
                    "MODEL_NOT_FOUND",
                    f"el modelo '{IDS['model']}' no existe",
                    {"model_id": IDS["model"]},
                ),
            ),
        ),
        ("GET", f"{m}/versions/{{number}}"): Operacion(
            titulo="Consultar una versión",
            descripcion=(
                "Detalle de una versión: el resumen, su modelo (`model`) y, si viene de una "
                "recalibración, su informe (`report`). Con `include`: `base_refs` (origen de cada "
                "fila de la base y candidatas que no entraron), `base_data` (la matriz de la "
                "base), `covariance` e `historical`.",
            ),
            errores={404: ("VERSION_NOT_FOUND",), 422: ("INVALID_INPUT",)},
            ko=(
                404,
                _error(
                    "VERSION_NOT_FOUND",
                    f"la versión 3 del modelo '{IDS['model']}' no existe",
                    {"model_id": IDS["model"], "version": 3},
                ),
            ),
            consulta={"include": ("base_refs",)},
            cambios_ok={"model": _modelo_recalibrado()},
        ),
        ("POST", f"{m}/versions/{{number}}/approve"): Operacion(
            titulo="Aprobar una versión",
            descripcion=(
                "Aprueba una versión `proposed`: pasa a `active` y la vigente a `superseded`. "
                "`effective_from` (por defecto, el instante de la aprobación) fija desde cuándo "
                "rige y no puede ser retroactivo: debe ser posterior a la última observación ya "
                "puntuada y a la entrada en vigor de la versión vigente. Las observaciones con "
                "fecha anterior se siguen puntuando con la versión que regía entonces.",
                "Quien decide (`decided_by`) es el `sub` del token. El cuerpo es opcional.",
            ),
            errores={
                404: ("MODEL_NOT_FOUND", "VERSION_NOT_FOUND"),
                409: ("VERSION_NOT_PROPOSED", "EFFECTIVE_FROM_NOT_AFTER_SCORED"),
                422: ("INVALID_INPUT",),
            },
            ko=(
                409,
                _error(
                    "EFFECTIVE_FROM_NOT_AFTER_SCORED",
                    "'effective_from' debe ser posterior a la última observación puntuada",
                    {
                        "effective_from": "2026-10-01T00:00:00+00:00",
                        "last_scored": "2026-10-01T21:00:00+00:00",
                    },
                ),
            ),
            cambios_ok={
                "status": "active",
                "effective_from": "2026-10-03T00:00:00Z",
                "approved_at": "2026-10-02T15:40:12Z",
                "decided_by": "carlos.ruiz",
                "decision_note": NOTA_APROBACION,
            },
        ),
        ("POST", f"{m}/versions/{{number}}/reject"): Operacion(
            titulo="Rechazar una versión",
            descripcion=(
                "Rechaza una versión `proposed`; la versión vigente no cambia. `note` registra "
                "el motivo y `decided_by` es el `sub` del token. El cuerpo es opcional.",
            ),
            errores={
                404: ("VERSION_NOT_FOUND",),
                409: ("VERSION_NOT_PROPOSED",),
                422: ("INVALID_INPUT",),
            },
            ko=(
                409,
                _error(
                    "VERSION_NOT_PROPOSED",
                    "la versión 0 no es una propuesta",
                    {"version": 0, "status": "active"},
                ),
            ),
            cambios_ok={
                "status": "rejected",
                "rejected_at": "2026-10-02T15:40:12Z",
                "decided_by": "carlos.ruiz",
                "decision_note": NOTA_RECHAZO,
            },
        ),
        ("GET", "/health"): Operacion(
            titulo="Vida del proceso",
            descripcion=(
                "Responde `200` si el proceso está vivo, sin consultar ninguna dependencia. Es "
                "la sonda de vida (liveness) del orquestador. Pública: no exige token.",
            ),
        ),
        ("GET", "/ready"): Operacion(
            titulo="Disponibilidad",
            descripcion=(
                "Comprueba cada dependencia externa: `database` (`SELECT 1` con tiempo máximo "
                "corto) cuando el estado persiste en Postgres y `storage` (directorio escribible) "
                "con almacenamiento local; sin dependencias externas, `checks` va vacío.",
                "Responde `200` con `ready` si todas están bien, o `503` con `not_ready` y la "
                "comprobación que falló. Es la sonda de disponibilidad (readiness). Pública: no "
                "exige token.",
            ),
            errores={503: ()},
            ko=(503, {"status": "not_ready", "checks": {"database": "fail", "storage": "ok"}}),
            significado={
                200: "Listo para recibir tráfico (`status: ready`).",
                503: "Alguna dependencia falló (`status: not_ready`).",
            },
        ),
    }


def _grupos() -> tuple[Grupo, ...]:
    """Grupos de la referencia, en orden de lectura.

    Returns:
        Los grupos.
    """
    m = MODELO
    c = PREFIJO_CARTA
    return (
        Grupo(
            "ref-datasets",
            "Datasets",
            (
                "Un dataset es una matriz n &times; p del tenant: la entrada de la Fase I. Es "
                "inmutable y no pertenece a ninguna carta; las exclusiones y las recalibraciones "
                "crean datasets derivados con su linaje.",
            ),
            (("POST", "/v1/datasets"), ("GET", "/v1/datasets/{dataset_id}")),
        ),
        Grupo(
            "ref-fase-1",
            "Fase I: ajuste, límites y modelo",
            (
                "La Fase I construye el modelo de la carta T²MRCD con el histórico: exclusión "
                "humana opcional (`/exclusions`), ajuste MRCD (`/fits`), calibración bootstrap "
                "de los límites (`/limits`) y ensamblado del modelo (`/models`). Cada paso es "
                "asíncrono: el `POST` valida, encola y responde `202 {id, status}`, y el `GET` del "
                "recurso informa del estado (`queued`, `running`, `succeeded` o `failed`).",
                "La tubería `/pipelines/phase1` encadena los mismos pasos y da el mismo modelo "
                "bit a bit.",
            ),
            (
                ("POST", f"{c}/fits"),
                ("GET", f"{c}/fits/{{fit_id}}"),
                ("POST", f"{c}/limits"),
                ("GET", f"{c}/limits/{{limits_id}}"),
                ("POST", f"{c}/exclusions"),
                ("GET", f"{c}/exclusions/{{exclusion_id}}"),
                ("POST", f"{c}/models"),
                ("GET", m),
                ("GET", f"{m}/status"),
                ("POST", f"{c}/pipelines/phase1"),
                ("GET", f"{c}/pipelines/{{pipeline_id}}"),
                ("GET", f"{c}/pipelines/phase1/{{pipeline_id}}"),
            ),
        ),
        Grupo(
            "ref-fase-2",
            "Fase II: puntuación y seguimiento",
            (
                "Con el modelo listo, la Fase II puntúa observaciones nuevas: cada una recibe su "
                "T² y se compara con el límite de la versión que rige en su fecha; si lo supera, "
                "es una señal. Las observaciones puntuadas quedan registradas, las señales se "
                "anotan y los cambios de régimen se registran como eventos estructurales.",
            ),
            (
                ("POST", f"{m}/scores"),
                ("GET", f"{m}/scores/{{score_id}}"),
                ("GET", f"{m}/observations"),
                ("POST", f"{m}/observations/{{observation_id}}/annotations"),
                ("POST", f"{m}/structural-events"),
                ("GET", f"{m}/structural-events"),
            ),
        ),
        Grupo(
            "ref-recalibracion",
            "Recalibración y extensión",
            (
                "La recalibración incorpora observaciones nuevas y produce una versión "
                "propuesta, que una persona aprueba o rechaza. Por defecto amplía la base "
                "vigente con las observaciones nuevas conservadas (EXTEND); la reemplaza "
                "(REPLACE) solo con `force_replace` o tras un evento estructural sin resolver. "
                "Si quedan menos de `min_observations`, termina `insufficient`. Como máximo hay "
                "una recalibración en curso y una propuesta pendiente por modelo.",
                "En modo paso a paso (`mode: stepwise`) se encadenan por id: `/exclusions` (si "
                "hay anotaciones con causa asignable) &rarr; `…/extension` (salvo REPLACE) "
                "&rarr; `/fits` &rarr; `/limits` con `recalibration_id` &rarr; `…/versions`.",
            ),
            (
                ("POST", f"{m}/recalibrations"),
                ("GET", f"{m}/recalibrations/{{recalibration_id}}"),
                ("POST", f"{m}/recalibrations/{{recalibration_id}}/extension"),
                ("POST", f"{m}/versions"),
                ("POST", f"{m}/recalibrations/{{recalibration_id}}/cancel"),
            ),
        ),
        Grupo(
            "ref-versiones",
            "Versiones",
            (
                "Cada modelo tiene versiones inmutables numeradas: la 0 nace con la Fase I y "
                "cada recalibración propone una nueva (`POST …/versions` en modo paso a paso). "
                "Estados: `proposed`, `active` (la vigente), `superseded` (sustituida; sigue "
                "rigiendo sus fechas) y `rejected`. Aprobar y rechazar exigen el rol `approver` "
                "o `admin`.",
            ),
            (
                ("GET", f"{m}/versions"),
                ("GET", f"{m}/versions/{{number}}"),
                ("POST", f"{m}/versions/{{number}}/approve"),
                ("POST", f"{m}/versions/{{number}}/reject"),
            ),
        ),
        Grupo(
            "ref-health",
            "Vida y disponibilidad",
            ("Rutas públicas (sin token) para el orquestador o el balanceador de carga.",),
            (("GET", "/health"), ("GET", "/ready")),
        ),
    )


# --- utilidades de OpenAPI ------------------------------------------------------------------------


def _resolver(openapi: Mapping[str, Any], esquema: Mapping[str, Any]) -> Mapping[str, Any]:
    """Sigue un ``$ref`` local (``#/components/schemas/X``).

    Args:
        openapi: Documento OpenAPI.
        esquema: Esquema (con o sin ``$ref``).

    Returns:
        El esquema referenciado, o el mismo.

    Raises:
        KeyError: Si la referencia no existe.
    """
    ref = esquema.get("$ref")
    if not isinstance(ref, str):
        return esquema
    destino: Any = openapi
    for parte in ref.removeprefix("#/").split("/"):
        destino = destino[parte]
    resuelto: Mapping[str, Any] = destino
    return _resolver(openapi, resuelto)


def _nombre(esquema: Mapping[str, Any]) -> str | None:
    """Nombre de un esquema: el de su ``$ref`` o su ``title``.

    Args:
        esquema: Esquema.

    Returns:
        El nombre, o ``None``.
    """
    ref = esquema.get("$ref")
    if isinstance(ref, str):
        return ref.rsplit("/", 1)[-1]
    titulo = esquema.get("title")
    return titulo if isinstance(titulo, str) and " " not in titulo else None


def _ramas(esquema: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Ramas de un ``anyOf``/``oneOf``, o el propio esquema.

    Args:
        esquema: Esquema.

    Returns:
        Las ramas.
    """
    ramas = esquema.get("anyOf") or esquema.get("oneOf")
    return list(ramas) if isinstance(ramas, list) else [esquema]


def _sin_nulo(esquema: Mapping[str, Any]) -> tuple[Mapping[str, Any], bool]:
    """Quita la rama ``null`` de un ``anyOf`` (campo opcional que admite ``null``).

    Args:
        esquema: Esquema.

    Returns:
        (esquema sin la rama nula, si admitía ``null``).
    """
    ramas = _ramas(esquema)
    utiles = [r for r in ramas if r.get("type") != "null"]
    if len(ramas) > 1 and len(utiles) == 1:
        base = dict(utiles[0])
        for clave in ("title", "default", "description"):
            if clave in esquema and clave not in base:
                base[clave] = esquema[clave]
        return base, True
    return esquema, False


def _operaciones_de(openapi: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    """Operaciones del OpenAPI por (método, plantilla).

    Args:
        openapi: Documento OpenAPI.

    Returns:
        Las operaciones.
    """
    salida: dict[tuple[str, str], Mapping[str, Any]] = {}
    for plantilla, operaciones in openapi.get("paths", {}).items():
        for metodo, operacion in operaciones.items():
            if metodo in METODOS:
                salida[(metodo.upper(), plantilla)] = operacion
    return salida


def _tipo(openapi: Mapping[str, Any], esquema: Mapping[str, Any]) -> str:
    """Tipo legible de un esquema.

    Args:
        openapi: Documento OpenAPI.
        esquema: Esquema.

    Returns:
        El tipo (p. ej. ``Array de Number``).
    """
    nombre = _nombre(esquema)
    esquema = _resolver(openapi, esquema)
    base, _ = _sin_nulo(esquema)
    if base is not esquema:
        return _tipo(openapi, base)
    ramas = _ramas(esquema)
    if len(ramas) > 1:
        return " o ".join(_tipo(openapi, r) for r in ramas)
    tipo = esquema.get("type")
    if tipo == "array":
        return f"Array de {_tipo(openapi, esquema.get('items', {}))}"
    if tipo == "object" or "properties" in esquema:
        return f"Object ({nombre})" if nombre and "properties" in esquema else "Object"
    if tipo == "string":
        formato = esquema.get("format")
        if formato == "date-time":
            return "String (fecha)"
        if formato == "binary":
            return "Fichero"
        return "String"
    nombres = {"integer": "Integer", "number": "Number", "boolean": "Boolean", "null": "null"}
    return nombres.get(str(tipo), "Cualquiera")


def _restricciones(esquema: Mapping[str, Any]) -> list[str]:
    """Restricciones legibles de un esquema (longitudes, mínimos, valores admitidos).

    En un array da las suyas (número de elementos) y las de cada elemento; los valores admitidos
    de un array de enumerados se dan sin más («Valores: …»).

    Args:
        esquema: Esquema (ya sin la rama nula).

    Returns:
        Las restricciones (HTML ya escapado).
    """
    items = esquema.get("items")
    elementos = items if isinstance(items, dict) and "$ref" not in items else {}
    salida = _valores_admitidos(esquema) + _valores_admitidos(elementos)
    propias = _limites(esquema)
    de_cada = _limites(elementos)
    if de_cada:
        propias.append(f"cada elemento {', '.join(de_cada)}")
    if propias:
        salida.append(f"Restricción: {'; '.join(propias)}.")
    return salida


def _valores_admitidos(esquema: Mapping[str, Any]) -> list[str]:
    """``enum`` o ``const`` de un esquema como texto.

    Args:
        esquema: Esquema.

    Returns:
        Cero o una frase (HTML).
    """
    if "enum" in esquema:
        valores = ", ".join(
            _codigo(json.dumps(v, ensure_ascii=False).strip('"')) for v in esquema["enum"]
        )
        return [f"Valores: {valores}."]
    if "const" in esquema:
        return [f"Único valor: {_codigo(str(esquema['const']))}."]
    return []


def _limites(esquema: Mapping[str, Any]) -> list[str]:
    """Límites numéricos y de longitud de un esquema, en singular o plural según el valor.

    Args:
        esquema: Esquema.

    Returns:
        Los límites (HTML).
    """
    pares = (
        ("minimum", "&ge; {}", None),
        ("exclusiveMinimum", "&gt; {}", None),
        ("maximum", "&le; {}", None),
        ("exclusiveMaximum", "&lt; {}", None),
        ("minLength", "mín. {} {}", ("carácter", "caracteres")),
        ("maxLength", "máx. {} {}", ("carácter", "caracteres")),
        ("minItems", "mín. {} {}", ("elemento", "elementos")),
        ("maxItems", "máx. {} {}", ("elemento", "elementos")),
    )
    salida: list[str] = []
    for clave, plantilla, unidades in pares:
        if clave not in esquema:
            continue
        numero = _numero(esquema[clave])
        if unidades is None:
            salida.append(plantilla.format(numero))
        else:
            salida.append(plantilla.format(numero, unidades[0] if numero == "1" else unidades[1]))
    return salida


def _numero(valor: object) -> str:
    """Número sin decimales superfluos (``0.0`` → ``0``).

    Args:
        valor: Número.

    Returns:
        El texto.
    """
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor)


def _atributos(descripcion: str) -> dict[str, str]:
    """Descripción de cada campo según la sección ``Attributes:`` de un docstring.

    Args:
        descripcion: Docstring del schema (la ``description`` del OpenAPI).

    Returns:
        Texto por campo (con el código en comillas invertidas simples).
    """
    salida: dict[str, str] = {}
    if "Attributes:" not in descripcion:
        return salida
    actual: str | None = None
    for linea in descripcion.split("Attributes:", 1)[1].splitlines():
        coincide = re.match(r"^ {4}(\w+): (.*)$", linea)
        if coincide:
            actual = coincide.group(1)
            salida[actual] = coincide.group(2).strip()
        elif actual is not None and linea.startswith("        "):
            salida[actual] += " " + linea.strip()
        elif linea.strip():
            actual = None
    return {k: _rst(v) for k, v in salida.items()}


def _rst(texto: str) -> str:
    """Pasa el código de reStructuredText (````x````) a comillas invertidas simples.

    Args:
        texto: Texto.

    Returns:
        El texto convertido.
    """
    return re.sub(r"``([^`]+)``", r"`\1`", texto)


# --- HTML -----------------------------------------------------------------------------------------


def _codigo(texto: str, *, partible: bool = False) -> str:
    """Código en línea, escapado.

    Args:
        texto: Texto del código.
        partible: Permitir cortes de línea tras ``.``, ``_``, ``/`` y entre palabras de un
            nombre en CamelCase (columnas estrechas). Solo ahí: WeasyPrint aplica
            ``overflow-wrap: anywhere`` antes que los ``<wbr>`` y partiría las palabras.

    Returns:
        El HTML.
    """
    seguro = escape(texto)
    if not partible:
        return f"<code>{seguro}</code>"
    con_cortes = re.sub(r"([./_\]])", r"\1<wbr>", seguro)
    con_cortes = re.sub(r"([a-z0-9])([A-Z])", r"\1<wbr>\2", con_cortes)
    return f'<code style="white-space:normal">{con_cortes}</code>'


def _texto(texto: str) -> str:
    """Texto escapado con el código entre comillas invertidas como ``<code>``.

    Conserva las entidades de ``ENTIDADES`` (``&times;``, ``&alpha;``…) que usan los textos.

    Args:
        texto: Texto.

    Returns:
        El HTML.
    """
    seguro = ENTIDADES.sub(r"&\1;", escape(texto, quote=False))
    return re.sub(r"`([^`]+)`", lambda m: f"<code>{m.group(1)}</code>", seguro)


def _json_html(valor: object, sangria: int = 0) -> str:
    """JSON indentado y coloreado con las clases de ``voracious.css`` (``.k .s .n .c``).

    Una lista ``Abreviada`` se escribe con sus elementos y una línea final «… N … más».

    Args:
        valor: Valor JSON.
        sangria: Nivel de sangría.

    Returns:
        El HTML (escapado).
    """
    espacio = "  " * sangria
    interior = "  " * (sangria + 1)
    if isinstance(valor, dict):
        if not valor:
            return "{}"
        filas = [
            f'{interior}<span class="k">{escape(json.dumps(k, ensure_ascii=False))}</span>: '
            f"{_json_html(v, sangria + 1)}"
            for k, v in valor.items()
        ]
        return "{\n" + ",\n".join(filas) + f"\n{espacio}}}"
    if isinstance(valor, Abreviada):
        filas = [f"{interior}{_json_html(v, sangria + 1)}" for v in valor]
        filas.append(
            f'{interior}<span class="c">&hellip; {valor.omitidos} {valor.unidad} más</span>'
        )
        return "[\n" + ",\n".join(filas) + f"\n{espacio}]"
    if isinstance(valor, list):
        if not valor:
            return "[]"
        if all(not isinstance(v, dict | list) for v in valor):
            linea = "[" + ", ".join(_json_html(v) for v in valor) + "]"
            if len(json.dumps(valor, ensure_ascii=False)) + len(interior) <= 72:
                return linea
        filas = [f"{interior}{_json_html(v, sangria + 1)}" for v in valor]
        return "[\n" + ",\n".join(filas) + f"\n{espacio}]"
    if isinstance(valor, str):
        return f'<span class="s">{escape(json.dumps(valor, ensure_ascii=False))}</span>'
    return f'<span class="n">{escape(json.dumps(valor))}</span>'


LINEAS_POR_PAGINA = 40
"""Líneas a partir de las que un bloque de código puede partirse entre páginas."""


def _pre(contenido: str) -> str:
    """Bloque de código que parte las líneas largas sin desbordar la página.

    ``voracious.css`` pide ``page-break-inside: avoid`` en ``pre``; un bloque más largo que una
    página saltaría entero a la siguiente y dejaría su encabezado solo en una página vacía, así
    que a partir de ``LINEAS_POR_PAGINA`` líneas se permite partirlo.

    Args:
        contenido: HTML ya escapado.

    Returns:
        El bloque.
    """
    estilo = "overflow-wrap:anywhere"
    if contenido.count("\n") + 1 > LINEAS_POR_PAGINA:
        estilo += ";page-break-inside:auto;break-inside:auto"
    return f'<pre style="{estilo}"><code>{contenido}</code></pre>'


ALTURA_TABLA_CORTA_MM = 70
"""Altura estimada hasta la que una tabla no se parte entre páginas (menos de un tercio de
página: si salta entera a la siguiente, el hueco que deja es pequeño)."""

CARACTERES_POR_ANCHO = 100
"""Caracteres de texto de tabla que caben en el ancho completo de la página (9,3 pt)."""

SIN_CORTE_DESPUES = "page-break-after:avoid;break-after:avoid"
"""Estilo que une un título o una cabecera de tabla con lo que le sigue."""


def _altura_mm(cabecera: Sequence[tuple[str, str | None]], filas: Sequence[Sequence[str]]) -> float:
    """Altura aproximada de una tabla: líneas de la celda más larga de cada fila.

    Args:
        cabecera: (texto, ancho CSS en porcentaje o ``None``) de cada columna.
        filas: Celdas ya en HTML.

    Returns:
        La altura en milímetros (título, cabecera y filas con su relleno).
    """
    fijos = [float(ancho.rstrip("%")) for _, ancho in cabecera if ancho]
    libres = sum(1 for _, ancho in cabecera if not ancho)
    resto = (100 - sum(fijos)) / max(libres, 1)
    anchos = [float(ancho.rstrip("%")) if ancho else resto for _, ancho in cabecera]
    altura = 14.0
    for fila in filas:
        lineas = 1
        for celda, ancho in zip(fila, anchos, strict=True):
            texto = re.sub(r"<[^>]+>", "", celda)
            caben = max(int(ancho * CARACTERES_POR_ANCHO / 100), 1)
            lineas = max(lineas, -(-len(texto) // caben))
        altura += 4.0 + 4.6 * lineas
    return altura


def _tabla(
    titulo: str, cabecera: Sequence[tuple[str, str | None]], filas: Sequence[Sequence[str]]
) -> str:
    """Tabla con título y anchos de columna fijos (``table-layout: fixed``).

    Con el reparto automático WeasyPrint no respeta los anchos en porcentaje y estrecha la
    columna de los nombres de campo. El título y la fila de cabecera no se separan de la primera
    fila (sin cabeceras huérfanas al pie de página) y una tabla corta (``ALTURA_TABLA_CORTA_MM``)
    no se parte.

    Args:
        titulo: Texto del ``caption``.
        cabecera: (texto, ancho CSS o ``None``) de cada columna.
        filas: Celdas ya en HTML.

    Returns:
        La tabla.
    """
    columnas = "".join(
        f'<th style="width:{ancho}">{escape(texto)}</th>' if ancho else f"<th>{escape(texto)}</th>"
        for texto, ancho in cabecera
    )
    cuerpo = "".join(
        "<tr>" + "".join(f"<td>{celda}</td>" for celda in fila) + "</tr>" for fila in filas
    )
    estilo = "table-layout:fixed"
    if _altura_mm(cabecera, filas) <= ALTURA_TABLA_CORTA_MM:
        estilo += ";page-break-inside:avoid;break-inside:avoid"
    return (
        f'<table style="{estilo}"><caption style="{SIN_CORTE_DESPUES}">{escape(titulo)}</caption>'
        f'<tr style="{SIN_CORTE_DESPUES}">{columnas}</tr>{cuerpo}</table>'
    )


def _ancla(metodo: str, plantilla: str) -> str:
    """``id`` de una operación (``ref-post-fits``, ``ref-get-models-model-id``…).

    Args:
        metodo: Método HTTP.
        plantilla: Plantilla de la ruta.

    Returns:
        El ``id``.
    """
    ruta = plantilla.removeprefix(PREFIJO_CARTA).removeprefix("/v1")
    partes = re.sub(r"[^a-z0-9]+", "-", f"{metodo.lower()}-{ruta.lower()}").strip("-")
    return f"ref-{partes}"


def _endpoint(metodo: str, plantilla: str) -> str:
    """Encabezado ``.endpoint`` con el método y la ruta (partible tras cada ``/``).

    Args:
        metodo: Método HTTP.
        plantilla: Plantilla de la ruta.

    Returns:
        El HTML.
    """
    ruta = escape(plantilla).replace("/", "/<wbr>")
    clase = metodo.lower() if metodo.lower() in {"get", "post", "delete"} else "get"
    return (
        f'<div class="endpoint"><span class="metodo {clase}">{escape(metodo)}</span>'
        f'<span style="min-width:0">{ruta}</span></div>'
    )


# --- ejemplos derivados del esquema ---------------------------------------------------------------

FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def _validar(
    openapi: Mapping[str, Any], valor: object, esquema: Mapping[str, Any], ruta: str
) -> list[str]:
    """Comprueba un ejemplo contra su esquema (subconjunto de JSON Schema que usa la API).

    Args:
        openapi: Documento OpenAPI.
        valor: Ejemplo.
        esquema: Esquema.
        ruta: Ruta del valor dentro del ejemplo (para los mensajes).

    Returns:
        Los errores (vacío si cumple).
    """
    esquema = _resolver(openapi, esquema)
    ramas = esquema.get("anyOf") or esquema.get("oneOf")
    if isinstance(ramas, list):
        if any(not _validar(openapi, valor, r, ruta) for r in ramas):
            return []
        return [f"{ruta}: no cumple ninguna rama de {[_tipo(openapi, r) for r in ramas]}"]
    errores: list[str] = []
    if "const" in esquema and valor != esquema["const"]:
        errores.append(f"{ruta}: debe ser {esquema['const']!r}")
    if "enum" in esquema and valor not in esquema["enum"]:
        errores.append(f"{ruta}: {valor!r} no está en {esquema['enum']}")
    tipo = esquema.get("type")
    tipos: dict[str, tuple[type, ...]] = {
        "object": (dict,),
        "array": (list,),
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
    }
    if tipo == "null":
        return errores if valor is None else [*errores, f"{ruta}: debe ser null"]
    if isinstance(tipo, str) and tipo in tipos:
        es_bool = isinstance(valor, bool)
        if not isinstance(valor, tipos[tipo]) or (es_bool and tipo != "boolean"):
            return [*errores, f"{ruta}: se esperaba {tipo}, no {type(valor).__name__}"]
    if isinstance(valor, dict):
        errores.extend(_validar_objeto(openapi, valor, esquema, ruta))
    elif isinstance(valor, list):
        if len(valor) < int(esquema.get("minItems", 0)):
            errores.append(f"{ruta}: menos de {esquema['minItems']} elementos")
        items = esquema.get("items")
        if isinstance(items, dict):
            for i, v in enumerate(valor):
                errores.extend(_validar(openapi, v, items, f"{ruta}[{i}]"))
    elif isinstance(valor, str):
        if esquema.get("format") == "date-time" and not FECHA.match(valor):
            errores.append(f"{ruta}: {valor!r} no es una fecha ISO 8601 con zona")
        if len(valor) < int(esquema.get("minLength", 0)):
            errores.append(f"{ruta}: demasiado corto")
    elif isinstance(valor, int | float) and not isinstance(valor, bool):
        errores.extend(_validar_numero(valor, esquema, ruta))
    return errores


def _validar_objeto(
    openapi: Mapping[str, Any], valor: Mapping[str, object], esquema: Mapping[str, Any], ruta: str
) -> list[str]:
    """Comprueba los campos de un objeto (obligatorios, desconocidos y sus valores).

    Args:
        openapi: Documento OpenAPI.
        valor: Objeto del ejemplo.
        esquema: Esquema del objeto.
        ruta: Ruta del objeto.

    Returns:
        Los errores.
    """
    errores = [
        f"{ruta}.{c}: falta (obligatorio)" for c in esquema.get("required", []) if c not in valor
    ]
    propiedades: Mapping[str, Any] = esquema.get("properties", {})
    adicionales = esquema.get("additionalProperties", True)
    for clave, v in valor.items():
        if clave in propiedades:
            errores.extend(_validar(openapi, v, propiedades[clave], f"{ruta}.{clave}"))
        elif adicionales is False:
            errores.append(f"{ruta}.{clave}: campo desconocido")
        elif isinstance(adicionales, dict):
            errores.extend(_validar(openapi, v, adicionales, f"{ruta}.{clave}"))
    return errores


def _validar_numero(valor: float, esquema: Mapping[str, Any], ruta: str) -> list[str]:
    """Comprueba los límites de un número.

    Args:
        valor: Número.
        esquema: Esquema.
        ruta: Ruta del valor.

    Returns:
        Los errores.
    """
    comprobaciones = (
        ("minimum", lambda lim: valor >= lim),
        ("exclusiveMinimum", lambda lim: valor > lim),
        ("maximum", lambda lim: valor <= lim),
        ("exclusiveMaximum", lambda lim: valor < lim),
    )
    return [
        f"{ruta}: {valor} no cumple {clave} {esquema[clave]}"
        for clave, cumple in comprobaciones
        if clave in esquema and not cumple(esquema[clave])
    ]


@dataclass(frozen=True)
class Generador:
    """Genera ejemplos verosímiles a partir de un esquema y de la tabla de valores.

    Attributes:
        openapi: Documento OpenAPI.
        valores: Valores por campo (``_valores``).
        peticion: Ejemplo de petición (solo obligatorios e ``INCLUIR_EN_PETICION``).
        recurso: Recurso del ``id`` de un ``AcceptedJob``.
        estado: Valor de ``status`` de un trabajo (``queued`` o ``succeeded``).
    """

    openapi: Mapping[str, Any]
    valores: Mapping[str, object]
    peticion: bool
    recurso: str | None = None
    estado: str = "succeeded"

    def ejemplo(
        self, esquema: Mapping[str, Any], campo: str | None = None, padre: str | None = None
    ) -> object:
        """Ejemplo de un valor del esquema.

        Args:
            esquema: Esquema del valor.
            campo: Nombre del campo que lo contiene (para buscar en la tabla).
            padre: Nombre del esquema que contiene el campo.

        Returns:
            El ejemplo.

        Raises:
            ValueError: Si un valor calificado de la tabla no cumple el esquema.
        """
        elegido = self._de_tabla(esquema, campo, padre)
        if elegido is not _NADA:
            return elegido
        nombre = _nombre(esquema)
        esquema = _resolver(self.openapi, esquema)
        base, nulo = _sin_nulo(esquema)
        if nulo:
            return self.ejemplo(base, campo, padre)
        ramas = esquema.get("anyOf") or esquema.get("oneOf")
        if isinstance(ramas, list):
            return self.ejemplo(ramas[0], campo, padre)
        if "const" in esquema:
            return esquema["const"]
        if "enum" in esquema:
            return esquema["enum"][0]
        return self._por_tipo(esquema, nombre, campo)

    def _de_tabla(self, esquema: Mapping[str, Any], campo: str | None, padre: str | None) -> object:
        """Valor de la tabla para el campo, si cumple su esquema.

        Args:
            esquema: Esquema del campo.
            campo: Nombre del campo.
            padre: Esquema que lo contiene.

        Returns:
            El valor, o ``_NADA`` si no hay uno aplicable.

        Raises:
            ValueError: Si un valor calificado no cumple el esquema.
        """
        if campo is None:
            return _NADA
        if self.recurso is not None and padre == "AcceptedJob":
            fijo = {"id": IDS[self.recurso], "status": "queued"}
            return fijo.get(campo, _NADA)
        if campo == "status" and padre not in {"ChartStatusOut", "VersionSummary", "VersionDetail"}:
            candidatos = [self.estado, "running", "ok", "ready"]
            for candidato in candidatos:
                if not _validar(self.openapi, candidato, esquema, campo):
                    return candidato
        claves = []
        if padre is not None:
            claves.append(f"{padre}.{campo}")
            if padre in ALIAS_DE_ESQUEMA:
                claves.append(f"{ALIAS_DE_ESQUEMA[padre]}.{campo}")
        for clave in claves:
            if clave in self.valores:
                valor = self.valores[clave]
                errores = _validar(self.openapi, valor, esquema, clave)
                if errores:
                    msg = f"el valor de ejemplo de {clave} no cumple el esquema: {errores}"
                    raise ValueError(msg)
                return valor
        if campo in self.valores:
            valor = self.valores[campo]
            if not _validar(self.openapi, valor, esquema, campo):
                return valor
        return _NADA

    def _por_tipo(
        self, esquema: Mapping[str, Any], nombre: str | None, campo: str | None
    ) -> object:
        """Ejemplo genérico según el tipo del esquema.

        Args:
            esquema: Esquema ya resuelto.
            nombre: Nombre del esquema (``Esquema`` de ``Esquema.campo``).
            campo: Campo que lo contiene.

        Returns:
            El ejemplo.
        """
        tipo = esquema.get("type")
        if tipo == "object" or "properties" in esquema:
            requeridos = set(esquema.get("required", []))
            salida: dict[str, object] = {}
            for clave, sub in esquema.get("properties", {}).items():
                if (
                    self.peticion
                    and clave not in requeridos
                    and f"{nombre}.{clave}" not in INCLUIR_EN_PETICION
                ):
                    continue
                salida[clave] = self.ejemplo(sub, clave, nombre)
            return salida
        if tipo == "array":
            items = esquema.get("items", {})
            return [self.ejemplo(items, campo, None)]
        if tipo == "string":
            return "2026-10-20T14:03:12Z" if esquema.get("format") == "date-time" else "texto"
        if tipo == "integer":
            return 1
        if tipo == "number":
            return 1.0
        if tipo == "boolean":
            return True
        return None


class _Nada:
    """Centinela: la tabla no tiene un valor aplicable."""


_NADA = _Nada()


# --- secciones de una operación -------------------------------------------------------------------


def _roles(operacion: Mapping[str, Any]) -> list[str] | None:
    """Roles exigidos por la operación (``x-voracious-roles``).

    Args:
        operacion: Operación del OpenAPI.

    Returns:
        Los roles, ``[]`` si es pública o ``None`` si el OpenAPI no los declara.
    """
    roles = operacion.get(EXTENSION_ROLES)
    return [str(r) for r in roles] if isinstance(roles, list) else None


def _html_roles(roles: list[str] | None) -> str:
    """Línea de roles exigidos.

    Args:
        roles: Roles (``[]``: pública; ``None``: no declarados).

    Returns:
        El HTML.
    """
    if roles is None:
        return '<p class="pequeno"><strong>Roles:</strong> no declarados en el OpenAPI.</p>'
    if not roles:
        return '<p class="pequeno"><strong>Acceso:</strong> público, sin token.</p>'
    chips = " ".join(f'<span class="chip">{escape(r)}</span>' for r in roles)
    grupo = ROLES_DE_GRUPO.get(frozenset(roles))
    sufijo = f' <span class="tenue">({escape(grupo)})</span>' if grupo else ""
    return f'<p class="pequeno"><strong>Roles exigidos:</strong> {chips}{sufijo}</p>'


def _cuerpo_de(
    openapi: Mapping[str, Any], operacion: Mapping[str, Any]
) -> tuple[Mapping[str, Any] | None, bool, list[str]]:
    """Esquema JSON del cuerpo, si es obligatorio y los tipos de contenido admitidos.

    Args:
        openapi: Documento OpenAPI.
        operacion: Operación.

    Returns:
        (esquema del cuerpo JSON sin la rama nula o ``None``, obligatorio, tipos de contenido).
    """
    cuerpo = operacion.get("requestBody")
    if not isinstance(cuerpo, dict):
        return None, False, []
    contenido: Mapping[str, Any] = cuerpo.get("content", {})
    tipos = list(contenido)
    json_ = contenido.get("application/json", {}).get("schema")
    if not isinstance(json_, dict):
        return None, bool(cuerpo.get("required")), tipos
    base, _ = _sin_nulo(json_)
    return base, bool(cuerpo.get("required")), tipos


def _html_cabeceras(roles: list[str] | None, tipos: list[str], obligatorio: bool) -> str:
    """Tabla de cabeceras.

    Args:
        roles: Roles (``[]``: pública).
        tipos: Tipos de contenido del cuerpo (vacío: sin cuerpo).
        obligatorio: El cuerpo es obligatorio.

    Returns:
        El HTML (vacío si no hay cabeceras).
    """
    filas: list[list[str]] = []
    if roles != []:
        filas.append(
            [
                _codigo("Authorization"),
                _texto("`Bearer <token>`: JWT firmado con los claims `tenant` y `roles`."),
                "String",
                "Sí",
            ]
        )
    if tipos:
        if len(tipos) > 1:
            lista = ", ".join(_codigo(t) for t in tipos)
            parte = _codigo("file")
            texto = (
                f"Tipo del cuerpo, uno de: {lista}. En multipart, el CSV va en la parte {parte}."
            )
        else:
            texto = f"Debe ser {_codigo(tipos[0])}."
        filas.append(
            [
                _codigo("Content-Type"),
                texto,
                "String",
                "Sí" if obligatorio else "Solo si se envía cuerpo",
            ]
        )
    if not filas:
        return ""
    cabecera = (("Nombre", "24%"), ("Descripción", None), ("Tipo", "12%"), ("Obligatorio", "14%"))
    return _tabla("Cabeceras", cabecera, filas)


def _html_parametros(openapi: Mapping[str, Any], operacion: Mapping[str, Any]) -> str:
    """Tabla de parámetros de ruta y de consulta.

    Args:
        openapi: Documento OpenAPI.
        operacion: Operación.

    Returns:
        El HTML (vacío si no hay parámetros).
    """
    filas: list[list[str]] = []
    for parametro in operacion.get("parameters", []):
        nombre = str(parametro["name"])
        ubicacion = {"path": "ruta", "query": "consulta"}.get(
            parametro.get("in"), parametro.get("in")
        )
        esquema, _ = _sin_nulo(_resolver(openapi, parametro.get("schema", {})))
        partes = [
            _texto(PARAMETROS.get(nombre, _rst(str(parametro.get("description", ""))))),
            *_restricciones(esquema),
        ]
        defecto = esquema.get("default", parametro.get("schema", {}).get("default"))
        filas.append(
            [
                f"{_codigo(nombre, partible=True)}<br>"
                f'<span class="pequeno tenue">{escape(str(ubicacion))}</span>',
                " ".join(p for p in partes if p),
                escape(_tipo(openapi, esquema)),
                "Sí" if parametro.get("required") else "No",
                _codigo(json.dumps(defecto, ensure_ascii=False).strip('"'))
                if defecto is not None
                else "&mdash;",
            ]
        )
    if not filas:
        return ""
    cabecera = (
        ("Nombre", "20%"),
        ("Descripción", None),
        ("Tipo", "14%"),
        ("Obligatorio", "11%"),
        ("Por defecto", "13%"),
    )
    return _tabla("Parámetros de ruta y de consulta", cabecera, filas)


def _filas_cuerpo(
    openapi: Mapping[str, Any],
    esquema: Mapping[str, Any],
    prefijo: str,
    opcional: str | None,
) -> Iterator[list[str]]:
    """Filas de la tabla del cuerpo, con los objetos anidados en notación ``a.b`` y ``a[].b``.

    Args:
        openapi: Documento OpenAPI.
        esquema: Esquema del objeto.
        prefijo: Prefijo de los campos (``""`` en el nivel superior).
        opcional: Antepasado opcional más cercano (para «Sí, si se envía …»).

    Yields:
        Las celdas de cada fila.
    """
    nombre = _nombre(esquema)
    esquema = _resolver(openapi, esquema)
    requeridos = set(esquema.get("required", []))
    docstring = _atributos(str(esquema.get("description", "")))
    textos = _defectos_de_campo()
    for campo, sub in esquema.get("properties", {}).items():
        ruta = f"{prefijo}{campo}"
        clave = f"{nombre}.{campo}"
        base, _ = _sin_nulo(_resolver(openapi, sub))
        base = _resolver(openapi, base)
        elementos = (
            _resolver(openapi, base.get("items", {})) if base.get("type") == "array" else base
        )
        descripcion = " ".join(
            p
            for p in (
                _texto(CAMPOS.get(clave, docstring.get(campo, ""))),
                *_restricciones(base),
            )
            if p
        )
        if campo in requeridos:
            obligatorio = (
                "Sí" if opcional is None else f"Sí, si se envía {_codigo(opcional, partible=True)}"
            )
        else:
            obligatorio = "No"
        if clave in textos:
            defecto = _texto(textos[clave])
        elif "default" in sub:
            defecto = _codigo(json.dumps(sub["default"], ensure_ascii=False))
        else:
            defecto = "&mdash;"
        tipo = _tipo(openapi, sub)
        yield [_codigo(ruta, partible=True), descripcion, escape(tipo), obligatorio, defecto]
        hijo_opcional = opcional if campo in requeridos else (opcional or ruta)
        if "properties" in base:
            yield from _filas_cuerpo(openapi, _sin_nulo(sub)[0], f"{ruta}.", hijo_opcional)
        elif base.get("type") == "array" and "properties" in elementos:
            yield from _filas_cuerpo(openapi, base.get("items", {}), f"{ruta}[].", hijo_opcional)


def _html_cuerpo(
    openapi: Mapping[str, Any], esquema: Mapping[str, Any] | None, tipos: list[str]
) -> str:
    """Tabla del cuerpo de la petición.

    Args:
        openapi: Documento OpenAPI.
        esquema: Esquema JSON del cuerpo (``None``: sin cuerpo JSON).
        tipos: Tipos de contenido admitidos.

    Returns:
        El HTML.
    """
    if esquema is None:
        return ""
    filas = list(_filas_cuerpo(openapi, esquema, "", None))
    if not filas:
        return ""
    cabecera = (
        ("Campo", "25%"),
        ("Descripción", None),
        ("Tipo", "12%"),
        ("Obligatorio", "12%"),
        ("Por defecto", "12%"),
    )
    titulo = "Cuerpo de la petición (JSON)" if len(tipos) > 1 else "Cuerpo de la petición"
    return _tabla(titulo, cabecera, filas)


def _ruta_de_ejemplo(plantilla: str, contenido: Operacion) -> str:
    """Ruta con los parámetros sustituidos por los identificadores de los ejemplos.

    Args:
        plantilla: Plantilla de la ruta.
        contenido: Textos de la operación (``ruta`` y ``consulta``).

    Returns:
        La ruta.
    """
    sustitutos = {
        "dataset_id": IDS["dataset"],
        "fit_id": IDS["fit"],
        "limits_id": IDS["limits"],
        "exclusion_id": IDS["exclusion"],
        "model_id": IDS["model"],
        "pipeline_id": IDS["pipeline"],
        "score_id": IDS["score"],
        "observation_id": IDS["observation"],
        "recalibration_id": IDS["recalibration"],
        "number": "1",
        **contenido.ruta,
    }
    ruta = re.sub(r"\{(\w+)\}", lambda m: sustitutos.get(m.group(1), m.group(1)), plantilla)
    pares = [
        f"{clave}={valor}" for clave, valores in contenido.consulta.items() for valor in valores
    ]
    return ruta + ("?" + "&".join(pares) if pares else "")


def _html_peticion(
    metodo: str,
    plantilla: str,
    contenido: Operacion,
    roles: list[str] | None,
    cuerpo: object,
    tipos: list[str],
) -> str:
    """Ejemplo de petición: línea de petición, cabeceras y cuerpo JSON.

    Args:
        metodo: Método.
        plantilla: Plantilla de la ruta.
        contenido: Textos de la operación.
        roles: Roles (``[]``: pública).
        cuerpo: Ejemplo del cuerpo (``None``: sin cuerpo).
        tipos: Tipos de contenido admitidos.

    Returns:
        El HTML.
    """
    lineas = [f"{escape(metodo)} {escape(_ruta_de_ejemplo(plantilla, contenido))}"]
    if roles != []:
        lineas.append("Authorization: Bearer &lt;token&gt;")
    texto = "\n".join(lineas)
    if cuerpo is not None:
        texto += "\nContent-Type: application/json\n\n" + _json_html(cuerpo)
    partes = ["<h4>Ejemplo de petición</h4>", _pre(texto)]
    if "text/csv" in tipos:
        csv = "observed_at," + ",".join(VARIABLES) + "\n"
        for fecha, fila in zip(_cierres("2025-10-24"), FILAS_HISTORICO, strict=True):
            csv += fecha + "," + ",".join(f"{v:.4f}" for v in fila) + "\n"
        cabeceras = (
            f"{escape(metodo)} {escape(plantilla)}?date_column=observed_at\n"
            "Authorization: Bearer &lt;token&gt;\nContent-Type: text/csv\n\n"
        )
        omitidas = f'<span class="c">&hellip; {N_FILAS - len(FILAS_HISTORICO)} filas más</span>'
        partes.append(
            '<p class="pequeno tenue">La misma subida en CSV, con cabecera y columna de fecha:</p>'
        )
        partes.append(_pre(cabeceras + escape(csv) + omitidas))
    return "".join(partes)


def _html_respuestas(
    openapi: Mapping[str, Any],
    operacion: Mapping[str, Any],
    contenido: Operacion,
    protegida: bool,
) -> str:
    """Tabla de respuestas: estado, significado (con los códigos posibles) y esquema.

    Solo lista los estados que la operación puede devolver: los 2xx del OpenAPI, ``401`` y
    ``403`` si es protegida y los estados de ``contenido.errores``.

    Args:
        openapi: Documento OpenAPI.
        operacion: Operación.
        contenido: Textos de la operación.
        protegida: Exige token.

    Returns:
        El HTML.
    """
    respuestas: Mapping[str, Any] = operacion.get("responses", {})
    estados = sorted({int(e) for e in respuestas if e.startswith("2")} | set(contenido.errores))
    errores = dict(contenido.errores)
    if protegida:
        estados = sorted({*estados, 401, 403})
        errores.setdefault(401, ("UNAUTHENTICATED",))
        errores.setdefault(403, ("FORBIDDEN",))
    filas: list[list[str]] = []
    for estado in estados:
        significado = _texto(contenido.significado.get(estado, SIGNIFICADO.get(estado, "")))
        codigos = errores.get(estado, ())
        if codigos:
            significado += " Códigos: " + ", ".join(_codigo(c) for c in codigos) + "."
        if estado in contenido.esquema:
            etiqueta = _codigo(contenido.esquema[estado], partible=True)
        else:
            esquema = (
                respuestas.get(str(estado), {})
                .get("content", {})
                .get("application/json", {})
                .get("schema")
            )
            etiqueta = (
                _etiqueta(openapi, esquema)
                if isinstance(esquema, dict)
                else _codigo("ErrorResponse")
            )
        filas.append([f"<strong>{estado}</strong>", significado, etiqueta])
    cabecera = (("Código HTTP", "13%"), ("Significado", None), ("Esquema", "24%"))
    return _tabla("Respuestas", cabecera, filas)


def _etiqueta(openapi: Mapping[str, Any], esquema: Mapping[str, Any]) -> str:
    """Nombre del esquema de una respuesta (``Array de X``, ``X o Y``).

    Args:
        openapi: Documento OpenAPI.
        esquema: Esquema de la respuesta.

    Returns:
        El HTML.
    """
    nombre = _nombre(esquema)
    if nombre is not None and "$ref" in esquema:
        return _codigo(nombre, partible=True)
    if esquema.get("type") == "array":
        return "Array de " + _etiqueta(openapi, esquema.get("items", {}))
    ramas = _ramas(esquema)
    if len(ramas) > 1:
        return " o ".join(_etiqueta(openapi, r) for r in ramas)
    return escape(_tipo(openapi, esquema))


def _ejemplos_ok(
    openapi: Mapping[str, Any], operacion: Mapping[str, Any], contenido: Operacion
) -> str:
    """Ejemplos de respuesta correcta, derivados del esquema y validados.

    Args:
        openapi: Documento OpenAPI.
        operacion: Operación.
        contenido: Textos de la operación.

    Returns:
        El HTML.

    Raises:
        ValueError: Si un ejemplo no cumple su esquema.
    """
    respuestas: Mapping[str, Any] = operacion.get("responses", {})
    estados = contenido.ok or tuple(sorted(int(e) for e in respuestas if e.startswith("2"))[:1])
    partes: list[str] = []
    valores = _valores()
    for estado in estados:
        esquema = (
            respuestas.get(str(estado), {})
            .get("content", {})
            .get("application/json", {})
            .get("schema")
        )
        if not isinstance(esquema, dict):
            continue
        if estado in contenido.esquema:
            esquema = {"$ref": f"#/components/schemas/{contenido.esquema[estado]}"}
        generador = Generador(
            openapi, valores, peticion=False, recurso=contenido.recurso if estado == 202 else None
        )
        ejemplo = generador.ejemplo(esquema)
        if isinstance(ejemplo, dict) and contenido.cambios_ok:
            ejemplo = {**ejemplo, **contenido.cambios_ok}
        if isinstance(ejemplo, list) and contenido.previos_ok:
            ejemplo = [*contenido.previos_ok, *ejemplo]
        errores = _validar(openapi, ejemplo, esquema, f"respuesta {estado}")
        if errores:
            msg = f"el ejemplo de respuesta {estado} no cumple su esquema: {errores}"
            raise ValueError(msg)
        partes.append(f'<h4><span class="chip ok">OK</span>  Respuesta {estado}</h4>')
        partes.append(_pre(_json_html(ejemplo)))
    return "".join(partes)


def _ejemplo_ko(openapi: Mapping[str, Any], contenido: Operacion, protegida: bool) -> str:
    """Ejemplo de respuesta de error, validado contra ``ErrorResponse`` o su esquema.

    Args:
        openapi: Documento OpenAPI.
        contenido: Textos de la operación.
        protegida: Exige token (sin ejemplo propio, se muestra el ``401``).

    Returns:
        El HTML.

    Raises:
        ValueError: Si el ejemplo de error no cumple su esquema.
    """
    ko = contenido.ko
    if ko is None and protegida:
        ko = (
            401,
            _error(
                "UNAUTHENTICATED",
                "falta la cabecera Authorization: Bearer <token>",
                {"reason": "missing_token"},
            ),
        )
    if ko is None:
        return ""
    estado, cuerpo = ko
    esquema_nombre = "ReadyResponse" if "code" not in cuerpo else "ErrorResponse"
    esquema = {"$ref": f"#/components/schemas/{esquema_nombre}"}
    errores = _validar(openapi, dict(cuerpo), esquema, f"error {estado}")
    if errores:
        msg = f"el ejemplo de error {estado} no cumple su esquema: {errores}"
        raise ValueError(msg)
    return f'<h4><span class="chip ko">KO</span>  Respuesta {estado}</h4>' + _pre(
        _json_html(dict(cuerpo))
    )


def _generico(operacion: Mapping[str, Any]) -> Operacion:
    """Textos de una operación sin redacción propia (nueva en el OpenAPI): los del docstring.

    Args:
        operacion: Operación.

    Returns:
        Los textos.
    """
    descripcion = str(operacion.get("description") or operacion.get("summary") or "")
    primero = re.split(r"\n\s*\n|\nArgs:|\nReturns:|\nRaises:", descripcion, maxsplit=1)[0]
    return Operacion(
        titulo=str(operacion.get("summary", "Operación")), descripcion=(_rst(primero.strip()),)
    )


def _html_operacion(
    openapi: Mapping[str, Any],
    metodo: str,
    plantilla: str,
    operacion: Mapping[str, Any],
    contenido: Operacion,
) -> str:
    """Documentación completa de una operación (h3 y sus secciones).

    Args:
        openapi: Documento OpenAPI.
        metodo: Método HTTP.
        plantilla: Plantilla de la ruta.
        operacion: Operación del OpenAPI.
        contenido: Textos redactados.

    Returns:
        El HTML.

    Raises:
        ValueError: Si un ejemplo no cumple su esquema.
    """
    roles = _roles(operacion)
    protegida = roles != []
    esquema, obligatorio, tipos = _cuerpo_de(openapi, operacion)
    partes = [
        f'<h3 id="{_ancla(metodo, plantilla)}">{escape(contenido.titulo)}</h3>',
        _endpoint(metodo, plantilla),
        *(f"<p>{_texto(p)}</p>" for p in contenido.descripcion),
    ]
    if contenido.nota is not None:
        clase, etiqueta, texto = contenido.nota
        partes.append(
            f'<div class="caja {escape(clase)}"><span class="etiqueta">{escape(etiqueta)}</span>'
            f"<p>{_texto(texto)}</p></div>"
        )
    partes.append(_html_roles(roles))
    partes.append(_html_cabeceras(roles, [] if contenido.sin_cuerpo else tipos, obligatorio))
    partes.append(_html_parametros(openapi, operacion))
    partes.append(_html_cuerpo(openapi, esquema, tipos))
    ejemplo_cuerpo: object = None
    if esquema is not None and not contenido.sin_cuerpo:
        ejemplo_cuerpo = Generador(openapi, _valores(), peticion=True).ejemplo(esquema)
        errores = _validar(openapi, ejemplo_cuerpo, esquema, "petición")
        if errores:
            msg = f"el ejemplo de petición de {metodo} {plantilla} no cumple su esquema: {errores}"
            raise ValueError(msg)
    partes.append(_html_peticion(metodo, plantilla, contenido, roles, ejemplo_cuerpo, tipos))
    partes.append(_html_respuestas(openapi, operacion, contenido, protegida))
    partes.append(_ejemplos_ok(openapi, operacion, contenido))
    partes.append(_ejemplo_ko(openapi, contenido, protegida))
    return "\n".join(p for p in partes if p)


# --- punto de entrada -----------------------------------------------------------------------------


def _plan(openapi: Mapping[str, Any]) -> list[tuple[Grupo, list[tuple[str, str]]]]:
    """Grupos con sus operaciones presentes en el OpenAPI; las no previstas van a «Otras».

    Args:
        openapi: Documento OpenAPI.

    Returns:
        Los grupos con sus operaciones.

    Raises:
        ValueError: Si una operación redactada aquí ya no está en el OpenAPI.
    """
    presentes = _operaciones_de(openapi)
    previstas = [op for grupo in _grupos() for op in grupo.operaciones]
    ausentes = [f"{m} {p}" for m, p in previstas if (m, p) not in presentes]
    if ausentes:
        msg = f"operaciones documentadas que ya no están en el OpenAPI: {ausentes}"
        raise ValueError(msg)
    plan = [(grupo, list(grupo.operaciones)) for grupo in _grupos()]
    otras = sorted(set(presentes) - set(previstas), key=lambda op: (op[1], op[0]))
    if otras:
        grupo = Grupo(
            "ref-otras",
            "Otras operaciones",
            ("Operaciones del contrato que aún no tienen redacción propia en esta guía.",),
            tuple(otras),
        )
        plan.append((grupo, otras))
    return plan


def entradas_indice(openapi: Mapping[str, Any]) -> list[tuple[int, str, str]]:
    """Entradas del índice de la referencia, para construir el índice del documento.

    Args:
        openapi: Documento OpenAPI.

    Returns:
        (nivel 2 o 3, ``id`` del encabezado, título) en orden.
    """
    redactadas = _operaciones()
    presentes = _operaciones_de(openapi)
    salida: list[tuple[int, str, str]] = []
    for grupo, operaciones in _plan(openapi):
        salida.append((2, grupo.ancla, grupo.titulo))
        for metodo, plantilla in operaciones:
            contenido = redactadas.get((metodo, plantilla)) or _generico(
                presentes[(metodo, plantilla)]
            )
            salida.append((3, _ancla(metodo, plantilla), contenido.titulo))
    return salida


def referencia_html(openapi: Mapping[str, Any]) -> str:
    """HTML de la referencia de la API para insertar bajo ``<h1 id="referencia">``.

    Emite una introducción, un ``<h2 id="ref-…">`` por grupo y un ``<h3 id="ref-…">`` por
    operación con su método y ruta, descripción, roles, cabeceras, parámetros, cuerpo, ejemplo de
    petición, respuestas y ejemplos OK y KO. Todo el texto va escapado.

    Args:
        openapi: Documento OpenAPI de ``exportar_openapi.py`` (con ``x-voracious-roles``).

    Returns:
        El fragmento HTML (sin el h1).

    Raises:
        ValueError: Si una operación redactada falta en el OpenAPI o un ejemplo no cumple su
            esquema.
    """
    redactadas = _operaciones()
    presentes = _operaciones_de(openapi)
    version = escape(str(openapi.get("info", {}).get("version", "")))
    partes = [
        f"<p>Esta referencia se genera desde el contrato OpenAPI que exporta el servicio (versión "
        f"{version}): de él salen las rutas, los parámetros, los cuerpos, los esquemas y los "
        "roles. Las descripciones y la lista de códigos de error de cada operación se redactan a "
        "partir del código fuente del servicio.</p>",
        '<div class="caja"><span class="etiqueta">Convenciones</span><p>'
        + _texto(
            "Las rutas de negocio exigen `Authorization: Bearer <token>`; el tenant sale del "
            "claim `tenant` del token y un recurso de otro tenant responde como inexistente "
            "(`404`). Los pasos de cómputo responden `202 {id, status}` y se consultan con "
            "`GET` hasta `succeeded` o `failed`. Todo error responde con el formato uniforme "
            "`{code, message, details}`. Cada tabla de respuestas lista los estados que la "
            "operación puede devolver y, en cada uno, sus códigos de error."
        )
        + "</p><p>"
        + _texto(
            f"Los ejemplos son ilustrativos: siguen un mismo caso (un histórico de {N_FILAS} "
            "cierres diarios con tres variables, su Fase I, la Fase II de julio a septiembre de "
            "2026 y una recalibración que amplía la base) y cada uno se comprueba contra su "
            "esquema al generar la guía, pero sus valores no salen de un cálculo real. Las listas "
            "largas se abrevian con «&hellip;»; los recuentos (`n`, `n_base`&hellip;) son los del "
            "contenido completo. Cada ejemplo KO es una respuesta de error posible de la "
            "operación."
        )
        + "</p></div>",
    ]
    for grupo, operaciones in _plan(openapi):
        partes.append(f'<h2 id="{escape(grupo.ancla)}">{escape(grupo.titulo)}</h2>')
        partes.extend(f"<p>{_texto(p)}</p>" for p in grupo.introduccion)
        for metodo, plantilla in operaciones:
            operacion = presentes[(metodo, plantilla)]
            contenido = redactadas.get((metodo, plantilla)) or _generico(operacion)
            partes.append(_html_operacion(openapi, metodo, plantilla, operacion, contenido))
    return "\n".join(partes)
