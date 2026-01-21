# utils.py
import os
import pandas as pd
import numpy as np
import logging
from db_connection import get_cursor

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


def _to_py(x):
    """Convert pandas/numpy types to native Python types."""
    if pd.isna(x):
        return None
    if isinstance(x, np.generic):
        return x.item()
    return x


def add_students_to_applications(student_list):
    """
    After adding students, populate their entries in all existing company applications.
    student_list: list of dicts with student info
    """
    cursor, conn = get_cursor()
    try:
        cursor.execute("SELECT name FROM companies")
        companies = cursor.fetchall()
        if not companies:
            logging.info("No companies found, skipping applications update.")
            return

        for student in student_list:
            cgpa = student.get('cgpa') or 0
            backlogs = student.get('backlogs') or 0
            eligible = "Yes" if cgpa >= 7 and backlogs == 0 else "No"

            for company in companies:
                company_name = company['name']
                cursor.execute("""
                    INSERT IGNORE INTO applications
                    (registration_number, student_name, cgpa, backlogs, section, specialization, company_name, eligible, applied)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    student.get('registration_number'),
                    student.get('name'),
                    cgpa,
                    backlogs,
                    student.get('section'),
                    student.get('specialization'),
                    company_name,
                    eligible,
                    "No"
                ))
        conn.commit()
    except Exception as e:
        logging.error(f"Failed to add students to applications: {e}")
    finally:
        cursor.close()
        conn.close()


def bulk_add_students(file_path, batch_size=200):
    """
    Bulk add students from Excel or CSV file.
    Returns dictionary: {'inserted': int, 'failed': int, 'errors': list}
    """

    # ----- READ FILE -----
    ext = file_path.rsplit('.', 1)[-1].lower()
    if ext == 'csv':
        df = pd.read_csv(file_path)
    elif ext in ['xls', 'xlsx']:
        df = pd.read_excel(file_path, engine='openpyxl')
    else:
        raise ValueError("Invalid file type. Only CSV or Excel allowed.")

    # Clean column names
    df.columns = [str(c).strip().lower() for c in df.columns]
    df = df.loc[:, df.columns.notna()].copy()

    # ----- ALL REQUIRED DB COLUMNS -----
    headers = [
        'registration_number', 'name', 'email', 'phone', 'course', 'section',
        'specialization', 'semester', 'backlogs', 'status', 'cgpa', 'roll_no',
        'department', 'marks_10th', 'marks_12th', 'current_stage'
    ]

    # KEEP only valid columns from file
    df = df[[c for c in df.columns if c in headers]].copy()

    # ADD missing columns with NULL
    for h in headers:
        if h not in df.columns:
            df[h] = None

    # Arrange columns in correct order
    df = df[headers]

    # Convert values to native Python types
    df = df.applymap(_to_py)

    # Ensure student has at least a name — minimal requirement
    df = df[df['name'].notna()]

    cursor, conn = get_cursor()
    inserted = 0
    errors = []
    student_list_for_applications = []

    # SQL Insert Query
    insert_sql = """
        INSERT IGNORE INTO students (
            registration_number, name, email, phone, course, section, specialization,
            semester, backlogs, status, cgpa, roll_no, department,
            marks_10th, marks_12th, current_stage
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    try:
        for idx, row in df.iterrows():
            values = tuple(row[h] for h in headers)

            # Optional strict check for registration_number
            # Remove this check if you want NULL allowed for reg_no also
            if not row.get('name'):
                errors.append({'row_index': idx, 'values': values, 'error': 'Missing name'})
                continue

            try:
                cursor.execute(insert_sql, values)
                inserted += 1
                student_list_for_applications.append(dict(row))

                # Commit in batches
                if inserted % batch_size == 0:
                    conn.commit()

            except Exception as e:
                errors.append({'row_index': idx, 'values': values, 'error': str(e)})

        conn.commit()

    except Exception as e:
        logging.error(f"Bulk insert failed: {e}")

    finally:
        cursor.close()
        conn.close()

    logging.info(f"Inserted: {inserted}, Failed: {len(errors)}")

    # Add students to applications table
    if student_list_for_applications:
        add_students_to_applications(student_list_for_applications)

    return {'inserted': inserted, 'failed': len(errors), 'errors': errors}
