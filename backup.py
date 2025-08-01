import os
import subprocess
from datetime import datetime

# Vytvoř název souboru
now = datetime.now().strftime("%Y-%m-%d_%H-%M")
backup_file = f"backup_{now}.sql"

# Vytvoř dočasný soubor s konfigurací rclone
rclone_conf = os.environ.get("RCLONE_CONFIG")
os.makedirs("temp_conf", exist_ok=True)
with open("temp_conf/rclone.conf", "w") as f:
    f.write(rclone_conf)

# Vytvoř zálohu PostgreSQL databáze
pg_user = os.environ.get("PGUSER", "postgres")
pg_host = os.environ.get("PGHOST")
pg_port = os.environ.get("PGPORT", "5432")
pg_db = os.environ.get("PGDATABASE")
pg_password = os.environ.get("PGPASSWORD")

os.environ["PGPASSWORD"] = pg_password

subprocess.run([
    "pg_dump",
    "-h", pg_host,
    "-p", pg_port,
    "-U", pg_user,
    "-d", pg_db,
    "-f", backup_file
], check=True)

# Nahraj na Google Drive pomocí rclone
subprocess.run([
    "rclone", "--config=temp_conf/rclone.conf",
    "copy", backup_file, "gdrive:railway_backups"
], check=True)

print("✅ Záloha hotová a nahraná!")
