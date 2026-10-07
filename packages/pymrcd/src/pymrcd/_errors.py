"""Errores tipados de pymrcd.

Cada error equivale a un ``stop()`` de R (o a un ``error()`` de C llamado desde R) en el camino de
``rrcov::CovMrcd``. El port no tiene *fallbacks*: donde R se detiene, pymrcd lanza ``RError`` con el
mismo mensaje (especificación §12, pregunta P7).
"""


class RError(ValueError):
    """Error equivalente a un ``stop()``/``error()`` de R.

    El mensaje reproduce el de R para facilitar la trazabilidad con el oráculo.
    """
