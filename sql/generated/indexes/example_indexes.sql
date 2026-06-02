-- =====================================================================
-- Recommended indexes across all layers.
-- These are SUGGESTIONS — review with your DBA before applying in prod.
-- =====================================================================

-- ---- Bronze --------------------------------------------------------
-- Lineage lookups by batch + file are the hottest path.
CREATE INDEX `ix_bronze_patients_batch_file`
  ON `dw_bronze`.`bronze_patients_ar__patients` (`_batch_id`, `_source_file_id`);

-- ---- Silver --------------------------------------------------------
-- Speed up Silver→Gold joins and reporting filters.
CREATE INDEX `ix_silver_patients_patient_id`
  ON `dw_silver`.`silver_patients_ar__patients` (`patient_id`);
CREATE INDEX `ix_silver_patients_visit_date`
  ON `dw_silver`.`silver_patients_ar__patients` (`visit_date`);

-- ---- Gold ----------------------------------------------------------
-- Foreign-key columns and the most common filter columns.
CREATE INDEX `ix_gold_visits_batch`
  ON `dw_gold`.`gold_fact_visits` (`_batch_id`);
CREATE INDEX `ix_gold_visits_date`
  ON `dw_gold`.`gold_fact_visits` (`visit_date`);
CREATE INDEX `ix_gold_visits_patients_sk`
  ON `dw_gold`.`gold_fact_visits` (`patients_sk`);

-- A covering index for the KPI view:
CREATE INDEX `ix_gold_visits_kpi_cover`
  ON `dw_gold`.`gold_fact_visits` (`_batch_id`, `visit_date`, `total_amount`, `discount_pct`);
