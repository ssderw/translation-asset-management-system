import pymysql
import bcrypt
from datetime import datetime
from contextlib import contextmanager
import json

DB_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'charset': 'utf8mb4',
    'autocommit': False,
}

DB_NAME = 'translation_assets'


def init_db():
    conn = pymysql.connect(**{k: v for k, v in DB_CONFIG.items() if k != 'database'})
    try:
        with conn.cursor() as cur:
            cur.execute("SET time_zone = '+08:00'")
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        conn.commit()
    finally:
        conn.close()

    cfg = dict(DB_CONFIG, database=DB_NAME)
    conn = pymysql.connect(**cfg)
    try:
        with conn.cursor() as cur:
            cur.execute("SET time_zone = '+08:00'")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(50) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(100) NOT NULL UNIQUE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS fixed_expressions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    chinese VARCHAR(1000) NOT NULL,
                    english VARCHAR(1000) NOT NULL,
                    domain VARCHAR(200) DEFAULT '',
                    notes TEXT,
                    usage_count INT DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    updated_by VARCHAR(50) DEFAULT '',
                    updated_ip VARCHAR(45) DEFAULT ''
                ) ENGINE=InnoDB
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS expression_tags (
                    expression_id INT NOT NULL,
                    tag_id INT NOT NULL,
                    PRIMARY KEY (expression_id, tag_id),
                    FOREIGN KEY (expression_id) REFERENCES fixed_expressions(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
                ) ENGINE=InnoDB
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS templates (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    content LONGTEXT,
                    domain VARCHAR(200) DEFAULT '',
                    notes TEXT,
                    usage_count INT DEFAULT 0,
                    filename VARCHAR(255) DEFAULT '',
                    file_path VARCHAR(500) DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    updated_by VARCHAR(50) DEFAULT '',
                    updated_ip VARCHAR(45) DEFAULT ''
                ) ENGINE=InnoDB
            """)
            try:
                cur.execute("ALTER TABLE templates ADD COLUMN file_path VARCHAR(500) DEFAULT '' AFTER filename")
            except Exception:
                pass  # column already exists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS template_tags (
                    template_id INT NOT NULL,
                    tag_id INT NOT NULL,
                    PRIMARY KEY (template_id, tag_id),
                    FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
                ) ENGINE=InnoDB
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS operation_logs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    action_type VARCHAR(20) NOT NULL,
                    target_type VARCHAR(20) NOT NULL,
                    target_id INT DEFAULT NULL,
                    details JSON,
                    operator VARCHAR(50) DEFAULT '',
                    operator_ip VARCHAR(45) DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    rollback_of INT DEFAULT NULL
                ) ENGINE=InnoDB
            """)
            cur.execute("SELECT COUNT(*) FROM users")
            if cur.fetchone()[0] == 0:
                pw = bcrypt.hashpw(b'admin123', bcrypt.gensalt()).decode('utf-8')
                cur.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", ('admin', pw))
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_db():
    cfg = dict(DB_CONFIG, database=DB_NAME)
    conn = pymysql.connect(**cfg)
    try:
        with conn.cursor() as cur:
            cur.execute("SET time_zone = '+08:00'")
        yield conn
    finally:
        conn.close()


def query_one(sql, params=None):
    with get_db() as conn:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def query_all(sql, params=None):
    with get_db() as conn:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def execute(sql, params=None):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()
            return cur.lastrowid


def execute_transaction(statements):
    """Execute a list of (sql, params) tuples in a single transaction."""
    with get_db() as conn:
        try:
            with conn.cursor() as cur:
                for sql, params in statements:
                    cur.execute(sql, params)
            conn.commit()
        except Exception:
            conn.rollback()
            raise


# ========== USER ==========

def user_create(username, password):
    pw_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    try:
        uid = execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", (username, pw_hash))
        return uid
    except pymysql.err.IntegrityError:
        return None


def user_verify(username, password):
    user = query_one("SELECT * FROM users WHERE username = %s", (username,))
    if user and bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
        return user
    return None


def user_get(uid):
    return query_one("SELECT id, username, created_at FROM users WHERE id = %s", (uid,))


# ========== TAG ==========

def tag_list():
    return query_all("""
        SELECT t.*,
            (SELECT COUNT(*) FROM expression_tags et WHERE et.tag_id = t.id) AS expression_count,
            (SELECT COUNT(*) FROM template_tags tt WHERE tt.tag_id = t.id) AS template_count
        FROM tags t ORDER BY t.id
    """)


def tag_create(name):
    try:
        tid = execute("INSERT INTO tags (name) VALUES (%s)", (name,))
        return tid
    except pymysql.err.IntegrityError:
        return None


def tag_rename(tid, new_name):
    try:
        execute("UPDATE tags SET name = %s WHERE id = %s", (new_name, tid))
        return True
    except pymysql.err.IntegrityError:
        return False


def tag_delete(tid):
    execute("DELETE FROM tags WHERE id = %s", (tid,))


def tag_get(tid):
    return query_one("SELECT * FROM tags WHERE id = %s", (tid,))


# ========== FIXED EXPRESSIONS ==========

def expression_list(search=None, tag_id=None, page=1, per_page=10):
    where = []
    params = []
    joins = ""

    if tag_id:
        joins = " JOIN expression_tags et ON e.id = et.expression_id"
        where.append("et.tag_id = %s")
        params.append(tag_id)

    if search:
        search_like = _transform_search(search)
        where.append("(e.chinese LIKE %s ESCAPE '\\\\' OR e.english LIKE %s ESCAPE '\\\\')")
        params.extend([search_like, search_like])

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""
    count_sql = f"SELECT COUNT(DISTINCT e.id) as cnt FROM fixed_expressions e{joins} {where_clause}"
    total = query_one(count_sql, params)['cnt']

    offset = (page - 1) * per_page
    data_sql = f"""
        SELECT DISTINCT e.* FROM fixed_expressions e{joins}
        {where_clause}
        ORDER BY e.usage_count DESC, e.updated_at DESC
        LIMIT %s OFFSET %s
    """
    rows = query_all(data_sql, params + [per_page, offset])

    for row in rows:
        tags = query_all("""
            SELECT t.id, t.name FROM tags t
            JOIN expression_tags et ON t.id = et.tag_id
            WHERE et.expression_id = %s ORDER BY t.id
        """, (row['id'],))
        row['tags'] = tags

    return rows, total


def expression_get(eid):
    row = query_one("SELECT * FROM fixed_expressions WHERE id = %s", (eid,))
    if row:
        row['tags'] = query_all("""
            SELECT t.id, t.name FROM tags t
            JOIN expression_tags et ON t.id = et.tag_id
            WHERE et.expression_id = %s ORDER BY t.id
        """, (eid,))
    return row


def expression_create(chinese, english, domain='', notes='', tag_ids=None, operator='', ip=''):
    existing = query_one(
        "SELECT id FROM fixed_expressions WHERE chinese = %s AND english = %s",
        (chinese, english)
    )
    if existing:
        return None

    eid = execute(
        "INSERT INTO fixed_expressions (chinese, english, domain, notes, updated_by, updated_ip) VALUES (%s,%s,%s,%s,%s,%s)",
        (chinese, english, domain, notes, operator, ip)
    )
    if tag_ids:
        for tid in tag_ids:
            execute("INSERT IGNORE INTO expression_tags (expression_id, tag_id) VALUES (%s,%s)", (eid, tid))
    return eid


def expression_update(eid, chinese, english, domain='', notes='', tag_ids=None, operator='', ip=''):
    dup = query_one(
        "SELECT id FROM fixed_expressions WHERE chinese = %s AND english = %s AND id != %s",
        (chinese, english, eid)
    )
    if dup:
        return False

    execute(
        "UPDATE fixed_expressions SET chinese=%s, english=%s, domain=%s, notes=%s, updated_by=%s, updated_ip=%s, updated_at=NOW() WHERE id=%s",
        (chinese, english, domain, notes, operator, ip, eid)
    )
    if tag_ids is not None:
        execute("DELETE FROM expression_tags WHERE expression_id = %s", (eid,))
        for tid in tag_ids:
            execute("INSERT IGNORE INTO expression_tags (expression_id, tag_id) VALUES (%s,%s)", (eid, tid))
    return True


def expression_delete(eid):
    execute("DELETE FROM fixed_expressions WHERE id = %s", (eid,))


def expression_autocomplete(q, tag_id=None, limit=8):
    like = f"%{_escape_like(q)}%"
    if tag_id:
        sql = """
            SELECT DISTINCT e.id, e.chinese, e.english FROM fixed_expressions e
            JOIN expression_tags et ON e.id = et.expression_id
            WHERE et.tag_id = %s AND (e.chinese LIKE %s ESCAPE '\\\\' OR e.english LIKE %s ESCAPE '\\\\')
            ORDER BY LENGTH(e.chinese) ASC LIMIT %s
        """
        return query_all(sql, (tag_id, like, like, limit))
    else:
        sql = """
            SELECT e.id, e.chinese, e.english FROM fixed_expressions e
            WHERE e.chinese LIKE %s ESCAPE '\\\\' OR e.english LIKE %s ESCAPE '\\\\'
            ORDER BY LENGTH(e.chinese) ASC LIMIT %s
        """
        return query_all(sql, (like, like, limit))


def expression_copy_increment(eid):
    execute("UPDATE fixed_expressions SET usage_count = usage_count + 1 WHERE id = %s", (eid,))


# ========== TEMPLATES ==========

def template_list(search=None, tag_id=None, page=1, per_page=10):
    where = []
    params = []
    joins = ""

    if tag_id:
        joins = " JOIN template_tags tt ON t.id = tt.template_id"
        where.append("tt.tag_id = %s")
        params.append(tag_id)

    if search:
        search_like = _transform_search(search)
        where.append("(t.name LIKE %s ESCAPE '\\\\' OR t.domain LIKE %s ESCAPE '\\\\' OR t.notes LIKE %s ESCAPE '\\\\')")
        params.extend([search_like, search_like, search_like])

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""
    count_sql = f"SELECT COUNT(DISTINCT t.id) as cnt FROM templates t{joins} {where_clause}"
    total = query_one(count_sql, params)['cnt']

    offset = (page - 1) * per_page
    data_sql = f"""
        SELECT DISTINCT t.* FROM templates t{joins}
        {where_clause}
        ORDER BY t.usage_count DESC, t.updated_at DESC
        LIMIT %s OFFSET %s
    """
    rows = query_all(data_sql, params + [per_page, offset])

    for row in rows:
        tags = query_all("""
            SELECT tg.id, tg.name FROM tags tg
            JOIN template_tags tt ON tg.id = tt.tag_id
            WHERE tt.template_id = %s ORDER BY tg.id
        """, (row['id'],))
        row['tags'] = tags

    return rows, total


def template_get(tid):
    row = query_one("SELECT * FROM templates WHERE id = %s", (tid,))
    if row:
        row['tags'] = query_all("""
            SELECT tg.id, tg.name FROM tags tg
            JOIN template_tags tt ON tg.id = tt.tag_id
            WHERE tt.template_id = %s ORDER BY tg.id
        """, (tid,))
    return row


def template_create(name, content='', domain='', notes='', filename='', file_path='', tag_ids=None, operator='', ip=''):
    tid = execute(
        "INSERT INTO templates (name, content, domain, notes, filename, file_path, updated_by, updated_ip) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (name, content, domain, notes, filename, file_path, operator, ip)
    )
    if tag_ids:
        for tag in tag_ids:
            execute("INSERT IGNORE INTO template_tags (template_id, tag_id) VALUES (%s,%s)", (tid, tag))
    return tid


def template_update(tid, name, content='', domain='', notes='', filename='', file_path=None, tag_ids=None, operator='', ip=''):
    if file_path is not None:
        execute(
            "UPDATE templates SET name=%s, content=%s, domain=%s, notes=%s, filename=%s, file_path=%s, updated_by=%s, updated_ip=%s, updated_at=NOW() WHERE id=%s",
            (name, content, domain, notes, filename, file_path, operator, ip, tid)
        )
    else:
        execute(
            "UPDATE templates SET name=%s, content=%s, domain=%s, notes=%s, filename=%s, updated_by=%s, updated_ip=%s, updated_at=NOW() WHERE id=%s",
            (name, content, domain, notes, filename, operator, ip, tid)
        )
    if tag_ids is not None:
        execute("DELETE FROM template_tags WHERE template_id = %s", (tid,))
        for tag in tag_ids:
            execute("INSERT IGNORE INTO template_tags (template_id, tag_id) VALUES (%s,%s)", (tid, tag))
    return True


def template_delete(tid):
    execute("DELETE FROM templates WHERE id = %s", (tid,))


def template_delete_all():
    rows = query_all("SELECT id, file_path FROM templates")
    execute("DELETE FROM templates")
    return rows


def template_autocomplete(q, tag_id=None, limit=8):
    like = f"%{_escape_like(q)}%"
    if tag_id:
        sql = """
            SELECT DISTINCT t.id, t.name FROM templates t
            JOIN template_tags tt ON t.id = tt.template_id
            WHERE tt.tag_id = %s AND t.name LIKE %s ESCAPE '\\\\'
            ORDER BY LENGTH(t.name) ASC LIMIT %s
        """
        return query_all(sql, (tag_id, like, limit))
    else:
        sql = """
            SELECT t.id, t.name FROM templates t
            WHERE t.name LIKE %s ESCAPE '\\\\'
            ORDER BY LENGTH(t.name) ASC LIMIT %s
        """
        return query_all(sql, (like, limit))


def template_copy_increment(tid):
    execute("UPDATE templates SET usage_count = usage_count + 1 WHERE id = %s", (tid,))


def template_update_path(tid, file_path, content=''):
    execute("UPDATE templates SET file_path=%s, content=%s WHERE id=%s", (file_path, content, tid))


# ========== OPERATION LOGS ==========

def log_create(action_type, target_type, target_id, details, operator='', ip=''):
    return execute(
        "INSERT INTO operation_logs (action_type, target_type, target_id, details, operator, operator_ip) VALUES (%s,%s,%s,%s,%s,%s)",
        (action_type, target_type, target_id, json.dumps(details, ensure_ascii=False), operator, ip)
    )


def log_list(page=1, per_page=20):
    total = query_one("SELECT COUNT(*) as cnt FROM operation_logs")['cnt']
    offset = (page - 1) * per_page
    rows = query_all(
        "SELECT * FROM operation_logs ORDER BY id DESC LIMIT %s OFFSET %s",
        (per_page, offset)
    )
    return rows, total


def log_recent(limit=5):
    return query_all("SELECT * FROM operation_logs ORDER BY id DESC LIMIT %s", (limit,))


def log_get(lid):
    return query_one("SELECT * FROM operation_logs WHERE id = %s", (lid,))


def log_get_since(lid):
    """Get all logs with id >= lid, ordered by id DESC."""
    return query_all("SELECT * FROM operation_logs WHERE id >= %s ORDER BY id DESC", (lid,))


def log_mark_rolled_back(lid, rollback_of=None):
    execute("UPDATE operation_logs SET rollback_of = %s WHERE id = %s", (rollback_of, lid))


# ========== HISTORY ==========

def expression_history(eid):
    return query_all(
        "SELECT * FROM operation_logs WHERE target_type = 'expression' AND target_id = %s ORDER BY id DESC LIMIT 20",
        (eid,)
    )


# ========== HELPERS ==========

def _escape_like(s):
    return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _transform_search(query):
    q = query.strip()
    if not q:
        return '%'
    has_wildcard = '*' in q
    q = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    q = q.replace('*', '%')
    if not has_wildcard:
        q = f'%{q}%'
    return q
