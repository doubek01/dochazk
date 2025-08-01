import os
import subprocess
from datetime import datetime
from urllib.parse import urlparse
import psycopg2

# 1. Ulož rclone config jako soubor
rclone_conf_content = os.environ["RCLONE_CONFIG"]
rclone_conf_path = "/tmp/rclone.conf"
with open(rclone_conf_path, "w") as f:
    f.write(rclone_conf_content)

os.environ["RCLONE_CONFIG"] = rclone_conf_path

# 2. Připrav název zálohy
now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
backup_path = f"backup_{now}.sql"

# 3. Rozparsuj DATABASE_URL
db_url = os.environ["DATABASE_URL"]
parsed = urlparse(db_url)

db_user = parsed.username
db_password = parsed.password
db_host = parsed.hostname
db_port = parsed.port
db_name = parsed.path.lstrip("/")

# 4. Vytvoř zálohu pomocí pg_dump
os.environ["PGPASSWORD"] = db_password
with open(backup_path, "w") as f:
    subprocess.run([
        "pg_dump",
        "-h", db_host,
        "-p", str(db_port),
        "-U", db_user,
        "-d", db_name
    ], stdout=f, check=True)

print(f"✅ Záloha databáze vytvořena: {backup_path}")

# 5. Nahraj na Google Drive (do složky 'backupy_dochazka')
gdrive_target = "gdrive:backupy_dochazka"
subprocess.run(["rclone", "copy", backup_path, gdrive_target], check=True)

print("✅ Záloha úspěšně nahrána na Google Drive.")
