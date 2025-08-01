from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String, unique=True, nullable=False)
    password = db.Column(db.String, nullable=False)
    first_name = db.Column(db.String)         # musí tam být
    last_name = db.Column(db.String)          # musí tam být
    is_admin = db.Column(db.Boolean, default=False)
    note = db.Column(db.String)               # musí tam být
    job_location = db.Column(db.String)       # musí tam být
    hourly_rate = db.Column(db.Float)         # musí tam být
    ico = db.Column(db.String(20))
    bank_account = db.Column(db.String(50))


class Dochazka(db.Model):
    __tablename__ = 'dochazka'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String, db.ForeignKey('users.username'), nullable=False)
    date = db.Column(db.String, nullable=False)
    in_time = db.Column(db.String)
    out_time = db.Column(db.String)
    status = db.Column(db.String)
    place = db.Column(db.String)  
    note = db.Column(db.String)  

class Vyplata(db.Model):
    __tablename__ = 'vyplaty'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String, db.ForeignKey('users.username'))
    total_hours = db.Column(db.Float)
    amount = db.Column(db.Float)
    date = db.Column(db.String)  # nebo db.Date
    month = db.Column(db.String(7))  # <== Tohle je důležité


class VyplataDochazky(db.Model):
    __tablename__ = 'vyplaty_dochazky'
    id = db.Column(db.Integer, primary_key=True)
    vyplata_id = db.Column(db.Integer, nullable=False)
    dochazka_id = db.Column(db.Integer, nullable=False)
