from fileinput import filename
import os
import io
import json
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
    cloud_name=os.getenv("CLOUD_NAME"),
    api_key=os.getenv("API_KEY"),
    api_secret=os.getenv("API_SECRET"),
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

def generate_qr(event_name):
    link = f"{BASE_URL}/guest/{event_name}"
    folder = "static/qr_codes"
    qr_path = os.path.join(folder,f"{event_name}_QR.png")

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
        event_name= request.form.get("event_name")
        qr_path = generate_qr(event_name)
        filename = f"{event_name}_QR.png"
        return render_template("dashboard.html", event_name=event_name, filename=filename)
    return render_template("dashboard.html")

    event_name = session.get("event")

    # Define paths and QR link
    qr_path = f"qr_codes/{event_name}.png"
    qr_link = f"{BASE_URL}/guest/{event_name}"

    # Get uploaded images from Cloudinary (optional)
    try:
        result = cloudinary.api.resources(prefix=f"{event_name}/known_faces")
        images = result.get("resources", [])
    except Exception as e:
        print("Cloudinary error:", e)
        images = []

    return render_template(
        "dashboard.html",
        event_name=event_name,
        qr_link=qr_link,
        qr_path=qr_path,
        images=images
    )

# -------------------- PHOTO UPLOAD --------------------
@app.route("/event_upload", methods=["GET", "POST"])
def event_upload():
    if "user" not in session:
        return redirect(url_for("login"))

    event_name = session["event"]

    if request.method == "POST":
        uploaded_files = request.files.getlist("files[]")
        for file in uploaded_files:
            if file and file.filename:
                cloudinary.uploader.upload(
                    file,
                    folder=f"{event_name}/known_faces"
                )

        # ✅ Generate QR after uploading faces
        qr_path = generate_qr(event_name)
        filename = f"{event_name}_QR.png"
        guest_link = f"{BASE_URL}/guest/{event_name}"

        print("✅ QR Generated and saved at:", qr_path)

        return render_template("dashboard.html",
                                event_name=event_name,
                                upload="success",
                                filename=filename,
                                qr_link=f"{BASE_URL}/guest/{event_name}",
                                guest_link=f"{BASE_URL}/guest/{event_name}")

    # GET Request
    return render_template("event_upload.html", event_name=event_name)

               
#--------------selfie-----------
@app.route("/upload", methods=["POST"])
def upload_selfie(event_name):
    try:
        file = request.files["file"]
        os.makedirs("uploads", exist_ok=True)
        selfie_path = os.path.join("uploads", "selfie.jpg")
        file.save(selfie_path)
        print("✅ Selfie uploaded successfully:", selfie_path)

        # Load uploaded selfie
        selfie_img = face_recognition.load_image_file(selfie_path)
        selfie_encodings = face_recognition.face_encodings(selfie_img)

        if not selfie_encodings:
            print("😕 No face found in selfie")
            return jsonify({"status": "error", "message": "No face detected in selfie"}), 400

        selfie_encoding = selfie_encodings[0]

        # Fetch all images from Cloudinary (Event Folder)
        response = cloudinary.api.resources(type="upload", prefix=f"{event_name}/known_faces")  # Change if event name differs
        matched_photos = []
        total_checked = 0

        print("☁️ Fetching images from Cloudinary...")

        for img in response.get("resources", []):
            img_url = img["secure_url"]
            total_checked += 1
            print(f"🔍 Checking photo {total_checked}/{len(response.get('resources',[]))}")

            # Download the Cloudinary image
            img_response = requests.get(img_url)
            known_img = face_recognition.load_image_file(BytesIO(img_response.content))
            encodings = face_recognition.face_encodings(known_img)

            if not encodings:
                continue  # Skip images with no faces

            # ✅ Compare selfie with *all* faces in the image
            matches = face_recognition.compare_faces(encodings, selfie_encoding, tolerance=0.55)

            # ✅ If *any* face matches, add the image
            if True in matches:
                matched_photos.append(img_url)

        print(f"🔍 Checked {total_checked} images, found {len(matched_photos)} matches.")

        # Save matches in session and redirect to result page
        session['matches'] = matched_photos
        return redirect(url_for("result"))

    except Exception as e:
        print(f"❌ Error in upload_selfie: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
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
#---------download route--------
@app.route("/download_qr/<filename>")
def download_qr(filename):
    return send_from_directory("static/qr_codes", filename, as_attachment=True)


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
    
