-- ProductScout A2A 数据库建表脚本
CREATE DATABASE IF NOT EXISTS product_scout DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
USE product_scout;

-- 候选商品
CREATE TABLE IF NOT EXISTS candidate_products (
    id INT PRIMARY KEY AUTO_INCREMENT,
    product_id INT UNIQUE NOT NULL COMMENT '商品ID',
    product_name VARCHAR(255) NOT NULL COMMENT '商品名称',
    category VARCHAR(100) NOT NULL COMMENT '类目',
    price DECIMAL(10,2) NOT NULL COMMENT '售价',
    monthly_sales INT DEFAULT 0 COMMENT '月销量',
    rating DECIMAL(3,1) DEFAULT 0 COMMENT '评分',
    description TEXT COMMENT '商品描述',
    image_url VARCHAR(500) COMMENT '图片URL',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_category (category),
    INDEX idx_price (price)
) ENGINE=InnoDB COMMENT='候选商品';

-- 市场趋势
CREATE TABLE IF NOT EXISTS market_trends (
    id INT PRIMARY KEY AUTO_INCREMENT,
    category VARCHAR(100) NOT NULL COMMENT '类目',
    season VARCHAR(20) NOT NULL COMMENT '季节',
    keyword VARCHAR(100) COMMENT '关键词',
    trend_score DECIMAL(5,1) DEFAULT 0 COMMENT '趋势分',
    search_volume INT DEFAULT 0 COMMENT '搜索量',
    growth_rate DECIMAL(5,2) DEFAULT 0 COMMENT '增长率',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_category_season (category, season)
) ENGINE=InnoDB COMMENT='市场趋势';

-- 竞品商品
CREATE TABLE IF NOT EXISTS competitor_products (
    id INT PRIMARY KEY AUTO_INCREMENT,
    product_id INT NOT NULL COMMENT '关联候选商品ID',
    competitor_name VARCHAR(255) NOT NULL COMMENT '竞品名称',
    competitor_price DECIMAL(10,2) NOT NULL COMMENT '竞品价格',
    competitor_sales INT DEFAULT 0 COMMENT '竞品月销量',
    competitor_rating DECIMAL(3,1) DEFAULT 0 COMMENT '竞品评分',
    platform VARCHAR(50) DEFAULT 'unknown' COMMENT '平台',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_product_id (product_id)
) ENGINE=InnoDB COMMENT='竞品商品';

-- 商品评论
CREATE TABLE IF NOT EXISTS product_reviews (
    id INT PRIMARY KEY AUTO_INCREMENT,
    review_id VARCHAR(100) UNIQUE NOT NULL COMMENT '评论ID',
    product_id INT NOT NULL COMMENT '商品ID',
    category VARCHAR(100) COMMENT '类目',
    rating DECIMAL(3,1) NOT NULL COMMENT '评分',
    sentiment VARCHAR(20) DEFAULT 'neutral' COMMENT '情感: positive/negative/neutral',
    review_text TEXT NOT NULL COMMENT '评论内容',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_product_id (product_id),
    INDEX idx_category (category),
    INDEX idx_sentiment (sentiment)
) ENGINE=InnoDB COMMENT='商品评论';

-- 商品资料
CREATE TABLE IF NOT EXISTS product_documents (
    id INT PRIMARY KEY AUTO_INCREMENT,
    doc_id VARCHAR(100) UNIQUE NOT NULL COMMENT '资料ID',
    product_id INT NOT NULL COMMENT '商品ID',
    category VARCHAR(100) COMMENT '类目',
    title VARCHAR(255) NOT NULL COMMENT '标题',
    description TEXT COMMENT '描述',
    feature_text TEXT COMMENT '特征文本',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_product_id (product_id),
    INDEX idx_category (category)
) ENGINE=InnoDB COMMENT='商品资料';

-- 供应商
CREATE TABLE IF NOT EXISTS suppliers (
    id INT PRIMARY KEY AUTO_INCREMENT,
    product_id INT NOT NULL COMMENT '商品ID',
    supplier_name VARCHAR(255) NOT NULL COMMENT '供应商名称',
    contact VARCHAR(100) COMMENT '联系方式',
    lead_time_days INT DEFAULT 7 COMMENT '交期天数',
    moq INT DEFAULT 100 COMMENT '最小起订量',
    reliability_score DECIMAL(5,1) DEFAULT 80 COMMENT '可靠度评分',
    location VARCHAR(100) COMMENT '所在地',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_product_id (product_id)
) ENGINE=InnoDB COMMENT='供应商';

-- 商品成本
CREATE TABLE IF NOT EXISTS product_costs (
    id INT PRIMARY KEY AUTO_INCREMENT,
    product_id INT NOT NULL COMMENT '商品ID',
    purchase_cost DECIMAL(10,2) NOT NULL COMMENT '采购成本',
    platform_fee_rate DECIMAL(5,2) DEFAULT 5.00 COMMENT '平台扣点(%)',
    shipping_cost DECIMAL(10,2) DEFAULT 0 COMMENT '物流成本',
    ad_cost_rate DECIMAL(5,2) DEFAULT 3.00 COMMENT '广告成本率(%)',
    other_cost DECIMAL(10,2) DEFAULT 0 COMMENT '其他成本',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE INDEX idx_product_id (product_id)
) ENGINE=InnoDB COMMENT='商品成本';

-- 风险规则
CREATE TABLE IF NOT EXISTS risk_rules (
    id INT PRIMARY KEY AUTO_INCREMENT,
    category VARCHAR(100) COMMENT '类目',
    rule_type VARCHAR(50) NOT NULL COMMENT '规则类型: compliance/ip/safety/return',
    risk_level VARCHAR(20) DEFAULT 'medium' COMMENT '风险等级: low/medium/high',
    description TEXT NOT NULL COMMENT '风险描述',
    is_active TINYINT(1) DEFAULT 1 COMMENT '是否启用',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_category (category),
    INDEX idx_rule_type (rule_type)
) ENGINE=InnoDB COMMENT='风险规则';

-- 选品报告
CREATE TABLE IF NOT EXISTS selection_reports (
    id INT PRIMARY KEY AUTO_INCREMENT,
    request_id VARCHAR(100) UNIQUE NOT NULL COMMENT '请求ID',
    user_query TEXT NOT NULL COMMENT '用户需求',
    constraints_json TEXT COMMENT '约束条件JSON',
    products_json TEXT COMMENT '分析结果JSON',
    final_report TEXT COMMENT '最终报告',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB COMMENT='选品报告';

-- Agent 调用日志
CREATE TABLE IF NOT EXISTS agent_call_logs (
    id INT PRIMARY KEY AUTO_INCREMENT,
    request_id VARCHAR(100) NOT NULL COMMENT '请求ID',
    agent_name VARCHAR(50) NOT NULL COMMENT 'Agent名称',
    product_id INT COMMENT '商品ID',
    status VARCHAR(20) NOT NULL COMMENT '状态: success/failed/partial',
    input_json TEXT COMMENT '输入JSON',
    output_json TEXT COMMENT '输出JSON',
    duration_ms INT COMMENT '耗时毫秒',
    error_message TEXT COMMENT '错误信息',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_request_id (request_id),
    INDEX idx_agent_name (agent_name)
) ENGINE=InnoDB COMMENT='Agent调用日志';

-- 会话表
CREATE TABLE IF NOT EXISTS chat_sessions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    session_id VARCHAR(64) UNIQUE NOT NULL COMMENT '会话ID (前端 UUID v4)',
    title VARCHAR(200) DEFAULT '新对话' COMMENT '会话标题',
    status VARCHAR(20) DEFAULT 'active' COMMENT 'active/archived',
    message_count INT DEFAULT 0 COMMENT '消息数',
    context_json TEXT COMMENT '当前上下文: 槽位积累/意图/追问轮数',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB COMMENT='会话表';

-- 消息表
CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    session_id VARCHAR(64) NOT NULL COMMENT '会话ID',
    role VARCHAR(20) NOT NULL COMMENT 'user/assistant/system',
    content TEXT NOT NULL COMMENT '消息内容',
    message_type VARCHAR(30) DEFAULT 'text' COMMENT 'text/options/slot_prompt/product_card/report_card',
    metadata TEXT COMMENT '附加数据: 产品ID/槽位信息等',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_session (session_id)
) ENGINE=InnoDB COMMENT='消息表';
