# Cómo se mantienen los docs

Los documentos explican **por qué** el sistema es como es. El *qué* cambió ya lo cuenta `git log`;
aquí no se repite el diff.

## Mapa

| Documento | Para qué | Quién lo actualiza | Cuándo |
| --- | --- | --- | --- |
| [`arquitectura.md`](arquitectura.md) | Capas, puertos, adaptadores, contrato de la API, variables `VORACIOUS_*` | `documentador` | Al añadir un puerto, adaptador, variable o endpoint |
| [`adr/`](adr/) | Decisiones difíciles de revertir | `documentador` (redacta), dueño (acepta) | Antes de implementar una decisión así |
| [`mrcd/fidelidad.md`](mrcd/fidelidad.md) | Cada decisión del port ↔ archivo:línea de `rrcov` | `documentador`, revisado por `validador-estadistico` | Con cada cambio en `domain/mrcd/` o `domain/charts/` |
| [`ESTADO.md`](ESTADO.md) | Hecho / parcial / pendiente y siguiente hito | `documentador` | Al cerrar cada paso |

## Reglas

- **Un ADR por decisión.** Numeración correlativa (`NNNN-titulo-corto.md`), estados `Propuesto`,
  `Aceptado`, `Sustituido por NNNN`. Un ADR aceptado no se reescribe: se sustituye por otro.
- **Nada estadístico sin fuente.** Todo default o fórmula de MRCD/T² cita `rrcov` (archivo:línea y versión)
  o el artículo (sección/ecuación). Si no hay fuente, se escribe como **decisión abierta**.
- **Los docs no se adelantan al código.** Lo que no existe se marca como «objetivo» o «pendiente».
- Español, Markdown, enlaces relativos.
