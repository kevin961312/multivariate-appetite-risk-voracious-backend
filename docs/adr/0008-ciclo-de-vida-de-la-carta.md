# ADR 0008 — Ciclo de vida de la carta: versiones, registro de observaciones y recalibración

- **Estado:** Aceptado (decisiones del dueño, 2026-10-07). Implementación: Paso 2b (dominio y aplicación) y
  Paso 3 (API y adaptadores). **Dominio implementado (Paso 2b.1, 2026-10-07, pendiente de commit); aplicación
  (versiones persistidas, observaciones, anotaciones, aprobación) pendiente (2b.2).**
- **Fecha:** 2026-10-07
- **Relacionado:** [ADR 0005](0005-api-fase-i-fase-ii.md) (endpoints), [ADR 0007](0007-limites-t2mrcd-por-bootstrap.md)
  (límites), [`../metodos/t2mrcd.md`](../metodos/t2mrcd.md), [`../arquitectura.md`](../arquitectura.md).

## Contexto

Hasta el Paso 2 el modelo era una foto: Fase I produce un modelo y Fase II lo usa sin cambiar nada. El dueño
entregó un diseño de operación real: la carta se vigila durante meses, las señales se investigan, el proceso
cambia y hay que **recalibrar** sin perder la trazabilidad de lo que se dijo en cada fecha. Hace falta decidir
quién es dueño de ese ciclo de vida y cómo se calcula el límite de Fase II.

## Decisión

### 1. El backend es dueño del ciclo de vida (opción a)

Versiones, observaciones, anotaciones, eventos estructurales, propuesta/aprobación y avisos viven en el
backend. El front solo muestra y pide. El ciclo:

1. **Fase I (versión v0).** Se ajusta con el histórico y se calculan **dos límites**: de Fase I y de Fase II
   (ADR 0007, enmienda). Ambos quedan como referencia de la versión.
2. **Arranque de Fase II.** Se vigila con el **límite de Fase I como provisional y fijo** (Q2): no hay aún
   observaciones propias de Fase II con las que calibrar.
3. **Registro.** Cada observación puntuada se guarda con fecha (`observed_at`), lote (`batch_label`), valores,
   T², límite usado y versión. Las observaciones **con señal** se pueden anotar: causa asignable (sí/no), cuál,
   acción tomada (Q12: solo se anotan las que señalan).
4. **Recalibración a petición** (base + rango de fechas): depuración (humana: causa asignable confirmada; y
   automática iterativa, también en v0, Q3), comparación con la base (cambio en S y en μ), decisión
   **ampliar o reemplazar**, nuevo límite de Fase II y una **versión inmutable en estado propuesta**, con
   reporte antes/después. **Solo rige cuando se aprueba.** Hereda B, α y parámetros MRCD de la versión vigente (Q8).
5. **Régimen.** Cada versión aprobada tiene un límite vigente fijo; cada observación se evalúa con la versión
   vigente en su fecha. `effective_from` es **no retroactivo**: posterior a la última observación ya puntuada (Q6).
6. **Eventos estructurales.** Un evento marca la carta como **«requiere nueva base»**; el siguiente recálculo
   **reemplaza** usando datos posteriores al evento. Mientras tanto se sigue vigilando con la versión vigente (Q7).
7. **Revalidación periódica** configurable (6 meses o N observaciones): genera un aviso.

Las versiones son **inmutables y solo se añaden** (append-only); lo único mutable es su estado
(`proposed → approved | rejected`, y `approved → superseded`), con comparar-y-cambiar (CAS) para que dos
aprobaciones concurrentes no coexistan.

### 2. Límite de Fase II por remuestreo no paramétrico

Nunca normal paramétrica: MRCD es robusto y la distribución del T² con MRCD es desconocida (y con p > n no hay
fuente citada, ADR 0007). En cada réplica: muestra con reemplazo de tamaño `h` de las filas limpias, reajuste
de MRCD sobre la muestra, T² de las filas que **no entraron** (OOB) con ese ajuste. Fase I y Fase II comparten
las réplicas (un solo conjunto de ajustes). Esto **revierte la anulación OOB** del ADR 0007 (ver su enmienda).

### 3. Agregación pool (Q1)

En ambas fases se juntan los T² de todas las réplicas y se toma **un único cuantil 1−α** (tipo 7). Sustituye
el promedio de cuantiles por réplica: con m valores por réplica y m·α < 1 el cuantil por réplica queda acotado
por el máximo y el α efectivo sube (≈ 0.018 en Fase I con m = 75 y ≈ 0.035 en Fase II con m ≈ 28, frente al 0.005
pedido). `phase2_alpha_limit` es configurable, default 0.005.

### 4. Otras decisiones

- **Umbrales:** mínimo de observaciones 25 configurable (sin regla por variable: MRCD vale en alta y baja
  dimensión); cambio en S medido con la norma de Frobenius relativa ‖S₁−S₀‖_F/‖S₀‖_F, umbral orientativo 0.10
  parametrizable (`relative_change_threshold`); **informativo por defecto** (`threshold_decides = False`): con
  datos estables la Frobenius relativa de MRCD sale ≈ 0.25–0.5 (n = 200, p = 3) y 0.10 reemplazaría siempre. Se
  **reemplaza** si cualquiera de las pruebas formales (S, μ) detecta cambio, o además si el umbral lo supera con
  `threshold_decides = True`.
- **Remuestreo solo sobre `best` (0.75), decisión del dueño 2026-10-07:** con todas las filas una contaminación
  no detectada inflaría el límite (enmascaramiento). Coste conocido y medido (n = 200, p = 3, B = 50): falsa
  alarma real ≈ 2.0–2.4 % en Fase I y ≈ 1.6–2.2 % en Fase II frente al 0.5 % nominal (≈ 0.4 % con todas las
  filas), porque `best` es el 75 % central; la depuración automática puede quitar entre 1 y 10 filas buenas.
  Característica del diseño; estudio futuro: reponderado tipo MCD. La Fase I final de una recalibración no
  vuelve a depurar (`final_depuration_skipped`), para no recortar filas buenas en cada versión.
- **Depuración:** máximo 5 vueltas (técnico); si no converge, sigue con `converged=false` en el reporte (Q5).
- **«Límite Fase II > Fase I»** es un diagnóstico, no un invariante (Q9).
- **Calidad de la tubería:** con estimador clásico y un muestreador de muestras independientes (normal, solo en
  `tests/`, nunca en `src/`) los límites simulados coinciden con Beta (Fase I) y F (Fase II), n > p. Valida la
  tubería, no el bootstrap OOB: con el clásico el OOB da una Fase II ≈ +16 % sobre la F (efecto .632: cada
  réplica usa ≈ 63 % de filas distintas), es decir, conservador.
- **M6 (aprobada):** el reporte incluye el error Monte Carlo del límite.
- **M1 (aprobada, 2b.2):** las estrategias (`clean_criterion`, `aggregation`) se persisten por nombre.

## Alternativas descartadas

| Alternativa | Por qué no |
| --- | --- |
| Front orquestando el ciclo (versiones y avisos en el cliente) | Cada cliente reimplementaría reglas de negocio y la trazabilidad dependería de quien llame; no se puede auditar ni garantizar la inmutabilidad ni la no retroactividad. |
| Límite de Fase II con distribución normal paramétrica (F de Hotelling/Beta) | Supone normalidad, justo lo que MRCD evita; sin fuente para el T² de MRCD. Solo se usa como control de calidad del muestreador, en tests. |
| Promedio de cuantiles por réplica | α efectivo mucho mayor que el pedido cuando m·α < 1 (ver arriba). |
| Recalibración automática sin aprobación | Cambiaría el límite sin que nadie lo vea; la propuesta con reporte antes/después existe para evitarlo. |
| Retroactividad de `effective_from` | Reescribiría señales ya emitidas. |

## Consecuencias

- **Coste:** la v0 hace hasta `(1 + max_depuration_rounds)·B` ajustes MRCD (cada ronda de depuración calibra); una
  recalibración, hasta `(1 + rondas)·B` para depurar las filas nuevas más `B` en EXTEND (en REPLACE se reutiliza
  la última calibración). Con B = 100 y 5 rondas son cientos de ajustes (la estimación del dueño era ≈ 300, 20–70
  min en 8 núcleos con `pymrcd` actual, para el caso sin rondas extra). Siempre trabajo asíncrono (`202`).
  **M5** (optimizar `pymrcd`) es más urgente por este coste; antes de producción.
- **Puertos nuevos previstos** (Paso 2b.2): `ModelVersionRepository` (append-only con CAS de estado),
  `ObservationRepository`, `SignalAnnotationRepository`, `StructuralEventRepository`, `RecalibrationRepository`.
- **Estados de la carta** con precedencia `requires_new_base > proposal_pending > revalidation_due >
  startup/active` (ver [`../arquitectura.md`](../arquitectura.md)).
- La API crece (ADR 0005, enmienda 2026-10-07).

## Pendientes

- **Pruebas formales de cambio** (igualdad de covarianzas y de medias por remuestreo): **pendientes de cita**.
  Sin ellas la recalibración termina en `failed / T2MRCD_DECISION_PENDING` salvo reemplazo forzado.
- Cita del umbral 0.10 y del 6 meses (hoy documento del dueño, orientativos).
- **2b.2:** guardar un hash del contenido de la base al persistir (la comprobación por T² con `rtol` no prueba
  identidad).
- **Mejoras aprobadas para después:** M2 (ARL al 90 %), M3 (avisos activos), M4 (roles con JWT); M5 antes de producción.
- Cita del artículo T²MRCD (P6) y del bootstrap (heredados del ADR 0007).
