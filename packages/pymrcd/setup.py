"""Compilación de la extensión C ``pymrcd._qn_ext`` (los metadatos viven en ``pyproject.toml``).

Especificación ``docs/metodos/mrcd-especificacion.md`` §3.12.9 b): las opciones van **al final**
para prevalecer sobre las ``CFLAGS`` de CPython (que no desactivan la contracción FMA); la macro
``PYMRCD_FP_CONTRACT_OFF`` la exige ``_ext/fpguard.h`` (``#error`` si falta).
"""

from setuptools import Extension, setup

SOURCES = [
    "src/pymrcd/_ext/qnmodule.c",
    "src/pymrcd/_ext/qn0.c",
    "src/pymrcd/_ext/rsort.c",
]

COMPILE_ARGS = [
    "-O2",
    "-std=c11",
    "-ffp-contract=off",
    "-fno-fast-math",
    "-pthread",
    "-Wall",
    "-Wextra",
]

setup(
    ext_modules=[
        Extension(
            "pymrcd._qn_ext",
            sources=SOURCES,
            depends=[
                "src/pymrcd/_ext/fpguard.h",
                "src/pymrcd/_ext/qn0.h",
                "src/pymrcd/_ext/rsort.h",
            ],
            define_macros=[("PYMRCD_FP_CONTRACT_OFF", "1")],
            extra_compile_args=COMPILE_ARGS,
            extra_link_args=["-pthread"],
        )
    ]
)
