from db_connection import get_cursor

# ---------------- STUDENTS ----------------
def add_student(name, email, phone):
    try:
        cursor, conn = get_cursor()
        cursor.execute("SELECT id FROM students WHERE email=%s", (email,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return "❌ Student with this email already exists!"

        sql = """INSERT INTO students (name, email, phone, current_stage, status) 
                 VALUES (%s, %s, %s, %s, %s)"""
        values = (name, email, phone, 1, "Enrolled")
        cursor.execute(sql, values)
        conn.commit()
        cursor.close()
        conn.close()
        return "✅ Student added successfully!"
    except Exception as e:
        return f"❌ Error adding student: {str(e)}"


# ---------------- TUTORS ----------------
def add_tutor(name, email, assigned_stage):
    try:
        cursor, conn = get_cursor()
        cursor.execute("SELECT id FROM tutors WHERE email=%s", (email,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return "❌ Tutor with this email already exists!"

        sql = "INSERT INTO tutors (name, email, assigned_stage) VALUES (%s, %s, %s)"
        values = (name, email, assigned_stage)
        cursor.execute(sql, values)
        conn.commit()
        cursor.close()
        conn.close()
        return "✅ Tutor added successfully!"
    except Exception as e:
        return f"❌ Error adding tutor: {str(e)}"


# ---------------- STUDENT STAGES ----------------
def update_student_stage(student_id, new_stage, updated_by):
    try:
        cursor, conn = get_cursor()

        # Update student
        sql = "UPDATE students SET current_stage=%s, status='In Progress' WHERE id=%s"
        cursor.execute(sql, (new_stage, student_id))
        conn.commit()

        # Log progress
        sql = """INSERT INTO student_stage_progress 
                 (student_id, stage_id, status, updated_by) 
                 VALUES (%s, %s, %s, %s)"""
        cursor.execute(sql, (student_id, new_stage, "In Progress", updated_by))
        conn.commit()

        cursor.close()
        conn.close()
        return "✅ Student stage updated!"
    except Exception as e:
        return f"❌ Error updating stage: {str(e)}"


# ---------------- APPLICATIONS ----------------
def student_apply(student_id, company_id, applied_by="student"):
    try:
        cursor, conn = get_cursor()

        # Validate student
        cursor.execute("SELECT id FROM students WHERE id=%s", (student_id,))
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return "❌ Student not found!"

        # Check duplicate
        cursor.execute("SELECT id FROM applications WHERE student_id=%s AND company_id=%s", (student_id, company_id))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return "❌ Already applied for this company!"

        sql = """INSERT INTO applications (student_id, company_id, applied_by, status) 
                 VALUES (%s, %s, %s, %s)"""
        values = (student_id, company_id, applied_by, "Pending")
        cursor.execute(sql, values)
        conn.commit()
        cursor.close()
        conn.close()
        return "✅ Application submitted!"
    except Exception as e:
        return f"❌ Error applying: {str(e)}"


# ---------------- COMPANIES ----------------
def add_company(name, job_description, job_type, package, eligibility, drive_date, location, selection_process, nomination_form):
    try:
        cursor, conn = get_cursor()
        sql = """INSERT INTO companies 
                 (name, job_description, job_type, package, eligibility, drive_date, location, selection_process, nomination_form)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        values = (name, job_description, job_type, package, eligibility, drive_date, location, selection_process, nomination_form)
        cursor.execute(sql, values)
        conn.commit()
        cursor.close()
        conn.close()
        return "✅ Company added successfully!"
    except Exception as e:
        return f"❌ Error adding company: {str(e)}"
