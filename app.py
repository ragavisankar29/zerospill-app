import os
import io
import socket
import random
import time
import sqlite3
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
import pandas as pd
import numpy as np

# Matplotlib headless backend for generating high-res charts & 3D OLAP Cube inside PDF
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

app = Flask(__name__)
app.secret_key = 'zerospill_production_secret_key'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, 'data', 'ZEROSPILL_cleaned.csv')
DB_PATH = os.path.join(BASE_DIR, 'zerospill.db')

# =========================================================
# GMAIL SMTP SETTINGS
# =========================================================
SENDER_EMAIL = "s.ragavi213@gmail.com"
SENDER_APP_PASSWORD = "cdcq sftk pvak rttg"

OTP_STORE = {}
PAYMENT_SESSIONS = {}

# Global state for Automatic Live Banquet Feed Simulator (ON/OFF toggle in Admin)
LIVE_FEED_STATE = {
    'enabled': False,
    'last_generated_at': 0,
    'recent_events': []
}

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def send_real_otp_email(recipient_email, otp_code, purpose="Verification"):
    if "your_gmail" in SENDER_EMAIL or "your_16_char" in SENDER_APP_PASSWORD:
        print(f"\n[DEMO MODE] OTP for {recipient_email}: {otp_code}\n")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"ZeroSpill {purpose} OTP: {otp_code}"
        msg["From"] = f"ZeroSpill Food Rescue <{SENDER_EMAIL}>"
        msg["To"] = recipient_email

        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:460px;margin:auto;padding:20px;border:1px solid #e2e8f0;border-radius:12px;">
            <h2 style="color:#065f46;margin:0 0 10px;">🌱 ZeroSpill Verification</h2>
            <p style="color:#334155;font-size:14px;">Your 6-digit OTP for <strong>{purpose}</strong> is:</p>
            <div style="background:#ecfdf5;border:1px solid #10b981;padding:14px;text-align:center;border-radius:8px;margin:16px 0;">
                <span style="font-size:28px;font-weight:bold;letter-spacing:6px;color:#047857;">{otp_code}</span>
            </div>
            <p style="color:#64748b;font-size:12px;">Valid for 5 minutes. Do not share this code.</p>
        </div>
        """
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
        return True
    except Exception as e:
        print(f"[SMTP ERROR] {e}")
        return False

# =========================================================
# DATABASE SETUP (Includes live surplus_stream table)
# =========================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'User',
            latitude TEXT,
            longitude TEXT,
            address TEXT
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS food_orders (
            order_id TEXT PRIMARY KEY,
            user_email TEXT NOT NULL,
            user_name TEXT NOT NULL,
            food_item TEXT NOT NULL,
            food_category TEXT,
            quantity_kg REAL NOT NULL,
            total_price REAL DEFAULT 0,
            payment_method TEXT DEFAULT 'UPI Paid',
            pickup_hub TEXT NOT NULL,
            user_location TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS surplus_stream (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venue_name TEXT NOT NULL,
            area TEXT NOT NULL,
            event_type TEXT NOT NULL,
            food_item TEXT NOT NULL,
            food_category TEXT NOT NULL,
            surplus_kg REAL NOT NULL,
            logged_at TEXT NOT NULL
        )
    ''')

    c.execute("SELECT id FROM users WHERE email = 'admin@zerospill.com'")
    if not c.fetchone():
        c.execute('''
            INSERT INTO users (full_name, email, phone, password_hash, role, latitude, longitude, address)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', ('System Admin', 'admin@zerospill.com', '9876543210', generate_password_hash('admin123'), 'Admin', '13.0827', '80.2707', 'Central Warehouse HQ'))

    conn.commit()
    conn.close()

init_db()

def load_dataset():
    base_df = pd.read_csv(CSV_PATH) if os.path.exists(CSV_PATH) else pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    stream_df = pd.read_sql_query("SELECT venue_name, area, event_type as Event_Type, food_item as Food_Item, food_category as Food_Category, surplus_kg as Surplus_Quantity FROM surplus_stream", conn)
    conn.close()

    if not stream_df.empty:
        stream_df['Quantity_Consumed'] = (stream_df['Surplus_Quantity'] * 2.5).round(1)
        if not base_df.empty:
            return pd.concat([base_df, stream_df], ignore_index=True)
        return stream_df
    return base_df

def generate_auto_surplus_tick():
    """Automatically simulates a live hotel/wedding hall logging surplus food every 8 seconds when enabled."""
    if not LIVE_FEED_STATE['enabled']:
        return None

    now = time.time()
    if now - LIVE_FEED_STATE['last_generated_at'] < 8:
        return None

    LIVE_FEED_STATE['last_generated_at'] = now

    sample_events = [
        ("Meenakshi Mahal Wedding Hall", "Tambaram", "Wedding", "Chicken Biryani", "Meat"),
        ("Sri Balaji Bhavan", "Poonamallee", "Corporate", "Vegetable Curry", "Vegetables"),
        ("Karpagambal Kalyana Mandapam", "Porur", "Wedding", "Payasam", "Dairy"),
        ("Hotel Saravana Bhavan (Local)", "Vadapalani", "Reception", "Bread Rolls", "Bakery"),
        ("Sree Devi Palace Mandapam", "Koyambedu", "Reception", "Paneer Curry", "Dairy"),
        ("Anandhaas Veg Hotel", "Avadi", "Birthday", "Fruit Platter", "Fruits"),
        ("Padmavathi Kalyana Mandapam", "Valasaravakkam", "Wedding", "Curd", "Dairy"),
        ("Murugan Mess & Tiffin Center", "T. Nagar", "Corporate", "Pastries", "Bakery")
    ]

    venue, area, evt, item, cat = random.choice(sample_events)
    qty = round(random.uniform(8.0, 28.0), 1)
    stamp = datetime.now().strftime("%I:%M:%S %p")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO surplus_stream (venue_name, area, event_type, food_item, food_category, surplus_kg, logged_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (venue, area, evt, item, cat, qty, stamp))
    conn.commit()
    conn.close()

    event_summary = {
        'venue': venue,
        'area': area,
        'event_type': evt,
        'food_item': item,
        'food_category': cat,
        'surplus_kg': qty,
        'logged_at': stamp
    }
    LIVE_FEED_STATE['recent_events'].insert(0, event_summary)
    LIVE_FEED_STATE['recent_events'] = LIVE_FEED_STATE['recent_events'][:6]
    return event_summary

# =========================================================
# CATALOG BUILDER (Stock-aware + Live Streamed Batches)
# =========================================================
def get_food_catalog():
    generate_auto_surplus_tick()

    df = load_dataset()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT food_item, SUM(quantity_kg) FROM food_orders WHERE status != 'Cancelled' GROUP BY food_item")
    ordered_map = dict(c.fetchall())

    conn.row_factory = sqlite3.Row
    c2 = conn.cursor()
    c2.execute("SELECT * FROM surplus_stream ORDER BY id DESC LIMIT 12")
    live_stream_rows = [dict(r) for r in c2.fetchall()]
    conn.close()

    local_venues = [
        {"venue": "Sri Balaji Bhavan", "area": "Poonamallee", "time": "20-25 mins", "rating": "4.6"},
        {"venue": "Karpagambal Kalyana Mandapam", "area": "Porur", "time": "25-30 mins", "rating": "4.7"},
        {"venue": "Hotel Saravana Bhavan (Local)", "area": "Vadapalani", "time": "20-25 mins", "rating": "4.5"},
        {"venue": "Meenakshi Mahal Wedding Hall", "area": "Tambaram", "time": "30-35 mins", "rating": "4.8"},
        {"venue": "Anandhaas Veg Hotel", "area": "Avadi", "time": "25-30 mins", "rating": "4.4"},
        {"venue": "Sree Devi Palace Mandapam", "area": "Koyambedu", "time": "20-25 mins", "rating": "4.6"},
        {"venue": "Amma Unavagam & Community Kitchen", "area": "Guindy", "time": "15-20 mins", "rating": "4.7"},
        {"venue": "Lakshmi Narayana Marriage Hall", "area": "Chromepet", "time": "25-30 mins", "rating": "4.5"},
        {"venue": "Murugan Mess & Tiffin Center", "area": "T. Nagar", "time": "20-25 mins", "rating": "4.6"},
        {"venue": "Padmavathi Kalyana Mandapam", "area": "Valasaravakkam", "time": "25-30 mins", "rating": "4.7"},
        {"venue": "New Woodlands Local Mess", "area": "Mylapore", "time": "25-30 mins", "rating": "4.5"},
        {"venue": "Thirumagal Thirumana Mandapam", "area": "Perambur", "time": "30-35 mins", "rating": "4.6"}
    ]

    category_rates = {
        "Bakery": 60, "Meat": 140, "Dairy": 70, "Fruits": 50,
        "Vegetables": 40, "Beverages": 45, "Grains": 55, "Seafood": 150, "Prepared Food": 80
    }

    def get_exact_food_image(food_name, category):
        name = food_name.lower()
        specific_matches = [
            ("vegetable curry", "/static/images/vegetable_curry.png"),
            ("veg curry", "/static/images/vegetable_curry.png"),
            ("fruit platter", "/static/images/fruit_platter.png"),
            ("fruit salad", "/static/images/fruit_salad.png"),
            ("payasam", "/static/images/payasam.png"),
            ("kheer", "/static/images/payasam.png"),
            ("pastries", "/static/images/pastries.png"),
            ("pastry", "/static/images/pastries.png"),
            ("curd", "/static/images/curd.png"),
            ("yogurt", "/static/images/curd.png"),
            ("bread", "https://images.unsplash.com/photo-1586444248902-2f64eddc13df?auto=format&fit=crop&w=800&q=80"),
            ("roll", "https://images.unsplash.com/photo-1586444248902-2f64eddc13df?auto=format&fit=crop&w=800&q=80"),
            ("cake", "https://images.unsplash.com/photo-1578985545062-69928b1d9587?auto=format&fit=crop&w=800&q=80"),
            ("cookie", "https://images.unsplash.com/photo-1499636136210-6f4ee915583e?auto=format&fit=crop&w=800&q=80"),
            ("biryani", "https://images.unsplash.com/photo-1563379091339-03b21ab4a4f8?auto=format&fit=crop&w=800&q=80"),
            ("grilled chicken", "https://images.unsplash.com/photo-1598515214211-89d3c73ae83b?auto=format&fit=crop&w=800&q=80"),
            ("chicken", "https://images.unsplash.com/photo-1603894584373-5ac82b2ae398?auto=format&fit=crop&w=800&q=80"),
            ("mutton", "https://images.unsplash.com/photo-1545247181-516773cae754?auto=format&fit=crop&w=800&q=80"),
            ("paneer", "https://images.unsplash.com/photo-1631452180519-c014fe946bc7?auto=format&fit=crop&w=800&q=80"),
            ("milk", "https://images.unsplash.com/photo-1550583724-b2692b85b150?auto=format&fit=crop&w=800&q=80"),
            ("fresh fruit", "https://images.unsplash.com/photo-1619566636858-adf3ef46400b?auto=format&fit=crop&w=800&q=80"),
            ("salad", "https://images.unsplash.com/photo-1512621776951-a57141f2eefd?auto=format&fit=crop&w=800&q=80"),
            ("curry", "https://images.unsplash.com/photo-1585937421612-70a008356fbe?auto=format&fit=crop&w=800&q=80"),
            ("vegetable", "https://images.unsplash.com/photo-1540420773420-3366772f4999?auto=format&fit=crop&w=800&q=80"),
            ("rice", "https://images.unsplash.com/photo-1516684732162-798a0062be99?auto=format&fit=crop&w=800&q=80"),
            ("juice", "https://images.unsplash.com/photo-1613478223719-2ab802602423?auto=format&fit=crop&w=800&q=80"),
            ("fish", "https://images.unsplash.com/photo-1519708227418-c8fd9a32b7a2?auto=format&fit=crop&w=800&q=80")
        ]
        for keyword, url in specific_matches:
            if keyword in name:
                return url

        category_fallback = {
            "Bakery": "https://images.unsplash.com/photo-1509440159596-0249088772ff?auto=format&fit=crop&w=800&q=80",
            "Meat": "https://images.unsplash.com/photo-1603894584373-5ac82b2ae398?auto=format&fit=crop&w=800&q=80",
            "Dairy": "/static/images/curd.png",
            "Fruits": "https://images.unsplash.com/photo-1619566636858-adf3ef46400b?auto=format&fit=crop&w=800&q=80",
            "Vegetables": "https://images.unsplash.com/photo-1540420773420-3366772f4999?auto=format&fit=crop&w=800&q=80",
            "Beverages": "https://images.unsplash.com/photo-1613478223719-2ab802602423?auto=format&fit=crop&w=800&q=80",
            "Grains": "https://images.unsplash.com/photo-1516684732162-798a0062be99?auto=format&fit=crop&w=800&q=80",
            "Prepared Food": "/static/images/vegetable_curry.png"
        }
        return category_fallback.get(category, "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?auto=format&fit=crop&w=800&q=80")

    items = []

    for srow in live_stream_rows:
        batch_title = f"{srow['food_item']} — Live Batch #{srow['id']}"
        remaining_batch = max(0.0, round(float(srow['surplus_kg']) - ordered_map.get(batch_title, 0), 1))
        if remaining_batch > 0:
            rate_1kg = category_rates.get(srow['food_category'], 60)
            half_kg_price = int(round(rate_1kg * 0.55))
            two_kg_price = int(round(rate_1kg * 1.9))
            five_kg_price = int(round(rate_1kg * 4.5))
            items.append({
                'Food_Item': batch_title,
                'Food_Category': srow['food_category'],
                'Event_Type': srow['event_type'],
                'Venue_Name': srow['venue_name'],
                'Area': srow['area'],
                'Delivery_Time': '15-20 mins',
                'Rating': '4.9',
                'Image_URL': get_exact_food_image(srow['food_item'], srow['food_category']),
                'Limited_Stock': remaining_batch <= 10.0,
                'Is_Live_Batch': True,
                'Logged_At': srow['logged_at'],
                'Remaining_Qty': remaining_batch,
                'Available_Stock': f"{remaining_batch} kg left",
                'Unit_Type': 'kg',
                'Base_Price': rate_1kg,
                'Pricing_Options': [
                    {'label': f'Half kg (500g) — ₹{half_kg_price}', 'qty': 0.5, 'price': half_kg_price},
                    {'label': f'1 kg Standard Pack — ₹{rate_1kg}', 'qty': 1.0, 'price': rate_1kg},
                    {'label': f'2 kg Family Pack — ₹{two_kg_price}', 'qty': 2.0, 'price': two_kg_price},
                    {'label': f'5 kg Community Pack — ₹{five_kg_price}', 'qty': 5.0, 'price': five_kg_price}
                ],
                'Description': f"Live surplus batch logged at {srow['logged_at']} from {srow['venue_name']} ({srow['area']}). {remaining_batch} kg freshly available!"
            })

    eco_specs = [
        ('Fresh Banana Leaves (Vazhai Ilai)', 'Eco Event Supplies', 'Wedding Hall', 'Meenakshi Mahal Wedding Hall', 'Tambaram', '20-25 mins', '4.8', '/static/images/banana_leaves.png', False, 45.0, 'bundles', 'bundle', 40,
         [{'label': 'Half Bundle (10 Leaves)', 'qty': 0.5, 'price': 25}, {'label': '1 Full Bundle (25 Leaves)', 'qty': 1.0, 'price': 40}, {'label': '2 Bundles (50 Leaves)', 'qty': 2.0, 'price': 75}, {'label': 'Wedding Pack (100 Leaves)', 'qty': 4.0, 'price': 140}],
         'Unused, freshly cut green banana leaves (Vazhai Ilai) from wedding feast dining halls. Washed, trimmed, and ideal for community meals or catering.'),
        ('Whole Banana Bunch (Vazhai Thaar)', 'Eco Event Supplies', 'Marriage Mandapam', 'Karpagambal Kalyana Mandapam', 'Porur', '25-30 mins', '4.9', 'https://images.unsplash.com/photo-1603833665858-e61d17a86224?auto=format&fit=crop&w=800&q=80', True, 18.0, 'bunches', 'bunch', 90,
         [{'label': 'Half Thaar (~35 Bananas)', 'qty': 0.5, 'price': 50}, {'label': '1 Full Vazhai Thaar (~75 Bananas)', 'qty': 1.0, 'price': 90}, {'label': '2 Full Vazhai Thaar (Event Combo)', 'qty': 2.0, 'price': 170}],
         'Fresh decorative & edible whole banana stem bunch (Vazhai Thaar) from marriage entrance decor. Ripe Yelakki/Poovan bananas ready for distribution.'),
        ('Wooden Spoons & Areca Plates Set', 'Eco Event Supplies', 'Reception Hall', 'Sree Devi Palace Mandapam', 'Koyambedu', '20-25 mins', '4.7', '/static/images/wooden_spoons.png', False, 30.0, 'packs', 'pack', 60,
         [{'label': 'Starter Pack (25 Plates + 25 Spoons)', 'qty': 0.5, 'price': 35}, {'label': '1 Full Pack (50 Plates + 50 Wooden Spoons)', 'qty': 1.0, 'price': 60}, {'label': '2 Full Packs (100 Sets)', 'qty': 2.0, 'price': 110}, {'label': 'Bulk Box (250 Sets)', 'qty': 5.0, 'price': 250}],
         '100% biodegradable birchwood spoons and pressed areca palm leaf plates (Paakku Mattai Thattu) left sealed and unused after banquet events.')
    ]
    for title, cat, evt, venue, area, dtime, rating, img, lim, init_stock, plural, unit, base_p, opts, desc in eco_specs:
        rem = max(0.0, round(init_stock - ordered_map.get(title, 0), 1))
        if rem > 0:
            items.append({
                'Food_Item': title, 'Food_Category': cat, 'Event_Type': evt, 'Venue_Name': venue, 'Area': area,
                'Delivery_Time': dtime, 'Rating': rating, 'Image_URL': img, 'Limited_Stock': lim or rem <= 5.0,
                'Is_Live_Batch': False, 'Remaining_Qty': rem, 'Available_Stock': f"{rem} {plural} left",
                'Unit_Type': unit, 'Base_Price': base_p, 'Pricing_Options': opts, 'Description': desc
            })

    if not df.empty:
        grouped = df.groupby(['Food_Item', 'Food_Category'], as_index=False).agg({
            'Surplus_Quantity': 'sum',
            'Event_Type': 'first'
        })
        median_stock = grouped['Surplus_Quantity'].median()

        for idx, row in grouped.iterrows():
            f_name = row['Food_Item']
            cat = row['Food_Category']
            remaining = max(0.0, round(float(row['Surplus_Quantity']) - ordered_map.get(f_name, 0), 1))
            if remaining > 0:
                vp = local_venues[idx % len(local_venues)]
                rate_1kg = category_rates.get(cat, 60)
                half_kg_price = int(round(rate_1kg * 0.55))
                two_kg_price = int(round(rate_1kg * 1.9))
                five_kg_price = int(round(rate_1kg * 4.5))
                is_limited = (remaining < median_stock) or (ordered_map.get(f_name, 0) > 0)

                items.append({
                    'Food_Item': f_name,
                    'Food_Category': cat,
                    'Event_Type': row['Event_Type'],
                    'Venue_Name': vp['venue'],
                    'Area': vp['area'],
                    'Delivery_Time': vp['time'],
                    'Rating': vp['rating'],
                    'Image_URL': get_exact_food_image(f_name, cat),
                    'Limited_Stock': is_limited,
                    'Is_Live_Batch': False,
                    'Remaining_Qty': remaining,
                    'Available_Stock': f"{int(remaining):,} kg left",
                    'Unit_Type': 'kg',
                    'Base_Price': rate_1kg,
                    'Pricing_Options': [
                        {'label': f'Half kg (500g) — ₹{half_kg_price}', 'qty': 0.5, 'price': half_kg_price},
                        {'label': f'1 kg Standard Pack — ₹{rate_1kg}', 'qty': 1.0, 'price': rate_1kg},
                        {'label': f'2 kg Family Pack — ₹{two_kg_price}', 'qty': 2.0, 'price': two_kg_price},
                        {'label': f'5 kg Community Pack — ₹{five_kg_price}', 'qty': 5.0, 'price': five_kg_price}
                    ],
                    'Description': f"Freshly cooked {f_name} surplus collected from {vp['venue']} in {vp['area']}. Hygienically packed at subsidised zero-waste rescue pricing."
                })

    categories = sorted(list({i['Food_Category'] for i in items}))
    return items, categories

# =========================================================
# DECORATORS
# =========================================================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            flash("Please login to continue.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session or session.get('role') != 'Admin':
            flash("Admin privileges required.", "danger")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# =========================================================
# AUTH ROUTES
# =========================================================
@app.route('/')
def index():
    if 'user' in session:
        return redirect(url_for('admin_dashboard' if session.get('role') == 'Admin' else 'user_dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name = request.form.get('full_name').strip()
        email = request.form.get('email').strip().lower()
        phone = request.form.get('phone').strip()
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        role = request.form.get('role', 'User')
        lat = request.form.get('latitude', '13.0827')
        lng = request.form.get('longitude', '80.2707')
        address = request.form.get('live_address', 'GPS Verified')

        if password != confirm_password:
            flash("Password and Confirm Password do not match!", "danger")
            return redirect(url_for('register'))

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE email = ?", (email,))
        if c.fetchone():
            conn.close()
            flash("This email is already registered. Please sign in.", "warning")
            return redirect(url_for('login'))
        conn.close()

        otp_code = str(random.randint(100000, 999999))
        OTP_STORE[email] = {
            'otp': otp_code,
            'expires_at': time.time() + 300,
            'action': 'register',
            'temp_user': {
                'full_name': full_name,
                'email': email,
                'phone': phone,
                'password_hash': generate_password_hash(password),
                'role': role,
                'latitude': lat,
                'longitude': lng,
                'address': address
            }
        }

        sent = send_real_otp_email(email, otp_code, "Account Registration")
        session['verify_email'] = email
        if sent:
            flash(f"Verification OTP sent to your email ({email}). Please check your inbox.", "success")
        else:
            flash(f"OTP generated! (Demo OTP: {otp_code})", "info")
        return redirect(url_for('verify_otp'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email').strip().lower()
        password = request.form.get('password')

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT full_name, password_hash, role, address, latitude, longitude FROM users WHERE email = ?", (email,))
        user = c.fetchone()
        conn.close()

        if not user or not check_password_hash(user[1], password):
            flash("Invalid email or password. If you are new, please create an account first.", "danger")
            return redirect(url_for('login'))

        otp_code = str(random.randint(100000, 999999))
        OTP_STORE[email] = {
            'otp': otp_code,
            'expires_at': time.time() + 300,
            'action': 'login',
            'user_info': {
                'full_name': user[0],
                'email': email,
                'role': user[2],
                'address': user[3],
                'latitude': user[4],
                'longitude': user[5]
            }
        }

        sent = send_real_otp_email(email, otp_code, "Login Verification")
        session['verify_email'] = email
        if sent:
            flash(f"Security OTP sent to {email}.", "success")
        else:
            flash(f"Login OTP generated! (Demo OTP: {otp_code})", "info")
        return redirect(url_for('verify_otp'))

    return render_template('login.html')

@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    email = session.get('verify_email')
    if not email or email not in OTP_STORE:
        return redirect(url_for('login'))

    if request.method == 'POST':
        entered = request.form.get('otp', '').strip()
        record = OTP_STORE.get(email)

        if record and record['otp'] == entered and time.time() <= record['expires_at']:
            if record['action'] == 'register':
                u = record['temp_user']
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute('''
                    INSERT INTO users (full_name, email, phone, password_hash, role, latitude, longitude, address)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (u['full_name'], u['email'], u['phone'], u['password_hash'], u['role'], u['latitude'], u['longitude'], u['address']))
                conn.commit()
                conn.close()
                user_data = u
            else:
                user_data = record['user_info']

            session['user'] = user_data['email']
            session['name'] = user_data['full_name']
            session['role'] = user_data['role']
            session['location'] = user_data['address']
            session['lat'] = user_data['latitude']
            session['lng'] = user_data['longitude']

            del OTP_STORE[email]
            session.pop('verify_email', None)

            flash(f"Welcome {user_data['full_name']}!", "success")
            return redirect(url_for('admin_dashboard' if user_data['role'] == 'Admin' else 'user_dashboard'))
        else:
            flash("Invalid or expired OTP. Please try again.", "danger")

    return render_template('verify.html', email=email)

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out securely.", "info")
    return redirect(url_for('login'))

# =========================================================
# USER PORTAL ROUTES
# =========================================================
@app.route('/dashboard')
@login_required
def user_dashboard():
    df = load_dataset()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(quantity_kg), 0) FROM food_orders WHERE status != 'Cancelled'")
    claimed_kg = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM food_orders WHERE user_email = ?", (session['user'],))
    my_order_count = c.fetchone()[0]
    conn.close()

    total_surplus = max(0, int(df['Surplus_Quantity'].sum()) - int(claimed_kg)) if not df.empty else 0
    stats = {
        'available_surplus': f"{total_surplus:,} kg",
        'claimed_by_community': f"{int(claimed_kg):,} kg",
        'my_active_orders': my_order_count
    }
    return render_template('dashboard.html', user=session.get('name'), location=session.get('location'), stats=stats)

@app.route('/food')
@login_required
def food():
    items, categories = get_food_catalog()
    return render_template('food.html', items=items, categories=categories)

@app.route('/api/live-catalog')
@login_required
def api_live_catalog():
    items, categories = get_food_catalog()
    return jsonify({'items': items, 'categories': categories, 'count': len(items)})

@app.route('/food/<path:food_name>')
@login_required
def food_detail(food_name):
    items, _ = get_food_catalog()
    selected = next((i for i in items if i['Food_Item'].lower() == food_name.lower()), None)
    if not selected:
        flash("Item not found or currently unavailable.", "warning")
        return redirect(url_for('food'))
    return render_template('food_detail.html', item=selected)

@app.route('/add-to-cart', methods=['POST'])
@login_required
def add_to_cart():
    food_item = request.form.get('food_item')
    items, _ = get_food_catalog()
    selected = next((i for i in items if i['Food_Item'].lower() == food_item.lower()), None)
    if not selected:
        flash("Item unavailable or out of stock.", "warning")
        return redirect(url_for('food'))

    qty = float(request.form.get('quantity', 1.0))
    unit_price = float(request.form.get('item_price', selected['Base_Price']))
    pack_label = request.form.get('pack_label', f"1 {selected['Unit_Type']}")
    pickup_hub = request.form.get('pickup_hub', f"Doorstep Delivery ({selected['Venue_Name']}, {selected['Area']})")

    cart = session.get('cart', [])
    already_in_cart = sum(c['total_qty'] for c in cart if c['food_item'] == selected['Food_Item'])
    available_now = float(selected.get('Remaining_Qty', 9999))

    if already_in_cart + qty > available_now:
        flash(f"Only {available_now} {selected['Unit_Type']} remaining for '{selected['Food_Item']}' (you already have {already_in_cart} in cart).", "warning")
        return redirect(url_for('view_cart') if already_in_cart > 0 else url_for('food'))

    existing = next((c for c in cart if c['food_item'] == selected['Food_Item'] and c['pack_label'] == pack_label), None)
    if existing:
        existing['count'] += 1
        existing['total_qty'] = round(existing['qty'] * existing['count'], 2)
        existing['subtotal'] = int(existing['unit_price'] * existing['count'])
    else:
        cart.append({
            'id': f"CART-{random.randint(1000, 9999)}",
            'food_item': selected['Food_Item'],
            'food_category': selected['Food_Category'],
            'venue': selected['Venue_Name'],
            'area': selected['Area'],
            'image': selected['Image_URL'],
            'pack_label': pack_label,
            'qty': qty,
            'count': 1,
            'total_qty': qty,
            'unit_price': int(unit_price),
            'subtotal': int(unit_price),
            'pickup_hub': pickup_hub
        })

    session['cart'] = cart
    session.modified = True
    flash(f"Added '{selected['Food_Item']}' to your cart!", "success")
    return redirect(url_for('view_cart'))

@app.route('/cart')
@login_required
def view_cart():
    cart = session.get('cart', [])
    subtotal = sum(item['subtotal'] for item in cart)
    delivery_fee = 15 if (cart and subtotal < 250) else 0
    grand_total = subtotal + delivery_fee

    pay_token = f"PAY-{random.randint(100000, 999999)}"
    local_ip = get_local_ip()
    if request.host.startswith("localhost") or request.host.startswith("127.0.0.1"):
        scan_url = f"http://{local_ip}:5000/mobile-pay/{pay_token}"
    else:
        scan_url = url_for('mobile_pay', pay_token=pay_token, _external=True)

    PAYMENT_SESSIONS[pay_token] = {
        'status': 'WAITING',
        'amount': grand_total,
        'user_email': session['user'],
        'user_name': session['name'],
        'user_location': session.get('location', 'Chennai'),
        'cart': [dict(i) for i in cart],
        'delivery_mode': 'Doorstep Delivery'
    }

    return render_template('cart.html', cart=cart, subtotal=subtotal, delivery_fee=delivery_fee,
                           grand_total=grand_total, pay_token=pay_token, scan_url=scan_url, local_ip=local_ip)

@app.route('/remove-from-cart/<item_id>', methods=['POST'])
@login_required
def remove_from_cart(item_id):
    cart = session.get('cart', [])
    session['cart'] = [c for c in cart if c['id'] != item_id]
    session.modified = True
    flash("Item removed from cart.", "info")
    return redirect(url_for('view_cart'))

@app.route('/mobile-pay/<pay_token>', methods=['GET', 'POST'])
def mobile_pay(pay_token):
    pay_data = PAYMENT_SESSIONS.get(pay_token)
    if not pay_data:
        return "<h2 style='font-family:sans-serif;text-align:center;margin-top:50px;'>❌ Payment Session Expired or Invalid</h2>", 404

    if request.method == 'POST':
        decision = request.form.get('decision')
        if decision == 'complete':
            pay_data['status'] = 'COMPLETED'
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            for item in pay_data['cart']:
                order_id = f"ZSP-{random.randint(10000, 99999)}"
                hub_text = f"{pay_data['delivery_mode']} ({item['venue']}, {item['area']})"
                c.execute('''
                    INSERT INTO food_orders (order_id, user_email, user_name, food_item, food_category, quantity_kg, total_price, payment_method, pickup_hub, user_location, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending')
                ''', (order_id, pay_data['user_email'], pay_data['user_name'], item['food_item'], item['food_category'], item['total_qty'], item['subtotal'], 'UPI QR Verified', hub_text, pay_data['user_location']))
            conn.commit()
            conn.close()
            return render_template('mobile_pay.html', pay=pay_data, pay_token=pay_token, done_state='COMPLETED')
        else:
            pay_data['status'] = 'DECLINED'
            return render_template('mobile_pay.html', pay=pay_data, pay_token=pay_token, done_state='DECLINED')

    if pay_data['status'] == 'WAITING':
        pay_data['status'] = 'SCANNED'
    return render_template('mobile_pay.html', pay=pay_data, pay_token=pay_token, done_state=None)

@app.route('/api/check-payment/<pay_token>')
@login_required
def check_payment(pay_token):
    pay_data = PAYMENT_SESSIONS.get(pay_token)
    if not pay_data:
        return jsonify({'status': 'EXPIRED'})
    if pay_data['status'] == 'COMPLETED':
        session['cart'] = []
        session.modified = True
    return jsonify({'status': pay_data['status']})

@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    cart = session.get('cart', [])
    if not cart:
        flash("Your cart is empty!", "warning")
        return redirect(url_for('food'))

    items, _ = get_food_catalog()
    stock_lookup = {i['Food_Item']: float(i.get('Remaining_Qty', 0)) for i in items}
    for item in cart:
        avail = stock_lookup.get(item['food_item'], 0)
        if float(item['total_qty']) > avail:
            flash(f"Stock changed! Only {avail} left for '{item['food_item']}'. Please adjust your cart.", "danger")
            return redirect(url_for('view_cart'))

    payment_method = request.form.get('payment_method', 'UPI (GPay / PhonePe / Paytm)')
    delivery_mode = request.form.get('delivery_mode', 'Doorstep Delivery')

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    created_ids = []

    for item in cart:
        order_id = f"ZSP-{random.randint(10000, 99999)}"
        created_ids.append(order_id)
        hub_text = f"{delivery_mode} ({item['venue']}, {item['area']})"
        c.execute('''
            INSERT INTO food_orders (order_id, user_email, user_name, food_item, food_category, quantity_kg, total_price, payment_method, pickup_hub, user_location, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending')
        ''', (order_id, session['user'], session['name'], item['food_item'], item['food_category'], item['total_qty'], item['subtotal'], payment_method, hub_text, session.get('location')))

    conn.commit()
    conn.close()

    session['cart'] = []
    session.modified = True

    flash(f"Payment confirmed via {payment_method}! Orders {', '.join(created_ids)} are now live.", "success")
    return redirect(url_for('requests_view'))

@app.route('/requests')
@login_required
def requests_view():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM food_orders WHERE user_email = ? ORDER BY created_at DESC", (session['user'],))
    orders = [dict(row) for row in c.fetchall()]
    conn.close()
    return render_template('requests.html', orders=orders)

@app.route('/api/live-orders')
@login_required
def api_live_orders():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if session.get('role') == 'Admin':
        c.execute("SELECT * FROM food_orders ORDER BY created_at DESC")
    else:
        c.execute("SELECT * FROM food_orders WHERE user_email = ? ORDER BY created_at DESC", (session['user'],))
    orders = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(orders)

@app.route('/api/update-order-status', methods=['POST'])
@admin_required
def update_order_status():
    order_id = request.form.get('order_id')
    new_status = request.form.get('status')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE food_orders SET status = ? WHERE order_id = ?", (new_status, order_id))
    conn.commit()
    conn.close()
    flash(f"Order {order_id} updated to '{new_status}'.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/nearby')
@login_required
def nearby():
    hubs = [
        {"name": "Sri Balaji Bhavan", "area": "Poonamallee", "type": "Local Hotel", "rating": "4.6", "distance": "1.1 km", "food": "Idli, Sambar, Pongal & Mini Meals", "status": "Live Pickup Open", "img": "https://images.unsplash.com/photo-1589301760014-d929f3979dbc?auto=format&fit=crop&w=600&q=80"},
        {"name": "Karpagambal Kalyana Mandapam", "area": "Porur", "type": "Wedding Hall", "rating": "4.7", "distance": "2.4 km", "food": "Wedding Feast, Vazhai Thaar & Sweet Pongal", "status": "Live Pickup Open", "img": "https://images.unsplash.com/photo-1519225421980-715cb0215aed?auto=format&fit=crop&w=600&q=80"},
        {"name": "Hotel Saravana Bhavan (Local)", "area": "Vadapalani", "type": "Local Hotel", "rating": "4.5", "distance": "3.1 km", "food": "Chapati, Kurma, Curd Rice & Bakery Rolls", "status": "Live Pickup Open", "img": "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?auto=format&fit=crop&w=600&q=80"},
        {"name": "Meenakshi Mahal Wedding Hall", "area": "Tambaram", "type": "Wedding Hall", "rating": "4.8", "distance": "3.8 km", "food": "Chicken Biryani, Fresh Banana Leaves & Wooden Spoons", "status": "Dispatch Ready", "img": "https://images.unsplash.com/photo-1519167758481-83f550bb49b3?auto=format&fit=crop&w=600&q=80"},
        {"name": "Anandhaas Veg Hotel", "area": "Avadi", "type": "Local Hotel", "rating": "4.4", "distance": "4.2 km", "food": "Variety Rice, Kesari, Vadai & Fresh Fruits", "status": "Live Pickup Open", "img": "https://images.unsplash.com/photo-1552566626-52f8b828add9?auto=format&fit=crop&w=600&q=80"},
        {"name": "Sree Devi Palace Mandapam", "area": "Koyambedu", "type": "Wedding Hall", "rating": "4.6", "distance": "4.7 km", "food": "Reception Buffet, Areca Plates & Wooden Spoons Set", "status": "Live Pickup Open", "img": "https://images.unsplash.com/photo-1464366400600-7168b8af9bc3?auto=format&fit=crop&w=600&q=80"}
    ]
    return render_template('nearby.html', hubs=hubs, lat=session.get('lat', '13.0827'), lng=session.get('lng', '80.2707'))

# =========================================================
# ADMIN & DWDM PORTAL ROUTES
# =========================================================
def get_admin_snapshot_data():
    new_event = generate_auto_surplus_tick()
    df = load_dataset()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM food_orders ORDER BY created_at DESC")
    all_orders = [dict(row) for row in c.fetchall()]
    conn.close()

    claimed_kg = sum(float(o['quantity_kg'] or 0) for o in all_orders if o['status'] != 'Cancelled')
    total_rev = sum(int(o['total_price'] or 0) for o in all_orders if o['status'] != 'Cancelled')
    raw_surplus = int(df['Surplus_Quantity'].sum()) if not df.empty else 0
    remaining_surplus = max(0, raw_surplus - int(claimed_kg))

    stats = {
        'total_records': f"{len(df):,}",
        'total_surplus': f"{remaining_surplus:,} kg",
        'waste_prevented': f"{int(df['Quantity_Consumed'].sum()):,} kg" if not df.empty else "0 kg",
        'active_requests': len([o for o in all_orders if o['status'] not in ('Delivered', 'Cancelled')]),
        'total_revenue': total_rev,
        'claimed_kg': round(claimed_kg, 1),
        'timestamp': datetime.now().strftime("%d-%b-%Y %I:%M:%S %p"),
        'live_feed_enabled': LIVE_FEED_STATE['enabled'],
        'recent_events': LIVE_FEED_STATE['recent_events'],
        'new_event': new_event
    }
    return df, all_orders, stats

@app.route('/admin')
@admin_required
def admin_dashboard():
    _, all_orders, stats = get_admin_snapshot_data()
    return render_template('admin.html', stats=stats, orders=all_orders)

@app.route('/api/toggle-live-feed', methods=['POST'])
@admin_required
def toggle_live_feed():
    LIVE_FEED_STATE['enabled'] = not LIVE_FEED_STATE['enabled']
    if LIVE_FEED_STATE['enabled']:
        LIVE_FEED_STATE['last_generated_at'] = 0
        generate_auto_surplus_tick()
    return jsonify({
        'enabled': LIVE_FEED_STATE['enabled'],
        'recent_events': LIVE_FEED_STATE['recent_events']
    })

@app.route('/api/log-venue-surplus', methods=['POST'])
@admin_required
def log_venue_surplus():
    venue = request.form.get('venue_name', 'Meenakshi Mahal Wedding Hall').strip()
    area = request.form.get('area', 'Tambaram').strip()
    event_type = request.form.get('event_type', 'Wedding').strip()
    food_item = request.form.get('food_item', 'Chicken Biryani').strip()
    food_category = request.form.get('food_category', 'Meat').strip()
    surplus_kg = float(request.form.get('surplus_kg', 15.0))
    stamp = datetime.now().strftime("%I:%M:%S %p")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO surplus_stream (venue_name, area, event_type, food_item, food_category, surplus_kg, logged_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (venue, area, event_type, food_item, food_category, surplus_kg, stamp))
    conn.commit()
    conn.close()

    LIVE_FEED_STATE['recent_events'].insert(0, {
        'venue': venue, 'area': area, 'event_type': event_type,
        'food_item': food_item, 'food_category': food_category,
        'surplus_kg': surplus_kg, 'logged_at': stamp
    })
    LIVE_FEED_STATE['recent_events'] = LIVE_FEED_STATE['recent_events'][:6]

    flash(f"Logged +{surplus_kg} kg of {food_item} from {venue} into live warehouse stream!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/api/admin-live-snapshot')
@admin_required
def api_admin_live_snapshot():
    _, all_orders, stats = get_admin_snapshot_data()
    return jsonify({'stats': stats, 'orders': all_orders})

@app.route('/admin/download-live-pdf')
@admin_required
def download_live_pdf():
    df, all_orders, stats = get_admin_snapshot_data()
    exact_time = datetime.now().strftime("%d %b %Y at %I:%M:%S %p")
    file_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    pdf_buffer = io.BytesIO()

    with PdfPages(pdf_buffer) as pdf:
        fig = plt.figure(figsize=(11.69, 8.27))
        fig.patch.set_facecolor('#f8fafc')

        fig.text(0.04, 0.94, "ZEROSPILL — LIVE OPERATIONS & DWDM VISUAL REPORT", fontsize=17, fontweight='bold', color='#065f46')
        fig.text(0.04, 0.905, f"Live Snapshot Captured At: {exact_time}   |   Auto Telemetry Stream: {'ACTIVE' if LIVE_FEED_STATE['enabled'] else 'PAUSED'}", fontsize=10, color='#475569')

        kpis = [
            ("ACTIVE DISPATCH ORDERS", str(stats['active_requests']), "#f59e0b"),
            ("LIVE REVENUE COLLECTED", f"INR {stats['total_revenue']:,}", "#10b981"),
            ("WAREHOUSE SURPLUS LEFT", stats['total_surplus'], "#3b82f6"),
            ("DWDM DATASET RECORDS", stats['total_records'], "#0f172a")
        ]
        for idx, (label, val, col) in enumerate(kpis):
            ax_kpi = fig.add_axes([0.04 + idx * 0.235, 0.77, 0.215, 0.10])
            ax_kpi.set_facecolor('white')
            for spine in ax_kpi.spines.values():
                spine.set_edgecolor(col)
                spine.set_linewidth(2)
            ax_kpi.set_xticks([])
            ax_kpi.set_yticks([])
            ax_kpi.text(0.08, 0.68, label, fontsize=8, fontweight='bold', color='#64748b')
            ax_kpi.text(0.08, 0.22, val, fontsize=15, fontweight='bold', color=col)

        ax1 = fig.add_axes([0.06, 0.41, 0.40, 0.30])
        statuses = ['Pending', 'Approved', 'Preparing', 'Ready', 'Delivered', 'Cancelled']
        status_counts = [len([o for o in all_orders if o['status'] == s]) for s in statuses]
        bar_colors = ['#f59e0b', '#06b6d4', '#3b82f6', '#10b981', '#047857', '#ef4444']
        bars = ax1.barh(statuses[::-1], status_counts[::-1], color=bar_colors[::-1], height=0.55)
        ax1.set_title("Live Order Pipeline Status (Real-Time Count)", fontsize=11, fontweight='bold', color='#0f172a', pad=10)
        ax1.set_xlabel("Number of Orders", fontsize=9)
        ax1.grid(axis='x', linestyle='--', alpha=0.4)
        for bar in bars:
            w = bar.get_width()
            ax1.text(w + 0.1, bar.get_y() + bar.get_height()/2, f"{int(w)}", va='center', fontsize=9, fontweight='bold')

        ax2 = fig.add_axes([0.54, 0.41, 0.40, 0.30])
        pay_groups = {}
        for o in all_orders:
            pm = o.get('payment_method') or 'UPI QR Verified'
            pay_groups[pm] = pay_groups.get(pm, 0) + int(o.get('total_price') or 0)
        if not pay_groups or sum(pay_groups.values()) == 0:
            pay_groups = {'UPI QR Verified': 1}
        wedges, texts, autotexts = ax2.pie(
            pay_groups.values(), labels=pay_groups.keys(), autopct='%1.1f%%',
            startangle=140, colors=['#10b981', '#3b82f6', '#f59e0b'],
            wedgeprops=dict(width=0.45, edgecolor='white'), textprops=dict(fontsize=8.5)
        )
        for at in autotexts:
            at.set_color('white')
            at.set_fontweight('bold')
        ax2.set_title("Revenue Share by Payment Method (INR)", fontsize=11, fontweight='bold', color='#0f172a', pad=10)

        ax3 = fig.add_axes([0.06, 0.08, 0.88, 0.25])
        if not df.empty:
            cat_grp = df.groupby('Food_Category')['Surplus_Quantity'].sum().sort_values(ascending=False)
            c_bars = ax3.bar(cat_grp.index, cat_grp.values, color='#0d9488', width=0.5)
            ax3.set_title("Multidimensional Warehouse Surplus by Food Category (kg)", fontsize=11, fontweight='bold', color='#0f172a')
            ax3.set_ylabel("Total Surplus (kg)", fontsize=9)
            ax3.grid(axis='y', linestyle='--', alpha=0.4)
            for b in c_bars:
                h = b.get_height()
                ax3.text(b.get_x() + b.get_width()/2, h + 150, f"{int(h):,}", ha='center', fontsize=8, fontweight='bold')

        pdf.savefig(fig)
        plt.close(fig)

        fig2 = plt.figure(figsize=(11.69, 8.27))
        fig2.patch.set_facecolor('#f8fafc')

        fig2.text(0.04, 0.94, "3D OLAP CUBE ANALYTICS & LIVE DISPATCH LEDGER", fontsize=16, fontweight='bold', color='#0f172a')
        fig2.text(0.04, 0.905, f"Multidimensional Slice: Event Type × Food Category × Surplus Volume   |   Generated: {exact_time}", fontsize=9.5, color='#475569')

        ax3d = fig2.add_axes([0.03, 0.38, 0.48, 0.48], projection='3d')
        if not df.empty:
            top_events = df['Event_Type'].dropna().unique()[:4]
            top_cats = df['Food_Category'].dropna().unique()[:5]
            xpos, ypos, zpos, dx, dy, dz, colors_3d = [], [], [], [], [], [], []
            palette = ['#10b981', '#3b82f6', '#f59e0b', '#8b5cf6', '#ec4899']

            for xi, evt in enumerate(top_events):
                for yi, cat in enumerate(top_cats):
                    val = df[(df['Event_Type'] == evt) & (df['Food_Category'] == cat)]['Surplus_Quantity'].sum()
                    xpos.append(xi)
                    ypos.append(yi)
                    zpos.append(0)
                    dx.append(0.55)
                    dy.append(0.55)
                    dz.append(val)
                    colors_3d.append(palette[yi % len(palette)])

            ax3d.bar3d(xpos, ypos, zpos, dx, dy, dz, color=colors_3d, shade=True, alpha=0.92)
            ax3d.set_xticks(np.arange(len(top_events)) + 0.25)
            ax3d.set_xticklabels(top_events, fontsize=7.5, rotation=12)
            ax3d.set_yticks(np.arange(len(top_cats)) + 0.25)
            ax3d.set_yticklabels(top_cats, fontsize=7.5)
            ax3d.set_zlabel("Surplus (kg)", fontsize=8)
            ax3d.set_title("3D OLAP Cube: Event × Category × Surplus", fontsize=10.5, fontweight='bold', pad=10)
            ax3d.view_init(elev=26, azim=-48)

        ax_evt = fig2.add_axes([0.56, 0.42, 0.38, 0.40])
        if not df.empty:
            evt_grp = df.groupby('Event_Type')['Surplus_Quantity'].sum()
            ax_evt.pie(evt_grp.values, labels=evt_grp.index, autopct='%1.1f%%', startangle=90,
                       colors=['#065f46', '#0ea5e9', '#f59e0b', '#6366f1', '#14b8a6'], textprops=dict(fontsize=8.5))
            ax_evt.set_title("Surplus Contribution by Event Type", fontsize=10.5, fontweight='bold')

        ax_tbl = fig2.add_axes([0.04, 0.05, 0.92, 0.28])
        ax_tbl.axis('off')
        ax_tbl.set_title("Live Database Orders Ledger (Snapshot at Print Time)", fontsize=11, fontweight='bold', loc='left', color='#0f172a')

        if all_orders:
            table_rows = []
            for o in all_orders[:8]:
                table_rows.append([
                    o['order_id'],
                    o['user_name'],
                    o['food_item'][:24],
                    f"{o['quantity_kg']} kg/pk",
                    f"INR {int(o.get('total_price') or 0)}",
                    (o.get('payment_method') or 'UPI')[:18],
                    o['status']
                ])
            col_labels = ["Order ID", "Customer", "Item", "Qty", "Amount", "Payment", "Live Status"]
            tbl = ax_tbl.table(cellText=table_rows, colLabels=col_labels, loc='center', cellLoc='center')
            tbl.auto_set_font_size(False)
            tbl.set_fontsize(8)
            tbl.scale(1, 1.35)
            for (row_idx, col_idx), cell in tbl.get_celld().items():
                if row_idx == 0:
                    cell.set_facecolor('#0f172a')
                    cell.get_text().set_color('white')
                    cell.get_text().set_weight('bold')
                else:
                    cell.set_facecolor('#ffffff' if row_idx % 2 == 1 else '#f1f5f9')
        else:
            ax_tbl.text(0.5, 0.5, "No live customer orders recorded at this timestamp.", ha='center', va='center', fontsize=10, color='#64748b')

        pdf.savefig(fig2)
        plt.close(fig2)

    pdf_buffer.seek(0)
    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=f"ZeroSpill_Live_Visual_Report_{file_stamp}.pdf",
        mimetype='application/pdf'
    )

# =========================================================
# ORIGINAL DWDM PAGES
# =========================================================
@app.route('/schema')
@admin_required
def schema_view():
    return render_template('schema.html')

@app.route('/olap')
@admin_required
def olap_view():
    return render_template('olap.html')

@app.route('/patterns')
@admin_required
def patterns_view():
    df = load_dataset()
    rules = []
    if not df.empty:
        total_rows = len(df)
        med = df['Surplus_Quantity'].median()
        prob_high = len(df[df['Surplus_Quantity'] > med]) / total_rows
        for (evt, cat), grp in df.groupby(['Event_Type', 'Food_Category']):
            sup = len(grp) / total_rows
            if sup >= 0.03:
                conf = len(grp[grp['Surplus_Quantity'] > med]) / len(grp)
                lift = conf / prob_high if prob_high > 0 else 1.0
                if conf > 0.45:
                    rules.append({
                        'antecedent': f"Event_Type = {evt} + Food_Category = {cat}",
                        'consequent': "High_Surplus_Quantity",
                        'support': f"{sup*100:.1f}%",
                        'confidence': f"{conf*100:.1f}%",
                        'lift': f"{lift:.2f}"
                    })
    rules = sorted(rules, key=lambda x: float(x['lift']), reverse=True)[:10]
    return render_template('patterns.html', rules=rules)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', debug=False, port=port)