# db_connection.py
import os
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv

# ✅ Load .env ONLY for local development.
# On Railway, values come from Railway Dashboard -> Variables.
load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),                 # ✅ Railway MySQL host
    "port": int(os.getenv("DB_PORT", "3306")),    # ✅ Railway MySQL port
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),             # ✅ Railway database name
    "autocommit": True
}

def get_connection():
    """
    Establish and return a MySQL database connection.
    """
    try:
        # ✅ Validate missing env values
        required_vars = ["DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"]
        missing = [v for v in required_vars if not os.getenv(v)]

        if missing:
            raise Error(f"❌ Missing DB Variables in Railway: {', '.join(missing)}")

        conn = mysql.connector.connect(**DB_CONFIG)
        if conn.is_connected():
            return conn
        else:
            raise Error("❌ Failed to connect to the database.")

    except Error as e:
        print(f"❌ Database connection error: {str(e)}")
        raise


def get_cursor(buffered=True, dictionary=True):
    """
    Returns a tuple (cursor, connection) for executing queries.
    Use cursor.close() and conn.close() after usage.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=buffered, dictionary=dictionary)
        return cursor, conn
    except Error as e:
        print(f"❌ Error creating cursor: {str(e)}")
        raise
