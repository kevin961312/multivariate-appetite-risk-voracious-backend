r"""Genera los PDF de la documentación de Voracious con la plantilla de marca (WeasyPrint).

Uso (macOS necesita ``brew install pango`` y la ruta de Homebrew)::

    DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run --no-project \
      --with weasyprint==70.0 python docs/guia/build.py plantilla

Los colores salen de ``marca/tokens.json``; las muestras de la paleta se generan desde ahí para
que el documento y los tokens no se desincronicen. La salida va a ``docs/guia/salida/`` (no se
versiona).

La guía de integración (``integracion``) inserta la referencia y el catálogo de errores generados
desde el código y arma el índice desde los encabezados. Antes hay que regenerar el OpenAPI con el
entorno del proyecto: ``uv run python docs/guia/integracion/exportar_openapi.py``.
"""

import argparse
import importlib
import json
import sys
from datetime import UTC, datetime
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from types import ModuleType
from typing import Any

from weasyprint import HTML

GUIA = Path(__file__).resolve().parent
MARCA = GUIA / "marca"
SALIDA = GUIA / "salida"
INTEGRACION = GUIA / "integracion"
DOCUMENTOS = {
    "plantilla": (GUIA / "plantilla" / "plantilla-marca.html", "Voracious-Plantilla-de-marca.pdf"),
    "integracion": (
        INTEGRACION / "guia-integracion.html",
        "Voracious-Guia-de-integracion-API.pdf",
    ),
}
REVISION = "1"
"""Revisión de los documentos generados (se sube al cambiar el contenido publicado)."""
FAMILIAS = (
    ("primario", "Color primario: índigo", "indigo", "Índigo"),
    ("secundarios", "Colores secundarios: morado y turquesa", "morado", "Morado"),
    (None, None, "turquesa", "Turquesa"),
)
ORDEN_TONOS = ("300", "400", "500", "600", "700")
ORDEN_TINTES = ("50", "100", "150", "200", "250")
PORCENTAJE_BLANCO = {"50": 96, "100": 92, "150": 85, "200": 70, "250": 50}


def _rgb(hexa: str) -> str:
    """Devuelve las componentes ``r g b`` de un color ``#RRGGBB``, unidas por raya.

    Args:
        hexa: Color en hexadecimal con almohadilla.

    Returns:
        Las tres componentes separadas por guiones.
    """
    valor = hexa.lstrip("#")
    return "\u2013".join(str(int(valor[i : i + 2], 16)) for i in (0, 2, 4))


def _franja(colores: list[tuple[str, str]], base: str | None) -> str:
    """HTML de una franja de muestras con sus etiquetas.

    Args:
        colores: Pares (nombre del token, hexadecimal) en orden.
        base: Nombre del token que se dibuja ancho (el tono base), o ``None``.

    Returns:
        El fragmento HTML.
    """
    muestras = "".join(
        f'<div class="muestra{" base" if nombre == base else ""}" style="background:{hexa}"></div>'
        for nombre, hexa in colores
    )
    etiquetas = "".join(
        f'<div class="{"base" if nombre == base else ""}"><b>{escape(hexa.upper())}</b>'
        f"{escape(nombre)}<br>RGB {_rgb(hexa)}</div>"
        for nombre, hexa in colores
    )
    return f'<div class="muestras">{muestras}</div><div class="etiquetas">{etiquetas}</div>'


def muestras_html(tokens: dict[str, Any]) -> str:
    """Genera las secciones de la paleta (familias, tintes, neutros y estados) desde los tokens.

    Args:
        tokens: Contenido de ``tokens.json``.

    Returns:
        El HTML que sustituye a ``{{MUESTRAS}}``.
    """
    color = tokens["color"]
    partes: list[str] = []
    for ancla, titulo, familia, nombre in FAMILIAS:
        if ancla is not None and titulo is not None:
            partes.append(f'<h2 id="{ancla}">{escape(titulo)}</h2>')
        datos = color[familia]
        partes.append(f"<h4>{escape(nombre)}</h4>")
        partes.append(f'<p class="pequeno tenue">{escape(datos["_uso"])}</p>')
        tonos = [(f"{familia} {t}", datos[t]) for t in ORDEN_TONOS]
        partes.append(_franja(tonos, f"{familia} 500"))
        tintes = [
            (f"tinte {t} · {PORCENTAJE_BLANCO[t]} % blanco", datos["tinte"][t])
            for t in ORDEN_TINTES
        ]
        partes.append(_franja(tintes, None))
    partes.append('<h2 id="neutros">Neutros y estados</h2>')
    neutro = color["neutro"]
    partes.append(f'<p class="pequeno tenue">{escape(neutro["_uso"])}</p>')
    partes.append(
        _franja([(k.replace("_", " "), v) for k, v in neutro.items() if k != "_uso"], None)
    )
    estados = color["estado"]
    filas = "".join(
        f'<tr><td><span class="chip" style="background:{v["fondo"]};color:{v["texto"]}">'
        f"{escape(k)}</span></td><td><code>{v['texto']}</code></td><td><code>{v['fondo']}</code></td>"
        f"<td><code>{v['borde']}</code></td></tr>"
        for k, v in estados.items()
        if k != "_uso"
    )
    partes.append(
        "<table><tr><th>Estado</th><th>Texto</th><th>Fondo</th><th>Borde</th></tr>"
        + filas
        + "</table>"
    )
    return "\n".join(partes)


class _Encabezados(HTMLParser):
    """Recoge los h1, h2 y h3 del cuerpo en orden, con su ``id``, texto y estilo en línea."""

    def __init__(self) -> None:
        """Prepara la lista de encabezados."""
        super().__init__(convert_charrefs=True)
        self.encabezados: list[tuple[int, str | None, str, str]] = []
        self._abierto: tuple[int, str | None, str] | None = None
        self._texto: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Abre un encabezado h1-h3.

        Args:
            tag: Etiqueta.
            attrs: Atributos.
        """
        if tag in {"h1", "h2", "h3"}:
            atributos = dict(attrs)
            self._abierto = (int(tag[1]), atributos.get("id"), atributos.get("style") or "")
            self._texto = []

    def handle_endtag(self, tag: str) -> None:
        """Cierra el encabezado abierto.

        Args:
            tag: Etiqueta.
        """
        if self._abierto is not None and tag == f"h{self._abierto[0]}":
            nivel, ancla, estilo = self._abierto
            texto = " ".join("".join(self._texto).split())
            self.encabezados.append((nivel, ancla, texto, estilo))
            self._abierto = None

    def handle_data(self, data: str) -> None:
        """Acumula el texto del encabezado abierto.

        Args:
            data: Texto.
        """
        if self._abierto is not None:
            self._texto.append(data)


def indice_html(html: str, *, nivel_maximo: int = 2, profundo: frozenset[str] = frozenset()) -> str:
    """Genera el índice numerado a partir de los encabezados, con la misma numeración que el CSS.

    Los encabezados sin ``id`` cuentan para la numeración pero no salen en el índice; los que tienen
    ``counter-increment:none`` (el título del propio índice) no cuentan.

    Args:
        html: Documento completo, con las secciones ya insertadas.
        nivel_maximo: Nivel más profundo que se lista en general.
        profundo: ``id`` de los h1 cuyos h3 también se listan (p. ej. la referencia).

    Returns:
        El HTML de la sección del índice (título y lista).
    """
    lector = _Encabezados()
    lector.feed(html)
    contador = [0, 0, 0]
    actual: str | None = None
    filas: list[str] = []
    for nivel, ancla, texto, estilo in lector.encabezados:
        if "counter-increment:none" in estilo.replace(" ", ""):
            continue
        contador[nivel - 1] += 1
        for inferior in range(nivel, 3):
            contador[inferior] = 0
        if nivel == 1:
            actual = ancla
        limite = 3 if actual in profundo else nivel_maximo
        if ancla is None or nivel > limite:
            continue
        numero = ".".join(str(c) for c in contador[:nivel])
        filas.append(
            f'<li class="n{nivel}"><a href="#{escape(ancla)}">{numero}  {escape(texto)}</a></li>'
        )
    return '<h2 style="counter-increment:none">Contenido</h2><ol>' + "".join(filas) + "</ol>"


def _modulo(nombre: str) -> ModuleType:
    """Importa un módulo de ``docs/guia/integracion``.

    Args:
        nombre: Nombre del módulo.

    Returns:
        El módulo.
    """
    if str(INTEGRACION) not in sys.path:
        sys.path.insert(0, str(INTEGRACION))
    return importlib.import_module(nombre)


def _integracion(html: str) -> str:
    """Inserta la referencia, el catálogo de errores y el índice de la guía de integración.

    Args:
        html: Plantilla de la guía.

    Returns:
        El documento completo.
    """
    openapi = json.loads((INTEGRACION / "openapi.json").read_text(encoding="utf-8"))
    html = html.replace("{{REFERENCIA_API}}", _modulo("referencia").referencia_html(openapi))
    html = html.replace("{{CATALOGO_ERRORES}}", _modulo("catalogo_errores").catalogo_html())
    return html.replace("{{INDICE}}", indice_html(html, profundo=frozenset({"referencia"})))


def construir(nombre: str) -> Path:
    """Genera un PDF a partir de su plantilla HTML.

    Args:
        nombre: Clave de ``DOCUMENTOS``.

    Returns:
        La ruta del PDF generado.
    """
    origen, destino = DOCUMENTOS[nombre]
    tokens = json.loads((MARCA / "tokens.json").read_text(encoding="utf-8"))
    html = origen.read_text(encoding="utf-8")
    html = html.replace("{{MUESTRAS}}", muestras_html(tokens))
    html = html.replace("{{FECHA}}", datetime.now(UTC).strftime("%d/%m/%Y"))
    html = html.replace("{{REVISION}}", REVISION)
    if nombre == "integracion":
        html = _integracion(html)
    SALIDA.mkdir(exist_ok=True)
    salida = SALIDA / destino
    HTML(string=html, base_url=str(origen)).write_pdf(salida)
    return salida


def main() -> None:
    """Punto de entrada de la línea de órdenes."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("documento", choices=sorted(DOCUMENTOS))
    args = parser.parse_args()
    print(construir(args.documento))


if __name__ == "__main__":
    main()
