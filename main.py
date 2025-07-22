from flask import Flask, render_template, redirect, url_for, request, session, jsonify, g
from datetime import datetime, timedelta
from functools import wraps
from flask import session, redirect, url_for
from collections import defaultdict
import sqlite3
import os
import pytz
import locale
import calendar


def login_required(f):

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function


app = Flask(__name__)
app.secret_key = 'tajnysuperklic123'

DATABASE = 'dochazka.db'


# Pomocná funkce pro připojení k DB
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


# Hlavní stránka / dashboard
@app.route('/')
def home():
    if 'username' not in session:
        return redirect(url_for('login'))

    db = get_db()
    username = session['username']
    today_str = datetime.today().strftime("%Y-%m-%d")

    record = db.execute(
        'SELECT in_time, out_time FROM dochazka WHERE username = ? AND date = ?',
        (username, today_str)).fetchone()

    today_in = record['in_time'] if record else None
    today_out = record['out_time'] if record else None

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

    rows = db.execute(
        'SELECT in_time, out_time FROM dochazka WHERE username = ? AND date >= ?',
        (username, monday_str)).fetchall()

    weekly_hours = 0
    for r in rows:
        if r['in_time'] and r['out_time']:
            try:
                in_dt = datetime.strptime(r['in_time'], "%H:%M")
                out_dt = datetime.strptime(r['out_time'], "%H:%M")
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


# Otevření Docházka.html
@app.route('/dochazka')
def dochazka():
    if 'username' not in session:
        return redirect(url_for('login'))
    if session.get('is_admin'):
        return render_template('admin_dochazka.html',
                               username=session['username'])
    return render_template('dochazka.html', username=session['username'])


# Zadat příchod na Dashboardu
@app.route('/zadat_prichod', methods=['POST'])
@login_required
def zadat_prichod():
    db = get_db()
    username = session['username']

    cz = pytz.timezone('Europe/Prague')
    now = datetime.now(cz)
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M')

    db.execute(
        '''
        INSERT OR REPLACE INTO dochazka (username, date, in_time, out_time, status)
        VALUES (?, ?, ?, (SELECT out_time FROM dochazka WHERE username = ? AND date = ?), 'Čeká na schválení')
    ''', (username, date_str, time_str, username, date_str))
    db.commit()
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

    db = get_db()
    db.execute(
        '''
        UPDATE dochazka
        SET out_time = ?, status = 'Čeká na schválení', place = ?, note = ?
        WHERE username = ? AND date = ?
        ''', (out_time, place, note, username, date_str))
    db.commit()
    return redirect(url_for('home'))


# Funkce na smazání docházky
@app.route('/api/dochazka', methods=['DELETE'])
@login_required
def delete_dochazka():
    data = request.get_json()
    date = data.get('date')
    username = session['username']

    db = get_db()
    if not date:
        return jsonify({"error": "Missing date"}), 400

    # Zjisti roli
    user = db.execute('SELECT is_admin FROM users WHERE username = ?',
                      (username, )).fetchone()
    is_admin = user and user['is_admin'] == 1

    if is_admin:
        db.execute('DELETE FROM dochazka WHERE date = ?', (date, ))
    else:
        db.execute('DELETE FROM dochazka WHERE username = ? AND date = ?',
                   (username, date))

    db.commit()
    return jsonify({"success": True})


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


# Přihlášení
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        cur = db.execute(
            'SELECT password, is_admin FROM users WHERE username = ?',
            (username, ))
        user = cur.fetchone()
        if user and user['password'] == password:
            session['username'] = username
            session['is_admin'] = bool(user['is_admin'])
            if user['is_admin']:
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('home'))
        error = 'Špatné jméno nebo heslo'
    return render_template('login.html', error=error)


# Odhlášení
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# Admin dashboard cesta
@app.route('/admin_dashboard')
def admin_dashboard():
    if 'username' not in session or not session.get('is_admin'):
        return redirect(url_for('login'))

    return render_template('admin_dashboard.html',
                           username=session['username'])


# Admin - správa uživatelů
@app.route('/admin/users', methods=['GET', 'POST'])
def admin_users():
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    db = get_db()
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        note = request.form.get('note') or ''
        is_admin = 1 if request.form.get('is_admin') == 'on' else 0
        position = request.form.get('position') or 'Stálý kopáč'
        hourly_rate = request.form.get('hourly_rate') or None
        # Kontrola duplicity
        cur = db.execute('SELECT id FROM users WHERE username = ?',
                         (username, ))
        if cur.fetchone():
            error = f"Uživatel '{username}' už existuje."
        else:
            db.execute(
                '''INSERT INTO users
                   (username, password, first_name, last_name, note, job_location,
                    is_admin, hourly_rate)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (username, password, first_name, last_name, note, position,
                 is_admin, hourly_rate))
            db.commit()
            return redirect(url_for('admin_users'))
    # Načtení uživatelů
    rows = db.execute('SELECT * FROM users').fetchall()
    users = [dict(r) for r in rows]
    return render_template('admin_users.html', users=users, error=error)


# Admin - smazat uživatele
@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    db = get_db()
    db.execute('DELETE FROM users WHERE id = ?', (user_id, ))
    db.commit()
    return redirect(url_for('admin_users'))


# Admin - upravit uživatele
@app.route('/admin/users/edit/<int:user_id>', methods=['POST'])
def edit_user(user_id):
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    db = get_db()
    # Zpracování úprav z modalu
    username = request.form['username']
    password = request.form.get('password')
    first_name = request.form.get('first_name')
    last_name = request.form.get('last_name')
    note = request.form.get('note') or ''
    job_location = request.form.get('job_location') or 'Stálý kopáč'
    is_admin = 1 if request.form.get('is_admin') == 'on' else 0
    hourly_rate = request.form.get('hourly_rate') or None
    # Update v DB
    if password:
        db.execute(
            '''UPDATE users SET username=?, password=?, first_name=?, last_name=?,
               note=?, job_location=?, is_admin=?, hourly_rate=?
               WHERE id=?''', (username, password, first_name, last_name, note,
                               job_location, is_admin, hourly_rate, user_id))
    else:
        db.execute(
            '''UPDATE users SET username=?, first_name=?, last_name=?,
               note=?, job_location=?, is_admin=?, hourly_rate=?
               WHERE id=?''', (username, first_name, last_name, note,
                               job_location, is_admin, hourly_rate, user_id))
    db.commit()
    return redirect(url_for('admin_users'))


# API pro admin docházku
@app.route('/api/admin_dochazka')
def api_admin_dochazka():
    if not session.get('is_admin'):
        return jsonify({'error': 'Přístup zamítnut'}), 403

    db = get_db()
    records = db.execute('''
        SELECT d.username, d.date, d.in_time, d.out_time, d.status,
               d.place, d.note,
               u.first_name, u.last_name

        FROM dochazka d
        LEFT JOIN users u ON d.username = u.username
        ''').fetchall()

    data = []
    for r in records:
        try:
            h1, m1 = map(int, r['in_time'].split(':'))
            h2, m2 = map(int, r['out_time'].split(':'))
            minutes = (h2 * 60 + m2) - (h1 * 60 + m1)
            if minutes < 0:
                minutes += 1440
            hours = round(minutes / 60, 2)
        except Exception:
            hours = 0

        data.append({
            'username': r['username'],
            'date': r['date'],
            'in_time': r['in_time'],
            'out_time': r['out_time'],
            'status': r['status'],
            'place': r['place'] or '',
            'note': r['note'] or '',
            'first_name': r['first_name'] or '',
            'last_name': r['last_name'] or '',
            'hours': hours
        })

    return jsonify(data)


# API pro ADMIN úpravu časů docházky
@app.route('/api/update_time', methods=['POST'])
def update_time():
    if not session.get('is_admin'):
        return jsonify({'error': 'Nepovolený přístup'}), 403

    data = request.get_json()
    username = data.get('username')
    date = data.get('date')
    in_time = data.get('in_time')
    out_time = data.get('out_time')

    db = get_db()
    if in_time:
        db.execute(
            'UPDATE dochazka SET in_time = ? WHERE username = ? AND date = ?',
            (in_time, username, date))
    if out_time:
        db.execute(
            'UPDATE dochazka SET out_time = ? WHERE username = ? AND date = ?',
            (out_time, username, date))
    db.commit()

    return jsonify({'success': True})


# API pro ADMIN změnu stavu docházky
@app.route('/api/zmenit_stav', methods=['POST'])
def zmenit_stav():
    if not session.get('is_admin'):
        return jsonify({'error': 'Nepovolený přístup'}), 403

    data = request.get_json()
    username = data.get('username')
    date = data.get('date')
    new_status = data.get('status')

    db = get_db()
    db.execute(
        'UPDATE dochazka SET status = ? WHERE username = ? AND date = ?',
        (new_status, username, date))
    db.commit()

    return jsonify({'success': True})


# API pro ADMIN smazání záznamu
@app.route('/api/smazat_zaznam', methods=['POST'])
def smazat_zaznam():
    if not session.get('is_admin'):
        return jsonify({'error': 'Nepovolený přístup'}), 403

    data = request.get_json()
    username = data.get('username')
    date = data.get('date')

    db = get_db()
    db.execute('DELETE FROM dochazka WHERE username = ? AND date = ?',
               (username, date))
    db.commit()

    return jsonify({'success': True})


# API pro ADMIN schválení záznamu
@app.route('/api/schvalit', methods=['POST'])
def api_schvalit():
    if not session.get('is_admin'):
        return jsonify({'error': 'Přístup zamítnut'}), 403

    data = request.get_json()
    username = data.get('username')
    date = data.get('date')

    db = get_db()
    db.execute(
        '''
        UPDATE dochazka
        SET status = 'Schváleno'
        WHERE username = ? AND date = ?
    ''', (username, date))
    db.commit()

    return jsonify({'success': True})


# API pro schválení celého dne
@app.route('/api/schvalit_den', methods=['POST'])
def api_schvalit_den():
    if not session.get('is_admin'):
        return jsonify({'error': 'Přístup zamítnut'}), 403

    data = request.get_json()
    date = data.get('date')

    db = get_db()
    db.execute(
        '''
        UPDATE dochazka
        SET status = 'Schváleno'
        WHERE date = ?
    ''', (date, ))
    db.commit()

    return jsonify({'success': True})


# Konec API pro admin docházku
#__________________________________________________________________________________________


# Admin - zaměstnanci cesta
@app.route('/admin/zamestnanci')
def admin_zamestnanci():
    return render_template('admin_zamestnanci.html')


# Admin - zaměstnanci API
@app.route('/api/admin_zamestnanci')
def get_zamestnanci():
    import datetime
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
    import datetime
    conn = sqlite3.connect('dochazka.db')
    c = conn.cursor()

    # Načtení základních údajů
    c.execute(
        """
        SELECT first_name, last_name, ico, bank_account, hourly_rate
        FROM users
        WHERE username = ?
    """, (username, ))
    user = c.fetchone()
    if not user:
        return jsonify({'error': 'Uživatel nenalezen'}), 404

    first_name, last_name, ico, bank_account, hourly_rate = user

    # Načtení docházky
    c.execute(
        "SELECT date, in_time, out_time, status FROM dochazka WHERE username = ?",
        (username, ))
    records = c.fetchall()

    attendance = []
    pending = 0.0
    unpaid = 0.0
    total = 0.0
    last_30_days_hours = 0.0
    days_set = set()

    today = datetime.datetime.today()
    threshold = today - datetime.timedelta(days=30)

    for r in records:
        date_str, in_time, out_time, status = r[0], r[1], r[2], r[3]
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

        attendance.append({
            "date": date_str,
            "in_time": in_time,
            "out_time": out_time,
            "status": status,
            "hours": round(hours, 2)
        })

    last_30_days_days = len(days_set)
    avg_daily_hours = round(last_30_days_hours /
                            last_30_days_days, 2) if last_30_days_days else 0

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


# Docházka
@app.route('/api/dochazka', methods=['GET'])
def get_dochazka():
    if 'username' not in session:
        return jsonify([])
    db = get_db()
    rows = db.execute(
        'SELECT date, in_time, out_time, status, place, note FROM dochazka WHERE username = ?',
        (session['username'], )).fetchall()

    return jsonify([dict(row) for row in rows])


# Funkce pro uložení docházky
@app.route('/api/dochazka', methods=['POST'])
def save_dochazka():
    if 'username' not in session:
        return jsonify({'success': False}), 403
    data = request.get_json()
    username = session['username']
    date = data['date']
    in_time = data['in_time']
    out_time = data['out_time']
    place = data.get('place', '')
    note = data.get('note', '')

    status = data.get('status') or 'Čeká na schválení'
    db = get_db()
    cur = db.execute('SELECT id FROM dochazka WHERE username=? AND date=?',
                     (username, date))
    existing = cur.fetchone()
    if existing:
        db.execute(
            'UPDATE dochazka SET in_time = ?, out_time = ?, place = ?, note = ? WHERE username = ? AND date = ?',
            (in_time, out_time, place, note, session['username'], date))

    else:
        db.execute(
            '''
            INSERT INTO dochazka (username, date, in_time, out_time, status, place, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (session['username'], date, in_time, out_time,
              'Čeká na schválení', place, note))

    db.commit()
    return jsonify({'success': True})


# Funkce pro úpravu docházky - v zaměstnaneckm rozhraní
@app.route('/api/dochazka', methods=['PATCH'])
def update_dochazka():
    data = request.get_json()

    original_date = data.get('original_date')
    in_time = data.get('in_time')
    out_time = data.get('out_time')
    place = data.get('place')
    note = data.get('note')

    if not original_date:
        return jsonify({'error': 'Chybí datum záznamu'}), 400

    conn = sqlite3.connect('dochazka.db')
    c = conn.cursor()

    c.execute(
        '''
        UPDATE dochazka
        SET in_time = ?, out_time = ?, place = ?, note = ?
        WHERE date = ?
    ''', (in_time, out_time, place, note, original_date))

    conn.commit()
    conn.close()

    return jsonify({'message': 'Záznam byl úspěšně upraven'}), 200


# Otevření admin výplat -> html souboru
@app.route('/admin_vyplaty')
def admin_vyplaty():
    return render_template('admin_vyplaty.html')


# Zobrazení výplat
@app.route('/api/admin_vyplaty')
def admin_vyplaty_json():
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

    # Zapiš napojení a označ jako proplacené
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

    db = get_db()

    # Získej všechna ID docházek navázaná na výplatu
    dochazky = db.execute(
        'SELECT dochazka_id FROM vyplaty_dochazky WHERE vyplata_id = ?',
        (vyplata_id, )).fetchall()
    dochazka_ids = [r['dochazka_id'] for r in dochazky]

    # Odpoj napojení
    db.execute('DELETE FROM vyplaty_dochazky WHERE vyplata_id = ?',
               (vyplata_id, ))
    # Smaž samotnou výplatu
    db.execute('DELETE FROM vyplaty WHERE id = ?', (vyplata_id, ))

    if option == '1':  # Označit jako schválené
        db.executemany('UPDATE dochazka SET status = ? WHERE id = ?',
                       [('Schváleno', did) for did in dochazka_ids])
    elif option == '2':  # Smazat docházky
        db.executemany('DELETE FROM dochazka WHERE id = ?',
                       [(did, ) for did in dochazka_ids])
    # option == '3': nechat jako „Proplaceno“ → nic neděláme

    db.commit()
    return jsonify({'success': True})


# Inicializace DB
def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS dochazka (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                date TEXT NOT NULL,
                in_time TEXT,
                out_time TEXT,
                status TEXT
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                first_name TEXT,
                last_name TEXT,
                note TEXT,
                job_location TEXT,
                is_admin INTEGER NOT NULL DEFAULT 0,
                hourly_rate REAL
            )
        ''')
        # Výchozí admin účty
        db.execute(
            "INSERT OR IGNORE INTO users (username, password, first_name, last_name, is_admin, job_location, hourly_rate) VALUES (?, ?, ?, ?, ?, ?, NULL)",
            ('admin1', 'adminheslo1', 'Jan', 'Novák', 1, 'Big Boss'))
        db.execute(
            "INSERT OR IGNORE INTO users (username, password, first_name, last_name, is_admin, job_location, hourly_rate) VALUES (?, ?, ?, ?, ?, ?, NULL)",
            ('admin2', 'adminheslo2', 'Petr', 'Svoboda', 1, 'Big Boss'))
        db.commit()


# Pro první spuštění odkomentovat:
#init_db()

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=3001, debug=True)
