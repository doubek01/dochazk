import bcrypt
from main import db, User  # Ujisti se, že máš správný import modelu User a db

def hash_and_update_passwords():
    users = User.query.all()
    for user in users:
        if not user.password.startswith("$2b$"):  # už hashované začínají takto
            hashed = bcrypt.hashpw(user.password.encode('utf-8'), bcrypt.gensalt())
            user.password = hashed.decode('utf-8')
    db.session.commit()
    print("✅ Hesla úspěšně zahashována.")

if __name__ == "__main__":
    from main import app
    with app.app_context():
        hash_and_update_passwords()
