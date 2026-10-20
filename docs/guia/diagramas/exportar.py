r"""Exporta ``arquitectura.drawio`` a SVG (con las fuentes de la marca incrustadas) y a PNG.

Uso (macOS; WeasyPrint necesita ``brew install pango`` y la ruta de Homebrew)::

    DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run --no-project \
      --with weasyprint==70.0 python docs/guia/diagramas/exportar.py [página ...]

Sin argumentos exporta todas las páginas; con números (desde 1), solo esas.

Pasos y por qué:

1. ``draw.io --export --format svg --theme light --page-index N``: la CLI numera las páginas
   desde 1. Las etiquetas son texto plano (``html=0``), así que el SVG lleva ``<text>`` y no
   ``<foreignObject>``, que WeasyPrint no pinta.
2. La CLI no descarga las fuentes web: deja un ``@import`` de Google Fonts que dentro de un
   ``<img>`` no se carga. Se sustituye por ``@font-face`` con Poppins, Lato e IBM Plex Mono de
   ``../marca/fuentes``, recortadas a los caracteres usados (WOFF2 en data URI).
3. El PNG (2x) se pinta desde ese SVG con WeasyPrint y ``pdftoppm``, el mismo motor de los PDF
   de la guía: el PNG que exporta la CLI de draw.io sale con fuentes de sustitución.

Al editar en draw.io, toda etiqueta debe seguir siendo texto plano (pestaña Texto, sin «Texto
con formato»): una etiqueta HTML se exporta como ``<foreignObject>`` y el script se para.
``DRAWIO`` cambia la ruta del ejecutable de draw.io (por defecto, la de macOS).
"""

import base64
import io
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from html import unescape
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from weasyprint import HTML

AQUI = Path(__file__).resolve().parent
FUENTES = AQUI.parent / "marca" / "fuentes"
DRAWIO = Path(os.environ.get("DRAWIO", "/Applications/draw.io.app/Contents/MacOS/draw.io"))
ORIGEN = AQUI / "arquitectura.drawio"
PAGINAS = {1: "arquitectura-despliegue", 2: "arquitectura-capas"}
CARAS = (
    ("Poppins", 400, "Poppins-Regular.ttf"),
    ("Poppins", 700, "Poppins-Bold.ttf"),
    ("Lato", 400, "Lato-Regular.ttf"),
    ("Lato", 700, "Lato-Bold.ttf"),
    ("IBM Plex Mono", 400, "IBMPlexMono-Regular.ttf"),
)


def _ejecutar(orden: list[str]) -> None:
    """Ejecuta un programa sin shell y falla si termina mal.

    Args:
        orden: Programa (ruta absoluta) y argumentos.
    """
    subprocess.run(orden, check=True, capture_output=True)  # noqa: S603 - sin shell; rutas propias


def exportar_svg(pagina: int, destino: Path) -> None:
    """Exporta una página con la CLI de draw.io.

    Args:
        pagina: Índice de página (desde 1).
        destino: Fichero SVG de salida.
    """
    orden = [str(DRAWIO), "--export", "--format", "svg", "--theme", "light"]
    _ejecutar([*orden, "--page-index", str(pagina), "--output", str(destino), str(ORIGEN)])


def _woff2(fichero: Path, texto: str) -> str:
    """Recorta una fuente a los caracteres de ``texto``.

    Args:
        fichero: Fuente TTF.
        texto: Caracteres que deben quedar.

    Returns:
        La fuente en WOFF2, codificada en base64.
    """
    fuente = TTFont(fichero)
    opciones = subset.Options()
    opciones.flavor = "woff2"
    opciones.layout_features = ["kern", "liga"]
    recorte = subset.Subsetter(opciones)
    recorte.populate(text=texto + " ")
    recorte.subset(fuente)
    salida = io.BytesIO()
    fuente.flavor = "woff2"
    fuente.save(salida)
    return base64.b64encode(salida.getvalue()).decode("ascii")


def incrustar_fuentes(svg: str) -> str:
    """Sustituye el ``@import`` de Google Fonts por ``@font-face`` con las fuentes de la marca.

    Args:
        svg: SVG exportado por draw.io.

    Returns:
        El SVG autocontenido.

    Raises:
        SystemExit: Si alguna etiqueta es HTML (``<foreignObject>``).
    """
    if "<foreignObject" in svg:
        msg = "el SVG tiene etiquetas HTML (<foreignObject>), que WeasyPrint no pinta"
        raise SystemExit(msg)
    texto = "".join(unescape(t) for t in re.findall(r"<text[^>]*>([^<]*)</text>", svg))
    reglas = "".join(
        f'@font-face{{font-family:"{familia}";font-weight:{peso};'
        f'src:url(data:font/woff2;base64,{_woff2(FUENTES / fichero, texto)}) format("woff2");}}'
        for familia, peso, fichero in CARAS
    )
    estilo = f'<style type="text/css">{reglas}</style>'
    nuevo, n = re.subn(r'<style type="text/css">.*?</style>', estilo, svg, count=1, flags=re.S)
    return nuevo if n else svg.replace("<defs>", f"<defs>{estilo}", 1)


def pintar_png(svg: Path, destino: Path, escala: int = 2) -> None:
    """Pinta el SVG con WeasyPrint (fuentes de la marca) y lo rasteriza con ``pdftoppm``.

    Args:
        svg: SVG autocontenido.
        destino: PNG de salida.
        escala: Factor sobre 96 ppp.

    Raises:
        SystemExit: Si falta ``pdftoppm`` (poppler).
    """
    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm is None:
        msg = "falta pdftoppm (brew install poppler)"
        raise SystemExit(msg)
    cabecera = svg.read_text(encoding="utf-8")[:2000]
    ancho = re.search(r'width="([\d.]+)px"', cabecera)
    alto = re.search(r'height="([\d.]+)px"', cabecera)
    if ancho is None or alto is None:
        msg = f"{svg.name} no declara su tamaño en px"
        raise SystemExit(msg)
    caras = "".join(
        f'@font-face{{font-family:"{f}";font-weight:{p};src:url("{(FUENTES / a).as_uri()}");}}'
        for f, p, a in CARAS
    )
    tam = f"{ancho.group(1)}px {alto.group(1)}px"
    html = (
        f"<html><head><style>{caras}@page{{size:{tam};margin:0}}body{{margin:0}}"
        f"img{{display:block;width:{ancho.group(1)}px}}</style></head>"
        f'<body><img src="{svg.as_uri()}"></body></html>'
    )
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "pagina.pdf"
        HTML(string=html).write_pdf(pdf)
        salida = str(destino.with_suffix(""))
        _ejecutar([pdftoppm, "-png", "-singlefile", "-r", str(96 * escala), str(pdf), salida])


def main() -> None:
    """Exporta las páginas pedidas por argumento (todas si no hay ninguno)."""
    logging.getLogger("fontTools").setLevel(logging.ERROR)
    pedidas = {int(a) for a in sys.argv[1:]} or set(PAGINAS)
    for pagina, nombre in PAGINAS.items():
        if pagina not in pedidas:
            continue
        svg = AQUI / f"{nombre}.svg"
        exportar_svg(pagina, svg)
        svg.write_text(incrustar_fuentes(svg.read_text(encoding="utf-8")), encoding="utf-8")
        pintar_png(svg, AQUI / f"{nombre}.png")
        print(svg, AQUI / f"{nombre}.png", file=sys.stderr)


if __name__ == "__main__":
    main()
