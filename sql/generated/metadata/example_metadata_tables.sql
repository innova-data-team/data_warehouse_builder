-- =====================================================================
-- Data Warehouse Builder — metadata schema DDL (example/reference).
-- Run against `dw_metadata`.
-- =====================================================================

USE `dw_metadata`;

-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `batches` (
  `batch_id`       VARCHAR(64)  NOT NULL,
  `status`         VARCHAR(32)  NOT NULL DEFAULT 'uploaded',
  `current_stage`  VARCHAR(64)  NOT NULL DEFAULT 'uploaded',
  `created_by`     VARCHAR(128) NULL,
  `note`           TEXT NULL,
  `created_at`     DATETIME NOT NULL,
  `updated_at`     DATETIME NOT NULL,
  PRIMARY KEY (`batch_id`),
  KEY `ix_batches_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `uploaded_files` (
  `file_id`             VARCHAR(64)   NOT NULL,
  `batch_id`            VARCHAR(64)   NOT NULL,
  `original_file_name`  VARCHAR(512)  NOT NULL,
  `stored_file_path`    VARCHAR(1024) NOT NULL,
  `file_type`           VARCHAR(16)   NOT NULL,
  `file_size`           BIGINT        NOT NULL,
  `file_hash`           VARCHAR(64)   NOT NULL,
  `detected_encoding`   VARCHAR(32)   NULL,
  `detected_delimiter`  VARCHAR(8)    NULL,
  `sheet_count`         BIGINT        NULL,
  `row_count`           BIGINT        NULL,
  `column_count`        BIGINT        NULL,
  `status`              VARCHAR(32)   NOT NULL DEFAULT 'uploaded',
  `error_message`       TEXT          NULL,
  `upload_time`         DATETIME      NOT NULL,
  PRIMARY KEY (`file_id`),
  KEY `ix_uploaded_files_batch` (`batch_id`),
  KEY `ix_uploaded_files_hash`  (`file_hash`),
  CONSTRAINT `fk_uploaded_files_batch`
    FOREIGN KEY (`batch_id`) REFERENCES `batches`(`batch_id`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `bronze_tables` (
  `id`                BIGINT      NOT NULL AUTO_INCREMENT,
  `batch_id`          VARCHAR(64) NOT NULL,
  `file_id`           VARCHAR(64) NOT NULL,
  `table_name`        VARCHAR(128) NOT NULL,
  `source_file_name`  VARCHAR(512) NOT NULL,
  `source_sheet_name` VARCHAR(256) NULL,
  `row_count`         BIGINT NOT NULL DEFAULT 0,
  `column_count`      BIGINT NOT NULL DEFAULT 0,
  `failed_row_count`  BIGINT NOT NULL DEFAULT 0,
  `created_at`        DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_bronze_table_name` (`table_name`),
  KEY `ix_bronze_tables_batch` (`batch_id`),
  CONSTRAINT `fk_bronze_tables_batch` FOREIGN KEY (`batch_id`) REFERENCES `batches`(`batch_id`),
  CONSTRAINT `fk_bronze_tables_file`  FOREIGN KEY (`file_id`)  REFERENCES `uploaded_files`(`file_id`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `silver_tables` (
  `id`                  BIGINT      NOT NULL AUTO_INCREMENT,
  `batch_id`            VARCHAR(64) NOT NULL,
  `bronze_table_id`     BIGINT      NOT NULL,
  `table_name`          VARCHAR(128) NOT NULL,
  `row_count`           BIGINT NOT NULL DEFAULT 0,
  `column_count`        BIGINT NOT NULL DEFAULT 0,
  `dedup_removed_rows`  BIGINT NOT NULL DEFAULT 0,
  `quality_score`       DOUBLE NULL,
  `created_at`          DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_silver_table_name` (`table_name`),
  KEY `ix_silver_tables_batch` (`batch_id`),
  CONSTRAINT `fk_silver_tables_batch`  FOREIGN KEY (`batch_id`)        REFERENCES `batches`(`batch_id`),
  CONSTRAINT `fk_silver_tables_bronze` FOREIGN KEY (`bronze_table_id`) REFERENCES `bronze_tables`(`id`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `gold_tables` (
  `id`                     BIGINT      NOT NULL AUTO_INCREMENT,
  `batch_id`               VARCHAR(64) NOT NULL,
  `table_name`             VARCHAR(128) NOT NULL,
  `role`                   VARCHAR(16) NOT NULL,
  `source_silver_tables`   VARCHAR(2048) NOT NULL DEFAULT '',
  `row_count`              BIGINT NOT NULL DEFAULT 0,
  `column_count`           BIGINT NOT NULL DEFAULT 0,
  `quality_score`          DOUBLE NULL,
  `created_at`             DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_gold_table_name` (`table_name`),
  KEY `ix_gold_tables_batch` (`batch_id`),
  CONSTRAINT `fk_gold_tables_batch` FOREIGN KEY (`batch_id`) REFERENCES `batches`(`batch_id`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `table_profiles` (
  `id`                       BIGINT      NOT NULL AUTO_INCREMENT,
  `batch_id`                 VARCHAR(64) NOT NULL,
  `layer`                    VARCHAR(16) NOT NULL,
  `table_name`               VARCHAR(128) NOT NULL,
  `row_count`                BIGINT NOT NULL DEFAULT 0,
  `column_count`             BIGINT NOT NULL DEFAULT 0,
  `duplicate_row_count`      BIGINT NOT NULL DEFAULT 0,
  `empty_row_count`          BIGINT NOT NULL DEFAULT 0,
  `memory_bytes`             BIGINT NULL,
  `source_file`              VARCHAR(512) NULL,
  `source_sheet`             VARCHAR(256) NULL,
  `candidate_primary_keys`   TEXT NULL,
  `classification`           VARCHAR(32) NULL,
  `quality_score`            DOUBLE NULL,
  `created_at`               DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_table_profiles_batch` (`batch_id`),
  KEY `ix_table_profiles_table` (`table_name`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `column_profiles` (
  `id`                             BIGINT      NOT NULL AUTO_INCREMENT,
  `batch_id`                       VARCHAR(64) NOT NULL,
  `layer`                          VARCHAR(16) NOT NULL,
  `table_name`                     VARCHAR(128) NOT NULL,
  `column_name`                    VARCHAR(128) NOT NULL,
  `original_column_name`           VARCHAR(512) NULL,
  `physical_type`                  VARCHAR(32) NOT NULL,
  `semantic_type`                  VARCHAR(32) NOT NULL,
  `type_confidence`                DOUBLE NULL,
  `null_count`                     BIGINT NOT NULL DEFAULT 0,
  `null_percentage`                DOUBLE NOT NULL DEFAULT 0,
  `empty_string_count`             BIGINT NOT NULL DEFAULT 0,
  `unique_count`                   BIGINT NOT NULL DEFAULT 0,
  `uniqueness_ratio`               DOUBLE NOT NULL DEFAULT 0,
  `min_value`                      VARCHAR(512) NULL,
  `max_value`                      VARCHAR(512) NULL,
  `mean_value`                     DOUBLE NULL,
  `median_value`                   DOUBLE NULL,
  `stddev_value`                   DOUBLE NULL,
  `top_values_json`                TEXT NULL,
  `sample_values_json`             TEXT NULL,
  `invalid_value_count`            BIGINT NOT NULL DEFAULT 0,
  `arabic_text_percentage`         DOUBLE NOT NULL DEFAULT 0,
  `english_text_percentage`        DOUBLE NOT NULL DEFAULT 0,
  `numeric_text_percentage`        DOUBLE NOT NULL DEFAULT 0,
  `date_text_percentage`           DOUBLE NOT NULL DEFAULT 0,
  `percentage_text_percentage`     DOUBLE NOT NULL DEFAULT 0,
  `currency_text_percentage`       DOUBLE NOT NULL DEFAULT 0,
  `created_at`                     DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_column_profiles_batch` (`batch_id`),
  KEY `ix_column_profiles_table_col` (`table_name`, `column_name`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `quality_issues` (
  `id`                          BIGINT      NOT NULL AUTO_INCREMENT,
  `batch_id`                    VARCHAR(64) NOT NULL,
  `layer`                       VARCHAR(16) NOT NULL,
  `table_name`                  VARCHAR(128) NOT NULL,
  `column_name`                 VARCHAR(128) NULL,
  `issue_type`                  VARCHAR(64) NOT NULL,
  `severity`                    VARCHAR(16) NOT NULL,
  `issue_description`           TEXT NOT NULL,
  `affected_rows_count`         BIGINT NOT NULL DEFAULT 0,
  `affected_rows_percentage`    DOUBLE NOT NULL DEFAULT 0,
  `sample_values_json`          TEXT NULL,
  `suggested_fix`               TEXT NULL,
  `auto_fix_available`          TINYINT(1) NOT NULL DEFAULT 0,
  `auto_fix_applied`            TINYINT(1) NOT NULL DEFAULT 0,
  `created_at`                  DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_quality_issues_batch`    (`batch_id`),
  KEY `ix_quality_issues_severity` (`severity`),
  KEY `ix_quality_issues_table`    (`table_name`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `relationship_suggestions` (
  `id`                                BIGINT      NOT NULL AUTO_INCREMENT,
  `batch_id`                          VARCHAR(64) NOT NULL,
  `source_table`                      VARCHAR(128) NOT NULL,
  `source_column`                     VARCHAR(128) NOT NULL,
  `source_original_column`            VARCHAR(512) NULL,
  `target_table`                      VARCHAR(128) NOT NULL,
  `target_column`                     VARCHAR(128) NOT NULL,
  `target_original_column`            VARCHAR(512) NULL,
  `suggested_relation_type`           VARCHAR(16) NOT NULL,
  `confidence_score`                  DOUBLE NOT NULL,
  `column_name_similarity_score`      DOUBLE NOT NULL DEFAULT 0,
  `value_overlap_score`               DOUBLE NOT NULL DEFAULT 0,
  `data_type_compatibility_score`     DOUBLE NOT NULL DEFAULT 0,
  `cardinality_score`                 DOUBLE NOT NULL DEFAULT 0,
  `matching_values_count`             BIGINT NOT NULL DEFAULT 0,
  `source_distinct_count`             BIGINT NOT NULL DEFAULT 0,
  `target_distinct_count`             BIGINT NOT NULL DEFAULT 0,
  `source_null_percentage`            DOUBLE NOT NULL DEFAULT 0,
  `target_null_percentage`            DOUBLE NOT NULL DEFAULT 0,
  `risk_level`                        VARCHAR(16) NOT NULL DEFAULT 'none',
  `risk_reason`                       TEXT NULL,
  `recommendation`                    TEXT NULL,
  `status`                            VARCHAR(16) NOT NULL DEFAULT 'suggested',
  `created_at`                        DATETIME NOT NULL,
  `updated_at`                        DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_rel_sugg_batch`  (`batch_id`),
  KEY `ix_rel_sugg_status` (`status`),
  KEY `ix_rel_sugg_source` (`source_table`, `source_column`),
  KEY `ix_rel_sugg_target` (`target_table`, `target_column`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `approved_relationships` (
  `id`              BIGINT      NOT NULL AUTO_INCREMENT,
  `batch_id`        VARCHAR(64) NOT NULL,
  `suggestion_id`   BIGINT      NULL,
  `source_table`    VARCHAR(128) NOT NULL,
  `source_column`   VARCHAR(128) NOT NULL,
  `target_table`    VARCHAR(128) NOT NULL,
  `target_column`   VARCHAR(128) NOT NULL,
  `relation_type`   VARCHAR(16)  NOT NULL,
  `decided_by`      VARCHAR(128) NULL,
  `note`            TEXT NULL,
  `decided_at`      DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_approved_rel_batch`  (`batch_id`),
  KEY `ix_approved_rel_source` (`source_table`, `source_column`),
  KEY `ix_approved_rel_target` (`target_table`, `target_column`),
  CONSTRAINT `fk_approved_rel_suggestion`
    FOREIGN KEY (`suggestion_id`) REFERENCES `relationship_suggestions`(`id`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `export_jobs` (
  `id`              BIGINT      NOT NULL AUTO_INCREMENT,
  `batch_id`        VARCHAR(64) NOT NULL,
  `target`          VARCHAR(32) NOT NULL,
  `status`          VARCHAR(16) NOT NULL DEFAULT 'pending',
  `started_at`      DATETIME    NULL,
  `finished_at`     DATETIME    NULL,
  `artifacts_json`  TEXT NULL,
  `message`         TEXT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_export_jobs_batch`  (`batch_id`),
  KEY `ix_export_jobs_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
