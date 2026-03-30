from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import uuid
from werkzeug.utils import secure_filename
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
from datetime import datetime
from PyPDF2 import PdfReader
import razorpay
from flask import Flask, request, jsonify
import hmac
import hashlib
import cloudinary
import cloudinary.uploader
from pymongo import MongoClient
import uuid
import math
import random
from flask import send_file
from io import BytesIO
import requests

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from datetime import datetime,timezone
import zoneinfo
from flask import Flask
# from waitress import serve
from dotenv import load_dotenv
load_dotenv()







#rozerpay




app = Flask(__name__)
CORS(app)
# Razorpay
razorpay_client = razorpay.Client(auth=(
    os.getenv("RAZORPAY_KEY_ID"),
    os.getenv("RAZORPAY_KEY_SECRET")
))

# -------------------------
#page price
# -------------------------
COST_PER_PAGE = 1  # ₹1 per page
MAX_PAGES = 50

#app = Flask(__name__)

# IST = zoneinfo.ZoneInfo("Asia/Kolkata")

# Admin
ADMIN_ID = os.getenv("ADMIN_ID")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

PARTNER_ID = os.getenv("PARTNER_ID")
PARTNER_PASSWORD = os.getenv("PARTNER_PASSWORD")




# Google login
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")


# UPLOAD_FOLDER = "uploads"
# os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# in memory storage
# print_jobs = {}


# Cloudinary
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

#mongodb freee



mongo_client = MongoClient(os.getenv("MONGO_URI"))
db = mongo_client["printezy"]
jobs_collection = db["jobs"]

# print(db.list_collection_names())


# -------------------------
# CREATE PRINT JOB
# -------------------------
@app.route("/print", methods=["POST"])
def create_print_job():
    try:
        file = request.files.get("file")
        otp = request.form.get("otp")
        email = request.form.get("email")
        print_type = request.form.get("printType")
        pages = int(request.form.get("pages", 0))

        if not file or not otp or not email:
            return jsonify({"success": False, "message": "Missing data"}), 400

        email = email.lower()

        # Upload
        result = cloudinary.uploader.upload(
            file,
            resource_type="raw",
            folder="printflash"
        )
        file_url = result["secure_url"]

        # Cost
        cost_per_page = 1.5 if print_type == "double" else 1
        total_cost = ((pages + 1)//2)*cost_per_page if print_type=="double" else pages*cost_per_page

        # ✅ FIXED PRINT ID
        def generate_print_id():
            while True:
                new_id = str(random.randint(100000, 999999))
                if not jobs_collection.find_one({"_id": new_id}):
                    return new_id

        print_id = generate_print_id()

        job = {
            "_id": print_id,
            "user_email": email,
            "fileName": file.filename,
            "pages": pages,
            "print_type": print_type,
            "cost": total_cost,
            "file_url": file_url,
            "otp": str(otp),
            "status": "pending",
            # "created_at": datetime.now().strftime("%d %b %Y, %I:%M %p")
           "created_at": datetime.now(timezone.utc)
        }

        jobs_collection.insert_one(job)

        return jsonify({
            "success": True,
            "printId": print_id,
            "otp": otp,
            "file_url": file_url,
            "cost": total_cost
        })

    except Exception as e:
        print("UPLOAD ERROR:", e)
        return jsonify({"success": False}), 500



# -------------------------
# HISTORY (ALL USERS)
# -------------------------
@app.route("/history/<email>", methods=["GET"])
def history(email):
    try:
        email = email.lower()

        jobs = list(
            jobs_collection.find({"user_email": email}).sort("_id", -1)
        )

        result = []

        for job in jobs:
            result.append({
                "printId": str(job.get("_id")),
                "fileName": job.get("fileName", "Document.pdf"),
                "otp": job.get("otp"),
                "verified": job.get("status") == "printed",
                "created_at": job.get("created_at"),
                "printed_at": job.get("printed_at")
            })

        return jsonify(result)

    except Exception as e:
        print("HISTORY ERROR:", e)
        return jsonify([])
        
        
# -------------------------
# VERIFY AT PRINTER
# -------------------------
@app.route("/verify", methods=["POST"])
def verify():
    try:
        data = request.json

        # ✅ Safe extraction
        print_id = data.get("printId")
        otp = str(data.get("otp"))

        # ❌ Missing data check
        if not print_id or not otp:
            return jsonify({
                "verified": False,
                "message": "Missing printId or OTP"
            }), 400

        # 🔥 Atomic update (secure + prevents reuse)
        result = jobs_collection.update_one(
            {
                "_id": print_id,
                "otp": otp,
                "status": {"$ne": "printed"}
            },
            {
                "$set": {
                    "status": "printed",
                    "otp": None,
                    "printed_at": datetime.now(timezone.utc)
                }
            }
        )

        # ✅ Success
        if result.modified_count == 1:
            return jsonify({"verified": True})

        # ❌ Failed (wrong OTP / already printed)
        return jsonify({
            "verified": False,
            "message": "Invalid or already used"
        }), 400

    except Exception as e:
        print("Verify Error:", e)
        return jsonify({
            "verified": False,
            "message": "Server error"
        }), 500    
# -------------------------
# DOWNLOAD AFTER VERIFY
# -------------------------
@app.route("/download/<printId>", methods=["GET"])
def download(printId):
    job = jobs_collection.find_one({"_id": printId})

    if job and job.get("status") == "printed":
        file_url = job["file_url"]
        r = requests.get(file_url)  # ✅ correct

        if r.status_code == 200:
            return send_file(
                BytesIO(r.content),
                download_name=job["fileName"],
                mimetype="application/pdf"
            )
        else:
            return jsonify({"error": "File not found"}), 404

    return jsonify({"error": "Not authorized"}), 403

# -------------------------
# GOOGLE LOGIN
# -------------------------
@app.route("/google-login", methods=["POST"])
def google_login():
    data = request.json
    token = data.get("token")

    try:
        idinfo = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID
        )

        return jsonify({
            "success": True,
            "user": {
                "id": idinfo['sub'],
                "name": idinfo.get('name'),
                "email": idinfo['email'],
                "profilePic": idinfo.get("picture")
            }
        })

    except Exception as e:
        print("GOOGLE LOGIN ERROR:", e)
        return jsonify({"success": False}), 401


# -------------------------
# USER-SPECIFIC HISTORY
# -------------------------
# @app.route("/my-prints/<email>", methods=["GET"])
# def my_prints(email):
#     email = email.lower()
#     return jsonify(print_jobs.get(email, {}))


# -------------------------
# CALCULATE PDF PAGES
# -------------------------
@app.route("/calculate", methods=["POST"])
def calculate():
    try:
        file = request.files.get("file")

        if not file:
            return jsonify({"success": False, "message": "No file"}), 400

        reader = PdfReader(file)
        num_pages = len(reader.pages)

        if num_pages > MAX_PAGES:
            return jsonify({
                "success": False,
                "message": f"Max {MAX_PAGES} pages allowed. Your file has {num_pages} pages."
            }), 400

        total_cost = num_pages * COST_PER_PAGE

        return jsonify({
            "success": True,
            "pages": num_pages,
            "cost_per_page": COST_PER_PAGE,
            "total_cost": total_cost
        })

    except Exception as e:
        print("CALC ERROR:", e)
        return jsonify({"success": False}), 500


# -------------------------
# REAL-TIME COST API
# -------------------------
@app.route("/get-cost", methods=["POST"])
def get_cost():
    try:
        data = request.get_json()

        pages = int(data.get("pages", 0))
        print_type = data.get("printType")

        if pages == 0:
            return jsonify({"success": False, "message": "Pages missing"}), 400

      
        cost_per_page = 1.5 if print_type == "double" else 1

        if print_type == "double":
            
            if pages % 2 == 0:
                total_cost = (pages // 2) * cost_per_page
            else:
                total_cost = ((pages // 2) + 1) * cost_per_page
        else:
            
            total_cost = pages * cost_per_page

        return jsonify({
            "success": True,
            "cost_per_page": cost_per_page,
            "total_cost": total_cost
        })

    except Exception as e:
        print("COST ERROR:", e)
        return jsonify({"success": False}), 500




#rozerpay 
@app.route("/create-order", methods=["POST"])
def create_order():
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "No JSON received"}), 400

        amount = data.get("amount")

        if not amount:
            return jsonify({"error": "Amount missing"}), 400

        print("AMOUNT RECEIVED:", amount)

        order = razorpay_client.order.create({
            "amount": int(amount),  # ensure integer
            "currency": "INR",
            "payment_capture": 1
        })

        print("ORDER CREATED:", order)

        return jsonify({
            "order_id": order["id"]
        })

    except Exception as e:
        print("CREATE ORDER ERROR:", e)
        return jsonify({"error": str(e)}), 500







#verify rozerpay
@app.route("/verify-payment", methods=["POST"])
def verify_payment():
    data = request.json

    order_id = data["razorpay_order_id"]
    payment_id = data["razorpay_payment_id"]
    signature = data["razorpay_signature"]

    generated_signature = hmac.new(
        bytes(os.getenv("RAZORPAY_KEY_SECRET"), 'utf-8'),
        bytes(order_id + "|" + payment_id, 'utf-8'),
        hashlib.sha256
    ).hexdigest()

    if generated_signature == signature:
        return jsonify({"status": "success"})
    else:
        return jsonify({"status": "failed"})





 # Upload to Cloudinary

@app.route("/upload", methods=["POST"])
def upload_file():
    try:
        # 1️⃣ Get file and form data
        file = request.files["file"]
        pages = int(request.form.get("pages", 0))
        print_type = request.form.get("printType")
        user_email = request.form.get("email")

        # 2️⃣ Check pages
        if pages == 0:
            return jsonify({"success": False, "message": "Pages missing"}), 400

        # 3️⃣ Upload to Cloudinary
        result = cloudinary.uploader.upload(
            file,
            resource_type="raw",  # must for PDFs
            folder="printflash"
        )
        file_url = result["secure_url"]

        # 4️⃣ Calculate cost (your exact logic)
        cost_per_page = 1.5 if print_type == "double" else 1

        if print_type == "double":
            if pages % 2 == 0:
                total_cost = (pages // 2) * cost_per_page
            else:
                total_cost = ((pages // 2) + 1) * cost_per_page
        else:
            total_cost = pages * cost_per_page

        # 5️⃣ Save job in MongoDB
        job_id = str(random.randint(100000, 999999))
        job = {
            "_id": job_id,
            "user_email": user_email,
             "fileName": file.filename,
            "pages": pages,
            "print_type": print_type,
            "cost": total_cost,
            "file_url": file_url,
            "status": "pending"
        }
        jobs_collection.insert_one(job)

        # 6️⃣ Return response
        return jsonify({
            "success": True,
            "job_id": job_id,
            "file_url": file_url,
            "cost": total_cost
        })

    except Exception as e:
        print("UPLOAD ERROR:", e)
        return jsonify({"success": False}), 500














def get_date_filter(from_date, to_date):
    query = {}

    if from_date and to_date:
        start = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        end = end.replace(hour=23, minute=59, second=59)

        query["created_at"] = {
            "$gte": start,
            "$lte": end
        }

    return query



@app.route("/admin-login", methods=["POST"])
def admin_login():
    data = request.json
    user = data.get("id")
    password = data.get("password")

    if user == ADMIN_ID and password == ADMIN_PASSWORD:
        return jsonify({"success": True})
    
    return jsonify({"success": False}), 401


@app.route("/admin-stats", methods=["POST"])
def admin_stats():
    data = request.json

    from_date = data.get("from")
    to_date = data.get("to")

    date_filter = get_date_filter(from_date, to_date)

    jobs = list(jobs_collection.find(date_filter))

    total_jobs = len(jobs)
    total_pages = sum(j.get("pages", 0) for j in jobs)
    total_revenue = sum(j.get("cost", 0) for j in jobs)

    single_prints = sum(1 for j in jobs if j.get("print_type") == "single")
    duplex_prints = sum(1 for j in jobs if j.get("print_type") == "double")

    success_jobs = sum(1 for j in jobs if j.get("status") == "printed")
    failed_jobs = total_jobs - success_jobs

    # USERS
    users = [j.get("user_email") for j in jobs]
    unique_users = set(users)

    total_users = len(unique_users)

    # New vs Returning
    user_counts = {}
    for email in users:
        user_counts[email] = user_counts.get(email, 0) + 1

    new_users = sum(1 for u in user_counts if user_counts[u] == 1)
    returning_users = total_users - new_users

    repeat_rate = (returning_users / total_users * 100) if total_users else 0

    avg_revenue_per_user = total_revenue / total_users if total_users else 0
    success_rate = (success_jobs / total_jobs * 100) if total_jobs else 0

    return jsonify({
        "total_users": total_users,
        "new_users": new_users,
        "returning_users": returning_users,
        "repeat_rate": round(repeat_rate, 2),

        "total_prints": total_jobs,
        "total_pages": total_pages,
        "single_prints": single_prints,
        "duplex_prints": duplex_prints,

        "total_revenue": total_revenue,
        "avg_revenue_per_user": round(avg_revenue_per_user, 2),

        "failed_jobs": failed_jobs,
        "success_rate": round(success_rate, 2)
    })



@app.route("/prints-graph", methods=["POST"])
def prints_graph():
    data = request.json
    from_date = data.get("from")
    to_date = data.get("to")

    match = get_date_filter(from_date, to_date)

    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": {
                    "$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}
                },
                "count": {"$sum": 1}
            }
        },
        {"$sort": {"_id": 1}}
    ]

    result = list(jobs_collection.aggregate(pipeline))

    return jsonify(result)




@app.route("/revenue-graph", methods=["POST"])
def revenue_graph():
    data = request.json
    from_date = data.get("from")
    to_date = data.get("to")

    match = get_date_filter(from_date, to_date)

    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": {
                    "$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}
                },
                "revenue": {"$sum": "$cost"}
            }
        },
        {"$sort": {"_id": 1}}
    ]

    result = list(jobs_collection.aggregate(pipeline))

    return jsonify(result)










# partner



# 👉 assume this exists
# prints = db.prints

# =========================
# 🔐 Partner Login API
# =========================
@app.route("/partner-login", methods=["POST"])
def partner_login():
    data = request.json
    user = data.get("id")
    password = data.get("password")

    if user == PARTNER_ID and password == PARTNER_PASSWORD:
        return jsonify({
            "success": True,
            "partner_id": PARTNER_ID
        })

    return jsonify({
        "success": False,
        "message": "Invalid credentials"
    }), 401


# =========================
# 📊 Partner Stats API
# =========================
from flask import request, jsonify
from datetime import datetime, timedelta

@app.route("/partner/stats")
def partner_stats():
    filter_type = request.args.get("filter")
    now = datetime.utcnow()

    query = {
        "status": "printed"
    }

    # ================= DATE FILTER =================
    if filter_type == "today":
        start = datetime(now.year, now.month, now.day)
        query["printed_at"] = {"$gte": start}

    elif filter_type == "yesterday":
        start = datetime(now.year, now.month, now.day) - timedelta(days=1)
        end = start + timedelta(days=1)
        query["printed_at"] = {"$gte": start, "$lt": end}

    elif filter_type == "7days":
        start = now - timedelta(days=7)
        query["printed_at"] = {"$gte": start}

    elif filter_type == "30days":
        start = now - timedelta(days=30)
        query["printed_at"] = {"$gte": start}

    # ================= FETCH ONLY REQUIRED FIELDS =================
    cursor = prints.find(query, {
        "pages": 1,
        "print_type": 1,
        "cost": 1
    })

    total_prints = 0
    total_earnings = 0
    total_sheets = 0

    # ================= CALCULATIONS =================
    for doc in cursor:
        total_prints += 1

        pages = doc.get("pages", 0)
        print_type = doc.get("print_type", "single")
        cost = doc.get("cost", 0)

        # 💰 Exact earnings
        total_earnings += cost

        # 📄 Exact sheets
        if print_type == "single":
            total_sheets += pages
        elif print_type == "duplex":
            total_sheets += (pages + 1) // 2  # ceil division

    # ================= RESPONSE =================
    return jsonify({
        "prints": total_prints,
        "earnings": total_earnings,
        "sheets": total_sheets
    })




# -------------------------
# RUN SERVER
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
