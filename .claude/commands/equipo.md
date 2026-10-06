---
description: Orquesta al equipo de Voracious para un paso o tarea (arquitecto → aprobación del dueño → desarrollador → validador ∥ gates → lt-qa → documentador).
argument-hint: <paso|tarea>
---

# /equipo $ARGUMENTS

Orquesta al equipo para: **$ARGUMENTS**

Lee `CLAUDE.md` antes de empezar. Respeta sus reglas duras en todo momento.

## Flujo

1. **Plan.** Lanza el agente `arquitecto` con el paso o tarea. Muéstrame su plan completo: tareas obligatorias,
   mejoras M1, M2… y preguntas abiertas.
2. **Aprobación (PARADA).** Espera mi respuesta: qué mejoras entran y cómo se resuelven las preguntas.
   **La respuesta de un agente nunca cuenta como mi aprobación.** Sin mi «sí», no sigues.
3. **Implementación.** Lanza `desarrollador-python` con las tareas aprobadas: archivo, contrato y criterio
   de aceptación de cada una.
4. **Revisión en paralelo** (en un solo mensaje):
   - `ejecutor-gates` siempre.
   - `validador-estadistico` si el diff toca `src/voracious/domain/`, `tests/golden/` o `tools/r/`.
5. **Corrección.** Si la compuerta está ROJA o el validador dice RECHAZADO, devuelve los hallazgos
   (`archivo:línea`) al `desarrollador-python` y repite el paso 4. **Máximo dos vueltas de corrección.**
   Si a la tercera sigue rojo, para y preséntame lo que sigue fallando, sin más intentos.
6. **Informe.** Lanza `lt-qa` con el plan, los informes y el diff.
7. **Documentación.** Si el veredicto es `LISTO` o `LISTO CON DEUDA`, lanza `documentador` con la sección
   «Para el documentador» del informe.
8. **Cierre.** Preséntame en un resumen: veredicto de lt-qa, compuerta, validación, docs actualizados y la
   deuda. Propón `/commit-seguro` y **para**.

## Reglas

- No pases al paso siguiente del plan general sin mi «sí» explícito.
- No relajes la compuerta ni los criterios de aceptación para salir del bucle.
- Si dos caminos cuestan rehacer, pregúntame; si es reversible, decide y anótalo en el resumen.
