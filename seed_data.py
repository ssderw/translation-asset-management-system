"""Generate test data for Translation Asset Management System."""
import sys
sys.path.insert(0, '.')
from db import execute, execute_transaction, query_all, query_one

# --- Tags ---
TAGS = ['游戏', '金融', '医疗', '法律', '电商', '技术', '文学', '影视']

print("Creating tags...")
for tag in TAGS:
    execute("INSERT IGNORE INTO tags (name) VALUES (%s)", (tag,))

# fetch tag ids
tag_map = {t['name']: t['id'] for t in query_all("SELECT * FROM tags")}
print(f"  {len(tag_map)} tags ready")

# --- Fixed Expressions ---
EXPRESSIONS = [
    # 游戏
    ('角色', 'Character', '游戏', ''),
    ('技能', 'Skill', '游戏', ''),
    ('等级', 'Level', '游戏', ''),
    ('攻击力', 'Attack', '游戏', ''),
    ('防御力', 'Defense', '游戏', ''),
    ('暴击率', 'Critical Hit Rate', '游戏', ''),
    ('生命值', 'HP (Health Points)', '游戏', ''),
    ('魔法值', 'MP (Mana Points)', '游戏', ''),
    ('经验值', 'EXP (Experience)', '游戏', ''),
    ('任务', 'Quest', '游戏', ''),
    ('装备', 'Equipment', '游戏', ''),
    ('道具', 'Item', '游戏', ''),
    ('金币', 'Gold Coin', '游戏', '通用游戏术语'),
    ('新手教程', 'Tutorial', '游戏', '首次游玩引导'),
    # 金融
    ('交易', 'Transaction', '金融', ''),
    ('账户余额', 'Account Balance', '金融', ''),
    ('利率', 'Interest Rate', '金融', ''),
    ('贷款', 'Loan', '金融', ''),
    ('存款', 'Deposit', '金融', ''),
    ('理财', 'Wealth Management', '金融', ''),
    ('风险评估', 'Risk Assessment', '金融', ''),
    ('信用评分', 'Credit Score', '金融', ''),
    ('跨境支付', 'Cross-border Payment', '金融', ''),
    ('年化收益率', 'Annualized Rate of Return', '金融', ''),
    # 医疗
    ('诊断', 'Diagnosis', '医疗', ''),
    ('处方', 'Prescription', '医疗', ''),
    ('病历', 'Medical Record', '医疗', ''),
    ('门诊', 'Outpatient', '医疗', ''),
    ('住院', 'Inpatient', '医疗', ''),
    ('手术', 'Surgery', '医疗', ''),
    ('过敏史', 'Allergy History', '医疗', ''),
    ('疫苗接种', 'Vaccination', '医疗', ''),
    ('血压', 'Blood Pressure', '医疗', ''),
    ('血糖', 'Blood Glucose', '医疗', ''),
    # 法律
    ('甲方', 'Party A', '法律', ''),
    ('乙方', 'Party B', '法律', ''),
    ('违约责任', 'Liability for Breach of Contract', '法律', ''),
    ('知识产权', 'Intellectual Property', '法律', ''),
    ('保密协议', 'NDA (Non-Disclosure Agreement)', '法律', ''),
    ('仲裁', 'Arbitration', '法律', ''),
    ('不可抗力', 'Force Majeure', '法律', ''),
    ('合同生效', 'Contract Effective Date', '法律', ''),
    ('管辖法院', 'Court of Jurisdiction', '法律', ''),
    ('赔偿', 'Indemnification', '法律', ''),
    # 电商
    ('商品', 'Product', '电商', ''),
    ('购物车', 'Shopping Cart', '电商', ''),
    ('订单', 'Order', '电商', ''),
    ('退款', 'Refund', '电商', ''),
    ('优惠券', 'Coupon', '电商', ''),
    ('包邮', 'Free Shipping', '电商', ''),
    ('好评率', 'Positive Review Rate', '电商', ''),
    ('秒杀', 'Flash Sale', '电商', ''),
    ('库存', 'Inventory', '电商', ''),
    ('商品规格', 'Product Specs', '电商', ''),
    # 技术
    ('登录', 'Login', '技术', ''),
    ('注册', 'Register', '技术', ''),
    ('设置', 'Settings', '技术', ''),
    ('保存', 'Save', '技术', ''),
    ('取消', 'Cancel', '技术', ''),
    ('删除', 'Delete', '技术', ''),
    ('确认', 'Confirm', '技术', ''),
    ('提交', 'Submit', '技术', ''),
    ('用户名', 'Username', '技术', ''),
    ('密码', 'Password', '技术', ''),
    ('数据库', 'Database', '技术', ''),
    ('接口', 'API', '技术', '通用技术术语'),
    ('前端', 'Frontend', '技术', ''),
    ('后端', 'Backend', '技术', ''),
    ('部署', 'Deploy', '技术', ''),
]

print("Creating fixed expressions...")
expr_stmts = []
for chinese, english, domain, notes in EXPRESSIONS:
    expr_stmts.append((
        "INSERT IGNORE INTO fixed_expressions (chinese, english, domain, notes) VALUES (%s,%s,%s,%s)",
        (chinese, english, domain, notes)
    ))
execute_transaction(expr_stmts)
print(f"  {len(expr_stmts)} expressions inserted")

# --- Associate expressions with tags ---
print("Linking expressions to tags...")
expressions = query_all("SELECT * FROM fixed_expressions")
tag_links = []
for expr in expressions:
    domain = expr['domain']
    if domain and domain in tag_map:
        tag_links.append((
            "INSERT IGNORE INTO expression_tags (expression_id, tag_id) VALUES (%s,%s)",
            (expr['id'], tag_map[domain])
        ))
if tag_links:
    execute_transaction(tag_links)
print(f"  {len(tag_links)} tag associations created")

# --- Templates ---
TEMPLATES = [
    ('游戏本地化翻译模板', '游戏',
     '请将以下游戏文本翻译为英文，注意保留变量占位符（如 {0}, {1}）和 HTML 标签。\n\n原文：\n{source}\n\n要求：\n1. 保持游戏术语一致性\n2. 保留原文格式和变量\n3. 注意上下文语境',
     '适用于游戏UI/对话翻译'),
    ('法律合同翻译模板', '法律',
     '请将以下合同条款翻译为英文，保持法律文书的正式语气。\n\n原文：\n{source}\n\n要求：\n1. 使用正式法律英语\n2. 术语统一\n3. 保留条款编号',
     '适用于合同条款翻译'),
    ('金融报告翻译模板', '金融',
     '请将以下金融内容翻译为英文，确保数字和百分比准确无误。\n\n原文：\n{source}',
     '适用于财务报表/报告翻译'),
    ('通用翻译模板', '',
     '请将以下内容翻译为英文，保持原文风格。\n\n原文：\n{source}',
     '默认通用翻译模板'),
    ('电商产品翻译模板', '电商',
     '请将以下产品信息翻译为英文，突出卖点，语言生动。\n\n原文：\n{source}\n\n要求：\n1. 突出产品优势\n2. 符合目标市场习惯\n3. 保留尺寸/规格信息',
     '适用于电商产品页面翻译'),
    ('医疗病历翻译模板', '医疗',
     '请将以下病历内容翻译为英文，务必准确翻译医学术语。\n\n原文：\n{source}\n\n要求：\n1. 使用标准医学术语\n2. 药物名称保持原样\n3. 数值准确无误',
     '适用于医疗文档翻译'),
]

print("Creating templates...")
tpl_stmts = []
for name, domain, content, notes in TEMPLATES:
    tpl_stmts.append((
        "INSERT INTO templates (name, domain, content, notes) VALUES (%s,%s,%s,%s)",
        (name, domain, content, notes)
    ))
execute_transaction(tpl_stmts)
print(f"  {len(tpl_stmts)} templates inserted")

# --- Associate templates with tags ---
print("Linking templates to tags...")
templates = query_all("SELECT * FROM templates")
tpl_tag_links = []
for tpl in templates:
    domain = tpl['domain']
    if domain and domain in tag_map:
        tpl_tag_links.append((
            "INSERT IGNORE INTO template_tags (template_id, tag_id) VALUES (%s,%s)",
            (tpl['id'], tag_map[domain])
        ))
if tpl_tag_links:
    execute_transaction(tpl_tag_links)
print(f"  {len(tpl_tag_links)} template tag associations created")

print("\n=== Test data generation complete ===")
print(f"Tags:        {len(TAGS)}")
print(f"Expressions: {len(EXPRESSIONS)}")
print(f"Templates:   {len(TEMPLATES)}")
print("Login: admin / admin123")
