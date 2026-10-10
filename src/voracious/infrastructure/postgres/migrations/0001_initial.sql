-- 0001: esquema inicial de Voracious en Postgres (Paso 4.2).
--
-- Una tabla por repositorio. Todas llevan tenant_id (y toda lectura filtra por él), seq BIGSERIAL
-- (orden de inserción), payload TEXT con el JSON exacto del codec del registro (TEXT y no JSONB:
-- JSONB rechaza NaN e infinitos y pierde -0) y format_version (versión de ese JSON). Las demás
-- columnas son copias del payload para filtrar, ordenar y garantizar invariantes; se leen siempre
-- del payload. Los estados de trabajo son queued | running | succeeded | failed | cancelled.
-- Las matrices de los datasets siguen en el almacén de ficheros (.npy); aquí van sus metadatos.
-- Este fichero no se edita una vez aplicado (el ejecutor compara su checksum): los cambios van en
-- una migración nueva.

CREATE TABLE tenants (
    tenant_id  TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- --- datasets --------------------------------------------------------------------------------

CREATE TABLE datasets (
    tenant_id      TEXT        NOT NULL REFERENCES tenants (tenant_id),
    dataset_id     TEXT        NOT NULL,
    seq            BIGSERIAL   NOT NULL,
    source         TEXT        NOT NULL,
    parent_id      TEXT,
    origin_ref     TEXT,
    content_hash   TEXT        NOT NULL,
    n_rows         INTEGER     NOT NULL,
    n_cols         INTEGER     NOT NULL,
    variables      TEXT[],
    created_at     TIMESTAMPTZ NOT NULL,
    format_version INTEGER     NOT NULL,
    payload        TEXT        NOT NULL,
    PRIMARY KEY (tenant_id, dataset_id)
);
CREATE INDEX datasets_parent ON datasets (tenant_id, parent_id);

-- Fecha de cada fila (y una referencia externa reservada para el cliente). Solo trazabilidad.
CREATE TABLE dataset_rows (
    tenant_id    TEXT        NOT NULL,
    dataset_id   TEXT        NOT NULL,
    row_index    INTEGER     NOT NULL,
    observed_at  TIMESTAMPTZ,
    external_ref TEXT,
    PRIMARY KEY (tenant_id, dataset_id, row_index),
    FOREIGN KEY (tenant_id, dataset_id) REFERENCES datasets (tenant_id, dataset_id)
);
CREATE INDEX dataset_rows_observed ON dataset_rows (tenant_id, dataset_id, observed_at);

-- --- pasos de la Fase I ----------------------------------------------------------------------

CREATE TABLE fits (
    tenant_id      TEXT        NOT NULL REFERENCES tenants (tenant_id),
    chart_id       TEXT        NOT NULL,
    fit_id         TEXT        NOT NULL,
    seq            BIGSERIAL   NOT NULL,
    status         TEXT        NOT NULL,
    dataset_id     TEXT        NOT NULL,
    pipeline_id    TEXT,
    created_at     TIMESTAMPTZ NOT NULL,
    format_version INTEGER     NOT NULL,
    payload        TEXT        NOT NULL,
    PRIMARY KEY (tenant_id, chart_id, fit_id),
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled'))
);
CREATE INDEX fits_unfinished ON fits (seq) WHERE status IN ('queued', 'running');

CREATE TABLE limits (
    tenant_id        TEXT        NOT NULL REFERENCES tenants (tenant_id),
    chart_id         TEXT        NOT NULL,
    limits_id        TEXT        NOT NULL,
    seq              BIGSERIAL   NOT NULL,
    status           TEXT        NOT NULL,
    fit_id           TEXT        NOT NULL,
    recalibration_id TEXT,
    pipeline_id      TEXT,
    created_at       TIMESTAMPTZ NOT NULL,
    format_version   INTEGER     NOT NULL,
    payload          TEXT        NOT NULL,
    PRIMARY KEY (tenant_id, chart_id, limits_id),
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled'))
);
CREATE INDEX limits_unfinished ON limits (seq) WHERE status IN ('queued', 'running');

CREATE TABLE exclusions (
    tenant_id      TEXT        NOT NULL REFERENCES tenants (tenant_id),
    chart_id       TEXT        NOT NULL,
    exclusion_id   TEXT        NOT NULL,
    seq            BIGSERIAL   NOT NULL,
    status         TEXT        NOT NULL,
    dataset_id     TEXT        NOT NULL,
    pipeline_id    TEXT,
    created_at     TIMESTAMPTZ NOT NULL,
    format_version INTEGER     NOT NULL,
    payload        TEXT        NOT NULL,
    PRIMARY KEY (tenant_id, chart_id, exclusion_id),
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled'))
);
CREATE INDEX exclusions_unfinished ON exclusions (seq) WHERE status IN ('queued', 'running');

CREATE TABLE pipelines (
    tenant_id        TEXT        NOT NULL REFERENCES tenants (tenant_id),
    chart_id         TEXT        NOT NULL,
    pipeline_id      TEXT        NOT NULL,
    seq              BIGSERIAL   NOT NULL,
    status           TEXT        NOT NULL,
    kind             TEXT        NOT NULL,
    dataset_id       TEXT        NOT NULL,
    n_steps          INTEGER     NOT NULL,
    model_id         TEXT,
    recalibration_id TEXT,
    created_at       TIMESTAMPTZ NOT NULL,
    format_version   INTEGER     NOT NULL,
    payload          TEXT        NOT NULL,
    PRIMARY KEY (tenant_id, chart_id, pipeline_id),
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled'))
);
CREATE INDEX pipelines_unfinished ON pipelines (seq) WHERE status IN ('queued', 'running');

-- --- modelos y versiones ---------------------------------------------------------------------

CREATE TABLE models (
    tenant_id       TEXT        NOT NULL REFERENCES tenants (tenant_id),
    chart_id        TEXT        NOT NULL,
    model_id        TEXT        NOT NULL,
    seq             BIGSERIAL   NOT NULL,
    status          TEXT        NOT NULL,
    root_dataset_id TEXT,
    pipeline_id     TEXT,
    created_at      TIMESTAMPTZ NOT NULL,
    format_version  INTEGER     NOT NULL,
    payload         TEXT        NOT NULL,
    PRIMARY KEY (tenant_id, chart_id, model_id),
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled'))
);
CREATE INDEX models_unfinished ON models (seq) WHERE status IN ('queued', 'running');

-- Append-only: el contenido no cambia; solo el estado y la decisión (comparar-y-cambiar).
CREATE TABLE model_versions (
    tenant_id        TEXT        NOT NULL REFERENCES tenants (tenant_id),
    chart_id         TEXT        NOT NULL,
    model_id         TEXT        NOT NULL,
    number           INTEGER     NOT NULL,
    seq              BIGSERIAL   NOT NULL,
    status           TEXT        NOT NULL,
    effective_from   TIMESTAMPTZ,
    recalibration_id TEXT,
    created_at       TIMESTAMPTZ NOT NULL,
    format_version   INTEGER     NOT NULL,
    payload          TEXT        NOT NULL,
    PRIMARY KEY (tenant_id, chart_id, model_id, number),
    CHECK (status IN ('proposed', 'active', 'superseded', 'rejected'))
);
-- D6: como mucho una propuesta sin resolver por modelo (add_proposal_if_none: ON CONFLICT).
CREATE UNIQUE INDEX model_versions_one_proposal
    ON model_versions (tenant_id, chart_id, model_id) WHERE status = 'proposed';

-- Origen y fecha de cada fila de la base de una versión (trazabilidad; append-only).
CREATE TABLE version_base_rows (
    tenant_id   TEXT        NOT NULL,
    chart_id    TEXT        NOT NULL,
    model_id    TEXT        NOT NULL,
    number      INTEGER     NOT NULL,
    row_index   INTEGER     NOT NULL,
    source      TEXT        NOT NULL,
    ref         TEXT        NOT NULL,
    observed_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, chart_id, model_id, number, row_index),
    FOREIGN KEY (tenant_id, chart_id, model_id, number)
        REFERENCES model_versions (tenant_id, chart_id, model_id, number)
);

-- --- Fase II ---------------------------------------------------------------------------------

CREATE TABLE scores (
    tenant_id      TEXT        NOT NULL REFERENCES tenants (tenant_id),
    chart_id       TEXT        NOT NULL,
    model_id       TEXT        NOT NULL,
    score_id       TEXT        NOT NULL,
    seq            BIGSERIAL   NOT NULL,
    status         TEXT        NOT NULL,
    batch_label    TEXT,
    created_at     TIMESTAMPTZ NOT NULL,
    format_version INTEGER     NOT NULL,
    payload        TEXT        NOT NULL,
    PRIMARY KEY (tenant_id, chart_id, model_id, score_id),
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled'))
);
CREATE INDEX scores_unfinished ON scores (seq) WHERE status IN ('queued', 'running');

-- Append-only: una fila por observación puntuada.
CREATE TABLE observations (
    tenant_id       TEXT        NOT NULL REFERENCES tenants (tenant_id),
    chart_id        TEXT        NOT NULL,
    model_id        TEXT        NOT NULL,
    observation_id  TEXT        NOT NULL,
    seq             BIGSERIAL   NOT NULL,
    score_id        TEXT        NOT NULL,
    batch_label     TEXT,
    observed_at     TIMESTAMPTZ NOT NULL,
    observed_values FLOAT8[]    NOT NULL,
    t2              FLOAT8      NOT NULL,
    limit_used      FLOAT8      NOT NULL,
    limit_kind      TEXT        NOT NULL,
    version_number  INTEGER     NOT NULL,
    signal          BOOLEAN     NOT NULL,
    recorded_at     TIMESTAMPTZ NOT NULL,
    format_version  INTEGER     NOT NULL,
    payload         TEXT        NOT NULL,
    PRIMARY KEY (tenant_id, chart_id, model_id, observation_id)
);
CREATE INDEX observations_by_date
    ON observations (tenant_id, chart_id, model_id, observed_at, seq);
CREATE INDEX observations_signals
    ON observations (tenant_id, chart_id, model_id, observed_at, seq) WHERE signal;
CREATE INDEX observations_by_version
    ON observations (tenant_id, chart_id, model_id, version_number);

-- Append-only: vale la anotación más reciente (mayor seq) de cada observación.
CREATE TABLE signal_annotations (
    tenant_id        TEXT        NOT NULL REFERENCES tenants (tenant_id),
    chart_id         TEXT        NOT NULL,
    model_id         TEXT        NOT NULL,
    annotation_id    TEXT        NOT NULL,
    seq              BIGSERIAL   NOT NULL,
    observation_id   TEXT        NOT NULL,
    assignable_cause BOOLEAN     NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL,
    format_version   INTEGER     NOT NULL,
    payload          TEXT        NOT NULL,
    PRIMARY KEY (tenant_id, chart_id, model_id, annotation_id)
);
CREATE INDEX signal_annotations_by_observation
    ON signal_annotations (tenant_id, chart_id, model_id, observation_id, seq);

-- Append-only.
CREATE TABLE structural_events (
    tenant_id      TEXT        NOT NULL REFERENCES tenants (tenant_id),
    chart_id       TEXT        NOT NULL,
    model_id       TEXT        NOT NULL,
    event_id       TEXT        NOT NULL,
    seq            BIGSERIAL   NOT NULL,
    occurred_at    TIMESTAMPTZ NOT NULL,
    registered_at  TIMESTAMPTZ NOT NULL,
    format_version INTEGER     NOT NULL,
    payload        TEXT        NOT NULL,
    PRIMARY KEY (tenant_id, chart_id, model_id, event_id)
);
CREATE INDEX structural_events_by_date
    ON structural_events (tenant_id, chart_id, model_id, occurred_at, registered_at, seq);

-- --- recalibración ---------------------------------------------------------------------------

CREATE TABLE recalibrations (
    tenant_id        TEXT        NOT NULL REFERENCES tenants (tenant_id),
    chart_id         TEXT        NOT NULL,
    model_id         TEXT        NOT NULL,
    recalibration_id TEXT        NOT NULL,
    seq              BIGSERIAL   NOT NULL,
    status           TEXT        NOT NULL,
    mode             TEXT        NOT NULL,
    proposal_status  TEXT,
    created_at       TIMESTAMPTZ NOT NULL,
    format_version   INTEGER     NOT NULL,
    payload          TEXT        NOT NULL,
    PRIMARY KEY (tenant_id, chart_id, model_id, recalibration_id),
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled'))
);
-- D6: como mucho una recalibración en curso por modelo (add_if_none_in_progress: ON CONFLICT).
CREATE UNIQUE INDEX recalibrations_one_in_progress
    ON recalibrations (tenant_id, chart_id, model_id) WHERE status IN ('queued', 'running');
CREATE INDEX recalibrations_by_id ON recalibrations (tenant_id, chart_id, recalibration_id);
CREATE INDEX recalibrations_unfinished
    ON recalibrations (seq) WHERE status IN ('queued', 'running');

CREATE TABLE comparisons (
    tenant_id        TEXT        NOT NULL REFERENCES tenants (tenant_id),
    chart_id         TEXT        NOT NULL,
    model_id         TEXT        NOT NULL,
    comparison_id    TEXT        NOT NULL,
    seq              BIGSERIAL   NOT NULL,
    status           TEXT        NOT NULL,
    recalibration_id TEXT        NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL,
    format_version   INTEGER     NOT NULL,
    payload          TEXT        NOT NULL,
    PRIMARY KEY (tenant_id, chart_id, model_id, comparison_id),
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled'))
);
CREATE INDEX comparisons_unfinished ON comparisons (seq) WHERE status IN ('queued', 'running');
