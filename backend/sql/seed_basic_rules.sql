USE product_scout;

-- 风险规则种子数据
INSERT INTO risk_rules (category, rule_type, risk_level, description) VALUES
('家居小电器', 'safety', 'high', '小电器类商品需通过 CCC 强制认证，注意安全标准'),
('家居小电器', 'ip', 'medium', '外观设计可能涉及专利侵权，需核查'),
('家居小电器', 'return', 'medium', '电器类退货率较高，需预留售后成本'),
('厨房用品', 'safety', 'high', '食品接触材料需符合 GB 4806 标准'),
('厨房用品', 'compliance', 'medium', '出口需符合 FDA / LFGB 等认证'),
('厨房用品', 'return', 'low', '厨房用品退货率相对较低'),
('宠物用品', 'safety', 'medium', '宠物食品需取得饲料生产许可证'),
('宠物用品', 'compliance', 'medium', '宠物用品出口需符合 ASTM 标准'),
('宠物用品', 'return', 'low', '宠物用品退货率低，但差评影响大'),
('美妆个护', 'safety', 'high', '化妆品需备案或注册，成分需合规'),
('美妆个护', 'compliance', 'high', '化妆品广告法限制严格，禁用绝对化用语'),
('美妆个护', 'return', 'medium', '美妆个护退货率中等，肤感差异大'),
('运动户外', 'safety', 'medium', '运动器材需关注承重和安全测试'),
('运动户外', 'ip', 'low', '运动户外类目侵权风险相对较低'),
('运动户外', 'return', 'medium', '尺码和舒适度差异导致退货'),
('家居小电器', 'compliance', 'medium', '能效标签要求，部分产品需 3C 认证'),
('厨房用品', 'ip', 'low', '厨房用具专利纠纷较少'),
('宠物用品', 'ip', 'low', '宠物用品设计专利风险低'),
('美妆个护', 'ip', 'medium', '包装设计和品牌名称需注意商标'),
('运动户外', 'compliance', 'low', '一般无特殊合规要求');
