from flask import Flask, render_template, redirect, url_for, request, session, jsonify, g, flash
from werkzeug.security import check_password_hash
from datetime import datetime, timedelta
from functools import wraps
from collections import defaultdict
from flask_migrate import Migrate


from flask_sqlalchemy import SQLAlchemy
from models import db, User, Dochazka, Vyplata, VyplataDochazky
from dotenv import load_dotenv

import os
import pytz
import locale
import calendar
import urllib.parse
import bcrypt


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
def muj_profil():
    if 'username' not in session:
        return redirect(url_for('login'))

    db = get_db()
    username = session['username']

    user = db.execute('SELECT * FROM users WHERE username = ?',
                      (username, )).fetchone()
    records = db.execute('SELECT * FROM dochazka WHERE username = ?',
                         (username, )).fetchall()

    total_hours = pending_hours = unpaid_hours = last_30_days_hours = last_30_days_days = 0

    today = datetime.today()
    threshold = today - timedelta(days=30)

    for r in records:
        if r['in_time'] and r['out_time']:
            try:
                in_dt = datetime.strptime(r['in_time'], "%H:%M")
                out_dt = datetime.strptime(r['out_time'], "%H:%M")
                duration = max(0, (out_dt - in_dt).total_seconds() / 3600)

                total_hours += duration
                if r['status'] == 'Čeká na schválení':
                    pending_hours += duration
                elif r['status'] == 'Schváleno – čeká na zaplacení':
                    unpaid_hours += duration

                date_obj = datetime.strptime(r['date'], "%Y-%m-%d")
                if date_obj >= threshold:
                    last_30_days_hours += duration
                    last_30_days_days += 1
            except Exception:
                continue

    avg_daily_hours = round(last_30_days_hours /
                            last_30_days_days, 2) if last_30_days_days else 0

    # Souhrn po měsících
    monthly_summary = defaultdict(lambda: {'hours': 0.0, 'days': 0})

    for r in records:
        if r['in_time'] and r['out_time']:
            try:
                in_dt = datetime.strptime(r['in_time'], "%H:%M")
                out_dt = datetime.strptime(r['out_time'], "%H:%M")
                duration = max(0, (out_dt - in_dt).total_seconds() / 3600)

                date_obj = datetime.strptime(r['date'], "%Y-%m-%d")
                month_key = date_obj.strftime("%Y-%m")

                monthly_summary[month_key]['hours'] += duration
                monthly_summary[month_key]['days'] += 1
            except Exception:
                continue

    # Převod do seznamu a výpočet průměru
    try:
        locale.setlocale(locale.LC_TIME, 'cs_CZ.UTF-8')
    except locale.Error:
        locale.setlocale(locale.LC_TIME, '')

    monthly_summary_list = []
    cz_months = [
        "leden", "únor", "březen", "duben", "květen", "červen", "červenec",
        "srpen", "září", "říjen", "listopad", "prosinec"
    ]
    # Seřazení a převod na seznam
    for month_key in sorted(monthly_summary.keys(), reverse=True):
        summary = monthly_summary[month_key]
        year, month = map(int, month_key.split('-'))
        month_name = f"{cz_months[month - 1]} {year}"
        # Výpočet průměrných denních hodin
        avg = round(summary['hours'] /
                    summary['days'], 2) if summary['days'] else 0
        monthly_summary_list.append({
            'month': month_name,
            'hours': round(summary['hours'], 2),
            'days': summary['days'],
            'avg': avg
        })

    # Omezení na 12 měsíců
    return render_template('muj_profil.html',
                           user=user,
                           total_hours=round(total_hours, 2),
                           pending_hours=round(pending_hours, 2),
                           unpaid_hours=round(unpaid_hours, 2),
                           last_30_days_hours=round(last_30_days_hours, 2),
                           last_30_days_days=last_30_days_days,
                           avg_daily_hours=avg_daily_hours,
                           monthly_summary_list=monthly_summary_list)


@app.route('/update_profile_data', methods=['POST'])
def update_profile_data():
    if 'username' not in session:
        return jsonify({'success': False, 'error': 'Nejste přihlášen'}), 403

    data = request.get_json()
    bank_account = data.get('bank_account', '').strip()
    ico = data.get('ico', '').strip()

    db = get_db()
    db.execute(
        '''
        UPDATE users
        SET bank_account = ?, ico = ?
        WHERE username = ?
    ''', (bank_account or None, ico or None, session['username']))
    db.commit()

    return jsonify({'success': True})


#Konec Muj profil


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

# Admin - změna času
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

# Konec admin docházky
#__________________________________________________________________________________________


# Admin - zaměstnanci cesta
@app.route('/admin/zamestnanci')
def admin_zamestnanci():
    return render_template('admin_zamestnanci.html')


# Admin - zaměstnanci API
@app.route('/api/admin_zamestnanci')
def get_zamestnanci():
    try:
        import datetime
        import sqlite3
        conn = sqlite3.connect('dochazka.db')
        c = conn.cursor()

        c.execute("""
            SELECT username, first_name, last_name, job_location, note
            FROM users
            WHERE is_admin = 0
        """)
        rows = c.fetchall()

        vystup = []
        for r in rows:
            username = r[0]
            first_name = r[1]
            last_name = r[2]
            job_location = r[3] or ""
            note = r[4] or ""

            if job_location.strip() == "Brigádník":
                typ_zavazku = "Brigádník"
            elif job_location.strip() == "Stálý kopáč":
                typ_zavazku = "Stálý kopáč"
            else:
                continue

            # Poslední platba
            c.execute(
                """
                SELECT MAX(date)
                FROM dochazka
                WHERE username = ? AND status = 'Proplaceno'
            """, (username, ))
            last_payment_row = c.fetchone()
            last_payment = last_payment_row[
                0] if last_payment_row and last_payment_row[0] else None

            # Výpočet statistik
            c.execute(
                "SELECT in_time, out_time, date, status FROM dochazka WHERE username = ?",
                (username, ))
            records = c.fetchall()

            pending = 0.0
            unpaid = 0.0
            total = 0.0
            last_30_days_hours = 0.0
            days_set = set()

            today = datetime.datetime.today()
            threshold = today - datetime.timedelta(days=30)

            for rec in records:
                in_time = rec[0] or ""
                out_time = rec[1] or ""
                date_str = rec[2]
                status = rec[3]

                try:
                    fmt = "%H:%M"
                    in_dt = datetime.datetime.strptime(in_time, fmt)
                    out_dt = datetime.datetime.strptime(out_time, fmt)
                    hours = (out_dt - in_dt).seconds / 3600
                except:
                    hours = 0

                total += hours

                if status == "Čeká na schválení":
                    pending += hours
                elif status.startswith("Schváleno"):
                    unpaid += hours

                try:
                    date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                    if date_obj >= threshold:
                        last_30_days_hours += hours
                        days_set.add(date_obj.date())
                except:
                    pass

            last_30_days_days = len(days_set)
            avg_daily_hours = round(last_30_days_hours / last_30_days_days,
                                    2) if last_30_days_days else 0

            vystup.append({
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "typ_zavazku": typ_zavazku,
                "stav": note.strip(),
                "last_payment": last_payment,
                "stats": {
                    "total_hours": round(total, 2),
                    "pending_hours": round(pending, 2),
                    "unpaid_hours": round(unpaid, 2),
                    "last_30_days_hours": round(last_30_days_hours, 2),
                    "last_30_days_days": last_30_days_days,
                    "avg_daily_hours": avg_daily_hours
                }
            })

        conn.close()
        return jsonify(vystup)
    except Exception as e:
        return jsonify({'error': 'Dočasně nedostupné', 'detail': str(e)}), 503


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
    try:
        import datetime
        import sqlite3
        conn = sqlite3.connect('dochazka.db')
        c = conn.cursor()

        # ... (zbytek původního těla funkce beze změn)

        conn.close()
        return jsonify({
            "first_name": first_name,
            "last_name": last_name,
            "ico": ico,
            "bank_account": bank_account,
            "hourly_rate": hourly_rate,
            "attendance": attendance,
            "stats": {
                "total_hours": round(total, 2),
                "pending_hours": round(pending, 2),
                "unpaid_hours": round(unpaid, 2),
                "last_30_days_hours": round(last_30_days_hours, 2),
                "last_30_days_days": last_30_days_days,
                "avg_daily_hours": avg_daily_hours
            }
        })
    except Exception as e:
        return jsonify({'error': 'Dočasně nedostupné', 'detail': str(e)}), 503

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
    try:
        import sqlite3
        conn = sqlite3.connect('dochazka.db')
        c = conn.cursor()
        c.execute("""
            SELECT v.id, v.username, v.month, v.total_hours, v.amount, v.date,
                u.first_name, u.last_name
            FROM vyplaty v
            JOIN users u ON v.username = u.username
            ORDER BY v.date DESC
        """)
        rows = c.fetchall()
        conn.close()

        vyplaty = []
        for row in rows:
            vyplaty.append({
                'id': row[0],
                'username': row[1],
                'month': row[2],
                'hours': row[3],
                'amount': row[4],
                'date': row[5],
                'first_name': row[6],
                'last_name': row[7]
            })

        return jsonify(vyplaty)
    except Exception as e:
        return jsonify({'error': 'Dočasně nedostupné', 'detail': str(e)}), 503


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

    db = get_db()
    db.execute(
        '''
        UPDATE vyplaty
        SET amount = ?, total_hours = ?
        WHERE id = ?
    ''', (new_amount, new_hours, vyplata_id))
    db.commit()

    return jsonify({'success': True})


# Zobrazit detail výplaty
@app.route('/api/admin_vyplata_detail/<int:vyplata_id>')
def get_payment_detail(vyplata_id):
    try:
        db = get_db()
        rows = db.execute(
            """
            SELECT d.date, d.in_time, d.out_time
            FROM dochazka d
            JOIN vyplaty_dochazky vd ON vd.dochazka_id = d.id
            WHERE vd.vyplata_id = ?
            ORDER BY d.date
        """, (vyplata_id, )).fetchall()

        result = []
        for r in rows:
            try:
                hours = calculate_hours(r['in_time'], r['out_time'])
            except Exception:
                hours = 0  # fallback při chybě
            result.append({
                'date': r['date'],
                'in_time': r['in_time'],
                'out_time': r['out_time'],
                'hours': hours
            })

        return jsonify(result)
    except Exception as e:
        return jsonify({'error': 'Dočasně nedostupné', 'detail': str(e)}), 503


# Zaplacení docházky
@app.route('/api/admin_zamestnanec_zaplaceno/<username>', methods=['POST'])
def zaplatit_dochazku(username):
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Nepovolený přístup'}), 403

        data = request.get_json()
        checked_ids = data.get('checkedIds', [])
        hourly_rate = float(data.get('hourlyRate', 0))

        if not checked_ids or not hourly_rate:
            return jsonify({'error': 'Chybné vstupy'}), 400

        db = get_db()

        total_hours = 0
        dochazka_ids = []

        # Zjisti ID a hodiny pro každé datum
        for date_str in checked_ids:
            row = db.execute(
                '''
                SELECT id, in_time, out_time
                FROM dochazka
                WHERE username = ? AND date = ? AND LOWER(status) LIKE 'schváleno%'
            ''', (username, date_str)).fetchone()

            if not row:
                continue

            hours = calculate_hours(row['in_time'], row['out_time'])
            total_hours += hours
            dochazka_ids.append((row['id'], hours))

        if total_hours == 0 or not dochazka_ids:
            return jsonify({'error': 'Žádné schválené záznamy'}), 400

        # Vytvoř výplatu
        now = datetime.now()
        month = now.strftime("%Y-%m")
        today_str = now.strftime("%Y-%m-%d")
        amount = round(total_hours * hourly_rate, 2)

        db.execute(
            '''
            INSERT INTO vyplaty (username, month, total_hours, amount, date)
            VALUES (?, ?, ?, ?, ?)
        ''', (username, month, total_hours, amount, today_str))
        vyplata_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]

        for dochazka_id, _ in dochazka_ids:
            db.execute(
                '''
                INSERT INTO vyplaty_dochazky (vyplata_id, dochazka_id)
                VALUES (?, ?)
            ''', (vyplata_id, dochazka_id))

            db.execute(
                '''
                UPDATE dochazka
                SET status = 'Proplaceno'
                WHERE id = ?
            ''', (dochazka_id, ))

        db.commit()
        return jsonify({'success': True, 'vyplata_id': vyplata_id})
    except Exception as e:
        return jsonify({'error': 'Dočasně nedostupné', 'detail': str(e)}), 503


# Funkce na smazání výplaty
@app.route('/api/delete_vyplata', methods=['POST'])
def delete_vyplata():
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Nepovolený přístup'}), 403

        data = request.get_json()
        vyplata_id = data.get('vyplata_id')
        option = data.get('option')

        if not vyplata_id or option not in ['1', '2', '3']:
            return jsonify({'error': 'Neplatný vstup'}), 400

        db = get_db()

        dochazky = db.execute(
            'SELECT dochazka_id FROM vyplaty_dochazky WHERE vyplata_id = ?',
            (vyplata_id, )).fetchall()
        dochazka_ids = [r['dochazka_id'] for r in dochazky]

        db.execute('DELETE FROM vyplaty_dochazky WHERE vyplata_id = ?',
                   (vyplata_id, ))
        db.execute('DELETE FROM vyplaty WHERE id = ?', (vyplata_id, ))

        if option == '1':
            db.executemany('UPDATE dochazka SET status = ? WHERE id = ?',
                           [('Schváleno', did) for did in dochazka_ids])
        elif option == '2':
            db.executemany('DELETE FROM dochazka WHERE id = ?',
                           [(did, ) for did in dochazka_ids])

        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': 'Dočasně nedostupné', 'detail': str(e)}), 503


if __name__ == '__main__':
    app.run(debug=True)

