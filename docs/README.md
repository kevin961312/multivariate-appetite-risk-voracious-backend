# Cómo se mantienen los docs

Los documentos explican **por qué** el sistema es como es. El *qué* cambió ya lo cuenta `git log`;
aquí no se repite el diff.

## Mapa

| Documento | Para qué | Quién lo actualiza | Cuándo |
| --- | --- | --- | --- |
| [`arquitectura.md`](arquitectura.md) | Capas, puertos, adaptadores, contrato de la API, variables `VORACIOUS_*` | `documentador` | Al añadir un puerto, adaptador, variable o endpoint |
| [`adr/`](adr/) | Decisiones difíciles de revertir | `documentador` (redacta), dueño (acepta) | Antes de implementar una decisión así |
| [`metodos/<método>.md`](metodos/README.md) | Un documento por carta o estimador: cada decisión ↔ su referencia (archivo:línea de `rrcov`, o artículo) | `documentador`, revisado por `validador-estadistico` | Con cada cambio en `domain/estimators/<estimador>/` o `domain/charts/<carta>/` |
| [`ESTADO.md`](ESTADO.md) | Hecho / parcial / pendiente y siguiente hito | `documentador` | Al cerrar cada paso |

## Reglas

- **Un ADR por decisión.** Numeración correlativa (`NNNN-titulo-corto.md`), estados `Propuesto`,
  `Aceptado`, `Sustituido por NNNN`, `Acotado por NNNN` (sigue vigente pero con un alcance menor) y
  `Ampliado por NNNN` (sigue vigente y otro ADR añade a su decisión). Se escriben como
  `Aceptado — acotado por [NNNN](...)`. Un ADR aceptado no se reescribe: se sustituye, acota o amplía con otro;
  en el antiguo solo cambia la línea de estado.
- **Nada estadístico sin fuente.** Todo default o fórmula de un método (MRCD, T², …) cita `rrcov` (archivo:línea y versión)
  o el artículo (sección/ecuación). Si no hay fuente, se escribe como **decisión abierta**.
- **Los docs no se adelantan al código.** Lo que no existe se marca como «objetivo» o «pendiente».
- Español, Markdown, enlaces relativos.
