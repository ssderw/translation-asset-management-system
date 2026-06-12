import os
import sys
import json
import uuid
import csv
import io
import getpass
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import Flask, request, jsonify, session, send_file, render_template

CST = timezone(timedelta(hours=8))

import db

if getattr(sys, 'frozen', False):
    DATA_DIR = os.path.dirname(sys.executable)
    TEMPLATE_DIR = os.path.join(sys._MEIPASS, 'templates')
else:
    DATA_DIR = os.path.dirname(os.path.abspath(__file__))
    TEMPLATE_DIR = 'templates'

app = Flask(__name__, template_folder=TEMPLATE_DIR)
app.secret_key = os.urandom(24)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024

# Custom JSON provider: serialize naive datetimes as ISO 8601 Beijing time
from flask.json.provider import DefaultJSONProvider
class BeijingJSONProvider(DefaultJSONProvider):
    def default(self, o):
        if isinstance(o, datetime):
            if o.tzinfo is None:
                o = o.replace(tzinfo=CST)
            return o.isoformat()
        return super().default(o)
app.json = BeijingJSONProvider(app)

ALLOWED_IMPORT_EXTS = {'csv', 'xlsx', 'xls'}
ALLOWED_TEMPLATE_EXTS = {'txt', 'csv', 'xlsx', 'xls', 'docx', 'pdf', 'tmx', 'xml', 'json', 'html', 'md', 'doc', 'ppt', 'pptx'}
TEXT_TEMPLATE_EXTS = {'txt', 'csv', 'tmx', 'xml', 'json', 'html', 'md'}
UPLOAD_FOLDER = os.path.join(DATA_DIR, 'upload')

MIME_MAP = {
    'txt': 'text/plain; charset=utf-8',
    'csv': 'text/csv; charset=utf-8',
    'xml': 'application/xml; charset=utf-8',
    'json': 'application/json; charset=utf-8',
    'html': 'text/html; charset=utf-8',
    'md': 'text/markdown; charset=utf-8',
    'tmx': 'application/xml; charset=utf-8',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'xls': 'application/vnd.ms-excel',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'pdf': 'application/pdf',
    'doc': 'application/msword',
    'ppt': 'application/vnd.ms-powerpoint',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
}


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': '请先登录'}), 401
        return f(*args, **kwargs)
    return decorated


def get_operator():
    return session.get('username', '')


def get_ip():
    return request.remote_addr or ''


@app.route('/')
def index():
    return render_template('index.html')


# ==================== AUTH ====================

@app.route('/api/auth/status')
def auth_status():
    if 'user_id' in session:
        user = db.user_get(session['user_id'])
        return jsonify({'authenticated': True, 'user': user})
    return jsonify({'authenticated': False})


@app.route('/api/auth/register', methods=['POST'])
def auth_register():
    data = request.get_json(force=True)
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    if not username or not password:
        return jsonify({'success': False, 'message': '用户名和密码不能为空'}), 400
    if len(username) < 2:
        return jsonify({'success': False, 'message': '用户名至少2个字符'}), 400
    if len(password) < 4:
        return jsonify({'success': False, 'message': '密码至少4个字符'}), 400
    uid = db.user_create(username, password)
    if uid is None:
        return jsonify({'success': False, 'message': '用户名已存在'}), 409
    db.log_create('add', 'user', uid, {'username': username}, username, get_ip())
    return jsonify({'success': True, 'message': '注册成功，请登录'})


@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    data = request.get_json(force=True)
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    user = db.user_verify(username, password)
    if user:
        session['user_id'] = user['id']
        session['username'] = user['username']
        return jsonify({'success': True, 'user': {'id': user['id'], 'username': user['username']}})
    return jsonify({'success': False, 'message': '用户名或密码错误'}), 401


@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    session.clear()
    return jsonify({'success': True})


# ==================== FIXED EXPRESSIONS ====================

@app.route('/api/expressions', methods=['GET'])
@login_required
def expression_list():
    search = request.args.get('search', '').strip()
    tag_id = request.args.get('tag_id', type=int)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    rows, total = db.expression_list(search=search, tag_id=tag_id, page=page, per_page=per_page)
    total_pages = max(1, (total + per_page - 1) // per_page)

    return jsonify({
        'data': rows,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages
    })


@app.route('/api/expressions/autocomplete', methods=['GET'])
@login_required
def expression_autocomplete():
    q = request.args.get('q', '').strip()
    tag_id = request.args.get('tag_id', type=int)
    if not q and not tag_id:
        return jsonify({'suggestions': []})

    if not q and tag_id:
        rows, _ = db.expression_list(tag_id=tag_id, page=1, per_page=8)
        suggestions = [{'id': r['id'], 'chinese': r['chinese'], 'english': r['english']} for r in rows]
    else:
        suggestions = db.expression_autocomplete(q, tag_id=tag_id)

    return jsonify({'suggestions': suggestions})


@app.route('/api/expressions/<int:eid>', methods=['GET'])
@login_required
def expression_get(eid):
    row = db.expression_get(eid)
    if not row:
        return jsonify({'success': False, 'message': '词条不存在'}), 404
    row['history'] = db.expression_history(eid)
    return jsonify({'data': row})


@app.route('/api/expressions', methods=['POST'])
@login_required
def expression_create():
    data = request.get_json(force=True)
    chinese = (data.get('chinese') or '').strip()
    english = (data.get('english') or '').strip()
    if not chinese or not english:
        return jsonify({'success': False, 'message': '中文和英文为必填项'}), 400

    domain = (data.get('domain') or '').strip()
    notes = (data.get('notes') or '').strip()
    tag_ids = data.get('tag_ids', [])

    eid = db.expression_create(chinese, english, domain, notes, tag_ids, get_operator(), get_ip())
    if eid is None:
        return jsonify({'success': False, 'message': '词条已存在（中文和英文完全相同）'}), 409

    details = {'chinese': chinese, 'english': english, 'domain': domain, 'notes': notes, 'tag_ids': tag_ids}
    db.log_create('add', 'expression', eid, details, get_operator(), get_ip())
    return jsonify({'success': True, 'id': eid})


@app.route('/api/expressions/<int:eid>', methods=['PUT'])
@login_required
def expression_update(eid):
    old = db.expression_get(eid)
    if not old:
        return jsonify({'success': False, 'message': '词条不存在'}), 404

    data = request.get_json(force=True)
    chinese = (data.get('chinese') or '').strip()
    english = (data.get('english') or '').strip()
    if not chinese or not english:
        return jsonify({'success': False, 'message': '中文和英文为必填项'}), 400

    domain = (data.get('domain') or '').strip()
    notes = (data.get('notes') or '').strip()
    tag_ids = data.get('tag_ids', None)

    old_tags = [t['id'] for t in old['tags']]
    details_before = {'chinese': old['chinese'], 'english': old['english'], 'domain': old['domain'],
                      'notes': old['notes'], 'tags': old_tags}

    ok = db.expression_update(eid, chinese, english, domain, notes, tag_ids, get_operator(), get_ip())
    if not ok:
        return jsonify({'success': False, 'message': '词条已存在（中文和英文完全相同）'}), 409

    details_after = {'chinese': chinese, 'english': english, 'domain': domain, 'notes': notes, 'tag_ids': tag_ids}
    details = {'before': details_before, 'after': details_after}
    db.log_create('edit', 'expression', eid, details, get_operator(), get_ip())
    return jsonify({'success': True})


@app.route('/api/expressions/<int:eid>', methods=['DELETE'])
@login_required
def expression_delete(eid):
    old = db.expression_get(eid)
    if not old:
        return jsonify({'success': False, 'message': '词条不存在'}), 404

    details = {
        'chinese': old['chinese'], 'english': old['english'], 'domain': old['domain'],
        'notes': old['notes'], 'tags': [t['id'] for t in old['tags']]
    }
    db.expression_delete(eid)
    db.log_create('delete', 'expression', eid, details, get_operator(), get_ip())
    return jsonify({'success': True})


@app.route('/api/expressions/batch-import', methods=['POST'])
@login_required
def expression_batch_import():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '请选择文件'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'success': False, 'message': '请选择文件'}), 400

    filename = file.filename.lower()
    if not any(filename.endswith(ext) for ext in ALLOWED_IMPORT_EXTS):
        return jsonify({'success': False, 'message': '不支持的文件格式，请上传 .csv / .xlsx / .xls 文件'}), 400

    tag_ids_str = request.form.get('tag_ids', '')
    tag_ids = [int(x) for x in tag_ids_str.split(',') if x.strip().isdigit()] if tag_ids_str else []

    try:
        rows = _parse_import_file(file, filename)
    except Exception as e:
        return jsonify({'success': False, 'message': f'文件解析失败：{str(e)}'}), 400

    imported = 0
    skipped = 0
    errors = []
    imported_ids = []

    for i, row in enumerate(rows):
        chinese = (row.get('chinese') or '').strip()
        english = (row.get('english') or '').strip()
        if not chinese or not english:
            errors.append({'row': i + 1, 'message': '缺少中文或英文'})
            continue

        domain = (row.get('domain') or '').strip()
        notes = (row.get('notes') or '').strip()

        eid = db.expression_create(chinese, english, domain, notes, tag_ids, get_operator(), get_ip())
        if eid is None:
            skipped += 1
        else:
            imported += 1
            imported_ids.append(eid)

    if imported_ids:
        db.log_create('batch_add', 'expression', None,
                      {'imported': imported, 'skipped': skipped, 'errors': len(errors), 'ids': imported_ids},
                      get_operator(), get_ip())

    return jsonify({
        'success': True,
        'imported': imported,
        'skipped': skipped,
        'errors': errors
    })


@app.route('/api/expressions/<int:eid>/copy', methods=['POST'])
@login_required
def expression_copy(eid):
    expr = db.expression_get(eid)
    if not expr:
        return jsonify({'success': False, 'message': '词条不存在'}), 404
    db.expression_copy_increment(eid)
    return jsonify({'success': True})


# ==================== BILINGUAL CORPUS ====================

@app.route('/api/bilingual', methods=['GET'])
@login_required
def bilingual_list():
    search = request.args.get('search', '').strip()
    tag_id = request.args.get('tag_id', type=int)
    lang_code = request.args.get('lang_code', '').strip() or None
    review_status = request.args.get('review_status', '').strip() or None
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    rows, total = db.bilingual_list(search=search, tag_id=tag_id, lang_code=lang_code, review_status=review_status, page=page, per_page=per_page)
    total_pages = max(1, (total + per_page - 1) // per_page)

    return jsonify({
        'data': rows,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages
    })


@app.route('/api/bilingual/autocomplete', methods=['GET'])
@login_required
def bilingual_autocomplete():
    q = request.args.get('q', '').strip()
    tag_id = request.args.get('tag_id', type=int)
    if not q and not tag_id:
        return jsonify({'suggestions': []})

    if not q and tag_id:
        rows, _ = db.bilingual_list(tag_id=tag_id, page=1, per_page=8)
        suggestions = [{'id': r['id'], 'chinese': r['chinese'], 'other_lang': r['other_lang'], 'lang_code': r['lang_code']} for r in rows]
    else:
        suggestions = db.bilingual_autocomplete(q, tag_id=tag_id)

    return jsonify({'suggestions': suggestions})


@app.route('/api/bilingual/<int:eid>', methods=['GET'])
@login_required
def bilingual_get(eid):
    row = db.bilingual_get(eid)
    if not row:
        return jsonify({'success': False, 'message': '语料条目不存在'}), 404
    return jsonify({'data': row})


@app.route('/api/bilingual', methods=['POST'])
@login_required
def bilingual_create():
    data = request.get_json(force=True)
    chinese = (data.get('chinese') or '').strip()
    other_lang = (data.get('other_lang') or '').strip()
    if not chinese or not other_lang:
        return jsonify({'success': False, 'message': '中文和译文为必填项'}), 400

    lang_code = (data.get('lang_code') or 'en').strip()
    source_type = (data.get('source_type') or 'sentence').strip()
    source_file = (data.get('source_file') or '').strip()
    notes = (data.get('notes') or '').strip()
    tag_ids = data.get('tag_ids', [])

    eid = db.bilingual_create(chinese, other_lang, lang_code, source_type, source_file, notes, tag_ids, get_operator(), get_ip())
    if eid is None:
        return jsonify({'success': False, 'message': '语料条目已存在（中文和译文完全相同）'}), 409

    details = {'chinese': chinese, 'other_lang': other_lang, 'lang_code': lang_code, 'source_type': source_type, 'source_file': source_file, 'notes': notes, 'tag_ids': tag_ids}
    db.log_create('add', 'bilingual_corpus', eid, details, get_operator(), get_ip())
    return jsonify({'success': True, 'id': eid})


@app.route('/api/bilingual/<int:eid>', methods=['PUT'])
@login_required
def bilingual_update(eid):
    old = db.bilingual_get(eid)
    if not old:
        return jsonify({'success': False, 'message': '语料条目不存在'}), 404

    data = request.get_json(force=True)
    chinese = (data.get('chinese') or '').strip()
    other_lang = (data.get('other_lang') or '').strip()
    if not chinese or not other_lang:
        return jsonify({'success': False, 'message': '中文和译文为必填项'}), 400

    lang_code = (data.get('lang_code') or old.get('lang_code', 'en')).strip()
    source_type = (data.get('source_type') or old.get('source_type', 'sentence')).strip()
    notes = (data.get('notes') or '').strip()
    tag_ids = data.get('tag_ids', None)

    old_tags = [t['id'] for t in old['tags']]
    details_before = {'chinese': old['chinese'], 'other_lang': old['other_lang'], 'lang_code': old['lang_code'],
                      'source_type': old['source_type'], 'notes': old['notes'], 'tags': old_tags}

    ok = db.bilingual_update(eid, chinese, other_lang, lang_code, source_type, notes, tag_ids, get_operator(), get_ip())
    if not ok:
        return jsonify({'success': False, 'message': '语料条目已存在（中文和译文完全相同）'}), 409

    details_after = {'chinese': chinese, 'other_lang': other_lang, 'lang_code': lang_code, 'source_type': source_type, 'notes': notes, 'tag_ids': tag_ids}
    details = {'before': details_before, 'after': details_after}
    db.log_create('edit', 'bilingual_corpus', eid, details, get_operator(), get_ip())
    return jsonify({'success': True})


@app.route('/api/bilingual/<int:eid>', methods=['DELETE'])
@login_required
def bilingual_delete(eid):
    old = db.bilingual_get(eid)
    if not old:
        return jsonify({'success': False, 'message': '语料条目不存在'}), 404

    details = {
        'chinese': old['chinese'], 'other_lang': old['other_lang'], 'lang_code': old['lang_code'],
        'source_type': old['source_type'], 'notes': old['notes'], 'tags': [t['id'] for t in old['tags']]
    }
    db.bilingual_delete(eid)
    db.log_create('delete', 'bilingual_corpus', eid, details, get_operator(), get_ip())
    return jsonify({'success': True})


@app.route('/api/bilingual/<int:eid>/approve', methods=['POST'])
@login_required
def bilingual_approve(eid):
    new_eid = db.bilingual_approve(eid, get_operator(), get_ip())
    if new_eid is None:
        return jsonify({'success': False, 'message': '语料条目不存在或已被处理'}), 404
    if new_eid == 0:
        return jsonify({'success': True, 'message': '词条重复，语料条目已删除'})
    return jsonify({'success': True, 'expression_id': new_eid, 'message': '已批准并转为固定表达'})


@app.route('/api/bilingual/<int:eid>/reject', methods=['POST'])
@login_required
def bilingual_reject(eid):
    old = db.bilingual_get(eid)
    if not old:
        return jsonify({'success': False, 'message': '语料条目不存在'}), 404
    db.bilingual_reject(eid, get_operator(), get_ip())
    return jsonify({'success': True, 'message': '已拒绝'})


@app.route('/api/bilingual/<int:eid>/restore', methods=['POST'])
@login_required
def bilingual_restore(eid):
    old = db.bilingual_get(eid)
    if not old:
        return jsonify({'success': False, 'message': '语料条目不存在'}), 404
    if old.get('review_status') != 'rejected':
        return jsonify({'success': False, 'message': '仅可恢复已拒绝的条目'}), 400
    db.bilingual_restore(eid, get_operator(), get_ip())
    return jsonify({'success': True, 'message': '已恢复到待审核状态'})


@app.route('/api/bilingual/batch-import', methods=['POST'])
@login_required
def bilingual_batch_import():
    data = request.get_json(force=True)
    entries = data.get('entries', [])
    lang_code = data.get('lang_code', 'en')

    if not entries:
        return jsonify({'success': False, 'message': '没有要导入的数据'}), 400

    imported = 0
    skipped = 0
    errors = []
    imported_ids = []

    for i, entry in enumerate(entries):
        chinese = (entry.get('chinese') or entry.get('source') or '').strip()
        other_lang = (entry.get('other_lang') or entry.get('target') or '').strip()
        if not chinese or not other_lang:
            errors.append({'row': i + 1, 'message': '缺少中文或译文'})
            continue

        source_type = (entry.get('source_type') or 'sentence').strip()
        source_file = (entry.get('source_file') or '').strip()
        notes = (entry.get('notes') or '').strip()
        entry_lang = (entry.get('lang_code') or lang_code).strip()
        tag_ids = entry.get('tag_ids', [])

        eid = db.bilingual_create(chinese, other_lang, entry_lang, source_type, source_file, notes, tag_ids, get_operator(), get_ip())
        if eid is None:
            skipped += 1
        else:
            imported += 1
            imported_ids.append(eid)

    if imported_ids:
        db.log_create('batch_add', 'bilingual_corpus', None,
                      {'imported': imported, 'skipped': skipped, 'errors': len(errors), 'ids': imported_ids},
                      get_operator(), get_ip())

    return jsonify({
        'success': True,
        'imported': imported,
        'skipped': skipped,
        'errors': errors
    })


@app.route('/api/bilingual/matcher', methods=['GET'])
@login_required
def bilingual_matcher():
    """Returns ALL bilingual_corpus entries for glossary matching by docutranslate."""
    lang_code = request.args.get('lang_code', '').strip() or None
    rows = db.bilingual_list_for_matcher(lang_code=lang_code)
    return jsonify({'data': rows})


@app.route('/api/bilingual/clear-all', methods=['DELETE'])
@login_required
def bilingual_clear_all():
    rows = db.bilingual_delete_all()
    db.log_create('delete', 'bilingual_corpus', None,
                  {'cleared_count': len(rows), 'cleared_ids': [r['id'] for r in rows]},
                  get_operator(), get_ip())
    return jsonify({'success': True, 'message': f'已清空 {len(rows)} 条双语语料', 'count': len(rows)})


@app.route('/api/bilingual/clean-invalid', methods=['DELETE'])
@login_required
def bilingual_clean_invalid():
    rows = db.bilingual_clean_invalid()
    db.log_create('delete', 'bilingual_corpus', None,
                  {'cleaned_count': len(rows), 'cleaned_ids': [r['id'] for r in rows]},
                  get_operator(), get_ip())
    return jsonify({'success': True, 'message': f'已清理 {len(rows)} 条无效语料', 'count': len(rows)})


# ==================== TEMPLATES ====================

@app.route('/api/templates', methods=['GET'])
@login_required
def template_list():
    search = request.args.get('search', '').strip()
    tag_id = request.args.get('tag_id', type=int)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    rows, total = db.template_list(search=search, tag_id=tag_id, page=page, per_page=per_page)
    total_pages = max(1, (total + per_page - 1) // per_page)

    return jsonify({
        'data': rows,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages
    })


@app.route('/api/templates/autocomplete', methods=['GET'])
@login_required
def template_autocomplete():
    q = request.args.get('q', '').strip()
    tag_id = request.args.get('tag_id', type=int)
    if not q and not tag_id:
        return jsonify({'suggestions': []})

    if not q and tag_id:
        rows, _ = db.template_list(tag_id=tag_id, page=1, per_page=8)
        suggestions = [{'id': r['id'], 'name': r['name']} for r in rows]
    else:
        suggestions = db.template_autocomplete(q, tag_id=tag_id)

    return jsonify({'suggestions': suggestions})


@app.route('/api/templates/<int:tid>', methods=['GET'])
@login_required
def template_get(tid):
    row = db.template_get(tid)
    if not row:
        return jsonify({'success': False, 'message': '模板不存在'}), 404
    row['preview'] = _build_preview(row)
    return jsonify({'data': row})


@app.route('/api/templates', methods=['POST'])
@login_required
def template_create():
    name = (request.form.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'message': '模板名不能为空'}), 400

    domain = (request.form.get('domain') or '').strip()
    notes = (request.form.get('notes') or '').strip()
    tag_ids = []
    tag_ids_str = request.form.get('tag_ids', '')
    if tag_ids_str:
        try:
            tag_ids = json.loads(tag_ids_str)
        except json.JSONDecodeError:
            tag_ids = [int(x) for x in tag_ids_str.split(',') if x.strip().isdigit()]

    content = ''
    filename = ''
    file_path = ''
    file_data = None

    if 'file' in request.files:
        file = request.files['file']
        if file.filename:
            filename = file.filename
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            if ext not in ALLOWED_TEMPLATE_EXTS:
                return jsonify({'success': False, 'message': f'不支持的文件类型 .{ext}'}), 400
            file_data = file.read()
            content = _decode_file_content(file_data, filename)

    tid = db.template_create(name, content, domain, notes, filename, file_path, tag_ids, get_operator(), get_ip())

    if file_data and tid:
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        safe_name = f"{tid}_{uuid.uuid4().hex[:8]}.{ext}"
        file_path = os.path.join('upload', safe_name)
        abs_path = os.path.join(DATA_DIR, file_path)
        with open(abs_path, 'wb') as f:
            f.write(file_data)
        db.template_update_path(tid, file_path, content)

    db.log_create('add', 'template', tid,
                  {'name': name, 'domain': domain, 'notes': notes, 'filename': filename,
                   'file_path': file_path, 'tag_ids': tag_ids},
                  get_operator(), get_ip())
    return jsonify({'success': True, 'id': tid})


@app.route('/api/templates/<int:tid>', methods=['PUT'])
@login_required
def template_update(tid):
    old = db.template_get(tid)
    if not old:
        return jsonify({'success': False, 'message': '模板不存在'}), 404

    name = (request.form.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'message': '模板名不能为空'}), 400

    domain = (request.form.get('domain') or '').strip()
    notes = (request.form.get('notes') or '').strip()
    tag_ids = None
    tag_ids_str = request.form.get('tag_ids', None)
    if tag_ids_str is not None and tag_ids_str != '':
        try:
            tag_ids = json.loads(tag_ids_str)
        except json.JSONDecodeError:
            tag_ids = [int(x) for x in tag_ids_str.split(',') if x.strip().isdigit()]

    content = old['content']
    filename = old.get('filename', '')
    file_path = old.get('file_path', '')
    if 'file' in request.files:
        file = request.files['file']
        if file.filename:
            file_data = file.read()
            filename = file.filename
            content = _decode_file_content(file_data, filename)
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            # Delete old file if exists
            old_path = old.get('file_path', '')
            if old_path:
                old_abs = os.path.join(DATA_DIR, old_path)
                _safe_remove(old_abs)
            # Save new file
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            safe_name = f"{tid}_{uuid.uuid4().hex[:8]}.{ext}"
            file_path = os.path.join('upload', safe_name)
            abs_path = os.path.join(DATA_DIR, file_path)
            with open(abs_path, 'wb') as f:
                f.write(file_data)

    old_tags = [t['id'] for t in old['tags']]
    details_before = {'name': old['name'], 'domain': old['domain'], 'notes': old['notes'],
                      'filename': old.get('filename', ''), 'file_path': old.get('file_path', ''), 'tags': old_tags}
    db.template_update(tid, name, content, domain, notes, filename, file_path, tag_ids, get_operator(), get_ip())
    details_after = {'name': name, 'domain': domain, 'notes': notes, 'filename': filename,
                     'file_path': file_path, 'tag_ids': tag_ids}
    db.log_create('edit', 'template', tid, {'before': details_before, 'after': details_after},
                  get_operator(), get_ip())
    return jsonify({'success': True})


@app.route('/api/templates/<int:tid>', methods=['DELETE'])
@login_required
def template_delete(tid):
    old = db.template_get(tid)
    if not old:
        return jsonify({'success': False, 'message': '模板不存在'}), 404

    old_path = old.get('file_path', '')
    if old_path:
        old_abs = os.path.join(DATA_DIR, old_path)
        _safe_remove(old_abs)

    details = {'name': old['name'], 'domain': old['domain'], 'notes': old['notes'],
               'filename': old.get('filename', ''), 'file_path': old_path,
               'tags': [t['id'] for t in old['tags']]}
    db.template_delete(tid)
    db.log_create('delete', 'template', tid, details, get_operator(), get_ip())
    return jsonify({'success': True})


@app.route('/api/templates/clear-all', methods=['DELETE'])
@login_required
def template_clear_all():
    rows = db.template_delete_all()
    for row in rows:
        fp = row.get('file_path', '')
        if fp:
            abs_path = os.path.join(DATA_DIR, fp)
            _safe_remove(abs_path)
    db.log_create('delete', 'template', None,
                  {'cleared_count': len(rows), 'cleared_ids': [r['id'] for r in rows]},
                  get_operator(), get_ip())
    return jsonify({'success': True, 'message': f'已清空 {len(rows)} 个模板', 'count': len(rows)})


@app.route('/api/templates/<int:tid>/download', methods=['GET'])
@login_required
def template_download(tid):
    row = db.template_get(tid)
    if not row:
        return jsonify({'success': False, 'message': '模板不存在'}), 404

    filename = row.get('filename', f'template_{tid}.txt')
    file_path = row.get('file_path', '')
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'txt'
    mimetype = MIME_MAP.get(ext, 'application/octet-stream')

    # Try serving from disk first
    if file_path:
        abs_path = os.path.join(DATA_DIR, file_path)
        if os.path.isfile(abs_path):
            return send_file(abs_path, as_attachment=True, download_name=filename, mimetype=mimetype)

    # Fallback: serve from DB content (backward compatibility)
    if row.get('content'):
        mem = io.BytesIO()
        mem.write(row['content'].encode('utf-8'))
        mem.seek(0)
        return send_file(mem, as_attachment=True, download_name=filename, mimetype=mimetype)

    return jsonify({'success': False, 'message': '该模板没有上传文件'}), 404


@app.route('/api/templates/<int:tid>/copy', methods=['POST'])
@login_required
def template_copy(tid):
    tpl = db.template_get(tid)
    if not tpl:
        return jsonify({'success': False, 'message': '模板不存在'}), 404
    db.template_copy_increment(tid)
    return jsonify({'success': True})


# ==================== TAGS ====================

@app.route('/api/tags', methods=['GET'])
@login_required
def tag_list():
    tags = db.tag_list()
    return jsonify({'tags': tags})


@app.route('/api/tags', methods=['POST'])
@login_required
def tag_create():
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'message': '标签名不能为空'}), 400
    tid = db.tag_create(name)
    if tid is None:
        return jsonify({'success': False, 'message': '标签已存在'}), 409
    db.log_create('add', 'tag', tid, {'name': name}, get_operator(), get_ip())
    return jsonify({'success': True, 'id': tid})


@app.route('/api/tags/<int:tid>', methods=['PUT'])
@login_required
def tag_rename(tid):
    data = request.get_json(force=True)
    new_name = (data.get('name') or '').strip()
    if not new_name:
        return jsonify({'success': False, 'message': '标签名不能为空'}), 400
    old_tag = db.tag_get(tid)
    if not old_tag:
        return jsonify({'success': False, 'message': '标签不存在'}), 404
    ok = db.tag_rename(tid, new_name)
    if not ok:
        return jsonify({'success': False, 'message': '标签名已存在'}), 409
    db.log_create('edit', 'tag', tid, {'before': old_tag['name'], 'after': new_name}, get_operator(), get_ip())
    return jsonify({'success': True})


@app.route('/api/tags/<int:tid>', methods=['DELETE'])
@login_required
def tag_delete(tid):
    old_tag = db.tag_get(tid)
    if not old_tag:
        return jsonify({'success': False, 'message': '标签不存在'}), 404
    db.tag_delete(tid)
    db.log_create('delete', 'tag', tid, {'name': old_tag['name']}, get_operator(), get_ip())
    return jsonify({'success': True})


# ==================== LOGS ====================

@app.route('/api/logs', methods=['GET'])
@login_required
def log_list_route():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    rows, total = db.log_list(page=page, per_page=per_page)
    total_pages = max(1, (total + per_page - 1) // per_page)
    return jsonify({'data': rows, 'total': total, 'page': page, 'per_page': per_page, 'total_pages': total_pages})


@app.route('/api/logs/clear-old', methods=['DELETE'])
@login_required
def log_clear_old():
    days = request.args.get('days', 3, type=int)
    deleted = db.log_delete_old(days=days)
    return jsonify({'success': True, 'deleted': deleted, 'message': f'已清空 {days} 天前的日志，共 {deleted} 条'})


@app.route('/api/logs/recent', methods=['GET'])
@login_required
def log_recent():
    rows = db.log_recent(5)
    return jsonify({'data': rows})


@app.route('/api/logs/<int:lid>/rollback', methods=['POST'])
@login_required
def log_rollback(lid):
    target_log = db.log_get(lid)
    if not target_log:
        return jsonify({'success': False, 'message': '日志记录不存在'}), 404
    if target_log.get('target_type') in ('template', 'bilingual_corpus'):
        return jsonify({'success': False, 'message': '模板和双语语料操作不支持回撤'}), 400
    if target_log.get('rollback_of') is not None:
        return jsonify({'success': False, 'message': '该操作已被回撤'}), 400

    all_logs = db.log_get_since(lid)
    unrolled = [l for l in all_logs if l.get('rollback_of') is None and l['target_type'] not in ('template', 'bilingual_corpus')]

    if len(unrolled) > 10:
        return jsonify({'success': False, 'message': '只能回撤最近10次操作'}), 400

    statements = []
    now = datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')

    for log_entry in unrolled:
        _reverse_operation(log_entry, statements)

    statements.append(
        ("INSERT INTO operation_logs (action_type, target_type, target_id, details, operator, operator_ip, created_at, rollback_of) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
         ('rollback', target_log['target_type'], target_log['target_id'],
          json.dumps({'rolled_back_log_id': lid, 'rolled_back_chain': [l['id'] for l in unrolled]}, ensure_ascii=False),
          get_operator(), get_ip(), now, lid))
    )

    try:
        db.execute_transaction(statements)
    except Exception as e:
        return jsonify({'success': False, 'message': f'回撤失败：{str(e)}'}), 500

    return jsonify({'success': True, 'message': f'已成功回撤 {len(unrolled)} 条操作'})


def _reverse_operation(log_entry, statements):
    lid = log_entry['id']
    target_type = log_entry['target_type']
    action = log_entry['action_type']
    details = log_entry['details']
    if isinstance(details, str):
        details = json.loads(details) if details else {}

    if action == 'add':
        if target_type == 'expression':
            statements.append(("DELETE FROM fixed_expressions WHERE id = %s", (log_entry['target_id'],)))
        elif target_type == 'template':
            statements.append(("DELETE FROM templates WHERE id = %s", (log_entry['target_id'],)))
        elif target_type == 'tag':
            statements.append(("DELETE FROM tags WHERE id = %s", (log_entry['target_id'],)))
        elif target_type == 'user':
            statements.append(("DELETE FROM users WHERE id = %s", (log_entry['target_id'],)))
        elif target_type == 'bilingual_corpus':
            statements.append(("DELETE FROM bilingual_corpus WHERE id = %s", (log_entry['target_id'],)))

    elif action == 'delete':
        if target_type == 'expression':
            statements.append((
                "INSERT INTO fixed_expressions (id, chinese, english, domain, notes, updated_by, updated_ip) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (log_entry['target_id'], details.get('chinese', ''), details.get('english', ''),
                 details.get('domain', ''), details.get('notes', ''), get_operator(), get_ip())
            ))
            for tid in details.get('tags', []):
                statements.append((
                    "INSERT IGNORE INTO expression_tags (expression_id, tag_id) VALUES (%s,%s)",
                    (log_entry['target_id'], tid)
                ))
        elif target_type == 'template':
            statements.append((
                "INSERT INTO templates (id, name, content, domain, notes, filename, file_path, updated_by, updated_ip) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (log_entry['target_id'], details.get('name', ''), '', details.get('domain', ''),
                 details.get('notes', ''), details.get('filename', ''), details.get('file_path', ''),
                 get_operator(), get_ip())
            ))
            for tid in details.get('tags', []):
                statements.append((
                    "INSERT IGNORE INTO template_tags (template_id, tag_id) VALUES (%s,%s)",
                    (log_entry['target_id'], tid)
                ))
        elif target_type == 'tag':
            statements.append(("INSERT INTO tags (id, name) VALUES (%s,%s)", (log_entry['target_id'], details.get('name', ''))))
        elif target_type == 'bilingual_corpus':
            statements.append((
                "INSERT INTO bilingual_corpus (id, chinese, other_lang, lang_code, source_type, source_file, notes, review_status, updated_by, updated_ip) VALUES (%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s)",
                (log_entry['target_id'], details.get('chinese', ''), details.get('other_lang', ''),
                 details.get('lang_code', 'en'), details.get('source_type', 'sentence'), details.get('source_file', ''),
                 details.get('notes', ''), get_operator(), get_ip())
            ))
            for tid in details.get('tags', []):
                statements.append((
                    "INSERT IGNORE INTO bilingual_corpus_tags (corpus_id, tag_id) VALUES (%s,%s)",
                    (log_entry['target_id'], tid)
                ))

    elif action == 'edit':
        before = details.get('before', {})
        if target_type == 'expression':
            statements.append((
                "UPDATE fixed_expressions SET chinese=%s, english=%s, domain=%s, notes=%s, updated_by=%s, updated_ip=%s, updated_at=NOW() WHERE id=%s",
                (before.get('chinese', ''), before.get('english', ''), before.get('domain', ''),
                 before.get('notes', ''), get_operator(), get_ip(), log_entry['target_id'])
            ))
            statements.append(("DELETE FROM expression_tags WHERE expression_id = %s", (log_entry['target_id'],)))
            for tid in before.get('tags', []):
                statements.append((
                    "INSERT IGNORE INTO expression_tags (expression_id, tag_id) VALUES (%s,%s)",
                    (log_entry['target_id'], tid)
                ))
        elif target_type == 'template':
            statements.append((
                "UPDATE templates SET name=%s, domain=%s, notes=%s, filename=%s, file_path=%s, updated_by=%s, updated_ip=%s, updated_at=NOW() WHERE id=%s",
                (before.get('name', ''), before.get('domain', ''), before.get('notes', ''),
                 before.get('filename', ''), before.get('file_path', ''), get_operator(), get_ip(), log_entry['target_id'])
            ))
            statements.append(("DELETE FROM template_tags WHERE template_id = %s", (log_entry['target_id'],)))
            for tid in before.get('tags', []):
                statements.append((
                    "INSERT IGNORE INTO template_tags (template_id, tag_id) VALUES (%s,%s)",
                    (log_entry['target_id'], tid)
                ))
        elif target_type == 'tag':
            statements.append(("UPDATE tags SET name=%s WHERE id=%s", (before, log_entry['target_id'])))
        elif target_type == 'bilingual_corpus':
            statements.append((
                "UPDATE bilingual_corpus SET chinese=%s, other_lang=%s, lang_code=%s, source_type=%s, notes=%s, updated_by=%s, updated_ip=%s, updated_at=NOW() WHERE id=%s",
                (before.get('chinese', ''), before.get('other_lang', ''), before.get('lang_code', 'en'),
                 before.get('source_type', 'sentence'), before.get('notes', ''), get_operator(), get_ip(), log_entry['target_id'])
            ))
            statements.append(("DELETE FROM bilingual_corpus_tags WHERE corpus_id = %s", (log_entry['target_id'],)))
            for tid in before.get('tags', []):
                statements.append((
                    "INSERT IGNORE INTO bilingual_corpus_tags (corpus_id, tag_id) VALUES (%s,%s)",
                    (log_entry['target_id'], tid)
                ))

    elif action == 'batch_add':
        ids = details.get('ids', [])
        if target_type == 'expression':
            for eid in ids:
                statements.append(("DELETE FROM fixed_expressions WHERE id = %s", (eid,)))
        elif target_type == 'bilingual_corpus':
            for eid in ids:
                statements.append(("DELETE FROM bilingual_corpus WHERE id = %s", (eid,)))

    elif action == 'approve':
        if target_type == 'bilingual_corpus':
            # Reverse approval: delete the fixed_expression, re-insert into bilingual_corpus
            if details.get('expression_id'):
                statements.append(("DELETE FROM fixed_expressions WHERE id = %s", (details['expression_id'],)))
            statements.append((
                "INSERT INTO bilingual_corpus (id, chinese, other_lang, lang_code, source_type, source_file, notes, review_status, updated_by, updated_ip) VALUES (%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s)",
                (log_entry['target_id'], details.get('chinese', ''), details.get('other_lang', ''),
                 details.get('lang_code', 'en'), details.get('source_type', 'sentence'),
                 details.get('source_file', ''), details.get('notes', ''),
                 get_operator(), get_ip())
            ))
            for tid in details.get('tags', []):
                statements.append((
                    "INSERT IGNORE INTO bilingual_corpus_tags (corpus_id, tag_id) VALUES (%s,%s)",
                    (log_entry['target_id'], tid)
                ))

    elif action == 'reject':
        if target_type == 'bilingual_corpus':
            statements.append((
                "UPDATE bilingual_corpus SET review_status='pending', updated_by=%s, updated_ip=%s, updated_at=NOW() WHERE id=%s",
                (get_operator(), get_ip(), log_entry['target_id'])
            ))

    elif action == 'restore':
        if target_type == 'bilingual_corpus':
            statements.append((
                "UPDATE bilingual_corpus SET review_status='rejected', updated_by=%s, updated_ip=%s, updated_at=NOW() WHERE id=%s",
                (get_operator(), get_ip(), log_entry['target_id'])
            ))

    statements.append(("UPDATE operation_logs SET rollback_of = %s WHERE id = %s", (lid, lid)))


# ==================== HELPERS ====================

def _parse_import_file(file, filename):
    rows = []
    if filename.endswith('.csv'):
        content = file.read()
        try:
            content_str = content.decode('utf-8-sig')
        except UnicodeDecodeError:
            try:
                content_str = content.decode('gbk')
            except UnicodeDecodeError:
                content_str = content.decode('latin-1')
        reader = csv.reader(io.StringIO(content_str))
        lines = list(reader)
        if not lines:
            return rows
        header = lines[0]
        col_map = _detect_columns(header)
        start = 1 if col_map else 0
        if not col_map:
            col_map = {0: 'chinese', 1: 'english', 2: 'domain', 3: 'notes'}
        for i in range(start, len(lines)):
            line = lines[i]
            if not line or all(c.strip() == '' for c in line):
                continue
            row = {}
            for idx, key in col_map.items():
                if idx < len(line):
                    row[key] = line[idx]
            if row.get('chinese') or row.get('english'):
                rows.append(row)
    elif filename.endswith(('.xlsx', '.xls')):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(file.read()), read_only=True)
            ws = wb.active
            line_data = []
            for r in ws.iter_rows(values_only=True):
                line_data.append([str(c) if c is not None else '' for c in r])
            if not line_data:
                return rows
            header = line_data[0]
            col_map = _detect_columns(header)
            start_row = 1 if col_map else 0
            if not col_map:
                col_map = {0: 'chinese', 1: 'english', 2: 'domain', 3: 'notes'}
            for i in range(start_row, len(line_data)):
                line = line_data[i]
                if not line or all(c.strip() == '' for c in line):
                    continue
                row = {}
                for idx, key in col_map.items():
                    if idx < len(line):
                        row[key] = line[idx]
                if row.get('chinese') or row.get('english'):
                    rows.append(row)
            wb.close()
        except Exception as e:
            raise Exception(f'Excel解析错误：{str(e)}')

    return rows


def _decode_file_content(file_data, filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in TEXT_TEMPLATE_EXTS:
        return ''
    for enc in ('utf-8', 'gbk', 'gb2312', 'latin-1'):
        try:
            return file_data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return ''


def _build_preview(row):
    filename = row.get('filename', '')
    content = row.get('content', '')
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

    # If no filename but has content, it's plain text (created without file upload)
    if not filename and content:
        return content

    is_text = ext in TEXT_TEMPLATE_EXTS

    if not is_text:
        return '[二进制文件，不支持在线预览，请下载后查看]'

    if content:
        return content

    file_path = row.get('file_path', '')
    if file_path:
        abs_path = os.path.join(DATA_DIR, file_path)
        if os.path.isfile(abs_path):
            try:
                with open(abs_path, 'rb') as f:
                    raw = f.read()
                for enc in ('utf-8', 'gbk', 'gb2312', 'latin-1'):
                    try:
                        return raw.decode(enc)
                    except (UnicodeDecodeError, LookupError):
                        continue
            except OSError:
                pass
    return '(无内容)'


def _safe_remove(path):
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _detect_columns(header):
    mapping = {}
    for i, h in enumerate(header):
        h_lower = (h or '').strip().lower()
        if h_lower in ('中文', 'chinese', 'source', 'source_text', 'zh', 'cn', 'a'):
            mapping[i] = 'chinese'
        elif h_lower in ('英文', 'english', 'target', 'target_text', 'en', 'b'):
            mapping[i] = 'english'
        elif h_lower in ('领域', 'domain', 'field', 'c'):
            mapping[i] = 'domain'
        elif h_lower in ('备注', 'notes', 'note', 'remark', 'comment', 'd'):
            mapping[i] = 'notes'
    if 'chinese' in mapping.values() and 'english' in mapping.values():
        return mapping
    return None


# ==================== MAIN ====================

def _prompt_mysql_config():
    print("=" * 50)
    print("  MySQL 数据库连接配置")
    print("=" * 50)
    print("(支持环境变量: MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD)")
    print()

    host = os.environ.get('MYSQL_HOST') or input("主机地址 [localhost]: ").strip() or 'localhost'
    port_str = os.environ.get('MYSQL_PORT') or input("端口 [3306]: ").strip() or '3306'
    port = int(port_str)
    user = os.environ.get('MYSQL_USER') or input("用户名 [root]: ").strip() or 'root'
    if os.environ.get('MYSQL_PASSWORD'):
        password = os.environ['MYSQL_PASSWORD']
        print("密码: 从环境变量 MYSQL_PASSWORD 读取")
    else:
        password = getpass.getpass("密码: ").strip()
        if not password:
            password = '123456'
            print("使用默认密码")

    db.configure_db(host=host, port=port, user=user, password=password)
    print()
    print(f"连接目标: {user}@{host}:{port}")
    print()


if __name__ == '__main__':
    _prompt_mysql_config()
    print("Initializing database...")
    db.init_db()
    print("Database ready.")
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    print(f"Upload folder ready: {UPLOAD_FOLDER}")
    print("Starting server on http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000)
