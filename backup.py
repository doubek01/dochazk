import os
from datetime import datetime

# Vytvoř název souboru podle data
today = datetime.now().strftime("%Y-%m-%d")
filename = f"backup_{today}.sql"

# Přístupové údaje (nebo použij environment variables)
PGUSER = os.getenv("PGUSER")
PGPASSWORD = os.getenv("PGPASSWORD")
PGHOST = os.getenv("PGHOST")
PGPORT = os.getenv("PGPORT")
PGDATABASE = os.getenv("PGDATABASE")

# Export databáze
dump_cmd = f"PGPASSWORD={PGPASSWORD} pg_dump -h {PGHOST} -U {PGUSER} -p {PGPORT} -d {PGDATABASE} > {filename}"
os.system(dump_cmd)

# Odeslání na Google Drive přes rclone
upload_cmd = f"rclone copy {filename} gdrive:ZalohaDochazka"
os.system(upload_cmd)
