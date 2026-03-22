import os
import json
from functools import wraps
from flask import Flask, render_template, request, session, redirect, url_for, jsonify, abort
import cloudinary
import cloudinary.uploader

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
except ImportError:
    pass

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-me-in-production')

ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '')
ADMIN_ENABLED  = os.environ.get('ADMIN_ENABLED', 'false').lower() == 'true'

cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
)

DATA_DIR       = os.path.join(os.path.dirname(__file__), 'data')
PRODUCTS_FILE  = os.path.join(DATA_DIR, 'products.json')
JOURNAL_FILE   = os.path.join(DATA_DIR, 'journal.json')
MESSAGES_FILE  = os.path.join(DATA_DIR, 'messages.json')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_json(path, default=None):
    if default is None:
        default = []
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not ADMIN_ENABLED:
            abort(404)
        if not session.get('admin'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated


# ─── Frontend ─────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


# ─── Public API ───────────────────────────────────────────────────────────────

@app.route('/api/products')
def api_products():
    return jsonify(load_json(PRODUCTS_FILE))


@app.route('/api/journal')
def api_journal():
    return jsonify(load_json(JOURNAL_FILE))


@app.route('/api/contact', methods=['POST'])
def api_contact():
    data = request.json or {}
    name    = data.get('name', '').strip()
    email   = data.get('email', '').strip()
    message = data.get('message', '').strip()

    if not (name and email and message):
        return jsonify({'error': 'All fields are required.'}), 400

    messages = load_json(MESSAGES_FILE)
    messages.append({'name': name, 'email': email, 'message': message})
    save_json(MESSAGES_FILE, messages)
    return jsonify({'ok': True}), 200


# ─── Admin Auth ───────────────────────────────────────────────────────────────

@app.route('/admin')
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if not ADMIN_ENABLED:
        abort(404)
    if session.get('admin'):
        return redirect(url_for('admin_dashboard'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
        error = 'Invalid username or password.'

    return render_template('admin_login.html', error=error)


@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    if not ADMIN_ENABLED:
        abort(404)
    session.pop('admin', None)
    return redirect(url_for('admin_login'))


@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    return render_template('admin.html')


# ─── Admin API — Products ─────────────────────────────────────────────────────

@app.route('/api/admin/products', methods=['GET'])
@admin_required
def admin_get_products():
    return jsonify(load_json(PRODUCTS_FILE))


@app.route('/api/admin/products', methods=['POST'])
@admin_required
def admin_add_product():
    products = load_json(PRODUCTS_FILE)
    data     = request.json or {}
    new_id   = max((p['id'] for p in products), default=0) + 1

    product = {
        'id':          new_id,
        'name':        data.get('name', '').strip(),
        'category':    data.get('category', '').strip(),
        'price':       data.get('price', '').strip(),
        'description': data.get('description', '').strip(),
        'image_url':   data.get('image_url', None) or None,
        'featured':    bool(data.get('featured', False)),
    }
    products.append(product)
    save_json(PRODUCTS_FILE, products)
    return jsonify(product), 201


@app.route('/api/admin/products/<int:product_id>', methods=['PUT'])
@admin_required
def admin_update_product(product_id):
    products = load_json(PRODUCTS_FILE)
    data     = request.json or {}

    for p in products:
        if p['id'] == product_id:
            p['name']        = data.get('name', p['name']).strip()
            p['category']    = data.get('category', p['category']).strip()
            p['price']       = data.get('price', p['price']).strip()
            p['description'] = data.get('description', p.get('description', '')).strip()
            p['image_url']   = data.get('image_url', p.get('image_url')) or None
            p['featured']    = bool(data.get('featured', p.get('featured', False)))
            save_json(PRODUCTS_FILE, products)
            return jsonify(p)

    return jsonify({'error': 'Product not found.'}), 404


@app.route('/api/admin/products/<int:product_id>', methods=['DELETE'])
@admin_required
def admin_delete_product(product_id):
    products = load_json(PRODUCTS_FILE)
    products = [p for p in products if p['id'] != product_id]
    save_json(PRODUCTS_FILE, products)
    return '', 204


# ─── Admin API — Journal ──────────────────────────────────────────────────────

@app.route('/api/admin/journal', methods=['GET'])
@admin_required
def admin_get_journal():
    return jsonify(load_json(JOURNAL_FILE))


@app.route('/api/admin/journal', methods=['POST'])
@admin_required
def admin_add_post():
    posts  = load_json(JOURNAL_FILE)
    data   = request.json or {}
    new_id = max((p['id'] for p in posts), default=0) + 1

    post = {
        'id':        new_id,
        'title':     data.get('title', '').strip(),
        'category':  data.get('category', '').strip(),
        'excerpt':   data.get('excerpt', '').strip(),
        'body':      data.get('body', '').strip(),
        'date':      data.get('date', '').strip(),
        'image_url': data.get('image_url', None) or None,
    }
    posts.append(post)
    save_json(JOURNAL_FILE, posts)
    return jsonify(post), 201


@app.route('/api/admin/journal/<int:post_id>', methods=['PUT'])
@admin_required
def admin_update_post(post_id):
    posts = load_json(JOURNAL_FILE)
    data  = request.json or {}

    for p in posts:
        if p['id'] == post_id:
            p['title']     = data.get('title', p['title']).strip()
            p['category']  = data.get('category', p['category']).strip()
            p['excerpt']   = data.get('excerpt', p.get('excerpt', '')).strip()
            p['body']      = data.get('body', p.get('body', '')).strip()
            p['date']      = data.get('date', p.get('date', '')).strip()
            p['image_url'] = data.get('image_url', p.get('image_url')) or None
            save_json(JOURNAL_FILE, posts)
            return jsonify(p)

    return jsonify({'error': 'Post not found.'}), 404


@app.route('/api/admin/journal/<int:post_id>', methods=['DELETE'])
@admin_required
def admin_delete_post(post_id):
    posts = load_json(JOURNAL_FILE)
    posts = [p for p in posts if p['id'] != post_id]
    save_json(JOURNAL_FILE, posts)
    return '', 204


# ─── Admin API — Messages ─────────────────────────────────────────────────────

@app.route('/api/admin/messages', methods=['GET'])
@admin_required
def admin_get_messages():
    return jsonify(load_json(MESSAGES_FILE))


# ─── Admin API — Image Upload ─────────────────────────────────────────────────

@app.route('/api/admin/upload', methods=['POST'])
@admin_required
def admin_upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file sent.'}), 400
    f = request.files['file']
    if f.filename == '' or not allowed_file(f.filename):
        return jsonify({'error': 'Invalid file type. Use PNG, JPG, GIF or WebP.'}), 400
    result = cloudinary.uploader.upload(f, folder='manuels-emporium')
    return jsonify({'url': result['secure_url']}), 201


if __name__ == '__main__':
    app.run(debug=True)
