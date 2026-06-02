-- =====================================================================
-- Example Gold analytical & KPI views.  Run against `dw_gold`.
-- =====================================================================

USE `dw_gold`;

-- ---------------------------------------------------------------------
-- Flat view: every fact row joined with its dimension descriptors.
-- Convenient for Power BI Import mode and ZakaaDash.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW `gold_v_visits_flat` AS
SELECT
   f.`_gold_id`               AS visit_id
  ,f.`_batch_id`              AS batch_id
  ,f.`visit_date`             AS visit_date
  ,YEAR(f.`visit_date`)       AS visit_year
  ,QUARTER(f.`visit_date`)    AS visit_quarter
  ,MONTH(f.`visit_date`)      AS visit_month
  ,f.`total_amount`           AS total_amount
  ,f.`discount_pct`           AS discount_pct
  ,(f.`total_amount` * (1 - COALESCE(f.`discount_pct`, 0))) AS net_amount
  ,d.`patient_id`             AS patient_id
  ,d.`patient_name`           AS patient_name
FROM `dw_gold`.`gold_fact_visits` f
LEFT JOIN `dw_gold`.`gold_dim_patients` d
  ON d.`patients_sk` = f.`patients_sk`;

-- ---------------------------------------------------------------------
-- KPI view: pre-aggregated for dashboard cards.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW `gold_v_kpi_summary` AS
SELECT
   `_batch_id`                                AS batch_id
  ,COUNT(*)                                   AS visit_count
  ,COUNT(DISTINCT `patients_sk`)              AS distinct_patients
  ,SUM(`total_amount`)                        AS total_revenue
  ,AVG(`total_amount`)                        AS avg_revenue_per_visit
  ,SUM(`total_amount` * (1 - COALESCE(`discount_pct`, 0))) AS net_revenue
FROM `dw_gold`.`gold_fact_visits`
GROUP BY `_batch_id`;

-- ---------------------------------------------------------------------
-- Business-area view: monthly trend.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW `gold_v_visits_monthly_trend` AS
SELECT
   DATE_FORMAT(`visit_date`, '%Y-%m-01') AS month_start
  ,COUNT(*)                              AS visit_count
  ,SUM(`total_amount`)                   AS total_revenue
FROM `dw_gold`.`gold_fact_visits`
WHERE `visit_date` IS NOT NULL
GROUP BY DATE_FORMAT(`visit_date`, '%Y-%m-01')
ORDER BY month_start;
