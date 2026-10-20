r"""Genera los PDF de la documentación de Voracious con la plantilla de marca (WeasyPrint).

Uso (macOS necesita ``brew install pango`` y la ruta de Homebrew)::

    DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run --no-project \
      --with weasyprint==70.0 python docs/guia/build.py plantilla

Los colores salen de ``marca/tokens.json``; las muestras de la paleta se generan desde ahí para
que el documento y los tokens no se desincronicen. La salida va a ``docs/guia/salida/`` (no se
versiona).
"""

import argparse
import json
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

from weasyprint import HTML

GUIA = Path(__file__).resolve().parent
MARCA = GUIA / "marca"
SALIDA = GUIA / "salida"
DOCUMENTOS = {
    "plantilla": (GUIA / "plantilla" / "plantilla-marca.html", "Voracious-Plantilla-de-marca.pdf"),
}
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
