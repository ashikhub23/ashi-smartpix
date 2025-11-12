from fileinput import filename
import os
import io
import json
from re import search
from sys import prefix
import time
import qrcode
import threading
import requests
import face_recognition
from io import BytesIO
from PIL import Image
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file, Response, stream_with_context, send_from_directory
import cloudinary
import cloudinary.uploader
import cloudinary.api
from cloudinary.utils import cloudinary_url
from dotenv import load_dotenv

# -------------------- CONFIG --------------------
load_dotenv()
app = Flask(__name__, template_folder="templates", static_folder="static")


cloudinary.config(
    cloud_name="dcelcw5aa",
    api_key="887344271542454",
    api_secret="_Ch0vgdSGJiDZI4Gjmx44Wq4ids",
    secure=True
)
STUDIO_LOGO_NAME = "studio_logo"  #to change the logo or as watermark

# -------------------- PHOTOGRAPHERS --------------------
PHOTOGRAPHER_CREDENTIALS = {
    "ashik": {"password": "1234", "event": "event_A"},
    "royal": {"password": "5678", "event": "event_B"},
    "frame": {"password": "9999", "event": "event_C"},
    "rasin": {"password": "0987", "event": "event_D"}
}

# -------------------- QR GENERATION --------------------
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:5000")

def generate_qr(event):
    link = f"{BASE_URL}/guest/{event}"
    folder = "static/qr_codes"
    qr_path = os.path.join(folder,f"{event}_QR.png")

    os.makedirs(folder, exist_ok=True)
    qr = qrcode.QRCode(
        version=1,
        box_size=10,
        border=5
    )
    qr.add_data(link)
    qr.make(fit=True)

    img = qrcode.make(link)

    img.save(qr_path)

    print("✅ QR Generated :", qr_path)
    return qr_path

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
            return redirect(url_for('event_upload'))
        else:
            flash('Invalid credentials', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))

# ------------------ DASHBOARD ------------------ #
@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if request.method == "POST":
        event= request.form.get("event")
        qr_path = generate_qr(event)
        filename = f"{event}_QR.png"
        return render_template("dashboard.html", event=event, filename=filename)
    return render_template("dashboard.html")

# -------------------- PHOTO UPLOAD --------------------
@app.route("/event_upload", methods=["GET", "POST"])
def event_upload():
    if "user" not in session:
        return redirect(url_for("login"))

    event = session["event"]

    if request.method == "POST":
        uploaded_files = request.files.getlist("files[]")
        for file in uploaded_files:
            if file and file.filename:
                cloudinary.uploader.upload(
                    file,
                    folder=f"{event}/known_faces"
                )

        # ✅ Generate QR after uploading faces
        qr_path = generate_qr(event)
        filename = f"{event}_QR.png"
        guest_link = f"{BASE_URL}/guest/{event}"

        print("✅ QR Generated and saved at:", qr_path)

        return render_template("dashboard.html",
                                event=event,
                                upload="success",
                                filename=filename,
                                qr_link=guest_link,
                                guest_link=guest_link)

    # GET Request
    return render_template("event_upload.html", event=event)
              
#--------------selfie-----------
@app.route("/upload/<event>", methods=["POST"])
def upload_selfie(event):
    print(f"🔥 Guest upload started for event: {event}")
    print(f"🧩 DEBUG — Event received in Flask route: '{event}'")
    try:
        print(f"\n🔥 Guest upload started for event: {event}")
        session["event"] = event

        # --- Selfie upload ---
        file = request.files.get("file")
        if not file:
            print("❌ No selfie file received")
            return "No file received", 400

        os.makedirs("uploads", exist_ok=True)
        selfie_path = os.path.join("uploads", "selfie.jpg")
        file.save(selfie_path)
        print(f"✅ Selfie uploaded successfully → {selfie_path}")

        # --- Face encoding for selfie ---
        selfie_img = face_recognition.load_image_file(selfie_path)
        selfie_encodings = face_recognition.face_encodings(selfie_img)
        if not selfie_encodings:
            print("😕 No face found in selfie.")
            session["matches"] = []
            return redirect(url_for("result"))

        selfie_encoding = selfie_encodings[0]
        print(f"🧠 Selfie encodings length = {len(selfie_encoding)}")

        # --- Fetch Cloudinary folder (final working version) ---
        folder_path = f"{event}/known_faces"
        print(f"📂 Checking Cloudinary folder path → '{folder_path}'")

        try:
            response = cloudinary.api.resources(
                prefix=folder_path,
                type="upload",
                resource_type="image",
                max_results=100
            )

            resources = response.get("resources", [])
            total_resources = len(resources)
            print(f"📸 Found {total_resources} Cloudinary images for event '{event}'")

            if total_resources == 0:
                print("⚠️ No images found in this event folder.")
        except Exception as e:
            print("❌ Cloudinary fetch error:", repr(e))
            return f"Cloudinary error: {e}", 500

        matched_photos = []

        # --- Compare each Cloudinary image with selfie ---
        for index, img in enumerate(resources, start=1):
            img_url = img["secure_url"]
            print(f"🔍 Checking image {index}/{total_resources} → {img_url}")

            try:
                img_response = requests.get(img_url, timeout=10)
                known_img = face_recognition.load_image_file(BytesIO(img_response.content))
                encodings = face_recognition.face_encodings(known_img)

                if not encodings:
                    print("⚠️ No face detected in:", img_url)
                    continue

                matches = face_recognition.compare_faces(encodings, selfie_encoding, tolerance=0.55)
                if True in matches:
                    print(f"✅ MATCH FOUND → {img_url}")
                    matched_photos.append(img_url)

            except Exception as err:
                print(f"⚠️ Error processing image {index}: {err}")

        # --- Save and show results ---
        session["matches"] = matched_photos
        print(f"🎯 FINAL MATCHES FOUND: {len(matched_photos)}")
        for m in matched_photos:
            print("   →", m)

        print("✅ Matches saved in session. Redirecting to result page.\n")
        return redirect(url_for("result"))

    except Exception as e:
        print(f"❌ SERVER ERROR: {e}\n")
        return "Server error", 500

app.secret_key = "ashik_smartpix_secret"

#------------progress-------
@app.route('/progress_stream')
def progress_stream():
    """Dummy progress stream (simulates scanning updates for front-end)"""
    def generate():
        total = 10  # Example count; just simulates 10 steps
        for i in range(1, total + 1):
            progress_data = {'progress': i, 'total': total}
            yield f"data: {json.dumps(progress_data)}\n\n"
            time.sleep(0.3)  # Simulate scanning time
        yield f"data: {json.dumps({'done': True})}\n\n"
    return Response(stream_with_context(generate()), mimetype='text/event-stream')
#result route
@app.route('/result')   # Flask: “When someone visits /result page...”
def result():
    try:
        # 👜 Open the student’s bag and check if there’s a paper called 'matches'
        matches = session.get('matches', [])
        print("✅ Matches being sent to result.html:", matches)
        print(f"🎯 Total matched photos: {len(matches)}")

        # 😕 If the bag has no 'matches' paper
        if not matches:
            print("⚠️ No matches found in session.")
            # Show empty result page
            return render_template('result.html', matches=[])

        # 🖼️ If matches exist, show them on the result.html page
        return render_template('result.html', matches=matches)

    except Exception as e:
        # 🚨 If anything breaks, show this message in terminal
        print(f"❌ Error loading result page: {e}")
        return f"Error displaying result page: {e}", 500

# -------------------- GUEST SIDE --------------------
@app.route('/guest/<event>')
def guest(event):
    print("🔥 Guest page opened for event:", event)
    session["event"] = event
    return render_template("index.html", event=event)

#---------download route--------
@app.route("/download_qr/<filename>")
def download_qr(filename):
    return send_from_directory("static/qr_codes", filename, as_attachment=True)
#download image
@app.route("/download")
def download_image():
    """Download image from Cloudinary and send to user"""
    img_url = request.args.get("url")
    if not img_url:
        return "No image URL provided", 400

    try:
        response = requests.get(img_url)
        if response.status_code != 200:
            return "Error downloading image", 500

        # Stream image bytes back to browser
        return send_file(
            BytesIO(response.content),
            mimetype='image/jpeg',
            as_attachment=True,
            download_name="AshiSmartPix_Photo.jpg"
        )
    except Exception as e:
        print(f"❌ Error in download route: {e}")
        return "Server error", 500
# -------------------- MAIN --------------------
if __name__ == '__main__':
    print("🚀 Wedding QR Business System running on http://127.0.0.1:5000")
    app.run(debug=True, use_reloader=False)
    
