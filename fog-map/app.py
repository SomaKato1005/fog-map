"""
霧の地図 - Fog of War Map Application
- ユーザー名 + パスワード認証（ドメイン・HTTPS不要）
- ユーザーごとにピン・探索済みエリア・写真を分離
- SQLite で永続化、写真はディスク保存
"""

import os
import uuid
import base64
import hashlib
import secrets
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, jsonify,
    redirect, url_for, session, g, send_from_directory
)
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, "templates"),
            static_folder=os.path.join(BASE_DIR, "static"))
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///fogmap.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

db = SQLAlchemy(app)

# ─────────────────────────────────────────
#  MODELS
# ─────────────────────────────────────────

class User(db.Model):
    __tablename__ = "users"
    id            = db.Column(db.String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    username      = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    display_name  = db.Column(db.String(128), default="")
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    pins          = db.relationship("Pin",          backref="user", lazy=True, cascade="all, delete-orphan")
    spots         = db.relationship("ExploredSpot", backref="user", lazy=True, cascade="all, delete-orphan")
    photos        = db.relationship("Photo",        backref="user", lazy=True, cascade="all, delete-orphan")

class Pin(db.Model):
    __tablename__ = "pins"
    id         = db.Column(db.String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id    = db.Column(db.String(64), db.ForeignKey("users.id"), nullable=False)
    lat        = db.Column(db.Float, nullable=False)
    lng        = db.Column(db.Float, nullable=False)
    name       = db.Column(db.String(256), default="")
    note       = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id, "lat": self.lat, "lng": self.lng,
            "name": self.name, "note": self.note,
            "created_at": self.created_at.isoformat(),
        }

class ExploredSpot(db.Model):
    __tablename__ = "explored_spots"
    id          = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id     = db.Column(db.String(64), db.ForeignKey("users.id"), nullable=False)
    lat         = db.Column(db.Float, nullable=False)
    lng         = db.Column(db.Float, nullable=False)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)

class Photo(db.Model):
    __tablename__ = "photos"
    id             = db.Column(db.String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id        = db.Column(db.String(64), db.ForeignKey("users.id"), nullable=False)
    lat            = db.Column(db.Float, nullable=False)
    lng            = db.Column(db.Float, nullable=False)
    filename       = db.Column(db.String(256), nullable=False)
    thumb_filename = db.Column(db.String(256), nullable=True)
    note           = db.Column(db.Text, default="")
    taken_at       = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id":        self.id,
            "lat":       self.lat,
            "lng":       self.lng,
            "url":       f"/uploads/{self.filename}",
            "thumb_url": f"/uploads/{self.thumb_filename}" if self.thumb_filename else f"/uploads/{self.filename}",
            "note":      self.note,
            "taken_at":  self.taken_at.isoformat(),
        }

# ─────────────────────────────────────────
#  パスワードのハッシュ化（標準ライブラリのみ）
# ─────────────────────────────────────────

def hash_password(password: str, salt: str = None):
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000)
    return f"{salt}:{hashed.hex()}"

def verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split(":", 1)
        return secrets.compare_digest(stored, hash_password(password, salt))
    except Exception:
        return False

# ─────────────────────────────────────────
#  AUTH HELPER
# ─────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return (jsonify({"error": "unauthorized"}), 401) if request.is_json \
                   else redirect(url_for("index"))
        g.user = db.session.get(User, session["user_id"])
        if not g.user:
            session.clear()
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated

# ─────────────────────────────────────────
#  ROUTES — 認証
# ─────────────────────────────────────────

@app.route("/")
def index():
    if "user_id" not in session:
        return render_template("login.html", error=None)
    user = db.session.get(User, session["user_id"])
    if user is None:
        # DBが消えた・セッションが古い場合はログアウト扱い
        session.clear()
        return render_template("login.html", error="セッションが切れました。再度ログインしてください。")
    return render_template("index.html", user=user)

@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    user = User.query.filter_by(username=username).first()
    if not user or not verify_password(password, user.password_hash):
        return render_template("login.html", error="ユーザー名またはパスワードが違います")
    session["user_id"] = user.id
    return redirect(url_for("index"))

@app.route("/register", methods=["POST"])
def register():
    username     = request.form.get("username", "").strip()
    password     = request.form.get("password", "")
    display_name = request.form.get("display_name", "").strip() or username

    if not username or not password:
        return render_template("login.html", error="ユーザー名とパスワードを入力してください")
    if len(username) < 3:
        return render_template("login.html", error="ユーザー名は3文字以上にしてください")
    if len(password) < 6:
        return render_template("login.html", error="パスワードは6文字以上にしてください")
    if User.query.filter_by(username=username).first():
        return render_template("login.html", error="そのユーザー名はすでに使われています")

    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name,
    )
    db.session.add(user)
    db.session.commit()
    session["user_id"] = user.id
    return redirect(url_for("index"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# ─────────────────────────────────────────
#  ROUTES — ファイル配信
# ─────────────────────────────────────────

@app.route("/uploads/<path:filename>")
@login_required
def serve_upload(filename):
    if not filename.startswith(g.user.id + "_"):
        return "forbidden", 403
    return send_from_directory(UPLOAD_DIR, filename)

# ─────────────────────────────────────────
#  ROUTES — Pins
# ─────────────────────────────────────────

@app.route("/api/pins", methods=["GET"])
@login_required
def get_pins():
    pins = Pin.query.filter_by(user_id=g.user.id).order_by(Pin.created_at.desc()).all()
    return jsonify([p.to_dict() for p in pins])

@app.route("/api/pins", methods=["POST"])
@login_required
def add_pin():
    data = request.get_json()
    pin  = Pin(user_id=g.user.id, lat=data["lat"], lng=data["lng"],
               name=data.get("name", ""), note=data.get("note", ""))
    db.session.add(pin); db.session.commit()
    return jsonify(pin.to_dict()), 201

@app.route("/api/pins/<pin_id>", methods=["PUT"])
@login_required
def update_pin(pin_id):
    pin  = Pin.query.filter_by(id=pin_id, user_id=g.user.id).first_or_404()
    data = request.get_json()
    pin.name = data.get("name", pin.name)
    pin.note = data.get("note", pin.note)
    db.session.commit()
    return jsonify(pin.to_dict())

@app.route("/api/pins/<pin_id>", methods=["DELETE"])
@login_required
def delete_pin(pin_id):
    pin = Pin.query.filter_by(id=pin_id, user_id=g.user.id).first_or_404()
    db.session.delete(pin); db.session.commit()
    return jsonify({"ok": True})

# ─────────────────────────────────────────
#  ROUTES — Explored spots
# ─────────────────────────────────────────

@app.route("/api/spots", methods=["GET"])
@login_required
def get_spots():
    spots = ExploredSpot.query.filter_by(user_id=g.user.id).all()
    return jsonify([{"lat": s.lat, "lng": s.lng} for s in spots])

@app.route("/api/spots", methods=["POST"])
@login_required
def add_spots():
    data = request.get_json()
    for item in data:
        db.session.add(ExploredSpot(user_id=g.user.id, lat=item["lat"], lng=item["lng"]))
    db.session.commit()
    return jsonify({"ok": True, "count": len(data)})

# ─────────────────────────────────────────
#  ROUTES — Photos
# ─────────────────────────────────────────

@app.route("/api/photos", methods=["GET"])
@login_required
def get_photos():
    photos = Photo.query.filter_by(user_id=g.user.id).order_by(Photo.taken_at.desc()).all()
    return jsonify([p.to_dict() for p in photos])

@app.route("/api/photos", methods=["POST"])
@login_required
def upload_photo():
    data       = request.get_json()
    lat        = data.get("lat")
    lng        = data.get("lng")
    note       = data.get("note", "")
    img_data   = data.get("image", "")
    thumb_data = data.get("thumb", "")

    if not img_data or lat is None or lng is None:
        return jsonify({"error": "lat/lng/image required"}), 400

    def decode_b64(raw):
        if "," in raw:
            raw = raw.split(",", 1)[1]
        return base64.b64decode(raw)

    try:
        image_bytes = decode_b64(img_data)
    except Exception:
        return jsonify({"error": "invalid image data"}), 400

    uid    = str(uuid.uuid4())
    prefix = g.user.id + "_"

    filename = f"{prefix}{uid}.jpg"
    with open(os.path.join(UPLOAD_DIR, filename), "wb") as f:
        f.write(image_bytes)

    thumb_filename = None
    if thumb_data:
        try:
            thumb_bytes    = decode_b64(thumb_data)
            thumb_filename = f"{prefix}{uid}_thumb.jpg"
            with open(os.path.join(UPLOAD_DIR, thumb_filename), "wb") as f:
                f.write(thumb_bytes)
        except Exception:
            thumb_filename = None

    photo = Photo(
        user_id=g.user.id, lat=lat, lng=lng,
        filename=filename, thumb_filename=thumb_filename, note=note,
    )
    db.session.add(photo); db.session.commit()
    return jsonify(photo.to_dict()), 201

@app.route("/api/photos/<photo_id>", methods=["DELETE"])
@login_required
def delete_photo(photo_id):
    photo = Photo.query.filter_by(id=photo_id, user_id=g.user.id).first_or_404()
    for fname in [photo.filename, photo.thumb_filename]:
        if fname:
            try:
                os.remove(os.path.join(UPLOAD_DIR, fname))
            except FileNotFoundError:
                pass
    db.session.delete(photo); db.session.commit()
    return jsonify({"ok": True})

# ─────────────────────────────────────────
#  INIT
# ─────────────────────────────────────────

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    print("=" * 55)
    print("  霧の地図アプリを起動中...")
    print("  ブラウザで http://localhost:5000 を開いてください")
    print("=" * 55)
    app.run(debug=True, host="0.0.0.0", port=5000)
