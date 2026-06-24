-- 创建数据库
CREATE DATABASE IF NOT EXISTS `diet_delushan`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `diet_delushan`;

-- 创建用户表
CREATE TABLE IF NOT EXISTS `users` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `username` VARCHAR(50) NOT NULL COMMENT '用户名',
  `email` VARCHAR(100) NOT NULL COMMENT '邮箱',
  `password_hash` VARCHAR(255) NOT NULL COMMENT '密码哈希值',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_users_username` (`username`),
  UNIQUE KEY `uk_users_email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统用户表';

-- 创建用户长期画像与体检报告缓存表
CREATE TABLE IF NOT EXISTS `user_profiles` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_id` INT NOT NULL COMMENT '用户ID',
  `goal` VARCHAR(80) NOT NULL DEFAULT '' COMMENT '长期饮食目标',
  `allergy_json` TEXT NOT NULL COMMENT '过敏信息JSON',
  `taboo_json` TEXT NOT NULL COMMENT '忌口信息JSON',
  `health_concerns_json` TEXT NOT NULL COMMENT '健康关注点JSON',
  `medical_report_text` LONGTEXT NULL COMMENT '用户体检报告Markdown文本',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_profiles_user_id` (`user_id`),
  CONSTRAINT `fk_user_profiles_user_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户长期画像表';

-- 创建聊天会话表
CREATE TABLE IF NOT EXISTS `chat_sessions` (
  `id` VARCHAR(64) NOT NULL COMMENT '会话ID',
  `user_id` INT NOT NULL COMMENT '用户ID',
  `title` VARCHAR(80) NOT NULL DEFAULT '新的饮食计划' COMMENT '会话标题',
  `workflow_state_json` LONGTEXT NOT NULL COMMENT '工作流状态JSON',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_chat_sessions_user_id` (`user_id`),
  KEY `idx_chat_sessions_updated_at` (`updated_at`),
  KEY `idx_chat_sessions_user_updated` (`user_id`, `updated_at`),
  CONSTRAINT `fk_chat_sessions_user_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='聊天会话表';

-- 创建聊天消息表
CREATE TABLE IF NOT EXISTS `chat_messages` (
  `id` VARCHAR(64) NOT NULL COMMENT '消息ID',
  `session_id` VARCHAR(64) NOT NULL COMMENT '会话ID',
  `user_id` INT NOT NULL COMMENT '用户ID',
  `role` VARCHAR(16) NOT NULL COMMENT '消息角色',
  `content` LONGTEXT NOT NULL COMMENT '消息内容',
  `thinking_content` LONGTEXT NOT NULL COMMENT '思考内容',
  `suggested_questions_json` TEXT NOT NULL COMMENT '推荐追问JSON',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_chat_messages_session_id` (`session_id`),
  KEY `idx_chat_messages_user_id` (`user_id`),
  KEY `idx_chat_messages_created_at` (`created_at`),
  KEY `idx_chat_messages_session_created` (`session_id`, `created_at`),
  CONSTRAINT `fk_chat_messages_session_id` FOREIGN KEY (`session_id`) REFERENCES `chat_sessions` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_chat_messages_user_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='聊天消息表';

-- 创建用餐记录表
CREATE TABLE IF NOT EXISTS `meal_records` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_id` INT NULL COMMENT '用户ID',
  `session_id` VARCHAR(64) NOT NULL COMMENT '来源会话ID',
  `recorded_at` DATETIME NOT NULL COMMENT '用餐时间',
  `meal_type` VARCHAR(32) NOT NULL COMMENT '餐次',
  `foods_json` LONGTEXT NULL COMMENT '识别食物JSON',
  `estimated_calories_kcal` INT NULL COMMENT '估算热量',
  `estimated_protein_g` FLOAT NULL COMMENT '估算蛋白质',
  `estimated_carbohydrate_g` FLOAT NULL COMMENT '估算碳水',
  `estimated_fat_g` FLOAT NULL COMMENT '估算脂肪',
  `user_feedback` VARCHAR(64) NULL COMMENT '用户反馈',
  `analysis_markdown` LONGTEXT NOT NULL COMMENT '分析正文',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_meal_records_user_id` (`user_id`),
  KEY `idx_meal_records_session_id` (`session_id`),
  KEY `idx_meal_records_recorded_at` (`recorded_at`),
  CONSTRAINT `fk_meal_records_user_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用餐记录表';

