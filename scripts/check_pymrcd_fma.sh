#!/usr/bin/env bash
# Comprueba el binario compilado de la extensión C de pymrcd (especificación
# docs/metodos/mrcd-especificacion.md §3.12.9 b, punto 4):
#   1. CERO instrucciones FMA en todo el binario (el qn0 de R del oráculo no tiene contracciones;
#      clang contrae por defecto k_L y (s*s - d*d)/4 si falta -ffp-contract=off).
#   2. Presencia de las conversiones double -> float -> double de qn_sn.c:195, :215, :224 en qn0.
# Desensamblado: otool -tV (macOS) u objdump -d (Linux). Sale con 1 si algo falla.
set -u

cd "$(dirname "$0")/.." || exit 1

so=$(uv run --no-sync python -c "import pymrcd._qn_ext as m; print(m.__file__)") || {
    echo "no se pudo importar pymrcd._qn_ext (¿falta 'uv sync --reinstall-package pymrcd'?)"
    exit 1
}
echo "binario: ${so}"

case "$(uname -s)" in
    Darwin) dis=$(otool -tV "${so}") || exit 1; qn0_sym='^_pymrcd_qn0:' ;;
    Linux) dis=$(objdump -d --no-show-raw-insn "${so}") || exit 1; qn0_sym='<pymrcd_qn0>:$' ;;
    *) echo "plataforma no soportada: $(uname -s)"; exit 1 ;;
esac

fma_re='\b(fmadd|fmsub|fnmadd|fnmsub|fmla|fmls)\b|\bvfn?m(add|sub)[0-9a-z]*\b'
n_fma=$(printf '%s\n' "${dis}" | grep -cE "${fma_re}")
echo "instrucciones FMA en el binario: ${n_fma}"
if [ "${n_fma}" -ne 0 ]; then
    printf '%s\n' "${dis}" | grep -nE "${fma_re}" | head -20
    exit 1
fi

qn0_body=$(printf '%s\n' "${dis}" | awk -v s="${qn0_sym}" '
    $0 ~ s { p = 1; next }
    p && (/^_[A-Za-z0-9_]+:$/ || /^[0-9a-f]+ <[^>]+>:$/) { exit }
    p { print }')
n_to_f=$(printf '%s\n' "${qn0_body}" | grep -cE 'fcvt[[:space:]]+s[0-9]+, d[0-9]+|cvtsd2ss')
n_to_d=$(printf '%s\n' "${qn0_body}" | grep -cE 'fcvt[[:space:]]+d[0-9]+, s[0-9]+|cvtss2sd')
echo "qn0: conversiones double->float ${n_to_f}, float->double ${n_to_d}"
if [ "${n_to_f}" -lt 3 ] || [ "${n_to_d}" -lt 3 ]; then
    echo "faltan las conversiones (float) de qn_sn.c:195, :215, :224 en pymrcd_qn0"
    exit 1
fi
echo "OK"
