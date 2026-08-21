-- Allow the 'material_group_backfill' background job kind: the "chạy lại
-- backfill" button on the per-client material-group-map admin page runs
-- scripts/backfill_johnson_material_group.py --exclusions-only --apply via the
-- shared _job_runner. It re-materializes BOM-row exclusions from
-- hub.v_material_classification (which reads client_material_group_map live)
-- after staff edit the map — classification updates instantly, but the stored
-- bom_artifact_rows.excluded_at tags only re-derive on this run.

alter table hub.background_jobs
    drop constraint if exists background_jobs_kind_check;

alter table hub.background_jobs
    add constraint background_jobs_kind_check
    check (kind in (
        'embedding_refresh',
        'substitute_refresh',
        'declaration_pdf_render',
        'material_group_backfill',
        'other'
    ));
