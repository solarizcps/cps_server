import pyodbc

print("=== DB TEST ===")

try:
    conn = pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        "SERVER=25.7.184.221;"
        "DATABASE=Solariz22;"
        "UID=claude;"
        "PWD=104099;"
        "TrustServerCertificate=yes;"
    )

    print("✔ DB CONNECT OK")

    cur = conn.cursor()
    cur.execute("SELECT TOP 5 name FROM sys.tables")
    rows = cur.fetchall()

    print("✔ TABLE OK:", len(rows))

except Exception as e:
    print("❌ DB FAIL:", e)