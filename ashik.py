# ashik.py  — FAST version, Cloudinary-backed encodings JSON, GROUP support
import os
import io
import json
import time
import qrcode
import threading
import requests
import face_recognition
import numpy as np
from io import BytesIO
from PIL import Image
from flask import (
    Flask, render_template, request, redirect, url_for, flash, session,
    jsonify, send_file, Response, stream_with_context, send_from_directory
)
import cloudinary
import cloudinary.uploader
import cloudinary.api
from dotenv import load_dotenv

# -------------------- CONFIG --------------------
load_dotenv()
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("SECRET_KEY", "ashik_smartpix_secret")

# Cloudinary config
cloudinary.config(
    cloud_name=os.getenv("CLOUD_NAME", "dcelcw5aa"),
    api_key=os.getenv("API_KEY", "887344271542454"),
    api_secret=os.getenv("API_SECRET", "_Ch0vgdSGJiDZI4Gjmx44Wq4ids"),
    secure=True
)

# -------------------- PATHS & SETTINGS --------------------
ENCODINGS_DIR = "encodings"
UPLOADS_DIR = "uploads"
QR_DIR = os.path.join("static", "qr_codes")

os.makedirs(ENCODINGS_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(QR_DIR, exist_ok=True)

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:5000")
STUDIO_LOGO_NAME = os.getenv("STUDIO_LOGO_NAME", "studio_logo")

# Photographers (change or load from secure store)
PHOTOGRAPHER_CREDENTIALS = {
    "ashik": {"password": "1234", "event": "event_A"},
    "royal": {"password": "5678", "event": "event_B"},
    "frame": {"password": "9999", "event": "event_C"},
    "rasin": {"password": "0987", "event": "event_D"}
}

# -------------------- HELPERS --------------------
def generate_qr(event):
    link = f"{BASE_URL}/guest/{event}"
    qr_path = os.path.join(QR_DIR, f"{event}_QR.png")
    img = qrcode.make(link)
    img.save(qr_path)
    print("✅ QR Generated:", qr_path, "->", link)
    return qr_path, link

def local_encoding_path(event):
    return os.path.join(ENCODINGS_DIR, f"{event}.json")

def load_local_encodings(event):
    p = local_encoding_path(event)
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r") as f:
            return json.load(f)
    except Exception as e:
        print("⚠️ Failed to load local encodings:", e)
        return []

def save_local_encodings(event, enc_list):
    p = local_encoding_path(event)
    try:
        with open(p, "w") as f:
            json.dump(enc_list, f)
        print("💾 Saved local encodings:", p)
        return True
    except Exception as e:
        print("❌ Could not save local encodings:", e)
        return False

def upload_encodings_to_cloud(event):
    """Upload encodings JSON to Cloudinary as a raw resource (persistent)."""
    p = local_encoding_path(event)
    if not os.path.exists(p):
        print("⚠️ No local encodings to upload for", event)
        return None
    pubid = f"encodings/{event}/encodings"
    try:
        res = cloudinary.uploader.upload(
            p,
            public_id=pubid,
            resource_type="raw",
            overwrite=True
        )
        print("☁️ Uploaded encodings JSON to Cloudinary:", pubid)
        return res
    except Exception as e:
        print("❌ Upload encodings to Cloudinary failed:", e)
        return None

def get_cloudinary_encodings_url(event):
    pubid = f"encodings/{event}/encodings"
    try:
        res = cloudinary.api.resource(pubid, resource_type="raw")
        url = res.get("secure_url") or res.get("url")
        return url
    except Exception:
        return None

def download_encodings_from_cloud(event):
    url = get_cloudinary_encodings_url(event)
    if not url:
        print("⚠️ No encodings file in Cloudinary for", event)
        return None
    try:
        r = requests.get(url, timeout=20)
        if r.status_code != 200:
            print("⚠️ Cloudinary encodings download returned", r.status_code)
            return None
        enc_list = json.loads(r.content.decode("utf-8"))
        save_local_encodings(event, enc_list)
        print("☁️ Downloaded encodings JSON from Cloudinary for", event)
        return enc_list
    except Exception as e:
        print("❌ Failed downloading encodings from Cloudinary:", e)
        return None

# -------------------- ENCODING GENERATION (GROUP SUPPORT) --------------------
def generate_encodings_for_event(event):
    """
    List images in Cloudinary folder {event}/known_faces,
    extract all face encodings from each image (group support),
    append each face as a separate encoding entry {public_id, url, encoding},
    save local JSON and upload JSON to Cloudinary.
    """
    print(f"🔄 Generating encodings for event: {event}")
    folder_prefix = f"{event}/known_faces"
    try:
        response = cloudinary.api.resources(
            prefix=folder_prefix,
            type="upload",
            resource_type="image",
            max_results=500
        )
        resources = response.get("resources", [])
    except Exception as e:
        print("❌ Cloudinary list error:", e)
        return False

    existing = load_local_encodings(event)
    existing_pubid_url_pairs = {(item.get("public_id"), item.get("face_index", 0)) for item in existing}
    updated_list = existing[:]  # keep existing entries

    added = 0
    for res in resources:
        pubid = res.get("public_id")
        url = res.get("secure_url") or res.get("url")
        if not pubid or not url:
            continue

        # Download image once
        try:
            r = requests.get(url, timeout=20)
            if r.status_code != 200:
                print("⚠️ Failed to download image:", url)
                continue
            img = face_recognition.load_image_file(BytesIO(r.content))
            encs = face_recognition.face_encodings(img)
            if not encs:
                print("⚠️ No faces detected in image:", pubid)
                continue
            # Store ALL faces found in the image (group support)
            for idx, enc in enumerate(encs):
                # avoid duplicates (public_id + index)
                key = (pubid, idx)
                if key in existing_pubid_url_pairs:
                    continue
                item = {
                    "public_id": pubid,
                    "face_index": idx,
                    "url": url,
                    "encoding": enc.tolist()
                }
                updated_list.append(item)
                added += 1
            if encs:
                print(f"✔️ Added {len(encs)} faces from {pubid}")
        except Exception as e:
            print("⚠️ Error processing image", pubid, e)
            continue

    if added > 0:
        saved = save_local_encodings(event, updated_list)
        if saved:
            upload_res = upload_encodings_to_cloud(event)
            if upload_res:
                print(f"🎉 Encodings JSON uploaded to Cloudinary for {event}")
    else:
        print("ℹ️ No new faces to encode.")
    return True

# -------------------- BACKGROUND (light) --------------------
def background_worker(interval=600):
    while True:
        # placeholder: could periodically refresh encodings, but avoid heavy ops
        time.sleep(interval)

threading.Thread(target=background_worker, daemon=True).start()

# -------------------- ROUTES --------------------
@app.route("/")
def home():
    return render_template("index.html")

# Photographer login
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        user = PHOTOGRAPHER_CREDENTIALS.get(username)
        if user and user["password"] == password:
            session["user"] = username
            session["event"] = user["event"]
            flash(f"Welcome, {username}!", "success")
            return redirect(url_for("event_upload"))
        else:
            flash("Invalid credentials", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out", "info")
    return redirect(url_for("login"))

# Photographer upload page
@app.route("/event_upload", methods=["GET", "POST"])
def event_upload():
    if "user" not in session:
        return redirect(url_for("login"))
    
    event = session["event"]
    
    if request.method == "POST":
        files = request.files.getlist("files[]")
        uploaded = 0
        
        for file in files:
            if file and file.filename:
                try:
                    img = Image.open(file.stream)
                    img = img.convert("RGB")
                    img.thumbnail((2048, 2048))
                    buffer = BytesIO()
                    img.save(buffer, format="JPEG", quality=85)
                    buffer.seek(0)
                    cloudinary.uploader.upload(
                        buffer,
                        folder=f"{event}/known_faces",
                        resource_type="image"
                    )
                    uploaded += 1
                except Exception as e:
                    flash(f"Upload failed for {file.filename}: {e}", "danger")
        if uploaded > 0:
            # generate encodings (this will add all faces from group photos)
            generate_encodings_for_event(event)
        qr_path, guest_link = generate_qr(event)
        filename = os.path.basename(qr_path)
        flash(f"Uploaded {uploaded} images. QR generated.", "success")
        return render_template("dashboard.html", event=event, filename=filename, guest_link=guest_link)
    return render_template("event_upload.html", event=event)

# Guest page (selfie capture UI)
@app.route("/guest/<event>", methods=["GET"])
def guest(event):
    session["event"] = event
    return render_template("index.html", event=event)

# Selfie upload and fast match (uses precomputed JSON)
@app.route("/upload/<event>", methods=["POST"])
def upload_selfie(event):
    print(f"🔥 Guest selfie upload for event: {event}")
    session["event"] = event

    file = request.files.get("file")
    if not file:
        print("❌ No selfie file received")
        flash("Please upload a selfie.", "warning")
        return redirect(url_for("guest", event=event))

    os.makedirs(UPLOADS_DIR, exist_ok=True)
    selfie_path = os.path.join(UPLOADS_DIR, "selfie.jpg")
    file.save(selfie_path)
    print("✅ Selfie saved:", selfie_path)

    # encode selfie
    try:
        selfie_img = face_recognition.load_image_file(selfie_path)
        selfie_encs = face_recognition.face_encodings(selfie_img)
    except Exception as e:
        print("❌ Error reading selfie:", e)
        selfie_encs = []

    if not selfie_encs:
        print("😕 No face found in selfie.")
        session["matches"] = []
        return redirect(url_for("result"))

    selfie_enc = selfie_encs[0]
    print("🧠 Selfie encoding length:", len(selfie_enc))

    # Load encodings (local or cloud)
    enc_list = load_local_encodings(event)
    if not enc_list:
        print("⚠️ Local encodings missing, trying Cloudinary download...")
        enc_list = download_encodings_from_cloud(event) or []
        if not enc_list:
            print("❌ No encodings available. Photographer needs to upload images first.")
            session["matches"] = []
            return redirect(url_for("result"))

    print(f"🔍 Comparing against {len(enc_list)} precomputed encodings...")
    matches = []
    for item in enc_list:
        try:
            known_enc = np.array(item["encoding"])
            url = item.get("url")
            is_match = face_recognition.compare_faces([known_enc], selfie_enc, tolerance=0.55)
            if is_match and is_match[0]:
                # add url only once
                if url not in matches:
                    matches.append(url)
        except Exception as e:
            print("⚠️ Compare error:", e)
            continue

    session["matches"] = matches
    print(f"🎯 Found {len(matches)} matches.")
    return redirect(url_for("result"))

# Result page
@app.route("/result")
def result():
    try:
        matches = session.get("matches", [])
        print("✅ Sending matches to result.html:", len(matches))
        return render_template("result.html", matches=matches)
    except Exception as e:
        print("❌ Error rendering result page:", e)
        return "Server error", 500
    
#link----- 
@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():

    # event ALWAYS comes from session
    event = session.get("event")

    if not event:
        return redirect(url_for("login"))

    # ALWAYS create guest link
    guest_link = f"{BASE_URL}/guest/{event}"

    # QR filename ALWAYS same
    filename = f"{event}_QR.png"

    # If user pressed "Generate QR Again"
    if request.method == "POST":
        generate_qr(event)

    # Send ALL required values to HTML
    return render_template(
        "dashboard.html",
        event=event,
        filename=filename,
        guest_link=guest_link
    )

# Download QR
@app.route("/download_qr/<filename>")
def download_qr(filename):
    return send_from_directory(QR_DIR, filename, as_attachment=True)

# Download image (proxy)
@app.route("/download")
def download_image():
    img_url = request.args.get("url")
    if not img_url:
        return "No URL specified", 400
    try:
        r = requests.get(img_url, timeout=20)
        if r.status_code != 200:
            return "Could not fetch image", 500
        # use original filename if possible
        return send_file(BytesIO(r.content), mimetype="image/jpeg", as_attachment=True, download_name="AshiSmartPix.jpg")
    except Exception as e:
        print("❌ Download error:", e)
        return "Server error", 500

# Progress SSE (optional)
@app.route("/progress_stream")
def progress_stream():
    def generate():
        total = 10
        for i in range(1, total + 1):
            yield f"data: {json.dumps({'progress': i, 'total': total})}\n\n"
            time.sleep(0.2)
        yield f"data: {json.dumps({'done': True})}\n\n"
    return Response(stream_with_context(generate()), mimetype="text/event-stream")

# -------------------- MAIN --------------------
if __name__ == "__main__":
    print("🚀 Ashi SmartPix (GROUP + Cloud JSON) running at http://127.0.0.1:5000")
    app.run(debug=True, threaded=True, use_reloader=False)
