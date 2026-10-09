#!/usr/bin/env bash
# Comprueba el binario compilado de la extensión C de pymrcd (especificación
# docs/metodos/mrcd-especificacion.md §3.12.9 b, punto 4):
#   1. CERO instrucciones FMA en todo el binario (el qn0 de R del oráculo no tiene contracciones;
#      clang contrae por defecto k_L y (s*s - d*d)/4 si falta -ffp-contract=off, y gcc en modo GNU
#      usa -ffp-contract=fast).
#   2. Presencia de las conversiones double -> float -> double de qn_sn.c:195, :215, :224 en qn0.
# Desensamblado: otool -tV (macOS) u objdump -d (Linux). Sale con 1 si algo falla.
#
# Antes de comprobar imprime la traza de compilación (compilador, CC/CFLAGS de sysconfig y del
# entorno, build_info() de la extensión) para que un fallo en CI o en Docker se pueda diagnosticar.
#
# Prueba de que la comprobación muerde (Linux x86-64; en macOS arm64 no aplica -march=x86-64-v3):
# compilar sin -ffp-contract=off y con FMA disponible debe dar rojo, p. ej. quitando temporalmente
# "-ffp-contract=off" de COMPILE_ARGS y el #error de _ext/fpguard.h y corriendo
#   CFLAGS=-march=x86-64-v3 uv sync --reinstall-package pymrcd && scripts/check_pymrcd_fma.sh
set -u

cd "$(dirname "$0")/.." || exit 1

echo "--- traza de compilación ---"
if command -v cc > /dev/null 2>&1; then
    cc --version 2>&1 | sed -n '1p'
else
    echo "cc: no encontrado en el PATH"
fi
echo "CFLAGS del entorno: ${CFLAGS:-<vacío>}"
uv run --no-sync python -c "
import sysconfig
print('sysconfig CC:', sysconfig.get_config_var('CC'))
print('sysconfig CFLAGS:', sysconfig.get_config_var('CFLAGS'))
" || exit 1
uv run --no-sync python -c "
import pymrcd._qn_ext as m
for key, value in m.build_info().items():
    print(f'build_info {key}: {value}')
" || {
    echo "no se pudo importar pymrcd._qn_ext (¿falta 'uv sync --reinstall-package pymrcd'?)"
    exit 1
}
echo "--- comprobación ---"

so=$(uv run --no-sync python -c "import pymrcd._qn_ext as m; print(m.__file__)") || {
    echo "no se pudo importar pymrcd._qn_ext (¿falta 'uv sync --reinstall-package pymrcd'?)"
    exit 1
}
echo "binario: ${so}"

# qn0_sym: cabecera del símbolo pymrcd_qn0. En Linux, gcc puede emitir además clones
# (pymrcd_qn0.constprop.0, .isra.0, .part.0...): sus cuerpos también cuentan para las conversiones.
case "$(uname -s)" in
    Darwin) dis=$(otool -tV "${so}") || exit 1; qn0_sym='^_pymrcd_qn0:$' ;;
    Linux)
        dis=$(objdump -d --no-show-raw-insn "${so}") || exit 1
        qn0_sym='<pymrcd_qn0([.][a-z]+[.][0-9]+)*>:$'
        ;;
    *) echo "plataforma no soportada: $(uname -s)"; exit 1 ;;
esac

# La búsqueda de FMA va sobre TODO el binario, no solo sobre qn0.
fma_re='\b(fmadd|fmsub|fnmadd|fnmsub|fmla|fmls)\b|\bvfn?m(add|sub)[0-9a-z]*\b'
n_fma=$(printf '%s\n' "${dis}" | grep -cE "${fma_re}")
echo "instrucciones FMA en el binario: ${n_fma}"
if [ "${n_fma}" -ne 0 ]; then
    printf '%s\n' "${dis}" | grep -nE "${fma_re}" | sed -n '1,20p'
    exit 1
fi

# Cuerpo de qn0 (y de sus clones): se imprime desde su cabecera hasta la cabecera siguiente.
qn0_body=$(printf '%s\n' "${dis}" | awk -v s="${qn0_sym}" '
    /^_[A-Za-z0-9_]+:$/ || /^[0-9a-f]+ <[^>]+>:$/ { p = ($0 ~ s); next }
    p { print }')
n_to_f=$(printf '%s\n' "${qn0_body}" | grep -cE 'fcvt[[:space:]]+s[0-9]+, d[0-9]+|cvtsd2ss')
n_to_d=$(printf '%s\n' "${qn0_body}" | grep -cE 'fcvt[[:space:]]+d[0-9]+, s[0-9]+|cvtss2sd')
echo "qn0: conversiones double->float ${n_to_f}, float->double ${n_to_d}"
if [ "${n_to_f}" -lt 3 ] || [ "${n_to_d}" -lt 3 ]; then
    echo "faltan las conversiones (float) de qn_sn.c:195, :215, :224 en pymrcd_qn0"
    exit 1
fi
echo "OK"
