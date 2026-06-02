-- =====================================================================
-- Example Gold star schema — fact + dimension + index suggestions.
-- Run against `dw_gold`.
-- =====================================================================

USE `dw_gold`;

-- ---------------------------------------------------------------------
-- Dimension: patients
-- ---------------------------------------------------------------------
CREATE TABLE `gold_dim_patients` (
   `patients_sk`            BIGINT       NOT NULL AUTO_INCREMENT
  ,`_gold_id`               BIGINT       NOT NULL
  ,`_batch_id`              VARCHAR(64)  NOT NULL
  ,`_source_silver_tables`  VARCHAR(512) NOT NULL
  ,`_gold_created_at`       DATETIME     NOT NULL
  ,`_gold_quality_score`    DOUBLE       NULL

  ,`patient_id`     VARCHAR(64)    NULL
  ,`patient_name`   VARCHAR(255)   NULL

  ,PRIMARY KEY (`patients_sk`)
  ,KEY `ix_patient_id` (`patient_id`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

INSERT INTO `gold_dim_patients`
  (`_gold_id`, `_batch_id`, `_source_silver_tables`,
   `_gold_created_at`, `_gold_quality_score`,
   `patient_id`, `patient_name`)
SELECT
   ROW_NUMBER() OVER (ORDER BY MIN(s.`_silver_id`))
  ,'b_20260524_120000_a1'
  ,'silver_patients_ar__patients'
  ,NOW()
  ,AVG(s.`_quality_score`)
  ,s.`patient_id`
  ,MAX(s.`patient_name`)
FROM `dw_silver`.`silver_patients_ar__patients` s
WHERE s.`_batch_id` = 'b_20260524_120000_a1'
GROUP BY s.`patient_id`;

-- ---------------------------------------------------------------------
-- Fact: visits (one Silver visits table assumed)
-- ---------------------------------------------------------------------
CREATE TABLE `gold_fact_visits` (
   `_gold_id`               BIGINT       NOT NULL AUTO_INCREMENT
  ,`_batch_id`              VARCHAR(64)  NOT NULL
  ,`_source_silver_tables`  VARCHAR(512) NOT NULL
  ,`_gold_created_at`       DATETIME     NOT NULL
  ,`_gold_quality_score`    DOUBLE       NULL

  ,`visit_date`    DATE           NULL
  ,`total_amount`  DECIMAL(20,6)  NULL
  ,`discount_pct`  DOUBLE         NULL
  ,`patients_sk`   BIGINT         NULL

  ,PRIMARY KEY (`_gold_id`)
  ,KEY `ix_visit_date`   (`visit_date`)
  ,KEY `ix_patients_sk`  (`patients_sk`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

INSERT INTO `gold_fact_visits`
  (`_batch_id`, `_source_silver_tables`, `_gold_created_at`, `_gold_quality_score`,
   `visit_date`, `total_amount`, `discount_pct`, `patients_sk`)
SELECT
   'b_20260524_120000_a1'
  ,'silver_patients_ar__patients'
  ,NOW()
  ,s.`_quality_score`
  ,s.`visit_date`
  ,s.`total_amount`
  ,s.`discount_pct`
  ,d.`patients_sk`
FROM `dw_silver`.`silver_patients_ar__patients` s
LEFT JOIN `dw_gold`.`gold_dim_patients` d
  ON d.`patient_id` = s.`patient_id`
WHERE s.`_batch_id` = 'b_20260524_120000_a1';

-- ---------------------------------------------------------------------
-- Suggested foreign-key (kept commented; enforce only after data review):
-- ---------------------------------------------------------------------
-- ALTER TABLE `gold_fact_visits`
--   ADD CONSTRAINT `fk_visits_patients`
--   FOREIGN KEY (`patients_sk`) REFERENCES `gold_dim_patients`(`patients_sk`);
