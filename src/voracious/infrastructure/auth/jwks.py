"""JWKS en fichero: lectura estricta de las llaves públicas y alta de una llave nueva (D3).

Un JWKS (RFC 7517) es el mismo formato que publica un IdP OIDC: cuando llegue el del banco solo
cambia la fuente (fichero → URL), no estas reglas. Cada llave lleva ``kid`` (obligatorio y único,
lo que permite rotar con dos vivas a la vez) y ``alg`` (uno de los permitidos). Se rechaza toda
llave simétrica (``kty: oct``) y todo miembro privado: el fichero se versiona en claro y la API
solo verifica.

Los mensajes de error nombran la regla y, como mucho, el ``kid``; nunca el material de la llave.
"""

import json
from collections.abc import Collection, Mapping
from typing import Final

from jwt import PyJWK
from jwt.exceptions import PyJWTError

__all__ = ["PRIVATE_MEMBERS", "JwksError", "add_public_key", "load_jwks"]

PRIVATE_MEMBERS: Final = frozenset({"d", "p", "q", "dp", "dq", "qi", "oth", "k"})
"""Miembros de un JWK que solo tiene una llave privada o simétrica (RFC 7518 §6)."""

_MAX_KID: Final = 128
"""Longitud máxima de un ``kid``."""


class JwksError(ValueError):
    """El JWKS o la llave que se quiere añadir no cumple las reglas."""


def _parse(text: str) -> list[dict[str, object]]:
    """Lista de llaves de un JWKS, comprobando solo la forma del documento.

    Args:
        text: JSON del JWKS.

    Returns:
        Las llaves (diccionarios), quizá vacía.

    Raises:
        JwksError: Si no es JSON, no es un objeto con ``keys`` o alguna llave no es un objeto.
    """
    try:
        document = json.loads(text)
    except ValueError as exc:
        msg = "el JWKS no es JSON válido"
        raise JwksError(msg) from exc
    if not isinstance(document, dict) or not isinstance(document.get("keys"), list):
        msg = "el JWKS debe ser un objeto con la lista 'keys'"
        raise JwksError(msg)
    keys: list[dict[str, object]] = []
    for entry in document["keys"]:
        if not isinstance(entry, dict):
            msg = "cada llave del JWKS debe ser un objeto"
            raise JwksError(msg)
        keys.append(entry)
    return keys


def _check_public(key: Mapping[str, object]) -> str:
    """Comprueba que una llave es pública, asimétrica y con ``kid``; devuelve el ``kid``.

    Args:
        key: JWK.

    Returns:
        El ``kid``.

    Raises:
        JwksError: Si falta el ``kid``, es simétrica o trae miembros privados.
    """
    kid = key.get("kid")
    if not isinstance(kid, str) or not kid or len(kid) > _MAX_KID:
        msg = "cada llave del JWKS necesita un 'kid' no vacío"
        raise JwksError(msg)
    if key.get("kty") == "oct":
        msg = f"la llave '{kid}' es simétrica (kty oct): solo se admiten llaves asimétricas"
        raise JwksError(msg)
    private = sorted(PRIVATE_MEMBERS & set(key))
    if private:
        msg = f"la llave '{kid}' trae miembros privados ({', '.join(private)}): solo públicas"
        raise JwksError(msg)
    use = key.get("use")
    if use is not None and use != "sig":
        msg = f"la llave '{kid}' no es de firma (use debe ser 'sig')"
        raise JwksError(msg)
    return kid


def load_jwks(text: str, *, allowed_algorithms: Collection[str]) -> Mapping[str, PyJWK]:
    """Lee un JWKS y devuelve sus llaves públicas por ``kid``.

    Args:
        text: JSON del JWKS.
        allowed_algorithms: Algoritmos admitidos (``alg`` de cada llave).

    Returns:
        ``kid → PyJWK``, cada una ligada a su ``alg``.

    Raises:
        JwksError: Si el JSON no es válido, no hay llaves, falta ``kid`` o ``alg``, un ``kid`` se
            repite, el ``alg`` no está permitido, la llave es simétrica, trae miembros privados o
            no se puede construir con su ``alg``.
    """
    entries = _parse(text)
    if not entries:
        msg = "el JWKS no tiene ninguna llave"
        raise JwksError(msg)
    keys: dict[str, PyJWK] = {}
    for entry in entries:
        kid = _check_public(entry)
        if kid in keys:
            msg = f"el kid '{kid}' está repetido en el JWKS"
            raise JwksError(msg)
        alg = entry.get("alg")
        if not isinstance(alg, str) or alg not in allowed_algorithms:
            msg = (
                f"la llave '{kid}' necesita un 'alg' permitido "
                f"({', '.join(sorted(allowed_algorithms))})"
            )
            raise JwksError(msg)
        try:
            keys[kid] = PyJWK(entry, algorithm=alg)
        except PyJWTError as exc:
            msg = f"la llave '{kid}' no es una llave {alg} válida"
            raise JwksError(msg) from exc
    return keys


def add_public_key(jwks_text: str | None, jwk: Mapping[str, object]) -> str:
    """Añade una llave pública a un JWKS (o crea uno) y devuelve el JSON determinista.

    Args:
        jwks_text: JWKS actual; ``None`` si aún no existe.
        jwk: Llave pública nueva (con ``kid`` y ``alg``).

    Returns:
        El JWKS con la llave añadida al final: claves ordenadas, sangría 2 y salto de línea final.

    Raises:
        JwksError: Si el JWKS actual no es válido, la llave no es pública o su ``kid`` ya existe.
    """
    entries = [] if jwks_text is None else _parse(jwks_text)
    kids = {_check_public(entry) for entry in entries}
    kid = _check_public(jwk)
    if not isinstance(jwk.get("alg"), str):
        msg = f"la llave '{kid}' necesita 'alg'"
        raise JwksError(msg)
    if kid in kids:
        msg = f"el kid '{kid}' ya está en el JWKS"
        raise JwksError(msg)
    document = {"keys": [*entries, dict(jwk)]}
    return json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
