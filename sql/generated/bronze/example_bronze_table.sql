-- =====================================================================
-- Example Bronze table — generated for source file: "patients_ar.xlsx",
-- sheet "المرضى" (patients).  Run against `dw_bronze`.
-- =====================================================================

USE `dw_bronze`;

CREATE TABLE `bronze_patients_ar__patients` (
   `_bronze_id`           BIGINT       NOT NULL AUTO_INCREMENT
  ,`_batch_id`            VARCHAR(64)  NOT NULL
  ,`_source_file_id`      VARCHAR(64)  NOT NULL
  ,`_source_file_name`    VARCHAR(512) NOT NULL
  ,`_source_sheet_name`   VARCHAR(256) NULL
  ,`_source_row_number`   BIGINT       NOT NULL
  ,`_raw_record_hash`     CHAR(40)     NOT NULL
  ,`_ingested_at`         DATETIME     NOT NULL

  -- Original column names (preserved in column_profiles.original_column_name):
  --   "رقم المريض"        => patient_id
  --   "اسم المريض"        => patient_name
  --   "تاريخ الزيارة"     => visit_date
  --   "إجمالي الفاتورة"   => total_amount
  --   "نسبة الخصم %"      => discount_pct
  ,`patient_id`     LONGTEXT NULL
  ,`patient_name`   LONGTEXT NULL
  ,`visit_date`     LONGTEXT NULL
  ,`total_amount`   LONGTEXT NULL
  ,`discount_pct`   LONGTEXT NULL

  ,PRIMARY KEY (`_bronze_id`)
  ,KEY `ix_batch` (`_batch_id`)
  ,KEY `ix_hash`  (`_raw_record_hash`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Example INSERT — every column lands as raw TEXT to prevent data loss.
INSERT INTO `bronze_patients_ar__patients`
  (`_batch_id`, `_source_file_id`, `_source_file_name`, `_source_sheet_name`,
   `_source_row_number`, `_raw_record_hash`, `_ingested_at`,
   `patient_id`, `patient_name`, `visit_date`, `total_amount`, `discount_pct`)
VALUES
  ('b_20260524_120000_a1', 'f_aaa111', 'patients_ar.xlsx', 'المرضى',
   1, '5f4dcc3b5aa765d61d8327deb882cf99', '2026-05-24 12:00:00',
   'P-0001', 'محمد عبدالله',  '2026-04-15',  '1,250.00',  '5%'),
  ('b_20260524_120000_a1', 'f_aaa111', 'patients_ar.xlsx', 'المرضى',
   2, 'c4ca4238a0b923820dcc509a6f75849b', '2026-05-24 12:00:00',
   'P-0002', 'Sarah Hamdan',  '15/04/2026', '٣٬٠٠٠٫٥٠',  '٧٪');
