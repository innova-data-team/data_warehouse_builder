# Run with MySQL

Use this when you want the full pipeline in **MySQL** (Power BI, ZakaaDash, SQL generator).

---

## 1. Prerequisites

- Python 3.11+
- **MySQL 8.0** (local install or Docker)
- MySQL Workbench or `mysql` CLI

---

## 2. Configure `.env`

```ini
STORAGE_BACKEND=mysql

MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=saber
MYSQL_PASSWORD=your_password
MYSQL_DRIVER=pymysql
```

Use the **same user and password** as MySQL Workbench.

---

## 3. Test connection

```powershell
cd data_warehouse_builder
.\.venv\Scripts\activate
python mysql_probe.py
```

You should see `[OK]` for at least one driver/host combination.

If you get **1044** (access denied to database): password works but grants are missing — run the grant script below.

If you get **1045**: wrong password — fix `MYSQL_PASSWORD` in `.env`.

---

## 4. Create databases (one time)

In **MySQL Workbench**, run as admin (`root`):

1. `sql/generated/create_databases.sql`
2. `sql/generated/grant_saber_user.sql` — edit username if not `saber`
3. On database `dw_metadata`, run:
   `sql/generated/metadata/example_metadata_tables.sql`

Or from command line:

```powershell
mysql -u root -p < sql/generated/create_databases.sql
mysql -u root -p < sql/generated/grant_saber_user.sql
mysql -u root -p dw_metadata < sql/generated/metadata/example_metadata_tables.sql
```

---

## 5. Verify

```powershell
python check_setup.py
```

Expect **MySQL connection** check to pass.

---

## 6. Run the app

```bat
run_streamlit.bat
```

Open http://127.0.0.1:8501 — sidebar should show **MySQL connected**.

---

## 7. Switch back to file mode

No MySQL needed for day-to-day dev:

```ini
STORAGE_BACKEND=file
```

Restart Streamlit. See [QUICKSTART.md](./QUICKSTART.md).

---

## Grant template (custom user)

Replace `your_user` and run as `root`:

```sql
GRANT ALL ON dw_metadata.* TO 'your_user'@'%';
GRANT ALL ON dw_bronze.*   TO 'your_user'@'%';
GRANT ALL ON dw_silver.*   TO 'your_user'@'%';
GRANT ALL ON dw_gold.*     TO 'your_user'@'%';
GRANT ALL ON dw_metadata.* TO 'your_user'@'localhost';
GRANT ALL ON dw_bronze.*   TO 'your_user'@'localhost';
GRANT ALL ON dw_silver.*   TO 'your_user'@'localhost';
GRANT ALL ON dw_gold.*     TO 'your_user'@'localhost';
FLUSH PRIVILEGES;
```

---

## Docker MySQL

```powershell
docker compose up -d mysql
```

Set in `.env`:

```ini
MYSQL_HOST=127.0.0.1
MYSQL_USER=dw_user
MYSQL_PASSWORD=change_me
```

(Defaults match `docker-compose.yml`.)
