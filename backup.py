import os
import subprocess
from datetime import datetime
from urllib.parse import urlparse
import sys

# Získání DATABASE_URL z prostředí
db_url = os.getenv("DATABASE_URL")
if not db_url:
    raise ValueError("DATABASE_URL není nastaven")

# Parsování URL
result = urlparse(db_url)

pg_user = result.username
pg_password = result.password or os.getenv("PGPASSWORD", "")
pg_host = result.hostname
pg_port = result.port or "5432"
pg_db = result.path.lstrip('/')

if not all([pg_user, pg_password, pg_host, pg_port, pg_db]):
    print("Chyba: Některá z hodnot připojení k databázi chybí.")
    sys.exit(1)

# Název souboru pro zálohu
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
backup_filename = f"backup_{timestamp}.sql"

# Cesta k výstupnímu souboru
backup_path = os.path.join(os.getcwd(), backup_filename)

# Příkaz k dumpu databáze
os.environ["PGPASSWORD"] = pg_password
command = [
    "pg_dump",
    "-h", pg_host,
    "-p", str(pg_port),
    "-U", pg_user,
    "-d", pg_db,
    "-F", "c",  # custom format – rychlejší a menší
    "-f", backup_path
]

# Spuštění dumpu
try:
    subprocess.run(command, check=True)
    print(f"Záloha databáze vytvořena: {backup_path}")
except subprocess.CalledProcessError as e:
    print(f"Chyba při záloze databáze: {e}")
    sys.exit(1)

# Upload na Google Drive přes rclone
gdrive_target = "gdrive:backupy_dochazka"
try:
    subprocess.run(["rclone", "copy", backup_path, gdrive_target], check=True)
    print("Záloha úspěšně nahrána na Google Drive.")
except subprocess.CalledProcessError as e:
    print(f"Chyba při nahrávání na Google Drive: {e}")
    sys.exit(1)
