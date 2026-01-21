# db_connection.py
import mysql.connector
from mysql.connector import Error

DB_CONFIG = {
    "host": "localhost",
    "user": "tp_user",
    "password": "tp_pass",
    "database": "training_portal_v2"  # ✅ updated DB name
}

def get_connection():
    """
    Establish and return a MySQL database connection.
    """
    try:
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
