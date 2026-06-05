-- Allow the 'declaration_pdf_render' background job kind: the
-- "Render PDF còn thiếu" button on the declarations page runs
-- scripts/backfill_declaration_pdfs.py via the shared _job_runner,
-- pre-rendering the print-standard PDF for each declaration .xls so the
-- merge endpoint (download.pdf) just concatenates cached PDFs.

alter table hub.background_jobs
    drop constraint if exists background_jobs_kind_check;

alter table hub.background_jobs
    add constraint background_jobs_kind_check
    check (kind in (
        'embedding_refresh',
        'substitute_refresh',
        'declaration_pdf_render',
        'other'
    ));
