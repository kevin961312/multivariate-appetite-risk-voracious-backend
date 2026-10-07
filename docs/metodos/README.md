# Documentos de método

Un documento por **método** (carta o estimador): `docs/metodos/<método>.md`. Hoy:
[`mrcd.md`](mrcd.md) (estimador) y [`t2mrcd.md`](t2mrcd.md) (carta).

Por qué existen: cada método es independiente y se valida contra su propia referencia
([ADR 0004](../adr/0004-cartas-y-estimadores-extensibles.md)). Para que entre un método nuevo, su documento
debe tener (requisitos del punto 7 del ADR 0004; los vigila `validador-estadistico`):

1. **Tipo** (carta o estimador) y, si es carta, el estimador que declara usar.
2. **Referencia citada**: artículo (sección/ecuación) o código fuente (archivo:línea y versión).
3. **Cada default y fórmula con su cita**; lo que no tenga fuente se escribe como decisión abierta.
4. **Pasos del algoritmo** ↔ origen en la referencia ↔ código Python.
5. **Tests golden** con casos, semilla y tolerancia declarada (`xfail(strict=True)` hasta que exista la
   implementación).
6. **API propia** (si es carta): router, schemas y tests con aislamiento por tenant.
7. **Sin sustituciones ni fallbacks** dentro del método.
