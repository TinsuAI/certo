-- 065 — add `human_label` to bom_artifacts.
--
-- Free-text label dùng để CO dossier UI hiển thị "BOM nào là BOM nào"
-- (e.g. "Mẫu 16/2025", "BOM kỹ thuật SAP"). Nullable; UI fallback về
-- auto-generated `display_label` khi không set.
--
-- Idempotent qua `if not exists`.

alter table hub.bom_artifacts add column if not exists human_label text;
