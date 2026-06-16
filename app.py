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
import jwt

import secrets
from flask import send_file
from io import BytesIO
import requests

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from datetime import datetime,timezone,timedelta
import zoneinfo
from flask import Flask
# from waitress import serve

import fitz  # PyMuPDF

import time
import threading

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
#price per page = ppp
# -------------------------
#ppp
COST_PER_PAGE = 0.8  
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

temp_uploads_collection = db["temp_uploads"]

users_collection = db["users"]

SECRET_KEY = os.getenv("JWT_SECRET", "supersecret_key_change_this")

# print(db.list_collection_names())



def cleanup_expired_uploads():
    while True:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=60)
            expired = list(temp_uploads_collection.find({"uploaded_at": {"$lt": cutoff}}))
            for doc in expired:
                try:
                    cloudinary.uploader.destroy(doc["public_id"], resource_type="raw")
                    print(f"Auto-deleted: {doc['public_id']}")
                except Exception as e:
                    print(f"Cloudinary delete error: {e}")
                temp_uploads_collection.delete_one({"_id": doc["_id"]})
        except Exception as e:
            print("CLEANUP ERROR:", e)
        time.sleep(300)  # runs every 5 min

threading.Thread(target=cleanup_expired_uploads, daemon=True).start()



def verify_jwt(token):
    try:
        decoded = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return decoded
    except:
        return None
    
    
    
    
    
    

# for api check
@app.route("/health", methods=["GET"])
def health():
    return {"status": "running"}, 200





# -------------------------
# CREATE PRINT JOB
# -------------------------
@app.route("/print", methods=["POST"])
def create_print_job():
    try:
        temp_id = request.form.get("temp_id")
        otp = request.form.get("otp")
        email = request.form.get("email")
        print_type = request.form.get("printType")
        # pages = temp_doc["pages"]

        if not temp_id or not otp or not email:
            return jsonify({"success": False, "message": "Missing data"}), 400

        email = email.lower()

        # Fetch the temp upload (already on Cloudinary)
        temp_doc = temp_uploads_collection.find_one({
            "_id": temp_id,
            "user_email": email
        })
        if not temp_doc:
            return jsonify({"success": False, "message": "Upload expired. Please re-upload."}), 404
        
        if not temp_doc.get("payment_verified", False):
            return jsonify({
                "success": False,
                "message": "Payment required"
            }), 402
            
        if print_type != temp_doc.get("paid_print_type"):
            return jsonify({
                "success": False,
                "message": "Print type mismatch"
        }), 400

        pages = temp_doc["pages"]

        file_url = temp_doc["file_url"]
        fileName = temp_doc["fileName"]

        # Cost (same logic as before)
        cost_per_page = 1.4 if print_type == "double" else 0.8
        if print_type == "double":
            total_cost = round(((pages // 2) + (1 if pages % 2 else 0)) * cost_per_page, 2)
        else:
            total_cost = round(pages * cost_per_page, 2)
        if pages == 1:
            total_cost = 1

        def generate_print_id():
            while True:
                new_id = str(random.randint(100000, 999999))
                if not jobs_collection.find_one({"_id": new_id}):
                    return new_id

        print_id = generate_print_id()

        job = {
            "_id": print_id,
            "user_email": email,
            "fileName": fileName,
            "pages": pages,
            "print_type": print_type,
            "cost": total_cost,
            "file_url": file_url,
            "otp": str(otp),
            "status": "pending",
            "created_at": datetime.now(timezone.utc)
        }

        jobs_collection.insert_one(job)

        # Remove temp record — payment confirmed
        temp_uploads_collection.delete_one({"_id": temp_id})

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
        token = request.headers.get("Authorization")

        if not token:
            return jsonify([]), 401

        user = verify_jwt(token)

        if not user:
            return jsonify([]), 401

        # SECURITY CHECK
        if user["email"] != email.lower():
            return jsonify([]), 403

        jobs = list(
            jobs_collection.find({"user_email": email.lower()}).sort("_id", -1)
        )

        result = []
        for job in jobs:
            result.append({
                "printId": str(job["_id"]),
                "fileName": job.get("fileName"),
                "otp": job.get("otp"),
                "verified": job.get("status") == "printed",
                "created_at": job.get("created_at"),
                "printed_at": job.get("printed_at")
            })

        return jsonify(result)

    except Exception as e:
        print("HISTORY ERROR:", e)
        return jsonify([]), 500
    
    
    
    
            
# -------------------------
# VERIFY AT PRINTER
# -------------------------
from pymongo import ReturnDocument

@app.route("/verify", methods=["POST"])
def verify():
    try:
        data = request.json

        print_id = data.get("printId")
        otp = str(data.get("otp"))

        if not print_id or not otp:
            return jsonify({
                "verified": False,
                "message": "Missing printId or OTP"
            }), 400

        # 🔥 atomic + get document
        doc = jobs_collection.find_one_and_update(
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
            },
            return_document=ReturnDocument.AFTER
        )

        # ✅ Success
        if doc:
            return jsonify({
                "verified": True,
                "print_type": doc.get("print_type", "single"),
                "file_url": doc.get("file_url")
            })

        # ❌ Failed
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
        # 1. Verify Google token
        idinfo = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID
        )

        email = idinfo["email"].lower()

        # 2. Create YOUR JWT (7 days expiry)
        payload = {
            "email": email,
            "name": idinfo.get("name"),
            "exp": datetime.utcnow() + timedelta(days=120)
        }

        app_token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")

        return jsonify({
            "success": True,
            "user": {
                "email": email,
                "name": idinfo.get("name"),
                "profilePic": idinfo.get("picture"),
                "token": app_token   # 👈 YOUR JWT
            }
        })

    except Exception as e:
        print("LOGIN ERROR:", e)
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
        user_email = request.form.get("email", "").lower()

        if not file:
            return jsonify({"success": False, "message": "No file"}), 400

        # Read once, reuse for both PyMuPDF and Cloudinary
        file_bytes = file.read()

        doc = fitz.open(stream=file_bytes, filetype="pdf")
        num_pages = len(doc)
        doc.close()

        if num_pages > MAX_PAGES:
            return jsonify({
                "success": False,
                "message": f"Max {MAX_PAGES} pages allowed. Your file has {num_pages} pages."
            }), 400

        # Upload to Cloudinary once here
        result = cloudinary.uploader.upload(
            BytesIO(file_bytes),
            resource_type="raw",
            folder="printflash"
        )
        file_url = result["secure_url"]
        public_id = result["public_id"]

        # Save temp record (user_email, fileName, file_url only for now)
        temp_id = str(uuid.uuid4())
        temp_uploads_collection.insert_one({
            "_id": temp_id,
            "file_url": file_url,
            "public_id": public_id,
            "fileName": file.filename,
            "user_email": user_email,
            "pages": num_pages,
            "payment_verified": False,
            "uploaded_at": datetime.now(timezone.utc)
        })

        return jsonify({
            "success": True,
            "pages": num_pages,
            "temp_id": temp_id
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

        #ppp
        cost_per_page = 1.4 if print_type == "double" else 0.8

        # total_cost = round(pages * cost_per_page, 2)
        if print_type == "double":
            
            if pages % 2 == 0:
                total_cost = round((pages // 2) * cost_per_page, 2)
            else:
                total_cost = round(((pages // 2) + 1) * cost_per_page, 2)
        else:
            
            total_cost = round(pages * cost_per_page, 2)

        if pages == 1:
            total_cost = 1
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
    try:
        data = request.json
        print("VERIFY PAYMENT DATA:", data)  # debug log

        if not data:
            return jsonify({
                "status": "failed",
                "message": "Missing data"            
                }),400

        order_id = data.get("razorpay_order_id")
        payment_id = data.get("razorpay_payment_id")
        signature = data.get("razorpay_signature")

        # ✅ If all fields present — verify properly
        if order_id and payment_id and signature:
            key_secret = os.getenv("RAZORPAY_KEY_SECRET")
            generated_signature = hmac.new(
                bytes(key_secret, 'utf-8'),
                bytes(order_id + "|" + payment_id, 'utf-8'),
                hashlib.sha256
            ).hexdigest()

            if generated_signature == signature:
                temp_id = data.get("temp_id")
                print_type = data.get("printType")
                
                temp_uploads_collection.update_one(
                    {"_id": temp_id},
                    {
                        "$set": {
                            "payment_verified": True,
                            "paid_print_type": print_type,
                            "payment_id": payment_id,
                             "payment_time": datetime.now(timezone.utc)
                        }
                        
                    }
                )
                return jsonify({"status": "success"})
            else:
                return jsonify({"status": "failed", "message": "Signature mismatch"})

        # ✅ If fields missing — trust Razorpay's callback
        # Razorpay handler only fires on real successful payments
        return jsonify({
             "status": "failed",
              "message": "Missing payment fields"
            
            }),400

    except Exception as e:
        print("VERIFY PAYMENT ERROR:", e)
        return jsonify({
            "status": "failed",
             "message": "Verification failed"
             }),500


 # Upload to Cloudinary

# @app.route("/upload", methods=["POST"])
# def upload_file():
#     try:
#         # 1️⃣ Get file and form data
#         file = request.files["file"]
#         pages = int(request.form.get("pages", 0))
#         print_type = request.form.get("printType")
#         user_email = request.form.get("email")

#         # 2️⃣ Check pages
#         if pages == 0:
#             return jsonify({"success": False, "message": "Pages missing"}), 400

#         # 3️⃣ Upload to Cloudinary
#         result = cloudinary.uploader.upload(
#             file,
#             resource_type="raw",  # must for PDFs
#             folder="printflash"
#         )
#         file_url = result["secure_url"]

#         # 4️⃣ Calculate cost (your exact logic)
#         #ppp
#         cost_per_page = 1.4 if print_type == "double" else 0.8

#         # total_cost = round(pages * cost_per_page, 2)
#         if print_type == "double":
            
#             if pages % 2 == 0:
#                 total_cost = round((pages // 2) * cost_per_page, 2)
#             else:
#                 total_cost = round(((pages // 2) + 1) * cost_per_page, 2)
#         else:
            
#             total_cost = round(pages * cost_per_page, 2)
#         if pages == 1:
#             total_cost = 1

#         # 5️⃣ Save job in MongoDB
#         job_id = str(random.randint(100000, 999999))
#         job = {
#             "_id": job_id,
#             "user_email": user_email,
#              "fileName": file.filename,
#             "pages": pages,
#             "print_type": print_type,
#             "cost": total_cost,
#             "file_url": file_url,
#             "status": "pending"
#         }
#         jobs_collection.insert_one(job)

#         # 6️⃣ Return response
#         return jsonify({
#             "success": True,
#             "job_id": job_id,
#             "file_url": file_url,
#             "cost": total_cost
#         })

#     except Exception as e:
#         print("UPLOAD ERROR:", e)
#         return jsonify({"success": False}), 500














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
 # ✅ add this import at top if missing





@app.route("/partner/stats")
def partner_stats():
    try:
        filter_type = request.args.get("filter")
        from_date = request.args.get("from")
        to_date = request.args.get("to")

        now = datetime.utcnow().replace(tzinfo=timezone.utc)

        query = {
            "status": "printed"
        }

        # ================= CUSTOM DATE (FIXED) =================
        if from_date and to_date:
            start = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
            end = datetime.fromisoformat(to_date).replace(tzinfo=timezone.utc)

            # 🔥 IMPORTANT: include full day
            end = end + timedelta(days=1)

            query["printed_at"] = {
                "$gte": start,
                "$lt": end
            }

        else:
            # ================= PRESET FILTER =================
            if filter_type == "today":
                start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
                query["printed_at"] = {"$gte": start}

            elif filter_type == "yesterday":
                start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) - timedelta(days=1)
                end = start + timedelta(days=1)

                query["printed_at"] = {
                    "$gte": start,
                    "$lt": end
                }

            elif filter_type == "7days":
                start = now - timedelta(days=7)
                query["printed_at"] = {"$gte": start}

            elif filter_type == "30days":
                start = now - timedelta(days=30)
                query["printed_at"] = {"$gte": start}

        # ================= FETCH =================
        cursor = jobs_collection.find(query)

        total_prints = 0
        total_earnings = 0
        total_sheets = 0

        for doc in cursor:
            total_prints += 1
            total_earnings += doc.get("cost", 0)

            pages = doc.get("pages", 0)
            print_type = doc.get("print_type", "single")

            if print_type == "single":
                total_sheets += pages
            elif print_type == "double":
                total_sheets += (pages + 1) // 2

        return jsonify({
            "prints": total_prints,
            "earnings": total_earnings,
            "sheets": total_sheets
        })

    except Exception as e:
        print("ERROR:", e)
        return jsonify({"error": str(e)}), 500
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
        
# -------------------------
# RUN SERVER
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
