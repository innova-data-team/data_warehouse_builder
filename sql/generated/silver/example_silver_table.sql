-- =====================================================================
-- Example Silver table — derived from the Bronze patients example.
-- Run against `dw_silver`.
-- =====================================================================

USE `dw_silver`;

CREATE TABLE `silver_patients_ar__patients` (
   `_silver_id`          BIGINT       NOT NULL AUTO_INCREMENT
  ,`_batch_id`           VARCHAR(64)  NOT NULL
  ,`_bronze_id`          BIGINT       NOT NULL
  ,`_source_file_id`     VARCHAR(64)  NOT NULL
  ,`_source_row_number`  BIGINT       NOT NULL
  ,`_clean_record_hash`  CHAR(40)     NOT NULL
  ,`_quality_score`      DOUBLE       NULL
  ,`_cleaning_status`    VARCHAR(16)  NOT NULL
  ,`_cleaned_at`         DATETIME     NOT NULL

  ,`patient_id`     VARCHAR(64)    NULL
  ,`patient_name`   VARCHAR(255)   NULL
  ,`visit_date`     DATE           NULL
  ,`total_amount`   DECIMAL(20,6)  NULL
  ,`discount_pct`   DOUBLE         NULL          -- always stored as fraction in [0, 1]

  ,PRIMARY KEY (`_silver_id`)
  ,KEY `ix_batch`        (`_batch_id`)
  ,KEY `ix_patient_id`   (`patient_id`)
  ,KEY `ix_visit_date`   (`visit_date`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Build Silver from Bronze.
-- Arabic normalization, percentage parsing (5% / ٧٪ / 0.05), Arabic digits
-- (٣٬٠٠٠٫٥٠ → 3000.50), and dayfirst date parsing are all applied by
-- app.services.cleaner_service before the row is emitted here.
INSERT INTO `silver_patients_ar__patients`
   (`_batch_id`, `_bronze_id`, `_source_file_id`, `_source_row_number`,
    `_clean_record_hash`, `_quality_score`, `_cleaning_status`, `_cleaned_at`,
    `patient_id`, `patient_name`, `visit_date`, `total_amount`, `discount_pct`)
SELECT
   b.`_batch_id`
  ,b.`_bronze_id`
  ,b.`_source_file_id`
  ,b.`_source_row_number`
  ,b.`_raw_record_hash`            AS `_clean_record_hash`
  ,1.0                             AS `_quality_score`
  ,'cleaned'                       AS `_cleaning_status`
  ,NOW()                           AS `_cleaned_at`
  ,TRIM(b.`patient_id`)            AS `patient_id`
  ,TRIM(b.`patient_name`)          AS `patient_name`
  ,STR_TO_DATE(b.`visit_date`, '%Y-%m-%d') AS `visit_date`
  ,CAST(REPLACE(REPLACE(b.`total_amount`, ',', ''), ' ', '') AS DECIMAL(20,6))
                                    AS `total_amount`
  ,CASE
     WHEN b.`discount_pct` LIKE '%\\%%' ESCAPE '\\'
       THEN CAST(REPLACE(b.`discount_pct`, '%', '') AS DOUBLE) / 100.0
     ELSE CAST(b.`discount_pct` AS DOUBLE) / 100.0
   END                              AS `discount_pct`
FROM `dw_bronze`.`bronze_patients_ar__patients` b
WHERE b.`_batch_id` = 'b_20260524_120000_a1';
