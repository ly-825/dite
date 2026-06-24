CREATE TABLE IF NOT EXISTS `meal_records` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `session_id` VARCHAR(64) NOT NULL,
  `recorded_at` DATETIME NOT NULL,
  `meal_type` VARCHAR(32) NOT NULL,
  `analysis_markdown` LONGTEXT NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_meal_records_session_id` (`session_id`),
  KEY `idx_meal_records_recorded_at` (`recorded_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
