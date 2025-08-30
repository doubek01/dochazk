from flask import Flask, render_template, redirect, url_for, request, session, jsonify, g, flash
from werkzeug.security import check_password_hash
from datetime import datetime, timedelta
from functools import wraps
from collections import defaultdict
from flask_migrate import Migrate
from io import BytesIO

from flask_sqlalchemy import SQLAlchemy
from models import db, User, Dochazka, Vyplata, VyplataDochazky
from dotenv import load_dotenv


import os
import pytz
import locale
import calendar
import urllib.parse
import bcrypt
import qrcode
import base64
import re


print("DB URI:", os.getenv("DATABASE_URL"))


# Načti proměnné z .env souboru
load_dotenv()

# Inicializace Flask aplikace
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "default_secret")

# Konfigurace databáze
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
migrate = Migrate(app, db)


def login_required(f):

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function

# Přihlášení
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()

        if user and bcrypt.checkpw(password.encode('utf-8'), user.password.encode('utf-8')):
            session['username'] = user.username
            session['user_id'] = user.id
            session['is_admin'] = user.is_admin
            flash('Přihlášení proběhlo úspěšně', 'success')
            return redirect(url_for('admin_dashboard') if user.is_admin else url_for('dashboard'))
        else:
            flash('Neplatné přihlašovací údaje', 'danger')

    return render_template('login.html')

# Přechod na dashboard
@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))

    return render_template('dashboard.html')

# Hlavní stránka / dashboard
@app.route('/')
def home():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    today_str = datetime.today().strftime("%Y-%m-%d")

    # Získání dnešního záznamu
    record = Dochazka.query.filter_by(username=username, date=today_str).first()

    today_in = record.in_time if record else None
    today_out = record.out_time if record else None

    # Výpočet aktuálního času
    cz_time = datetime.now(pytz.timezone("Europe/Prague"))
    current_time = cz_time.strftime('%H:%M')
    today_hours = None
    if today_in:
        try:
            in_dt = datetime.strptime(today_in, "%H:%M")
            out_dt = datetime.strptime(current_time, "%H:%M")
            duration = (out_dt - in_dt).total_seconds() / 3600
            today_hours = round(max(0, duration), 2)
        except Exception as e:
            print("Chyba výpočtu hodin:", e)
            today_hours = "—"

    # Výpočet týdenních hodin
    monday = datetime.today() - timedelta(days=datetime.today().weekday())
    monday_str = monday.strftime("%Y-%m-%d")

    rows = Dochazka.query.filter(
        Dochazka.username == username,
        Dochazka.date >= monday_str
    ).all()

    weekly_hours = 0
    for r in rows:
        if r.in_time and r.out_time:
            try:
                in_dt = datetime.strptime(r.in_time, "%H:%M")
                out_dt = datetime.strptime(r.out_time, "%H:%M")
                weekly_hours += max(0, (out_dt - in_dt).total_seconds() / 3600)
            except:
                continue

    return render_template('dashboard.html',
                           username=username,
                           today_in=today_in,
                           today_out=today_out,
                           weekly_hours=round(weekly_hours, 2),
                           current_time=current_time,
                           today_hours=today_hours)


# Zadat příchod na Dashboardu
@app.route('/zadat_prichod', methods=['POST'])
@login_required
def zadat_prichod():
    username = session['username']

    cz = pytz.timezone('Europe/Prague')
    now = datetime.now(cz)
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M')

    existing_record = Dochazka.query.filter_by(username=username, date=date_str).first()
    out_time = existing_record.out_time if existing_record else None

    if existing_record:
        existing_record.in_time = time_str
        existing_record.out_time = out_time
        existing_record.status = 'Čeká na schválení'
    else:
        new_record = Dochazka(
            username=username,
            date=date_str,
            in_time=time_str,
            out_time=out_time,
            status='Čeká na schválení'
        )
        db.session.add(new_record)

    db.session.commit()
    return redirect(url_for('home'))


# Zadat odchod na Dashboardu
@app.route('/zadat_odchod', methods=['POST'])
@login_required
def zadat_odchod():
    username = session.get('username')
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_time = request.form.get('real_out_time')

    place = request.form.get('place')
    custom_place = request.form.get('custom_place')
    note = request.form.get('note')

    # použij vlastní místo, pokud je vyplněné
    if place == 'vlastni' and custom_place:
        place = custom_place

    record = Dochazka.query.filter_by(username=username, date=date_str).first()
    if record:
        record.out_time = out_time
        record.status = 'Čeká na schválení'
        record.place = place
        record.note = note
        db.session.commit()

    return redirect(url_for('home'))



@app.route('/admin/dochazka')
def admin_dochazka():
    if 'username' not in session or not session.get('is_admin'):
        return redirect(url_for('login'))
    return render_template('admin_dochazka.html', username=session['username'])


# Můj profil
@app.route('/muj_profil')
@login_required
def muj_profil():
    username = session['username']
    user = User.query.filter_by(username=username).first()
    records = Dochazka.query.filter_by(username=username).all()

    total_hours = pending_hours = unpaid_hours = last_30_days_hours = last_30_days_days = 0
    today = datetime.today()
    threshold = today - timedelta(days=30)

    for r in records:
        if r.in_time and r.out_time:
            try:
                in_dt = datetime.strptime(r.in_time, "%H:%M")
                out_dt = datetime.strptime(r.out_time, "%H:%M")
                duration = max(0, (out_dt - in_dt).total_seconds() / 3600)

                total_hours += duration
                if r.status == 'Čeká na schválení':
                    pending_hours += duration
                elif r.status == 'Schváleno – čeká na zaplacení':
                    unpaid_hours += duration

                date_obj = datetime.strptime(r.date, "%Y-%m-%d")
                if date_obj >= threshold:
                    last_30_days_hours += duration
                    last_30_days_days += 1
            except:
                continue

    avg_daily_hours = round(last_30_days_hours / last_30_days_days, 2) if last_30_days_days else 0

    monthly_summary = defaultdict(lambda: {'hours': 0.0, 'days': 0})
    for r in records:
        if r.in_time and r.out_time:
            try:
                in_dt = datetime.strptime(r.in_time, "%H:%M")
                out_dt = datetime.strptime(r.out_time, "%H:%M")
                duration = max(0, (out_dt - in_dt).total_seconds() / 3600)

                date_obj = datetime.strptime(r.date, "%Y-%m-%d")
                month_key = date_obj.strftime("%Y-%m")

                monthly_summary[month_key]['hours'] += duration
                monthly_summary[month_key]['days'] += 1
            except:
                continue

    try:
        locale.setlocale(locale.LC_TIME, 'cs_CZ.UTF-8')
    except locale.Error:
        locale.setlocale(locale.LC_TIME, '')

    monthly_summary_list = []
    cz_months = [
        "leden", "únor", "březen", "duben", "květen", "červen", "červenec",
        "srpen", "září", "říjen", "listopad", "prosinec"
    ]
    for month_key in sorted(monthly_summary.keys(), reverse=True):
        summary = monthly_summary[month_key]
        year, month = map(int, month_key.split('-'))
        month_name = f"{cz_months[month - 1]} {year}"
        avg = round(summary['hours'] / summary['days'], 2) if summary['days'] else 0
        monthly_summary_list.append({
            'month': month_name,
            'hours': round(summary['hours'], 2),
            'days': summary['days'],
            'avg': avg
        })

    return render_template('muj_profil.html',
                           user=user,
                           total_hours=round(total_hours, 2),
                           pending_hours=round(pending_hours, 2),
                           unpaid_hours=round(unpaid_hours, 2),
                           last_30_days_hours=round(last_30_days_hours, 2),
                           last_30_days_days=last_30_days_days,
                           avg_daily_hours=avg_daily_hours,
                           monthly_summary_list=monthly_summary_list)


# Aktualizace dat v muj_profilu
@app.route('/update_profile_data', methods=['POST'])
@login_required
def update_profile_data():
    data = request.get_json()
    bank_account = data.get('bank_account', '').strip()
    ico = data.get('ico', '').strip()

    user = User.query.filter_by(username=session['username']).first()
    if not user:
        return jsonify({'success': False, 'error': 'Uživatel nenalezen'}), 404

    user.bank_account = bank_account or None
    user.ico = ico or None
    db.session.commit()

    return jsonify({'success': True})



#Konec Muj profil
#_____________________________________________________________________________________________


# Odhlášení
@app.route('/logout')
def logout():
    session.clear()
    flash('Byl jste úspěšně odhlášen.', 'info')
    return redirect(url_for('login'))


# Admin dashboard cesta
@app.route('/admin_dashboard')
@login_required
def admin_dashboard():
    if not session.get('is_admin'):
        flash('Přístup pouze pro administrátory.', 'danger')
        return redirect(url_for('login'))

    username = session.get('username') or 'Admin'
    return render_template('admin_dashboard.html', username=username)


# Admin - správa uživatelů a vytvoření nového
@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
def admin_users():
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    error = None

    if request.method == 'POST' and 'username' in request.form:
        username = request.form['username']
        password = request.form['password']
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        note = request.form.get('note') or ''
        is_admin = True if request.form.get('is_admin') == 'on' else False
        position = request.form.get('position') or 'Stálý kopáč'
        hourly_rate = request.form.get('hourly_rate') or None

        # Kontrola duplicity
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            error = f"Uživatel '{username}' už existuje."
        else:
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            new_user = User(
                username=username,
                password=hashed_password.decode('utf-8'),
                first_name=first_name,
                last_name=last_name,
                note=note,
                job_location=position,
                is_admin=is_admin,
                hourly_rate=hourly_rate
            )
            db.session.add(new_user)
            db.session.commit()
            return redirect(url_for('admin_users'))

    users = User.query.all()
    return render_template('admin_users.html', users=users, error=error)


# Admin – smazání uživatele
@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    user_to_delete = User.query.get(user_id)
    if user_to_delete:
        db.session.delete(user_to_delete)
        db.session.commit()

    return redirect(url_for('admin_users'))


# Admin - upravit uživatele
@app.route('/admin/users/edit/<int:user_id>', methods=['POST'])
def edit_user(user_id):
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    user = User.query.get(user_id)
    if not user:
        return redirect(url_for('admin_users'))

    username = request.form['username']
    password = request.form.get('password')
    first_name = request.form.get('first_name')
    last_name = request.form.get('last_name')
    note = request.form.get('note') or ''
    job_location = request.form.get('job_location') or 'Stálý kopáč'
    is_admin = True if request.form.get('is_admin') == 'on' else False
    hourly_rate = request.form.get('hourly_rate') or None

    user.username = username
    user.first_name = first_name
    user.last_name = last_name
    user.note = note
    user.job_location = job_location
    user.is_admin = is_admin
    user.hourly_rate = hourly_rate

    if password:
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        user.password = hashed_password.decode('utf-8')

    db.session.commit()
    return redirect(url_for('admin_users'))


# Konec admin_users
#__________________________________________________________________________________________
#Začátek admin docházky

# API pro admin docházku
@app.route('/api/admin_dochazka')
def api_admin_dochazka():
    if not session.get('is_admin'):
        return jsonify({'error': 'Přístup zamítnut'}), 403

    records = db.session.query(
        Dochazka.username,
        Dochazka.date,
        Dochazka.in_time,
        Dochazka.out_time,
        Dochazka.status,
        Dochazka.place,
        Dochazka.note,
        User.first_name,
        User.last_name
    ).join(User, Dochazka.username == User.username, isouter=True).all()

    data = []
    for r in records:
        try:
            h1, m1 = map(int, r.in_time.split(':'))
            h2, m2 = map(int, r.out_time.split(':'))
            minutes = (h2 * 60 + m2) - (h1 * 60 + m1)
            if minutes < 0:
                minutes += 1440
            hours = round(minutes / 60, 2)
        except Exception:
            hours = 0

        data.append({
            'username': r.username,
            'date': r.date,
            'in_time': r.in_time,
            'out_time': r.out_time,
            'status': r.status,
            'place': r.place or '',
            'note': r.note or '',
            'first_name': r.first_name or '',
            'last_name': r.last_name or '',
            'hours': hours
        })

    return jsonify(data)

# Admin - úprava dochazky (kromě stavu)
@app.route('/api/update_time', methods=['POST'])
def update_time():
    data = request.get_json()
    username = data['username']
    date = data['date']
    in_time = data['in_time']
    out_time = data['out_time']
    place = data['place']
    note = data['note']
    record = Dochazka.query.filter_by(username=username, date=date).first()
    if record:
        record.in_time = in_time
        record.out_time = out_time
        record.place = place
        record.note = note
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Záznam nenalezen'}), 404


# Admin - změna stavu
@app.route('/api/zmenit_stav', methods=['POST'])
def zmenit_stav():
    data = request.get_json()
    username = data['username']
    date = data['date']
    status = data['status']
    record = Dochazka.query.filter_by(username=username, date=date).first()
    if record:
        record.status = status
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Záznam nenalezen'}), 404


# Admin - smazání záznamu
@app.route('/api/smazat_zaznam', methods=['POST'])
def smazat_zaznam():
    data = request.get_json()
    username = data['username']
    date = data['date']
    record = Dochazka.query.filter_by(username=username, date=date).first()
    if record:
        db.session.delete(record)
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Záznam nenalezen'}), 404

# Admin – schválení docházky
@app.route('/api/schvalit', methods=['POST'])
def schvalit_dochazku():
    data = request.get_json()
    date = data.get('date')
    username = data.get('username')

    if not date or not username:
        return jsonify({'error': 'Neplatné vstupní údaje'}), 400

    dochazka = Dochazka.query.filter_by(date=date, username=username).first()

    if not dochazka:
        return jsonify({'error': 'Záznam nenalezen'}), 404

    if dochazka.status == 'Proplaceno':
        return jsonify({'error': 'Záznam již byl proplacen'}), 400

    dochazka.status = 'Schváleno'
    db.session.commit()

    return jsonify({'message': 'Záznam úspěšně schválen'}), 200


# Admin - schválení všech záznamů v daný den
@app.route('/api/schvalit_den', methods=['POST'])
def schvalit_den():
    data = request.get_json()
    date_str = data['date']
    dochazky = Dochazka.query.filter_by(date=date_str).all()
    for d in dochazky:
        if d.status != 'Proplaceno':
            d.status = 'Schváleno'
    db.session.commit()
    return jsonify({'success': True})

# Admin - seznam zaměstnanců API
@app.route('/api/seznam_zamestnancu')
def seznam_zamestnancu():
    try:
        users = db.session.query(User).all()
        print("DEBUG: Found", len(users), "users")
        return jsonify([
            {
                'username': u.username,
                'first_name': u.first_name,
                'last_name': u.last_name
            } for u in users
        ])
    except Exception as e:
        print("ERROR v seznam_zamestnancu:", e)
        return jsonify({'error': str(e)}), 500


# Admin - přidání docházky pro zaměstnance
@app.route('/api/pridat_dochazku_admin', methods=['POST'])
def pridat_dochazku_admin():
    data = request.get_json()
    username = data.get('username')
    date = data.get('date')
    in_time = data.get('in_time')
    out_time = data.get('out_time')
    place = data.get('place')
    note = data.get('note')

    if not all([username, date, in_time, out_time]):
        return "Chybí povinná pole", 400

    nova_dochazka = Dochazka(
        username=username,
        date=date,
        in_time=in_time,
        out_time=out_time,
        place=place,
        note=note,
        status='Čeká na schválení'
    )

    db.session.add(nova_dochazka)
    db.session.commit()
    return jsonify({"success": True})



# Konec admin docházky
#__________________________________________________________________________________________


# Admin - zaměstnanci cesta
@app.route('/admin/zamestnanci')
def admin_zamestnanci():
    return render_template('admin_zamestnanci.html')


# Admin - zaměstnanci API
@app.route('/api/admin_zamestnanci')
def get_zamestnanci():
    if not session.get('is_admin'):
        return jsonify({'error': 'Nepovolený přístup'}), 403

    users = User.query.filter_by(is_admin=False).all()
    today = datetime.today()
    threshold = today - timedelta(days=30)

    vystup = []

    for user in users:
        attendance = Dochazka.query.filter_by(username=user.username).all()

        pending = unpaid = total = last_30_days_hours = 0.0
        days_set = set()

        for record in attendance:
            try:
                if record.in_time and record.out_time:
                    in_dt = datetime.strptime(record.in_time, "%H:%M")
                    out_dt = datetime.strptime(record.out_time, "%H:%M")
                    hours = (out_dt - in_dt).total_seconds() / 3600
                else:
                    hours = 0
            except:
                hours = 0

            total += hours
            if record.status == "Čeká na schválení":
                pending += hours
            elif record.status.startswith("Schváleno"):
                unpaid += hours

            try:
                date_obj = datetime.strptime(record.date, "%Y-%m-%d")
                if date_obj >= threshold:
                    last_30_days_hours += hours
                    days_set.add(date_obj.date())
            except:
                pass

        last_payment_raw = (
            db.session.query(db.func.max(Vyplata.date))
            .filter_by(username=user.username)
            .scalar()
        )

        # Bezpečný převod na string
        if isinstance(last_payment_raw, datetime):
            last_payment = last_payment_raw.strftime("%Y-%m-%d")
        else:
            try:
                last_payment = datetime.strptime(str(last_payment_raw), "%Y-%m-%d").strftime("%Y-%m-%d")
            except:
                last_payment = ""


        job_location = (user.job_location or "").strip()
        if job_location not in ["Brigádník", "Stálý kopáč"]:
            continue

        vystup.append({
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "typ_zavazku": job_location,
            "stav": (user.note or "").strip(),
            "last_payment": last_payment,
            "stats": {
                "total_hours": round(total, 2),
                "pending_hours": round(pending, 2),
                "unpaid_hours": round(unpaid, 2),
                "last_30_days_hours": round(last_30_days_hours, 2),
                "last_30_days_days": len(days_set),
                "avg_daily_hours": round(last_30_days_hours / len(days_set), 2) if days_set else 0
            }
        })

    return jsonify(vystup)

# Spočítání hodin (používáme pak níž)
def calculate_hours(in_time, out_time):
    if not in_time or not out_time:
        return 0
    try:
        in_dt = datetime.strptime(in_time, "%H:%M")
        out_dt = datetime.strptime(out_time, "%H:%M")
        delta = (out_dt - in_dt).seconds / 3600
        return round(delta, 2)
    except:
        return 0


# Detail zaměstnance
@app.route('/api/admin_zamestnanec/<username>')
def admin_zamestnanec_detail(username):
    if not session.get('is_admin'):
        return jsonify({'error': 'Nepovolený přístup'}), 403

    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({'error': 'Uživatel nenalezen'}), 404

    attendance = Dochazka.query.filter_by(username=username).all()
    today = datetime.today()
    threshold = today - timedelta(days=30)

    total = pending = unpaid = last_30_days_hours = 0.0
    days_set = set()

    for record in attendance:
        try:
            if record.in_time and record.out_time:
                in_dt = datetime.strptime(record.in_time, "%H:%M")
                out_dt = datetime.strptime(record.out_time, "%H:%M")
                hours = (out_dt - in_dt).total_seconds() / 3600
            else:
                hours = 0
        except:
            hours = 0

        total += hours

        if record.status == "Čeká na schválení":
            pending += hours
        elif record.status.startswith("Schváleno"):
            unpaid += hours

        try:
            date_obj = datetime.strptime(record.date, "%Y-%m-%d")
            if date_obj >= threshold:
                last_30_days_hours += hours
                days_set.add(date_obj.date())
        except:
            pass

    return jsonify({
        "first_name": user.first_name or '',
        "last_name": user.last_name or '',
        "ico": user.ico or '',
        "bank_account": user.bank_account or '',
        "hourly_rate": user.hourly_rate or '',
        "attendance": [
            {
                "date": r.date,
                "in_time": r.in_time,
                "out_time": r.out_time,
                "status": r.status,
                "note": r.note or '',
                "place": r.place or '',
                "hours": calculate_hours(r.in_time, r.out_time)
            }
            for r in attendance
            if r.in_time and r.out_time
        ],
        "stats": {
            "total_hours": round(total, 2),
            "pending_hours": round(pending, 2),
            "unpaid_hours": round(unpaid, 2),
            "last_30_days_hours": round(last_30_days_hours, 2),
            "last_30_days_days": len(days_set),
            "avg_daily_hours": round(last_30_days_hours / len(days_set), 2) if days_set else 0
        }
    })



@app.route('/api/generate_qr', methods=['POST'])
def generate_qr():
    data = request.get_json()
    amount = data.get('amount')
    account_number = data.get('account')

    iban_account = convert_to_cz_iban(account_number)
    if not iban_account:
        return jsonify({'error': 'Chybný formát účtu'}), 400

    qr_text = f"SPD*1.0*ACC:{iban_account}*AM:{amount}*CC:CZK"

    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(qr_text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()

    return jsonify({'qr_base64': img_str})



def convert_to_cz_iban(account_number):

    # Podpora i formátu s předčíslím: "115-1234567890/0100"
    match = re.match(r'^(?:(\d+)-)?(\d{1,10})\/(\d{4})$', account_number)
    if not match:
        return None

    predcisli, cislo, kod_banky = match.groups()

    # Sestavení čísla účtu podle pravidel ČNB
    predcisli = predcisli or '0'
    predcisli = predcisli.zfill(6)
    cislo = cislo.zfill(10)

    bban = f"{kod_banky}{predcisli}{cislo}"
    tmp = bban + "123500"  # CZ = 12, Z = 35, 00
    mod = int(tmp) % 97
    checksum = 98 - mod
    return f"CZ{checksum:02d}{bban}"




# Konec admin zaměstnanců
#___________________________________________________________________________________________
# Docházka – vše co se týká dochazka.html

# Otevření Docházka.html
@app.route('/dochazka')
def dochazka():
    if 'username' not in session:
        return redirect(url_for('login'))
    if session.get('is_admin'):
        return render_template('admin_dochazka.html',
                               username=session['username'])
    return render_template('dochazka.html', username=session['username'])

# Docházka – zobrazení všech záznamů přihlášeného uživatele
@app.route('/api/dochazka')
def get_dochazka():
    username = session.get('username')
    if not username:
        return jsonify([])

    zaznamy = Dochazka.query.filter_by(username=username).all()
    data = []
    for z in zaznamy:
        # Vynecháme záznamy bez in_time nebo out_time
        if not z.date or not z.in_time or not z.out_time:
            continue

        data.append({
            'id': z.id,
            'title': z.place or '',
            'start': f"{z.date}T{z.in_time}",
            'end': f"{z.date}T{z.out_time}",
            'date': z.date,
            'in_time': z.in_time,
            'out_time': z.out_time,
            'status': z.status,
            'place': z.place,
            'note': z.note
        })
    return jsonify(data)

# ✅ Vytvoření nové docházky
@app.route('/api/dochazka', methods=['POST'])
def create_dochazka():
    data = request.get_json()
    username = session.get('username')
    if not username:
        return jsonify({'error': 'Nepřihlášený uživatel'}), 401

    new_record = Dochazka(
        username=username,
        date=data['date'],
        in_time=data.get('in_time'),
        out_time=data.get('out_time'),
        place=data.get('place'),
        note=data.get('note'),
        status='Čeká na schválení'
    )
    db.session.add(new_record)
    db.session.commit()
    return jsonify({'message': 'Docházka vytvořena'}), 201


# ✅ Úprava existující docházky
@app.route('/api/dochazka', methods=['PATCH'])
def update_dochazka():
    data = request.get_json()
    username = session.get('username')
    if not username:
        return jsonify({'error': 'Nepřihlášený uživatel'}), 401

    record = Dochazka.query.filter_by(id=data['id'], username=username).first_or_404()

    if record.status != 'Čeká na schválení':
        return jsonify({'error': 'Docházku nelze upravit, protože již byla schválena nebo proplacena.'}), 403

    record.in_time = data.get('in_time') or record.in_time
    record.out_time = data.get('out_time') or record.out_time
    record.place = data.get('place') or record.place
    record.note = data.get('note') or record.note
    db.session.commit()
    return jsonify({'message': 'Docházka upravena'})


# ✅ Smazání docházky podle ID
@app.route('/api/dochazka', methods=['DELETE'])
def delete_dochazka():
    data = request.get_json()
    username = session.get('username')
    if not username:
        return jsonify({'error': 'Nepřihlášený uživatel'}), 401

    record = Dochazka.query.filter_by(id=data['id'], username=username).first_or_404()
    db.session.delete(record)
    db.session.commit()
    return jsonify({'message': 'Docházka smazána'})

# Konec všeho co se týká dochazka.html
#______________________________________________________________________________________________
# Výplaty – vše co se týká admin_vyplaty.html



# Otevření admin výplat -> html souboru
@app.route('/admin_vyplaty')
def admin_vyplaty():
    return render_template('admin_vyplaty.html')


# Zobrazení výplat
@app.route('/api/admin_vyplaty')
def admin_vyplaty_json():
    if not session.get('is_admin'):
        return jsonify({'error': 'Nepovolený přístup'}), 403

    vyplaty = (
        db.session.query(
            Vyplata.id,
            Vyplata.username,
            Vyplata.month,
            Vyplata.total_hours,
            Vyplata.amount,
            Vyplata.date,
            User.first_name,
            User.last_name
        )
        .join(User, Vyplata.username == User.username)
        .order_by(Vyplata.date.desc())
        .all()
    )

    result = []
    for v in vyplaty:
        result.append({
            'id': v.id,
            'username': v.username,
            'month': v.month,
            'hours': v.total_hours,
            'amount': v.amount,
            'date': v.date,
            'first_name': v.first_name,
            'last_name': v.last_name
        })

    return jsonify(result)



# Úprava výplaty
@app.route('/api/update_vyplata', methods=['POST'])
def update_vyplata():
    if not session.get('is_admin'):
        return jsonify({'error': 'Nepovolený přístup'}), 403

    data = request.get_json()
    vyplata_id = data.get('vyplata_id')
    new_amount = data.get('amount')
    new_hours = data.get('hours')

    if not vyplata_id or new_amount is None or new_hours is None:
        return jsonify({'error': 'Neplatné vstupy'}), 400

    vyplata = Vyplata.query.get(vyplata_id)
    if not vyplata:
        return jsonify({'error': 'Výplata nenalezena'}), 404

    vyplata.amount = new_amount
    vyplata.total_hours = new_hours
    db.session.commit()

    return jsonify({'success': True})



# Zobrazit detail výplaty
@app.route('/api/admin_vyplata_detail/<int:vyplata_id>')
def get_payment_detail(vyplata_id):
    try:
        zaznamy = (
            db.session.query(Dochazka)
            .join(VyplataDochazky, VyplataDochazky.dochazka_id == Dochazka.id)
            .filter(VyplataDochazky.vyplata_id == vyplata_id)
            .order_by(Dochazka.date)
            .all()
        )

        result = []
        for r in zaznamy:
            try:
                hours = calculate_hours(r.in_time, r.out_time)
            except Exception:
                hours = 0
            result.append({
                'date': r.date,
                'in_time': r.in_time,
                'out_time': r.out_time,
                'hours': hours
            })

        return jsonify(result)
    except Exception as e:
        return jsonify({'error': 'Dočasně nedostupné', 'detail': str(e)}), 503


# Zaplacení docházky
@app.route('/api/admin_zamestnanec_zaplaceno/<username>', methods=['POST'])
def zaplatit_dochazku(username):
    if not session.get('is_admin'):
        return jsonify({'error': 'Nepovolený přístup'}), 403

    data = request.get_json()
    checked_ids = data.get('checkedIds', [])
    hourly_rate = float(data.get('hourlyRate', 0))

    if not checked_ids or not hourly_rate:
        return jsonify({'error': 'Chybné vstupy'}), 400

    total_hours = 0
    dochazky = []

    for date_str in checked_ids:
        record = Dochazka.query.filter_by(
            username=username,
            date=date_str
        ).filter(Dochazka.status.ilike('schváleno%')).first()

        if not record or not record.in_time or not record.out_time:
            continue

        hours = calculate_hours(record.in_time, record.out_time)
        total_hours += hours
        dochazky.append((record, hours))

    if total_hours == 0 or not dochazky:
        return jsonify({'error': 'Žádné schválené záznamy'}), 400

    now = datetime.now()
    month = now.strftime("%Y-%m")
    today_str = now.strftime("%Y-%m-%d")
    amount = round(total_hours * hourly_rate, 2)

    nova_vyplata = Vyplata(
        username=username,
        month=month,
        total_hours=total_hours,
        amount=amount,
        date=today_str
    )
    db.session.add(nova_vyplata)
    db.session.flush()  # získáme vyplata.id ještě před commitem

    for dochazka, _ in dochazky:
        vazba = VyplataDochazky(
            vyplata_id=nova_vyplata.id,
            dochazka_id=dochazka.id
        )
        db.session.add(vazba)
        dochazka.status = 'Proplaceno'

    db.session.commit()

    return jsonify({'success': True, 'vyplata_id': nova_vyplata.id})


# Funkce na smazání výplaty
@app.route('/api/delete_vyplata', methods=['POST'])
def delete_vyplata():
    if not session.get('is_admin'):
        return jsonify({'error': 'Nepovolený přístup'}), 403

    data = request.get_json()
    vyplata_id = data.get('vyplata_id')
    option = data.get('option')  # '1', '2', nebo '3'

    if not vyplata_id or option not in ['1', '2', '3']:
        return jsonify({'error': 'Neplatný vstup'}), 400

    vyplata = Vyplata.query.get(vyplata_id)
    if not vyplata:
        return jsonify({'error': 'Výplata nenalezena'}), 404

    vazby = VyplataDochazky.query.filter_by(vyplata_id=vyplata_id).all()
    dochazka_ids = [v.dochazka_id for v in vazby]

    # Smazání vazeb
    for v in vazby:
        db.session.delete(v)

    # Úprava nebo smazání docházek podle volby
    if option == '1':
        Dochazka.query.filter(Dochazka.id.in_(dochazka_ids)).update(
            {Dochazka.status: 'Schváleno'}, synchronize_session=False)
    elif option == '2':
        Dochazka.query.filter(Dochazka.id.in_(dochazka_ids)).delete(synchronize_session=False)

    # Smazání samotné výplaty
    db.session.delete(vyplata)
    db.session.commit()

    return jsonify({'success': True})


if __name__ == '__main__':
    app.run(debug=True)

