-- 0002: sin comparación de bases en la recalibración de T²MRCD (decisión del dueño, 2026-10-14).
--
-- La carta T² ya es la prueba de hipótesis sobre la media: la recalibración amplía la base por
-- defecto y la reemplaza solo ante un evento estructural o una petición explícita. Desaparecen el
-- paso de comparación y su tabla, y cambian los formatos de lo que dejó la comparación: el informe
-- de recalibración (REPORT_FORMAT_VERSION 3, sin comparación ni «forced») y la sesión de
-- recalibración (sin el id de la comparación en la propuesta; con kept_dataset_id y
-- extension_dataset_id).
--
-- No se escribe lector del formato anterior (decisión del dueño): si hay datos que dependen de él
-- (comparaciones, recalibraciones o versiones recalibradas, number > 0), la migración aborta sin
-- aplicar nada y la base se recrea. Una base sin recalibraciones (solo Fase I) migra sin pérdida.
-- Este fichero no se edita una vez aplicado: los cambios van en una migración nueva.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM comparisons)
        OR EXISTS (SELECT 1 FROM recalibrations)
        OR EXISTS (SELECT 1 FROM model_versions WHERE number > 0)
    THEN
        RAISE EXCEPTION
            'hay comparaciones, recalibraciones o versiones recalibradas en el formato anterior '
            '(sin lector): recrea la base antes de migrar a 0002';
    END IF;
END
$$;

DROP TABLE comparisons;
