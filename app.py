import os
import json
import sqlite3
import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash

from core.harvest_model import train_yield_model, predict_yield, get_model_meta
from core.crop_advisor import get_full_farm_analysis
from core.rimai_assistant_free import get_chat_response
from core.explanation_engine import build_virtual_agronomist_response
from integrations.whatsapp_service import (
    send_whatsapp, log_message,
    build_planting_alert, build_pest_warning, build_weather_alert,
    build_fertilizer_reminder, build_harvest_reminder, build_weekly_digest,
    _is_configured as twilio_configured
)
from integrations.email_service import (
    send_email, log_email,
    build_risk_alert_email, build_pest_alert_email, build_weekly_report_email,
    _is_configured as email_configured
)
from integrations.proactive_alerts import ensure_tables as ensure_alert_tables, start_background_watcher
from core.farm_manager import health_score, daily_brief, farm_memory, action_calendar, run_scenario
from core.harvest_model import PROVINCE_META
from dashboards.agritex import latest_farmer_snapshots, ward_risk_table, priority_queue, ask_the_data
import dashboards.ministry as ministry_module
import dashboards.admin as admin_module
import data_pipeline.synthetic_registry as registry_module

app = Flask(__name__)
app.secret_key = "rimai_2026_secret"
DB = "rimai.db"

app.jinja_env.filters['from_json'] = json.loads

PROVINCES = ["Mashonaland West", "Mashonaland Central", "Mashonaland East", "Harare",
             "Manicaland", "Midlands", "Masvingo", "Matabeleland North",
             "Matabeleland South", "Bulawayo"]
SOIL_TYPES = ["Clay-Loam", "Sandy", "Sandy-Loam", "Clay", "Loam", "Red Clay", "Black Cotton"]
PREVIOUS_CROPS = ["Maize", "Tobacco", "Groundnuts", "Soybeans", "Cotton", "Fallow/None"]


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'farmer',
                full_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                prediction_type TEXT,
                inputs TEXT,
                result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS yield_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                province TEXT,
                year INTEGER,
                crop TEXT,
                yield_t_ha REAL,
                rainfall_mm REAL,
                area_ha REAL
            );
            CREATE TABLE IF NOT EXISTS whatsapp_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                phone TEXT NOT NULL,
                alert_planting INTEGER DEFAULT 1,
                alert_pest INTEGER DEFAULT 1,
                alert_weather INTEGER DEFAULT 1,
                alert_fertilizer INTEGER DEFAULT 1,
                alert_harvest INTEGER DEFAULT 1,
                alert_weekly INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS whatsapp_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                msg_type TEXT,
                message TEXT,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                role TEXT,
                content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS field_visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                officer_id INTEGER,
                farmer_id INTEGER,
                observation TEXT,
                recommendation TEXT,
                follow_up_date TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS input_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                province TEXT,
                district TEXT,
                bags_allocated INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        existing = db.execute("SELECT id FROM users WHERE username='demo'").fetchone()
        if not existing:
            db.execute("INSERT INTO users (username,password,role) VALUES (?,?,?)",
                       ('demo', generate_password_hash('rimai2026'), 'farmer'))
            db.execute("INSERT INTO users (username,password,role) VALUES (?,?,?)",
                       ('officer', generate_password_hash('officer2026'), 'officer'))
            seed_data = [
                ('Mashonaland West', 2020, 'Maize', 1.8, 650, 120000),
                ('Mashonaland West', 2021, 'Maize', 2.1, 720, 130000),
                ('Mashonaland West', 2022, 'Maize', 1.5, 480, 115000),
                ('Mashonaland West', 2023, 'Maize', 2.3, 800, 140000),
                ('Mashonaland Central', 2020, 'Maize', 1.6, 600, 90000),
                ('Mashonaland Central', 2021, 'Maize', 1.9, 680, 95000),
                ('Mashonaland Central', 2022, 'Maize', 1.2, 420, 80000),
                ('Mashonaland Central', 2023, 'Maize', 2.0, 750, 100000),
                ('Manicaland', 2020, 'Maize', 2.2, 850, 60000),
                ('Manicaland', 2021, 'Maize', 2.5, 920, 65000),
                ('Manicaland', 2022, 'Maize', 1.8, 600, 55000),
                ('Manicaland', 2023, 'Maize', 2.7, 980, 70000),
                ('Masvingo', 2020, 'Maize', 0.9, 380, 45000),
                ('Masvingo', 2021, 'Maize', 1.1, 420, 48000),
                ('Masvingo', 2022, 'Maize', 0.7, 310, 40000),
                ('Masvingo', 2023, 'Maize', 1.3, 460, 50000),
                ('Matabeleland North', 2020, 'Maize', 0.7, 320, 30000),
                ('Matabeleland North', 2021, 'Maize', 0.9, 370, 32000),
                ('Matabeleland North', 2022, 'Maize', 0.5, 250, 28000),
                ('Matabeleland North', 2023, 'Maize', 1.0, 400, 35000),
            ]
            db.executemany("INSERT INTO yield_history VALUES (NULL,?,?,?,?,?,?)", seed_data)
        db.commit()

        alloc_seed_check = db.execute("SELECT COUNT(*) c FROM input_allocations").fetchone()
        if alloc_seed_check["c"] == 0:
            db.executemany(
                "INSERT INTO input_allocations (province, district, bags_allocated) VALUES (?,?,?)",
                [
                    ("Mashonaland West", "Chegutu", 1200),
                    ("Mashonaland Central", "Bindura", 950),
                    ("Manicaland", "Mutare", 800),
                    ("Masvingo", "Chivi", 600),
                    ("Matabeleland North", "Hwange", 450),
                    ("Matabeleland South", "Gwanda", 400),
                ],
            )
            db.commit()

        # Defensive migration: databases created before full_name was added
        # to the schema above won't have the column yet. Add it if missing,
        # so both fresh installs and pre-existing databases work identically.
        existing_cols = [row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()]
        if "full_name" not in existing_cols:
            db.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
            db.commit()


init_db()
train_yield_model()
ensure_alert_tables(DB)
start_background_watcher(DB)


def login_required(f):
    @wraps(f)
    def dec(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return dec


@app.context_processor
def inject_unseen_alerts():
    if 'user_id' not in session:
        return {}
    with get_db() as db:
        count = db.execute('SELECT COUNT(*) FROM alerts WHERE user_id=? AND seen=0',
                           (session['user_id'],)).fetchone()[0]
    return {"unseen_alert_count": count}


@app.route('/')
def home():
    with get_db() as db:
        yh = db.execute('SELECT province, year, yield_t_ha, rainfall_mm FROM yield_history ORDER BY year').fetchall()
    yh_data = [{k: r[k] for k in ['province', 'year', 'yield_t_ha', 'rainfall_mm']} for r in yh]
    return render_template('home.html', yh_data=json.dumps(yh_data))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        with get_db() as db:
            user = db.execute('SELECT * FROM users WHERE username=?', (u,)).fetchone()
        if user and check_password_hash(user['password'], p):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['full_name'] = user['full_name'] if 'full_name' in user.keys() and user['full_name'] else None
            role = session.get('role', 'farmer')
            if role == 'officer':
                return redirect(url_for('agritex_dashboard'))
            elif role == 'ministry':
                return redirect(url_for('ministry_dashboard'))
            elif role == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('farm_manager_page'))
        flash('Invalid credentials. Try demo / rimai2026', 'error')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        try:
            with get_db() as db:
                db.execute('INSERT INTO users (username,password) VALUES (?,?)',
                           (u, generate_password_hash(p)))
                db.commit()
            flash('Account created. Please log in.', 'success')
            return redirect(url_for('login'))
        except Exception:
            flash('Username already taken.', 'error')
    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))


@app.route('/advisor', methods=['GET', 'POST'])
@login_required
def advisor():
    result = None
    if request.method == 'POST':
        inputs = {
            'province': request.form.get('province'),
            'district': request.form.get('district'),
            'soil_type': request.form.get('soil_type'),
            'crop': request.form.get('crop', 'Maize'),
            'previous_crop': request.form.get('previous_crop'),
            'years_continuous': int(request.form.get('years_continuous', 1)),
            'planting_date': request.form.get('planting_date'),
            'farm_size': float(request.form.get('farm_size', 1)),
        }
        lat = request.form.get('lat')
        lon = request.form.get('lon')
        if lat and lon:
            inputs['lat'] = float(lat)
            inputs['lon'] = float(lon)

        result = get_full_farm_analysis(inputs)
        session['last_analysis'] = result

        with get_db() as db:
            db.execute('INSERT INTO predictions (user_id,prediction_type,inputs,result) VALUES (?,?,?,?)',
                       (session['user_id'], 'crop_advisor', json.dumps(inputs), json.dumps(result)))
            db.commit()
    return render_template('advisor.html', result=result, provinces=PROVINCES,
                           soil_types=SOIL_TYPES, previous_crops=PREVIOUS_CROPS)


@app.route('/yield', methods=['GET', 'POST'])
@login_required
def yield_pred():
    result = None
    if request.method == 'POST':
        inputs = {
            'rainfall_mm': float(request.form.get('rainfall_mm', 600)),
            'temperature_c': float(request.form.get('temperature_c', 22)),
            'soil_type': request.form.get('soil_type'),
            'planting_month': int(request.form.get('planting_month', 11)),
            'farm_size_ha': float(request.form.get('farm_size_ha', 1)),
            'rotation_score': float(request.form.get('rotation_score', 0)),
        }
        result = predict_yield(inputs)
        with get_db() as db:
            db.execute('INSERT INTO predictions (user_id,prediction_type,inputs,result) VALUES (?,?,?,?)',
                       (session['user_id'], 'yield_prediction', json.dumps(inputs), json.dumps(result)))
            db.commit()
    return render_template('yield.html', result=result, soil_types=SOIL_TYPES)


@app.route('/farm-manager', methods=['GET', 'POST'])
@login_required
def farm_manager_page():
    with get_db() as db:
        user = db.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
        preds = db.execute(
            "SELECT result, created_at FROM predictions WHERE user_id=? AND prediction_type='crop_advisor' "
            "ORDER BY created_at DESC LIMIT 2", (session['user_id'],)).fetchall()
    display_name = (user['full_name'] if user and user['full_name']
                     else session.get('username', 'Farmer').capitalize())

    if not preds:
        return render_template('farm_manager.html', has_analysis=False, display_name=display_name,
                               farm_data={})

    current = json.loads(preds[0]['result'])
    previous = json.loads(preds[1]['result']) if len(preds) > 1 else None

    scenario = None
    scenario_form = {'rainfall_pct': '0', 'fertilizer': 'on'}
    if request.method == 'POST' and request.form.get('run_scenario'):
        scenario_form = {'rainfall_pct': request.form.get('rainfall_pct', '0'),
                         'fertilizer': request.form.get('fertilizer', 'on')}
        scenario = run_scenario(current, rainfall_pct_change=float(scenario_form['rainfall_pct']),
                                fertilizer_on=(scenario_form['fertilizer'] == 'on'))

    score = health_score(current)
    with get_db() as db:
        alert_row = db.execute('SELECT message FROM alerts WHERE user_id=? ORDER BY created_at DESC LIMIT 1',
                               (session['user_id'],)).fetchone()
    latest_alert = alert_row['message'] if alert_row else None
    brief = daily_brief(current, latest_alert)
    memory_note = farm_memory(current, previous)
    calendar = action_calendar(current)

    province = current.get('inputs_used', {}).get('province', 'Harare')
    benchmark_yield = PROVINCE_META.get(province, {}).get('avg_yield', 1.8)
    yield_pred = float(current.get('yield_t_ha') or 0)
    yield_vs_benchmark_pct = round(((yield_pred - benchmark_yield) / benchmark_yield) * 100, 1) if benchmark_yield else 0
    recoverable_t_ha = round(max(0, benchmark_yield - yield_pred), 2)

    farm_data = {}
    farm_data.update(current.get('inputs_used', {}))
    farm_data['yield_t_ha'] = yield_pred

    return render_template('farm_manager.html', has_analysis=True, display_name=display_name,
                           farm_data=farm_data, score=score, brief=brief, memory_note=memory_note,
                           calendar=calendar, benchmark_yield=benchmark_yield,
                           yield_vs_benchmark_pct=yield_vs_benchmark_pct, recoverable_t_ha=recoverable_t_ha,
                           scenario=scenario, scenario_form=scenario_form)


@app.route('/dashboard')
@login_required
def dashboard():
    with get_db() as db:
        total_farmers = db.execute("SELECT COUNT(*) FROM users WHERE role='farmer'").fetchone()[0]
        total_preds = db.execute('SELECT COUNT(*) FROM predictions').fetchone()[0]
        provinces = db.execute('SELECT DISTINCT province FROM yield_history').fetchall()
        province_list = [r['province'] for r in provinces]
        yh = db.execute('SELECT province, year, yield_t_ha, rainfall_mm FROM yield_history ORDER BY year').fetchall()
    yh_data = [{k: r[k] for k in ['province', 'year', 'yield_t_ha', 'rainfall_mm']} for r in yh]
    return render_template('farmer_dashboard.html', total_farmers=total_farmers, total_preds=total_preds,
                           provinces=province_list, yh_data=json.dumps(yh_data))


@app.route('/chat')
@login_required
def chat():
    from core.rimai_assistant_free import build_greeting
    with get_db() as db:
        history = db.execute('SELECT role, content, created_at FROM chat_history WHERE user_id=? ORDER BY created_at',
                             (session['user_id'],)).fetchall()
    chat_log = [{'role': r['role'], 'content': r['content']} for r in history]

    # Build farm context for greeting
    analysis  = session.get('last_analysis', {})
    farm_data = {}
    if analysis:
        farm_data.update(analysis.get('inputs_used', {}))
        farm_data.update(analysis.get('weather', {}))
        farm_data['timing']              = analysis.get('timing', 'unknown')
        farm_data['risk_label']          = analysis.get('risk_label', 'unknown')
        farm_data['risk_confidence']     = analysis.get('risk_confidence')
        farm_data['yield_t_ha']          = analysis.get('yield_t_ha')
        farm_data['recommended_variety'] = analysis.get('recommended_variety', 'SC513')
        farm_data['pest_alerts']         = analysis.get('pest_risk', {}).get('active_alerts', [])

    # Inject greeting if not already recently shown
    recent = [m for m in chat_log[-5:] if m['role']=='assistant'
              and ('Welcome back' in m['content'] or 'Good to meet' in m['content'])]
    if not recent:
        greeting = build_greeting(
            session.get('username',''), farm_data, len(chat_log))
        chat_log = [{'role': 'assistant', 'content': greeting}] + chat_log

    with get_db() as db:
        db.execute('UPDATE alerts SET seen=1 WHERE user_id=?', (session['user_id'],))
        db.commit()

    return render_template('chat.html', chat_log=chat_log,
                           suggested_questions=['Should I plant maize this week?', 'What fertilizer should I apply?', 'What yield should I expect?', 'Why is my yield low?', 'When should I irrigate?', 'What does the weather look like?', 'Are there any pest or disease risks?', 'What does my crop rotation look like?', 'How risky is this season?', 'Which seed variety should I use?'])


@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    message = request.form.get('message', '')
    analysis = session.get('last_analysis', {})
    farm_data = {}
    if analysis:
        farm_data.update(analysis.get('inputs_used', {}))
        farm_data.update(analysis.get('weather', {}))
        farm_data['timing']            = analysis.get('timing', 'unknown')
        farm_data['risk_label']        = analysis.get('risk_label', 'unknown')
        farm_data['risk_score']        = analysis.get('risk_score', 0)
        farm_data['recommended_variety']= analysis.get('recommended_variety', 'SC513')
        farm_data['agro_zone']         = analysis.get('agro_zone', 'II')
        farm_data['irrigation']        = analysis.get('irrigation', '')
        rot = analysis.get('rotation', {})
        farm_data['rotation_verdict']  = rot.get('verdict', 'Neutral')
        farm_data['rotation_note']     = rot.get('note', '')
        pest = analysis.get('pest_risk', {})
        farm_data['pest_alerts']       = pest.get('active_alerts', [])
        fert = analysis.get('fertilizer', {})
        farm_data['compound_d_kg']     = fert.get('compound_d_kg', 0)
        farm_data['an_kg']             = fert.get('an_kg', 0)
        farm_data['yield_t_ha']        = analysis.get('yield_t_ha')
    # Route 'why/explain/economic/intervention' questions to Virtual Agronomist
    va_keywords = ['why','explain','reason','cause','what should i do','action',
                   'intervention','improve','fix','money','revenue','profit',
                   'economic','risk','danger','probability']
    use_va = any(kw in message.lower() for kw in va_keywords)
    analysis_full = session.get('last_analysis', {})
    if use_va and analysis_full:
        reply = build_virtual_agronomist_response(message, analysis_full)
        result = {"success": True, "reply": reply}
    else:
        result = get_chat_response(message, farm_data, username=session.get('username',''))
    with get_db() as db:
        db.execute('INSERT INTO chat_history (user_id, role, content) VALUES (?,?,?)',
                   (session['user_id'], 'user', message))
        db.execute('INSERT INTO chat_history (user_id, role, content) VALUES (?,?,?)',
                   (session['user_id'], 'assistant', result['reply']))
        db.commit()
    return jsonify({'success': True, 'reply': result['reply']})



NATIONAL_AREA_HA = {  # approximate planted maize area per province
    "Mashonaland West":140000,"Mashonaland Central":100000,
    "Mashonaland East":90000,"Harare":20000,"Manicaland":70000,
    "Midlands":80000,"Masvingo":50000,"Matabeleland North":35000,
    "Matabeleland South":28000,"Bulawayo":10000,
}
NATIONAL_INTERVENTIONS = {
    "Low":      "Conditions are favourable. Maintain standard extension support and monitor for Fall Armyworm during vegetative stage.",
    "Moderate": "Elevated risk. Recommend AGRITEX field visits to verify planting progress and fertilizer application rates.",
    "High":     "High crop failure risk. Deploy emergency AGRITEX support, assess irrigation availability, and pre-position input relief.",
}

def compute_national_snapshot():
    from core.harvest_model import predict_yield, PROVINCE_META
    from data_pipeline.weather_service import get_weather_for_farm
    province_data = {}
    for prov, meta in PROVINCE_META.items():
        weather = get_weather_for_farm(prov)
        rainfall = weather.get('total_rainfall_mm', meta['avg_rain'])
        result = predict_yield({
            'province': prov, 'rainfall_mm': rainfall,
            'temperature_c': weather.get('avg_temp_c', 22),
            'planting_month': 11, 'farm_size_ha': 1,
        })
        vs_norm = round((result['yield_t_ha'] - meta['avg_yield']) / meta['avg_yield'] * 100, 1)
        province_data[prov] = {
            "yield": result['yield_t_ha'], "risk": result['risk_label'],
            "rainfall": round(rainfall), "zone": meta['zone'], "norm": meta['avg_yield'],
            "vs_norm": vs_norm, "area_ha": NATIONAL_AREA_HA.get(prov, 50000),
            "recommendation": NATIONAL_INTERVENTIONS[result['risk_label']],
        }
    return province_data


@app.route('/national-dashboard')
@login_required
def national_dashboard():
    province_data = compute_national_snapshot()
    return render_template('national_dashboard.html',
                           province_data=json.dumps(province_data))


@app.route('/ministry', methods=['GET', 'POST'])
@login_required
def ministry_dashboard():
    from harvest_model import PROVINCE_META
    province_data = compute_national_snapshot()
    fsi = ministry_module.food_security_index(province_data)
    production = ministry_module.national_production(province_data)
    warnings = ministry_module.early_warning_feed(province_data)
    allocation = ministry_module.input_allocation_intelligence(province_data)

    policy_sim = None
    sim_form = {'rainfall_pct': '0', 'temp_delta': '0'}
    if request.method == 'POST' and request.form.get('run_policy_sim'):
        sim_form = {'rainfall_pct': request.form.get('rainfall_pct', '0'),
                    'temp_delta': request.form.get('temp_delta', '0')}
        policy_sim = ministry_module.policy_simulation(
            float(sim_form['rainfall_pct']), float(sim_form['temp_delta']),
            NATIONAL_AREA_HA, PROVINCE_META)

    return render_template('ministry_dashboard.html', fsi=fsi, production=production,
                           warnings=warnings, allocation=allocation, policy_sim=policy_sim,
                           sim_form=sim_form, province_data=province_data)


@app.route('/model-insights')
@login_required
def model_insights():
    meta = get_model_meta()

    backtest_results = []
    backtest_metrics = None
    backtest_path = os.path.join('data', 'processed', 'backtest_results.csv')
    metrics_path = os.path.join('data', 'processed', 'backtest_metrics.json')

    if os.path.exists(backtest_path):
        import csv
        with open(backtest_path) as f:
            backtest_results = list(csv.DictReader(f))

    if os.path.exists(metrics_path):
        with open(metrics_path) as f:
            backtest_metrics = json.load(f)

    return render_template('model_insights.html', meta=meta,
                           backtest_results=json.dumps(backtest_results),
                           backtest_metrics=backtest_metrics)




@app.route('/whatsapp')
@login_required
def whatsapp():
    analysis = session.get('last_analysis', {})
    farm_data = {}
    if analysis:
        farm_data.update(analysis.get('inputs_used', {}))
        farm_data.update(analysis.get('weather', {}))
        farm_data['timing']              = analysis.get('timing', 'unknown')
        farm_data['risk_label']          = analysis.get('risk_label', 'unknown')
        farm_data['risk_score']          = analysis.get('risk_score', 0)
        farm_data['recommended_variety'] = analysis.get('recommended_variety', 'SC513')
        farm_data['yield_t_ha']          = analysis.get('yield_t_ha', 0)
        farm_data['pest_alerts']         = analysis.get('pest_risk', {}).get('active_alerts', [])
        farm_data['an_kg']               = analysis.get('fertilizer', {}).get('an_kg', 0)
    previews = {
        'tabPlanting': build_planting_alert(farm_data) if farm_data else None,
        'tabPest':     build_pest_warning(farm_data) if farm_data else None,
        'tabWeather':  build_weather_alert(farm_data) if farm_data else None,
        'tabDigest':   build_weekly_digest(farm_data) if farm_data else None,
    }
    with get_db() as db:
        sub = db.execute('SELECT * FROM whatsapp_subscriptions WHERE user_id=?',
                         (session['user_id'],)).fetchone()
        log = db.execute('SELECT * FROM whatsapp_log WHERE user_id=? ORDER BY created_at DESC LIMIT 20',
                         (session['user_id'],)).fetchall()
    return render_template('whatsapp.html', subscription=sub,
                           log=[dict(r) for r in log],
                           previews=previews, twilio_configured=twilio_configured())


@app.route('/whatsapp/subscribe', methods=['POST'])
@login_required
def whatsapp_subscribe():
    phone = request.form.get('phone', '').strip().lstrip('0')
    if not phone.isdigit() or len(phone) != 9:
        flash('Enter a valid 9-digit Zimbabwe mobile number.', 'error')
        return redirect(url_for('whatsapp'))
    full_number = '+263' + phone
    prefs = {k: 1 if request.form.get(k) else 0 for k in
             ['alert_planting','alert_pest','alert_weather',
              'alert_fertilizer','alert_harvest','alert_weekly']}
    with get_db() as db:
        db.execute(
            "INSERT INTO whatsapp_subscriptions "
            "(user_id,phone,alert_planting,alert_pest,alert_weather,"
            "alert_fertilizer,alert_harvest,alert_weekly) "
            "VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "phone=excluded.phone,alert_planting=excluded.alert_planting,"
            "alert_pest=excluded.alert_pest,alert_weather=excluded.alert_weather,"
            "alert_fertilizer=excluded.alert_fertilizer,alert_harvest=excluded.alert_harvest,"
            "alert_weekly=excluded.alert_weekly",
            (session['user_id'], full_number,
             prefs['alert_planting'],prefs['alert_pest'],prefs['alert_weather'],
             prefs['alert_fertilizer'],prefs['alert_harvest'],prefs['alert_weekly']))
        db.commit()
    welcome = ("Welcome to RimAI Farm Alerts! You are now subscribed to personalised "
               "WhatsApp alerts. Run the Crop Advisor in the RimAI app to activate "
               "your personalised alerts. Reply STOP to unsubscribe. RimAI.zw")
    result = send_whatsapp(full_number, welcome)
    log_message(DB, session['user_id'], 'welcome', welcome, result)
    mode = "sent to " + full_number if result.get("success") else "logged (demo mode — add Twilio keys for real messages)"
    flash("Subscribed! Welcome message " + mode, 'success')
    return redirect(url_for('whatsapp'))


@app.route('/whatsapp/send-now', methods=['POST'])
@login_required
def whatsapp_send_now():
    analysis = session.get('last_analysis', {})
    if not analysis:
        flash('Run the Crop Advisor first, then send alerts.', 'error')
        return redirect(url_for('whatsapp'))
    with get_db() as db:
        sub = db.execute('SELECT * FROM whatsapp_subscriptions WHERE user_id=?',
                         (session['user_id'],)).fetchone()
    if not sub:
        flash('Subscribe first before sending alerts.', 'error')
        return redirect(url_for('whatsapp'))
    farm_data = {}
    farm_data.update(analysis.get('inputs_used', {}))
    farm_data.update(analysis.get('weather', {}))
    farm_data['timing']              = analysis.get('timing', 'unknown')
    farm_data['risk_label']          = analysis.get('risk_label', 'unknown')
    farm_data['recommended_variety'] = analysis.get('recommended_variety', 'SC513')
    farm_data['yield_t_ha']          = analysis.get('yield_t_ha', 0)
    farm_data['pest_alerts']         = analysis.get('pest_risk', {}).get('active_alerts', [])
    farm_data['an_kg']               = analysis.get('fertilizer', {}).get('an_kg', 0)
    builders = []
    if sub['alert_planting']:    builders.append(('planting_alert',     build_planting_alert))
    if sub['alert_pest']:        builders.append(('pest_warning',        build_pest_warning))
    if sub['alert_weather']:     builders.append(('weather_alert',       build_weather_alert))
    if sub['alert_fertilizer']:  builders.append(('fertilizer_reminder', build_fertilizer_reminder))
    if sub['alert_harvest']:     builders.append(('harvest_reminder',    build_harvest_reminder))
    if sub['alert_weekly']:      builders.append(('weekly_digest',       build_weekly_digest))
    sent = 0
    for msg_type, builder in builders:
        msg = builder(farm_data)
        if msg:
            result = send_whatsapp(sub['phone'], msg)
            log_message(DB, session['user_id'], msg_type, msg, result)
            if result.get('success') or result.get('simulated'):
                sent += 1
    mode = "sent to " + sub['phone'] if twilio_configured() else "logged in demo mode"
    flash(str(sent) + " alert(s) " + mode + ".", 'success')
    return redirect(url_for('whatsapp'))


@app.route('/whatsapp/unsubscribe', methods=['POST'])
@login_required
def whatsapp_unsubscribe():
    with get_db() as db:
        db.execute('DELETE FROM whatsapp_subscriptions WHERE user_id=?', (session['user_id'],))
        db.commit()
    flash('Unsubscribed from WhatsApp alerts.', 'success')
    return redirect(url_for('whatsapp'))

@app.route('/email')
@login_required
def email_page():
    analysis = session.get('last_analysis', {})
    farm_data = {}
    if analysis:
        farm_data.update(analysis.get('inputs_used', {}))
        farm_data.update(analysis.get('weather', {}))
        farm_data['timing']      = analysis.get('timing', 'unknown')
        farm_data['risk_label']  = analysis.get('risk_label', 'unknown')
        farm_data['risk_confidence'] = analysis.get('risk_confidence')
        farm_data['yield_t_ha']  = analysis.get('yield_t_ha', 0)
        farm_data['pest_alerts'] = analysis.get('pest_risk', {}).get('active_alerts', [])
    preview = None
    if farm_data:
        weekly = build_weekly_report_email(farm_data)
        preview = weekly[1] if weekly else None
    with get_db() as db:
        sub = db.execute('SELECT * FROM email_subscriptions WHERE user_id=?',
                         (session['user_id'],)).fetchone()
        log = db.execute('SELECT * FROM email_log WHERE user_id=? ORDER BY created_at DESC LIMIT 20',
                         (session['user_id'],)).fetchall()
    return render_template('email.html', subscription=sub,
                           log=[dict(r) for r in log],
                           preview=preview, email_configured=email_configured())


@app.route('/email/subscribe', methods=['POST'])
@login_required
def email_subscribe():
    addr = request.form.get('email', '').strip()
    if '@' not in addr or '.' not in addr:
        flash('Enter a valid email address.', 'error')
        return redirect(url_for('email_page'))
    prefs = {k: 1 if request.form.get(k) else 0 for k in
             ['alert_risk', 'alert_pest', 'alert_weekly']}
    with get_db() as db:
        db.execute(
            "INSERT INTO email_subscriptions (user_id,email,alert_risk,alert_pest,alert_weekly) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "email=excluded.email,alert_risk=excluded.alert_risk,"
            "alert_pest=excluded.alert_pest,alert_weekly=excluded.alert_weekly",
            (session['user_id'], addr, prefs['alert_risk'], prefs['alert_pest'], prefs['alert_weekly']))
        db.commit()
    welcome_subject = "Welcome to RimAI Email Reports"
    welcome_body = ("You're now subscribed to RimAI farm reports. Run the Crop Advisor "
                     "in the RimAI app to activate your personalised alerts.\n\n— RimAI")
    result = send_email(addr, welcome_subject, welcome_body)
    log_email(DB, session['user_id'], 'welcome', welcome_body, result)
    mode = "sent to " + addr if result.get("success") else "logged (demo mode — add SMTP credentials for real emails)"
    flash("Subscribed! Welcome email " + mode, 'success')
    return redirect(url_for('email_page'))


@app.route('/email/send-now', methods=['POST'])
@login_required
def email_send_now():
    analysis = session.get('last_analysis', {})
    if not analysis:
        flash('Run the Crop Advisor first, then send reports.', 'error')
        return redirect(url_for('email_page'))
    with get_db() as db:
        sub = db.execute('SELECT * FROM email_subscriptions WHERE user_id=?',
                         (session['user_id'],)).fetchone()
    if not sub:
        flash('Subscribe first before sending reports.', 'error')
        return redirect(url_for('email_page'))
    farm_data = {}
    farm_data.update(analysis.get('inputs_used', {}))
    farm_data.update(analysis.get('weather', {}))
    farm_data['timing']      = analysis.get('timing', 'unknown')
    farm_data['risk_label']  = analysis.get('risk_label', 'unknown')
    farm_data['risk_confidence'] = analysis.get('risk_confidence')
    farm_data['yield_t_ha']  = analysis.get('yield_t_ha', 0)
    farm_data['pest_alerts'] = analysis.get('pest_risk', {}).get('active_alerts', [])
    sent = 0
    if sub['alert_risk']:
        subject, body = build_risk_alert_email(farm_data)
        result = send_email(sub['email'], subject, body)
        log_email(DB, session['user_id'], 'risk_alert', body, result)
        if result.get('success') or result.get('simulated'):
            sent += 1
    if sub['alert_pest']:
        built = build_pest_alert_email(farm_data)
        if built:
            subject, body = built
            result = send_email(sub['email'], subject, body)
            log_email(DB, session['user_id'], 'pest_alert', body, result)
            if result.get('success') or result.get('simulated'):
                sent += 1
    if sub['alert_weekly']:
        subject, body = build_weekly_report_email(farm_data)
        result = send_email(sub['email'], subject, body)
        log_email(DB, session['user_id'], 'weekly_report', body, result)
        if result.get('success') or result.get('simulated'):
            sent += 1
    mode = "sent to " + sub['email'] if email_configured() else "logged in demo mode"
    flash(str(sent) + " report(s) " + mode + ".", 'success')
    return redirect(url_for('email_page'))


@app.route('/email/unsubscribe', methods=['POST'])
@login_required
def email_unsubscribe():
    with get_db() as db:
        db.execute('DELETE FROM email_subscriptions WHERE user_id=?', (session['user_id'],))
        db.commit()
    flash('Unsubscribed from email reports.', 'success')
    return redirect(url_for('email_page'))


@app.route('/agritex', methods=['GET', 'POST'])
@login_required
def agritex_dashboard():
    snapshots = latest_farmer_snapshots(DB)
    ward_table = ward_risk_table(snapshots)
    queue = priority_queue(snapshots)

    answer, last_question = None, None
    if request.method == 'POST' and request.form.get('action') == 'ask':
        last_question = request.form.get('question', '')
        answer = ask_the_data(last_question, snapshots)
    elif request.method == 'POST' and request.form.get('action') == 'visit':
        with get_db() as db:
            db.execute(
                "INSERT INTO field_visits (officer_id,farmer_id,observation,recommendation,follow_up_date) "
                "VALUES (?,?,?,?,?)",
                (session['user_id'], request.form.get('farmer_id'),
                 request.form.get('observation'), request.form.get('recommendation'),
                 request.form.get('follow_up_date')))
            db.commit()
        flash('Field visit report saved.', 'success')

    farmers_by_district = {}
    for s in snapshots:
        farmers_by_district.setdefault(s['district'], []).append(s)

    with get_db() as db:
        alloc_rows = db.execute('SELECT * FROM input_allocations ORDER BY province, district').fetchall()
        visit_rows = db.execute(
            "SELECT fv.*, u.full_name, u.username FROM field_visits fv "
            "JOIN users u ON u.id = fv.farmer_id "
            "ORDER BY fv.created_at DESC LIMIT 10"
        ).fetchall()

    allocations = []
    for a in alloc_rows:
        district_farmers = farmers_by_district.get(a['district'], [])
        allocations.append({
            'district': a['district'], 'bags_allocated': a['bags_allocated'],
            'farms_reached': len(district_farmers), 'farmers_in_district': max(len(district_farmers), 1),
        })

    visits = [{'farmer_name': (v['full_name'] or v['username'].capitalize()),
              'observation': v['observation'], 'recommendation': v['recommendation'],
              'follow_up_date': v['follow_up_date']} for v in visit_rows]

    return render_template('agritex_dashboard.html', ward_table=ward_table, priority_queue=queue,
                           farmer_count=len(snapshots), answer=answer, last_question=last_question,
                           allocations=allocations, visits=visits)


@app.route('/admin')
@login_required
def admin_dashboard():
    from core.harvest_model import get_model_meta
    model_meta = get_model_meta()
    backtest_results, metrics, is_synthetic = admin_module.load_backtest()
    pipeline_stages = admin_module.data_pipeline_status()
    health = admin_module.system_health(DB)
    return render_template('admin_dashboard.html', model_meta=model_meta,
                           backtest_results=backtest_results, metrics=metrics,
                           is_synthetic=is_synthetic, pipeline_stages=pipeline_stages,
                           health=health, whatsapp_live=twilio_configured(),
                           email_live=email_configured())


@app.route('/admin/data-provenance')
@login_required
def data_provenance():
    registry = registry_module.load_registry()
    gaps = registry_module.detect_gaps(registry)
    quality = registry_module.data_quality_summary(registry)
    return render_template('data_provenance.html', registry=registry, gaps=gaps, quality=quality)


@app.route('/admin/synthetic-toggle', methods=['POST'])
@login_required
def synthetic_toggle():
    dataset_id = request.form.get('dataset_id')
    enabled = request.form.get('enabled') == 'true'
    registry_module.set_dataset_enabled(dataset_id, enabled)
    return redirect(url_for('data_provenance'))


@app.route('/about')
def about():
    return render_template('about.html')


if __name__ == '__main__':
    app.run(port=5000)
