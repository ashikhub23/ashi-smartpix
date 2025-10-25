import os
import io
import time
import qrcode
import threading
import requests
import face_recognition
from io import BytesIO
from PIL import Image
from flask import Flask, render_template, request, redirect, url_for, flash, session
import cloudinary
import cloudinary.uploader
import cloudinary.api
from cloudinary.utils import cloudinary_url
from dotenv import load_dotenv

# -------------------- CONFIG --------------------
load_dotenv()
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "ashik_photostudio_secret"

cloudinary.config(
    cloud_name=os.getenv("CLOUD_NAME"),
    api_key=os.getenv("API_KEY"),
    api_secret=os.getenv("API_SECRET"),
    secure=True
)
STUDIO_LOGO_NAME = "studio_logo"  #to change the logo or as watermark

# -------------------- PHOTOGRAPHERS --------------------
PHOTOGRAPHER_CREDENTIALS = {
    "ashik": {"password": "1234", "event": "event_A"},
    "rasin": {"password": "5678", "event": "event_B"},
    "imran": {"password": "9999", "event": "event_C"}
}

# -------------------- QR GENERATION --------------------
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:5000")

def generate_qr(event_name):
    """Generate unique QR code for each event automatically"""
    link = f"{BASE_URL}/guest/{event_name}"
    qr_path = f"static/qr_codes/{event_name}.png"
    os.makedirs("static/qr_codes", exist_ok=True)
    img = qrcode.make(link)
    img.save(qr_path)
    print(f"✅ QR Generated for {event_name}: {link}")
    return qr_path, link
# -------------------- AUTO REFRESH --------------------
def auto_refresh(interval=300):
    while True:
        print("Refreshing Cloudinary data...")
        time.sleep(interval)

threading.Thread(target=auto_refresh, daemon=True).start()

# -------------------- ROUTES --------------------
@app.route('/')
def home():
    return render_template('index.html')

# -------------------- LOGIN --------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = PHOTOGRAPHER_CREDENTIALS.get(username)
        if user and user['password'] == password:
            session['user'] = username
            session['event'] = user['event']
            flash(f"Welcome, {username}!", "success")
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))

# -------------------- DASHBOARD --------------------
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    event_name = session['event']
    qr_path, qr_link = generate_qr(event_name)

    try:
        result = cloudinary.api.resources(prefix=f"{event_name}/known_faces")
        images = result.get('resources', [])
    except Exception as e:
        print("Cloudinary error:", e)
        images = []

    return render_template(
        'dashboard.html',
        user=session['user'],
        event=event_name,
        images=images,
        qr_link=qr_link,
        qr_path=qr_path
    )

# -------------------- PHOTO UPLOAD --------------------
@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'user' not in session:
        flash("Login first!", "warning")
        return redirect(url_for('login'))

    event_name = session['event']
    upload_folder = f"{event_name}/known_faces"

    if request.method == 'POST':
        files = request.files.getlist('files')
        if not files:
            flash("No files selected!", "danger")
            return redirect(url_for('upload'))

        count = 0
        for file in files:
            try:
                img = Image.open(file)
                img = img.convert("RGB")
                img.thumbnail((1920, 1080))
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=85)
                buffer.seek(0)
                cloudinary.uploader.upload(buffer, folder=upload_folder, resource_type="image")
                count += 1
            except Exception as e:
                flash(f"Upload failed for {file.filename}: {e}", "danger")

        flash(f"✅ {count} photo(s) uploaded to {upload_folder}", "success")
        return redirect(url_for('dashboard'))

    return render_template('event_upload.html', user=session['user'], event=event_name)

# -------------------- GUEST SIDE --------------------
@app.route('/guest/<event_name>', methods=['GET', 'POST'])
def guest(event_name):
    matches = []

    if request.method == 'POST':
        selfie = request.files.get('selfie')
        if not selfie:
            flash("Please upload a selfie.", "warning")
            return redirect(request.url)

        # Load guest selfie
        with BytesIO() as selfie_bytes:
            selfie.save(selfie_bytes)
            selfie_bytes.seek(0)
            guest_img = face_recognition.load_image_file(selfie_bytes)
            guest_encs = face_recognition.face_encodings(guest_img)
            if not guest_encs:
                flash("No face detected in selfie.", "danger")
                return redirect(request.url)
            guest_enc = guest_encs[0]

        # Fetch Cloudinary images for event
        folder_path = f"{event_name}/known_faces"
        try:
            response = cloudinary.api.resources(type="upload", prefix=folder_path, max_results=100)
        except Exception as e:
            flash(f"Error fetching from Cloudinary: {e}", "danger")
            return redirect(request.url)

        for res in response.get("resources", []):
            img_url = res["secure_url"]
            try:
                r = requests.get(img_url)
                image = face_recognition.load_image_file(BytesIO(r.content))
                encs = face_recognition.face_encodings(image)
                for enc in encs:
                    match = face_recognition.compare_faces([guest_enc], enc, tolerance=0.55)
                    if match[0]:
                        try:
                            logo_overlay = f"{STUDIO_LOGO_NAME}"
                            watermarked_url, _ =cloudinary_url(
                                res['public_id'],transformation=[{'overlay': logo_overlay,'gravity':
                                    'south_east','opacity':75, 'width':250,
                                    'crop': 'scale'},{'quality':'auto'},{'fetch_format':'auto'}])
                            matches.append(watermarked_url)
                        except Exception as e:
                            print(f"Logo overlay failed: {e}")
                            matches.append(img_url)
                        break
            except Exception as err:
                print(f"Error comparing {img_url}: {err}")

    return render_template('result.html', matches=matches, event=event_name)

# -------------------- MAIN --------------------
if __name__ == '__main__':
    print("🚀 Wedding QR Business System running on http://127.0.0.1:5000")
    app.run(debug=True)
