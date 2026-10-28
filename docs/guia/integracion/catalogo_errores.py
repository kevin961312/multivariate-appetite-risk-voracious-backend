"""Catálogo de códigos de error de la API para la guía de integración.

Lee el mapeo código → estado HTTP (``CODE_TO_STATUS`` de ``src/voracious/api/errors.py``) con
``ast``, **sin importar** el módulo: importarlo arrastra FastAPI y el resto del paquete, que no
están en el entorno de ``build.py`` (``uv run --no-project``). Los nombres de constantes de la
tabla (``UNAUTHENTICATED``, ``InvalidInputError.CODE``…) se resuelven siguiendo los ``import`` del
propio código fuente.

Uso::

    from catalogo_errores import catalogo_html

    html = catalogo_html()  # párrafo de introducción + tabla Código / HTTP / Cuándo ocurre

Cada código de la tabla necesita su descripción en ``CUANDO``; si aparece un código nuevo sin
descripción, o una descripción de un código que ya no existe, la generación falla.
"""

import ast
import re
from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Final

SRC: Final = Path(__file__).resolve().parents[3] / "src"
"""Raíz de los paquetes del backend (``src/voracious``)."""

ERRORES: Final = "voracious.api.errors"
"""Módulo con ``CODE_TO_STATUS`` y ``DEFAULT_DOMAIN_STATUS``."""

SIN_CORTE_DESPUES: Final = "page-break-after:avoid;break-after:avoid"
"""Estilo que une el título y la cabecera de la tabla con la primera fila (sin huérfanas)."""

CUANDO: Final[Mapping[str, str]] = {
    "UNAUTHENTICATED": "Falta la cabecera `Authorization: Bearer`, está mal formada o el token no "
    "verifica (firma, llave, algoritmo, vigencia, emisor, audiencia o claims). `details.reason` "
    "da el motivo: {motivos}. La respuesta lleva `WWW-Authenticate`.",
    "FORBIDDEN": "El token es válido, pero ninguno de sus roles permite la operación; "
    "`details.required_roles` lista los roles admitidos.",
    "CHART_NOT_FOUND": "La carta de la ruta no está registrada en el servidor.",
    "MODEL_NOT_FOUND": "El modelo no existe, es de otra carta o pertenece a otro tenant (un "
    "recurso ajeno responde siempre como inexistente).",
    "MONITORING_NOT_FOUND": "La puntuación (`score_id`) no existe para ese modelo y tenant.",
    "VERSION_NOT_FOUND": "La versión pedida no existe para ese modelo y tenant.",
    "RECALIBRATION_NOT_FOUND": "La recalibración no existe para ese modelo y tenant.",
    "OBSERVATION_NOT_FOUND": "La observación que se quiere anotar no existe para ese modelo y "
    "tenant.",
    "DATASET_NOT_FOUND": "El dataset indicado no existe o es de otro tenant.",
    "FIT_NOT_FOUND": "El ajuste indicado no existe o es de otro tenant.",
    "LIMITS_NOT_FOUND": "Los límites indicados no existen o son de otro tenant.",
    "EXCLUSION_NOT_FOUND": "La exclusión indicada no existe o es de otro tenant.",
    "PIPELINE_NOT_FOUND": "La tubería indicada no existe o es de otro tenant.",
    "ROUTE_NOT_FOUND": "La ruta no existe. Dentro de `/v1`, con un token válido (sin token se "
    "responde antes `401`). Fuera de `/v1` y de `/health` (p. ej. `/ready`, `/docs`, `/redoc`, "
    "`/openapi.json`) la responde el borde público, sin token y con `details: {}`.",
    "METHOD_NOT_ALLOWED": "La ruta existe, pero no admite ese método HTTP.",
    "MODEL_NOT_READY": "El modelo existe pero aún no está `succeeded` (o no tiene versión "
    "vigente): no se puede puntuar, recalibrar, registrar eventos ni consultar su estado.",
    "VERSION_NOT_PROPOSED": "Se aprueba o rechaza una versión que no está `proposed` (ya está "
    "activa, sustituida o rechazada) o ganó antes otra decisión concurrente.",
    "PROPOSAL_PENDING": "Ya hay una versión propuesta sin aprobar ni rechazar; hay que "
    "resolverla antes de pedir otra recalibración o propuesta.",
    "RECALIBRATION_IN_PROGRESS": "Ya hay una recalibración en curso para el modelo (como máximo "
    "una a la vez).",
    "NOT_A_SIGNAL": "Se intenta anotar una observación que no dio señal (solo se anotan señales).",
    "EFFECTIVE_FROM_NOT_AFTER_SCORED": "La aprobación sería retroactiva: `effective_from` no es "
    "posterior a la última observación puntuada o a la entrada en vigor de la versión vigente.",
    "FIT_NOT_READY": "El ajuste indicado aún no está `succeeded` (en cola, en curso o fallido).",
    "LIMITS_NOT_READY": "Los límites indicados aún no están `succeeded`.",
    "RECALIBRATION_NOT_IN_PROGRESS": "La recalibración ya terminó, se canceló o ya pidió su "
    "propuesta: no admite más pasos ni cancelarse.",
    "PAYLOAD_TOO_LARGE": "El cuerpo de `POST /v1/datasets` supera `VORACIOUS_MAX_UPLOAD_MB` "
    "(en MiB); `details.max_bytes` da el máximo en bytes. El borde público también lo responde "
    "en cualquier ruta cuando el cuerpo supera 51 MiB, y entonces `details` va vacío.",
    "UNSUPPORTED_MEDIA_TYPE": "`POST /v1/datasets` con un `Content-Type` distinto de "
    "`application/json`, `text/csv` o `multipart/form-data`.",
    "INVALID_INPUT": "La petición no cumple el esquema (falta un campo, tipo erróneo o campo "
    "desconocido; `details.errors`) o la entrada no es válida para el método o el ciclo de vida: "
    "matriz vacía o no finita, `p` distinto del modelo, CSV no numérico, fecha sin zona horaria, "
    "combinación de campos no admitida… `details.reason` o `details.input` precisan la causa.",
    "RANGE_BEFORE_STRUCTURAL_EVENT": "El rango de la recalibración incluye observaciones "
    "anteriores a un evento estructural sin resolver (tras el evento solo valen las "
    "posteriores).",
    "RECALIBRATION_INSUFFICIENT_OBSERVATIONS": "El rango de la recalibración no tiene suficientes "
    "observaciones candidatas (`details.available` frente a `details.required`, el "
    "`min_observations`).",
    "OBSERVATION_BEFORE_FIRST_VERSION": "Alguna observación del lote tiene una fecha en la que no "
    "rige ninguna versión aprobada del modelo.",
    "T2MRCD_FIT_PARAMS_MISMATCH": "En `/limits`, los parámetros de MRCD de la carta no son los del "
    "ajuste indicado (`details.fit_mrcd` frente a `details.chart_mrcd`).",
    "LIMITS_FIT_MISMATCH": "Los límites indicados no se calibraron sobre el ajuste indicado.",
    "RECALIBRATION_MISMATCH": "Un paso referencia recursos que no pertenecen a esa recalibración "
    "(o a ninguna): p. ej. un `recalibration_id` distinto del del dataset del ajuste o un modelo "
    "de Fase I con datos de una recalibración.",
    "VERSION_INPUTS_MISMATCH": "La propuesta de versión no usa el ajuste y los límites que exige "
    "la decisión: los del dataset de extensión en EXTEND (`extension_required` si aún no se "
    "construyó) o los de las filas nuevas en REPLACE; `details.reason`.",
    "VARIABLES_MISMATCH": "Las variables de una puntuación o recalibración no son las del dataset "
    "raíz del modelo (en número, nombres u orden).",
    "RATE_LIMITED": "Demasiadas peticiones desde la misma IP de cliente (por defecto 600 por "
    "minuto con ráfaga de 120, también las que no llevan token). La respuesta lleva `Retry-After` "
    "y `details.retry_after_seconds`: hay que esperar al menos ese tiempo antes de reintentar.",
    "TOO_MANY_JOBS": "El tenant ya tiene el máximo de trabajos de cómputo en cola o en curso "
    "(`details.max_active_jobs` frente a `details.active_jobs`); se vuelve a pedir cuando "
    "termine alguno.",
    "INTERNAL_ERROR": "Fallo inesperado del servidor; el detalle queda en el registro del "
    "servidor, nunca en el cuerpo. También puede aparecer en el `error` de un trabajo `failed`.",
    "JOB_INTERRUPTED": "Solo en el `error` de un trabajo `failed` (el `GET` responde `200`): el "
    "servicio se reinició con el trabajo en cola o en curso. Hay que volver a pedirlo.",
}
"""Cuándo ocurre cada código de ``CODE_TO_STATUS`` (``{motivos}``: valores de ``AuthFailure``)."""


@dataclass(frozen=True)
class CodigoExtra:
    """Código del formato uniforme que no está en ``CODE_TO_STATUS``.

    Attributes:
        codigo: Código.
        http: Texto de la columna HTTP.
        cuando: Cuándo ocurre.
    """

    codigo: str
    http: str
    cuando: str


HTTP_NOMINAL: Final[Mapping[str, str]] = {
    "JOB_INTERRUPTED": "{estado} (nominal; llega con 200 en un trabajo `failed`)",
}
"""Columna HTTP de los códigos cuyo estado de la tabla no es el que recibe el integrador."""

EN_TRABAJO: Final = "200 (trabajo `failed`)"
"""Columna HTTP de los códigos que solo llegan en el ``error`` de un trabajo fallido."""

EXTRA: Final = (
    CodigoExtra(
        "HTTP_ERROR",
        "el del error",
        "Cualquier otro error HTTP del enrutado; conserva su estado y su texto.",
    ),
    CodigoExtra(
        "T2MRCD_DECISION_PENDING",
        "{defecto}",
        "Algún parámetro estadístico decisivo de la carta quedó sin decidir; `details.pending` "
        "lista los campos. Se comprueba antes de encolar los límites. Con los valores por defecto "
        "vigentes no se produce por la API.",
    ),
    CodigoExtra(
        "MRCD_FIT_FAILED",
        EN_TRABAJO,
        "El ajuste MRCD falló dentro de `pymrcd` (en `/fits`, en una réplica bootstrap, en la "
        "tubería o en una recalibración); `details.r_message`.",
    ),
    CodigoExtra(
        "BOOTSTRAP_REPLICATE_FAILED",
        EN_TRABAJO,
        "Una réplica bootstrap falló y con ella toda la calibración de límites (no se descartan "
        "réplicas).",
    ),
    CodigoExtra(
        "BOOTSTRAP_OOB_EMPTY",
        EN_TRABAJO,
        "Una réplica bootstrap no dejó observaciones fuera de la muestra (OOB) para el límite de "
        "Fase II; la calibración falla.",
    ),
    CodigoExtra(
        "BOOTSTRAP_LIMIT_NOT_FINITE",
        EN_TRABAJO,
        "La agregación bootstrap devolvió un límite no finito (`details.phase`).",
    ),
    CodigoExtra(
        "T2MRCD_NO_CLEAN_OBSERVATIONS",
        EN_TRABAJO,
        "El criterio de filas limpias no dejó ninguna observación que remuestrear.",
    ),
    CodigoExtra(
        "T2MRCD_CLEAN_CRITERION_INVALID",
        EN_TRABAJO,
        "El criterio de filas limpias no devolvió una máscara booleana de longitud n (fallo "
        "interno del método).",
    ),
)
"""Códigos del formato uniforme fuera de la tabla: enrutado, dominio síncrono y trabajos."""


CADDYFILE: Final = Path(__file__).resolve().parents[3] / "deploy" / "proxy" / "Caddyfile"
"""Configuración del borde público: de ahí salen los códigos que da el borde y no la API."""

_ERROR_BORDE: Final = re.compile(
    r"import json_error\s+([A-Z][A-Z_]+)\s+\"[^\"]*\"\s+(\d{3}|\{err\.status_code\})"
)
_MANEJADOR: Final = re.compile(r"handle_errors\s*([\d ]*)\{")

CUANDO_BORDE: Final[Mapping[str, str]] = {
    "UPSTREAM_UNAVAILABLE": "La API no está disponible (se reinicia, se despliega o está caída). "
    "Reintentar con espera progresiva.",
    "UPSTREAM_TIMEOUT": "La API no respondió a tiempo (más de 2 minutos hasta las cabeceras de la "
    "respuesta).",
    "EDGE_ERROR": "Cualquier otro fallo del borde que no tiene un código propio; el estado es el "
    "del fallo.",
}
"""Cuándo ocurre cada código del borde que no es ``ROUTE_NOT_FOUND`` ni ``PAYLOAD_TOO_LARGE``."""


def codigos_del_borde() -> list[tuple[str, str]]:
    """Códigos de los manejadores ``handle_errors`` de ``deploy/proxy/Caddyfile``.

    Returns:
        Pares (código, estado HTTP como texto) en el orden del fichero. Si el estado es
        ``{err.status_code}`` se muestra el del manejador (p. ej. ``502/503``) o «el del fallo»
        cuando el manejador cubre cualquier error.

    Raises:
        ValueError: Si el Caddyfile no tiene ningún manejador de errores.
    """
    pares: list[tuple[str, str]] = []
    estados: str | None = None  # None: fuera de un manejador de errores
    for linea in CADDYFILE.read_text(encoding="utf-8").splitlines():
        manejador = _MANEJADOR.search(linea)
        if manejador:
            estados = "/".join(manejador.group(1).split())
        elif linea.rstrip() == "\t}":
            estados = None
        elif estados is not None:
            encontrado = _ERROR_BORDE.search(linea)
            if encontrado:
                codigo, estado = encontrado.groups()
                pares.append((codigo, estado if estado.isdigit() else estados or "el del fallo"))
    if not pares:
        msg = f"no se encuentran manejadores de errores en {CADDYFILE}"
        raise ValueError(msg)
    return pares


# --- lectura del código fuente --------------------------------------------------------------------


def _archivo(modulo: str) -> Path:
    """Fichero de un módulo de ``src`` (``a.b`` → ``a/b.py`` o ``a/b/__init__.py``).

    Args:
        modulo: Nombre con puntos.

    Returns:
        La ruta.

    Raises:
        FileNotFoundError: Si el módulo no está en ``src``.
    """
    base = SRC.joinpath(*modulo.split("."))
    for candidato in (base.with_suffix(".py"), base / "__init__.py"):
        if candidato.is_file():
            return candidato
    msg = f"no existe el módulo {modulo} en {SRC}"
    raise FileNotFoundError(msg)


def _arbol(modulo: str) -> ast.Module:
    """Árbol sintáctico de un módulo.

    Args:
        modulo: Nombre con puntos.

    Returns:
        El árbol.
    """
    return ast.parse(_archivo(modulo).read_text(encoding="utf-8"))


def _definicion(modulo: str, nombre: str) -> tuple[str, ast.AST]:
    """Nodo que define ``nombre`` en ``modulo``, siguiendo ``from … import`` del proyecto.

    Args:
        modulo: Módulo donde se usa el nombre.
        nombre: Nombre (constante o clase).

    Returns:
        (módulo que lo define, nodo de la asignación o de la clase).

    Raises:
        LookupError: Si no se encuentra.
    """
    for nodo in _arbol(modulo).body:
        if isinstance(nodo, ast.ClassDef) and nodo.name == nombre:
            return modulo, nodo
        if isinstance(nodo, ast.Assign | ast.AnnAssign):
            objetivos = nodo.targets if isinstance(nodo, ast.Assign) else [nodo.target]
            if any(isinstance(t, ast.Name) and t.id == nombre for t in objetivos):
                return modulo, nodo
        if isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.module.startswith("voracious"):
            for alias in nodo.names:
                if (alias.asname or alias.name) == nombre:
                    return _definicion(nodo.module, alias.name)
    msg = f"no se encuentra {nombre} en {modulo}"
    raise LookupError(msg)


def _texto_de(modulo: str, expresion: ast.expr) -> str:
    """Valor de texto de una clave de ``CODE_TO_STATUS`` (literal, constante o ``Clase.ATRIBUTO``).

    Args:
        modulo: Módulo donde aparece la expresión.
        expresion: Expresión.

    Returns:
        El código.

    Raises:
        LookupError: Si no se puede resolver a un literal de texto.
    """
    if isinstance(expresion, ast.Constant) and isinstance(expresion.value, str):
        return expresion.value
    if isinstance(expresion, ast.Name):
        origen, nodo = _definicion(modulo, expresion.id)
        if isinstance(nodo, ast.Assign | ast.AnnAssign) and nodo.value is not None:
            return _texto_de(origen, nodo.value)
    if isinstance(expresion, ast.Attribute) and isinstance(expresion.value, ast.Name):
        origen, nodo = _definicion(modulo, expresion.value.id)
        if isinstance(nodo, ast.ClassDef):
            for sentencia in nodo.body:
                if isinstance(sentencia, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == expresion.attr for t in sentencia.targets
                ):
                    return _texto_de(origen, sentencia.value)
    msg = f"no se puede resolver {ast.unparse(expresion)} en {modulo}"
    raise LookupError(msg)


def tabla_de_estados() -> list[tuple[str, int]]:
    """``CODE_TO_STATUS`` en su orden de declaración, leído del código fuente.

    Returns:
        Pares (código, estado HTTP).

    Raises:
        LookupError: Si la tabla no está o tiene una clave no resoluble.
    """
    for nodo in _arbol(ERRORES).body:
        if (
            isinstance(nodo, ast.AnnAssign)
            and isinstance(nodo.target, ast.Name)
            and nodo.target.id == "CODE_TO_STATUS"
            and isinstance(nodo.value, ast.Dict)
        ):
            pares: list[tuple[str, int]] = []
            for clave, valor in zip(nodo.value.keys, nodo.value.values, strict=True):
                if clave is None or not isinstance(valor, ast.Constant):
                    msg = "CODE_TO_STATUS tiene una entrada no literal"
                    raise LookupError(msg)
                pares.append((_texto_de(ERRORES, clave), int(valor.value)))
            return pares
    msg = f"no se encuentra CODE_TO_STATUS en {ERRORES}"
    raise LookupError(msg)


def _estado_por_defecto() -> int:
    """``DEFAULT_DOMAIN_STATUS``: estado de un error de dominio síncrono sin entrada propia.

    Returns:
        El estado.
    """
    _, nodo = _definicion(ERRORES, "DEFAULT_DOMAIN_STATUS")
    if isinstance(nodo, ast.Assign | ast.AnnAssign) and isinstance(nodo.value, ast.Constant):
        return int(nodo.value.value)
    msg = "DEFAULT_DOMAIN_STATUS no es un literal"
    raise LookupError(msg)


def motivos_401() -> list[str]:
    """Valores de ``AuthFailure`` (``details.reason`` de un ``401``), leídos del código fuente.

    Returns:
        Los motivos en su orden de declaración.
    """
    _, nodo = _definicion("voracious.application.auth", "AuthFailure")
    if not isinstance(nodo, ast.ClassDef):
        return []
    return [
        s.value.value
        for s in nodo.body
        if isinstance(s, ast.Assign)
        and isinstance(s.value, ast.Constant)
        and isinstance(s.value.value, str)
    ]


def _presente_en_fuente(codigo: str) -> bool:
    """Indica si el literal ``"CODIGO"`` aparece en el código fuente del backend.

    Args:
        codigo: Código.

    Returns:
        ``True`` si algún módulo de ``src/voracious`` lo contiene.
    """
    literal = f'"{codigo}"'
    return any(literal in f.read_text(encoding="utf-8") for f in (SRC / "voracious").rglob("*.py"))


# --- HTML -----------------------------------------------------------------------------------------


def _texto(texto: str) -> str:
    """Texto escapado con el código entre comillas invertidas como ``<code>``.

    Args:
        texto: Texto.

    Returns:
        El HTML.
    """
    partes = escape(texto, quote=False).split("`")
    return "".join(f"<code>{p}</code>" if i % 2 else p for i, p in enumerate(partes))


def filas_catalogo() -> list[tuple[str, str, str]]:
    """Filas del catálogo: código, estado HTTP y cuándo ocurre (texto con comillas invertidas).

    Returns:
        Las filas, primero las de ``CODE_TO_STATUS`` (en su orden) y luego ``EXTRA``.

    Raises:
        ValueError: Si un código de la tabla no tiene descripción, una descripción no tiene
            código o un código de ``EXTRA`` ya no aparece en el código fuente.
    """
    tabla = tabla_de_estados()
    codigos = [c for c, _ in tabla]
    sin_texto = [c for c in codigos if c not in CUANDO]
    sobrantes = sorted(set(CUANDO) - set(codigos))
    perdidos = [e.codigo for e in EXTRA if not _presente_en_fuente(e.codigo)]
    if sin_texto or sobrantes or perdidos:
        msg = (
            f"catálogo desactualizado: sin descripción {sin_texto}, descripciones sin código "
            f"{sobrantes}, códigos extra que ya no existen {perdidos}"
        )
        raise ValueError(msg)
    motivos = ", ".join(f"`{m}`" for m in motivos_401())
    filas = [
        (
            codigo,
            HTTP_NOMINAL.get(codigo, "{estado}").replace("{estado}", str(estado)),
            CUANDO[codigo].replace("{motivos}", motivos),
        )
        for codigo, estado in tabla
    ]
    defecto = str(_estado_por_defecto())
    filas.extend((e.codigo, e.http.replace("{defecto}", defecto), e.cuando) for e in EXTRA)
    return filas


def catalogo_html() -> str:
    """Párrafo de introducción y tabla Código / HTTP / Cuándo ocurre.

    Returns:
        El fragmento HTML (sin encabezado; todo el texto va escapado).
    """
    filas = "".join(
        f'<tr><td><code style="white-space:normal">'
        f"{escape(codigo).replace('_', '_<wbr>')}</code></td>"
        f"<td>{_texto(http)}</td><td>{_texto(cuando)}</td></tr>"
        for codigo, http, cuando in filas_catalogo()
    )
    # La tabla sale de CODE_TO_STATUS (ERRORES); el texto visible no nombra rutas del código.
    introduccion = _texto(
        "Todo error responde con el formato uniforme `{code, message, details}`: `code` es "
        "estable y es lo que debe comprobar el integrador, `message` es legible y puede cambiar, y "
        "`details` trae datos adicionales. Los errores de una petición se responden con el "
        "estado HTTP de la tabla; los fallos de un trabajo asíncrono no son errores HTTP: el "
        "`GET` del recurso responde `200` con `status: failed` y el error en `error`."
    )
    return (
        f"<p>{introduccion}</p>"
        '<table style="table-layout:fixed">'
        f'<caption style="{SIN_CORTE_DESPUES}">Catálogo de códigos de error</caption>'
        f'<tr style="{SIN_CORTE_DESPUES}"><th style="width:34%">Código</th>'
        '<th style="width:15%">HTTP</th><th>Cuándo ocurre</th></tr>'
        f"{filas}</table>" + _borde_html()
    )


def filas_borde() -> list[tuple[str, str, str]]:
    """Filas de los códigos que solo da el borde público (además de los de la tabla principal).

    Returns:
        Las filas (código, estado, cuándo), sin ``ROUTE_NOT_FOUND`` ni ``PAYLOAD_TOO_LARGE``,
        que ya están en el catálogo principal.

    Raises:
        ValueError: Si un código del Caddyfile no tiene descripción o una descripción ya no
            tiene código en el Caddyfile.
    """
    propios = [
        (c, e) for c, e in codigos_del_borde() if c not in {"ROUTE_NOT_FOUND", "PAYLOAD_TOO_LARGE"}
    ]
    codigos = {c for c, _ in propios}
    if codigos != set(CUANDO_BORDE):
        msg = (
            "códigos del borde desactualizados: "
            f"sin descripción {sorted(codigos - set(CUANDO_BORDE))}, "
            f"descripciones sin código {sorted(set(CUANDO_BORDE) - codigos)}"
        )
        raise ValueError(msg)
    return [(c, e, CUANDO_BORDE[c]) for c, e in propios]


def _borde_html() -> str:
    """Lista aparte de los códigos del borde: texto introductorio y tabla.

    Returns:
        El fragmento HTML.
    """
    filas = "".join(
        f'<tr><td><code style="white-space:normal">{escape(c).replace("_", "_<wbr>")}</code></td>'
        f"<td>{escape(e.replace('/', ' / '))}</td><td>{_texto(cuando)}</td></tr>"
        for c, e, cuando in filas_borde()
    )
    intro = _texto(
        "Además, el borde público (el proxy HTTPS delante de la API) responde con el mismo "
        "formato, `details` siempre vacío, y **sin las cabeceras CORS**: un navegador los ve "
        "como un error de red. No llegan de la API, por lo que no están en la tabla anterior."
    ).replace("**sin las cabeceras CORS**", "<strong>sin las cabeceras CORS</strong>")
    return (
        f'<p style="margin-top:4mm">{intro}</p>'
        '<table class="corta" style="table-layout:fixed">'
        f'<caption style="{SIN_CORTE_DESPUES}">Códigos que solo da el borde</caption>'
        f'<tr style="{SIN_CORTE_DESPUES}"><th style="width:34%">Código</th>'
        '<th style="width:15%">HTTP</th><th>Cuándo ocurre</th></tr>'
        f"{filas}</table>"
    )
