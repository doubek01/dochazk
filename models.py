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
    username = db.Column(db.String(80), nullable=False)
    od_datum = db.Column(db.String(10), nullable=False)
    do_datum = db.Column(db.String(10), nullable=False)
    celkem_hodin = db.Column(db.Float)
    sazba = db.Column(db.Float)
    celkem_castka = db.Column(db.Float)
    zaplaceno = db.Column(db.Boolean, default=False)

class VyplataDochazky(db.Model):
    __tablename__ = 'vyplaty_dochazky'
    id = db.Column(db.Integer, primary_key=True)
    vyplata_id = db.Column(db.Integer, nullable=False)
    dochazka_id = db.Column(db.Integer, nullable=False)
