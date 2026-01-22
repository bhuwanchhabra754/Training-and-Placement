from multiprocessing.resource_tracker import getfd
import os
import json
import mysql.connector
import pandas as pd
from flask import (
    Flask, request, render_template, redirect, send_file, url_for, flash,
    send_from_directory, session, abort
)
from werkzeug.utils import secure_filename
from db_connection import get_connection  # must return mysql connector connection
from utils import bulk_add_students        # your existing util (ensure it handles registration_number)
from datetime import datetime
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS



from portal_ai import AI  
app = Flask(__name__)
CORS(app)
@app.route("/api/ai/ask", methods=["POST"])
def ask_ai():
    data = request.get_json()
    question = data.get("question", "").strip()

    if not question:
        return jsonify({"error": "Question is required"}), 400

    try:
        answer = AI(question)
        return jsonify({"answer": answer})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



app = Flask(__name__)
app.secret_key = "your_secret_key"

# ---------------- CONFIG ----------------
# UPLOAD_FOLDER is the folder where files are physically stored on disk
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_COMPANY_EXTENSIONS = {'pdf', 'docx'}
ALLOWED_STUDENT_EXTENSIONS = {'csv', 'xls', 'xlsx'}
ALLOWED_ROUND_EXTENSIONS = {'csv', 'xls', 'xlsx'}

def allowed_file(filename, allowed_exts=None):
    if not filename:
        return False

    if allowed_exts is None:
        allowed_exts = set()

    return (
        '.' in filename
        and filename.rsplit('.', 1)[1].lower() in allowed_exts
    )



load_dotenv()

oauth = OAuth(app)

google = oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile"
    }
)
# ===========================
# GOOGLE OAUTH LOGIN
# ===========================
@app.route("/auth/google")
def google_login():
    role = request.args.get("role", "").strip().lower()

    # ✅ Only allow known roles
    if role not in ["admin", "tutor", "student"]:
        flash("Invalid login role.", "danger")
        return redirect(url_for("home"))

    session["google_role"] = role  # store selected role for callback

    redirect_uri = url_for("google_callback", _external=True, _scheme="https")
    return google.authorize_redirect(redirect_uri)




@app.route("/auth/google/callback")
def google_callback():
    try:
        token = google.authorize_access_token()
        user_info = token.get("userinfo")

        if not user_info:
            user_info = google.get("userinfo").json()

        email = (user_info.get("email") or "").strip()

        if not email:
            flash("Google login failed (email missing).", "danger")
            return redirect(url_for("home"))

        role = session.get("google_role")  # 🔥 get selected role

        if role not in ["admin", "tutor", "student"]:
            flash("Login role missing. Please try again.", "danger")
            return redirect(url_for("home"))

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # ✅ ADMIN ONLY
        if role == "admin":
            cursor.execute("SELECT * FROM admin_auth WHERE email=%s", (email,))
            admin = cursor.fetchone()
            cursor.close(); conn.close()

            if admin:
                session.clear()
                session["admin_email"] = email
                flash("Welcome Admin (Google Login)", "success")
                return redirect(url_for("admin_dashboard"))
            else:
                flash("This email is not registered as Admin.", "danger")
                return redirect(url_for("admin_login"))

        # ✅ TUTOR ONLY
        if role == "tutor":
            cursor.execute("SELECT * FROM tutors WHERE email=%s", (email,))
            tutor = cursor.fetchone()
            cursor.close(); conn.close()

            if tutor:
                session.clear()
                session["tutor_id"] = tutor.get("id")
                session["tutor_email"] = tutor.get("email")
                flash(f"Welcome {tutor.get('name')}! (Google Login)", "success")
                return redirect(url_for("tutor_dashboard"))
            else:
                flash("This email is not registered as Tutor.", "danger")
                return redirect(url_for("tutor_login"))

        # ✅ STUDENT ONLY
        if role == "student":
            cursor.execute("SELECT * FROM students WHERE email=%s", (email,))
            student = cursor.fetchone()
            cursor.close(); conn.close()

            if student:
                session.clear()
                session["student_email"] = student.get("email")
                session["student_reg"] = student.get("registration_number")
                session["student_name"] = student.get("name")
                flash(f"Welcome {student.get('name')}! (Google Login)", "success")
                return redirect(url_for("student_dashboard"))
            else:
                flash("This email is not registered as Student.", "danger")
                return redirect(url_for("student_login"))

    except Exception as e:
        print("GOOGLE CALLBACK ERROR:", e)
        flash("Google login failed. Try again.", "danger")
        return redirect(url_for("home"))




# ----------------- DB HELPER: ensure helper tables exist -----------------
def ensure_helper_tables():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # ✅ 1) Ensure companies table exists (required for FK)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL
            )
        """)

        # ✅ 2) company_shortlist table (depends on companies)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS company_shortlist (
                id INT AUTO_INCREMENT PRIMARY KEY,
                company_id INT NOT NULL,
                round_number INT NOT NULL,
                registration_number VARCHAR(50) NOT NULL,
                student_name VARCHAR(255),
                email VARCHAR(255),
                branch VARCHAR(50),
                year VARCHAR(20),
                status ENUM('Passed','Failed') DEFAULT 'Passed',
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_student_round (company_id, round_number, registration_number),
                CONSTRAINT fk_company_shortlist_company
                    FOREIGN KEY (company_id) REFERENCES companies(id)
                    ON DELETE CASCADE
                    ON UPDATE CASCADE
            )
        """)

        # ✅ 3) uploaded_round_files table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS uploaded_round_files (
                id INT AUTO_INCREMENT PRIMARY KEY,
                company_id INT NOT NULL,
                round_number INT NOT NULL,
                file_name VARCHAR(255),
                file_path VARCHAR(255),
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        print("✅ Helper tables ensured successfully.")

    except Exception as e:
        print("⚠️ ensure_helper_tables error:", e)
        conn.rollback()

    finally:
        cursor.close()
        conn.close()


# 🔥 CALL IT (THIS WAS MISSING)
ensure_helper_tables()
# -------- ADMIN SIGNUP --------
@app.route('/admin/signup', methods=['GET', 'POST'])
def admin_signup():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        confirm = request.form.get('confirm', '').strip()

        if not email or not password or not confirm:
            flash("All fields are required", "danger")
            return redirect(url_for('admin_signup'))

        if password != confirm:
            flash("Passwords do not match", "danger")
            return redirect(url_for('admin_signup'))

        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "INSERT INTO admin_auth (email, password) VALUES (%s, %s)",
                (email, password)
            )
            conn.commit()
            flash("Admin account created successfully. Please login.", "success")
            return redirect(url_for('admin_login'))

        except mysql.connector.IntegrityError:
            flash("Admin already exists with this email", "danger")

        finally:
            cursor.close()
            conn.close()

    return render_template('admin_signup.html')



# -------- ADMIN LOGIN --------
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        if not email or not password:
            flash("Email and password are required", "danger")
            return redirect(url_for('admin_login'))

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM admin_auth WHERE email=%s AND password=%s",
            (email, password)
        )
        admin = cursor.fetchone()

        cursor.close()
        conn.close()

        if admin:
            session.clear()                 # 🔥 clear old sessions
            session['admin_email'] = admin['email']

            flash("Welcome Admin", "success")
            return redirect(url_for('admin_dashboard'))

        else:
            flash("Invalid email or password", "danger")

    return render_template('admin_login.html')



# ---------------- ADMIN DASHBOARD (INDEX_ADMIN) ----------------
@app.route('/admin/dashboard')
def admin_dashboard():
    # 🔐 Admin protection
    if 'admin_email' not in session:
        flash("Please login as admin", "warning")
        return redirect(url_for('admin_login'))

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT COUNT(*) AS total_students FROM students")
        total_students = cursor.fetchone()['total_students']

        cursor.execute("SELECT COUNT(*) AS total_companies FROM companies")
        total_companies = cursor.fetchone()['total_companies']

        cursor.execute("SELECT COUNT(*) AS total_applications FROM applications")
        total_applications = cursor.fetchone()['total_applications']

        cursor.execute("SELECT COUNT(*) AS total_eligible FROM applications WHERE eligible='Yes'")
        total_eligible = cursor.fetchone()['total_eligible']

        cursor.execute("SELECT COUNT(*) AS total_not_eligible FROM applications WHERE eligible='No'")
        total_not_eligible = cursor.fetchone()['total_not_eligible']

        cursor.execute("SELECT COUNT(*) AS total_applied FROM applications WHERE applied='Yes'")
        total_applied = cursor.fetchone()['total_applied']

        cursor.execute("SELECT COUNT(*) AS total_not_applied FROM applications WHERE applied='No'")
        total_not_applied = cursor.fetchone()['total_not_applied']

    finally:
        cursor.close()
        conn.close()

    stats = {
        'total_students': total_students,
        'total_companies': total_companies,
        'total_applications': total_applications,
        'total_eligible': total_eligible,
        'total_not_eligible': total_not_eligible,
        'total_applied': total_applied,
        'total_not_applied': total_not_applied
    }

    return render_template('index_admin.html', stats=stats)



# ---------------- ROOT / HOME ----------------
@app.route('/')
def home():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT COUNT(*) AS total_students FROM students")
        total_students = cursor.fetchone().get('total_students', 0) or 0

        cursor.execute("SELECT COUNT(*) AS total_companies FROM companies")
        total_companies = cursor.fetchone().get('total_companies', 0) or 0

        cursor.execute("SELECT COUNT(*) AS total_applications FROM applications")
        total_applications = cursor.fetchone().get('total_applications', 0) or 0

        cursor.execute("SELECT COUNT(*) AS total_eligible FROM applications WHERE eligible='Yes'")
        total_eligible = cursor.fetchone().get('total_eligible', 0) or 0

        cursor.execute("SELECT COUNT(*) AS total_not_eligible FROM applications WHERE eligible='No'")
        total_not_eligible = cursor.fetchone().get('total_not_eligible', 0) or 0

        cursor.execute("SELECT COUNT(*) AS total_applied FROM applications WHERE applied='Yes'")
        total_applied = cursor.fetchone().get('total_applied', 0) or 0

        cursor.execute("SELECT COUNT(*) AS total_not_applied FROM applications WHERE applied='No'")
        total_not_applied = cursor.fetchone().get('total_not_applied', 0) or 0

    finally:
        cursor.close()
        conn.close()

    stats = {
        'total_students': total_students,
        'total_companies': total_companies,
        'total_applications': total_applications,
        'total_eligible': total_eligible,
        'total_not_eligible': total_not_eligible,
        'total_applied': total_applied,
        'total_not_applied': total_not_applied
    }
    return render_template('index.html', stats=stats)
@app.route('/companies_dashboard')
def companies_dashboard():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # FIXED: Removed invalid column "status"
        cursor.execute("SELECT name FROM companies")
        companies = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template("companies_dashboard.html", companies=companies)


@app.route('/company/<company_name>')
def company_dashboard(company_name):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT 
                COUNT(*) AS total_applications,
                SUM(eligible='Yes') AS total_eligible,
                SUM(eligible='No') AS total_not_eligible,
                SUM(applied='Yes') AS total_applied,
                SUM(applied='No') AS total_not_applied
            FROM applications
            WHERE company_name=%s
        """, (company_name,))
        data = cursor.fetchone()

    finally:
        cursor.close()
        conn.close()

    stats = {
        'company_name': company_name,
        'total_applications': data.get('total_applications', 0),
        'total_eligible': data.get('total_eligible', 0),
        'total_not_eligible': data.get('total_not_eligible', 0),
        'total_applied': data.get('total_applied', 0),
        'total_not_applied': data.get('total_not_applied', 0)
    }

    return render_template('company_dashboard.html', stats=stats)



@app.route('/status')
def status():
    return {"message": "🚀 Training Portal API is running!"}


# ---------------- ADMIN: Company Rounds - list of companies ----------------
@app.route('/admin/company_rounds')
def admin_company_rounds_list():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, name FROM companies ORDER BY name ASC")
        companies = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
    return render_template('admin_company_rounds.html', companies=companies)


# ---------------- ADMIN: Company Rounds View (specific company) ----------------
@app.route('/admin/company_rounds/<int:company_id>')
def admin_company_rounds_view(company_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM companies WHERE id = %s", (company_id,))
        company = cursor.fetchone()
        if not company:
            return "Company not found", 404

        selection_process = company.get("selection_process") or ""

        rounds = []
        if isinstance(selection_process, str) and selection_process.strip().startswith('['):
            try:
                sel = json.loads(selection_process)
                if isinstance(sel, list):
                    for i, name in enumerate(sel):
                        rounds.append({"round_number": i+1, "round_name": str(name)})
            except Exception:
                parts = selection_process.split(",")
                for i, p in enumerate(parts):
                    rounds.append({"round_number": i+1, "round_name": p.strip()})
        else:
            parts = [p.strip() for p in str(selection_process).split(",") if p.strip()]
            for i, p in enumerate(parts):
                rounds.append({"round_number": i+1, "round_name": p})

        cursor.execute("""
            SELECT id, round_number, file_name, file_path, uploaded_at
            FROM uploaded_round_files
            WHERE company_id = %s
            ORDER BY round_number ASC, uploaded_at DESC
        """, (company_id,))
        uploaded_files = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template(
        'admin_company_rounds_view.html',
        company=company,
        rounds=rounds,
        uploaded_files=uploaded_files
    )


# ---------------- ADMIN: Upload results for a specific company round ----------------
@app.route('/admin/company_rounds/upload/<int:company_id>/<int:round_number>', methods=['POST'])
def admin_upload_round(company_id, round_number):

    if 'file' not in request.files:
        flash("No file uploaded", "danger")
        return redirect(request.referrer)

    file = request.files['file']

    if file.filename == '':
        flash("No file selected", "danger")
        return redirect(request.referrer)

    if not allowed_file(file.filename, {'csv', 'xls', 'xlsx'}):
        flash("Invalid file type", "danger")
        return redirect(request.referrer)

    # 📥 Read file
    try:
        if file.filename.endswith(('xls', 'xlsx')):
            df = pd.read_excel(file)
        else:
            df = pd.read_csv(file)
    except Exception as e:
        flash(f"File read error: {e}", "danger")
        return redirect(request.referrer)

    # Normalize columns
    df.columns = [c.strip().lower() for c in df.columns]

    REQUIRED = ['registration_number', 'student_name', 'email', 'branch', 'year']
    for col in REQUIRED:
        if col not in df.columns:
            flash(f"Missing column: {col}", "danger")
            return redirect(request.referrer)

    conn = get_connection()
    cursor = conn.cursor()

    try:
        # 🧹 Clean old round data
        cursor.execute("""
            DELETE FROM company_shortlist
            WHERE company_id=%s AND round_number=%s
        """, (company_id, round_number))

        insert_sql = """
            INSERT INTO company_shortlist
            (company_id, round_number, registration_number,
             student_name, email, branch, year, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """

        inserted = 0

        for _, row in df.iterrows():
            cursor.execute(insert_sql, (
                company_id,
                round_number,
                str(row['registration_number']).strip(),
                row['student_name'],
                row['email'],
                row['branch'],
                row['year'],
                row.get('status', 'Passed')
            ))
            inserted += 1

        conn.commit()
        flash(f"✅ Uploaded successfully: {inserted} students", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ DB Error: {e}", "danger")

    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin_company_rounds_view', company_id=company_id))





# ---------------- EDIT STUDENT BY EMAIL ----------------
@app.route('/admin/edit-student-by-email', methods=['GET', 'POST'])
def edit_student_by_email():
    student = None
    if request.method == 'POST':
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            if 'fetch' in request.form:
                email = request.form.get('email', '').strip()
                cursor.execute("SELECT * FROM students WHERE email = %s", (email,))
                student = cursor.fetchone()
                if not student:
                    flash("❌ No student found for that email.", "danger")
            elif 'update' in request.form:
                email = request.form.get('email')
                name = request.form.get('name')
                phone = request.form.get('phone')
                course = request.form.get('course')
                cgpa = request.form.get('cgpa')
                backlogs = request.form.get('backlogs')
                section = request.form.get('section')
                specialization = request.form.get('specialization')
                registration_number = request.form.get('registration_number')

                cursor.execute("""
                    UPDATE students
                    SET name=%s, phone=%s, course=%s, cgpa=%s, backlogs=%s,
                        section=%s, specialization=%s, registration_number=%s
                    WHERE email=%s
                """, (name, phone, course, cgpa, backlogs, section, specialization, registration_number, email))

                conn.commit()  # <-- use this directly
                flash("✅ Student updated successfully.", "success")

                cursor.execute("SELECT * FROM students WHERE email = %s", (email,))
                student = cursor.fetchone()
        finally:
            cursor.close()
            conn.close()

    return render_template('edit_student_by_email.html', student=student)

# ---------------- ADMIN: View all companies ----------------
# ---------------- ADMIN: View all companies ----------------
@app.route('/admin/companies')
def admin_companies():
    selected_role = request.args.get('role')

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if selected_role:
            cursor.execute("""
                SELECT *
                FROM companies
                WHERE LOWER(job_description) LIKE %s
                ORDER BY drive_date DESC
            """, (f"%{selected_role.lower()}%",))
        else:
            cursor.execute("""
                SELECT *
                FROM companies
                ORDER BY drive_date DESC
            """)

        companies = cursor.fetchall()

    finally:
        cursor.close()
        conn.close()

    JOB_ROLES = [
        "Data Analytics",
        "Data Science",
        "Digital Management",
        "SE",
        "Frontend Developer",
        "Backend Developer",
        "Full Stack Developer"
    ]

    return render_template(
        'admin_companies.html',
        companies=companies,
        job_roles=JOB_ROLES,
        selected_role=selected_role
    )



# ---------------- ADMIN: Update eligibility for a company ----------------
@app.route('/admin/update-eligibility/<company_name>', methods=['GET', 'POST'])
def update_eligibility(company_name):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM companies WHERE name=%s", (company_name,))
        company = cursor.fetchone()
        if not company:
            flash("❌ Company not found.", "danger")
            return redirect(url_for('admin_companies'))

        if request.method == 'POST':
            eligibility_10th = request.form.get('tenth', '0')
            eligibility_12th = request.form.get('twelfth', '0')
            eligibility_cgpa = request.form.get('cgpa', '0')
            eligibility_backlogs = request.form.get('backlogs', '0')
            tcsion_active = request.form.get('tcsion_active', 'No')

            eligibility = json.dumps({
                "10th": eligibility_10th,
                "12th": eligibility_12th,
                "cgpa": eligibility_cgpa,
                "backlogs": eligibility_backlogs,
                "tcsion_active": tcsion_active
            })

            cursor.execute("UPDATE companies SET eligibility=%s WHERE name=%s", (eligibility, company_name))
            conn.commit()
            flash("✅ Eligibility updated successfully.", "success")
            return redirect(url_for('admin_companies'))

    finally:
        cursor.close()
        conn.close()

    return render_template('set_eligibility.html', company=company)


# ---------------- ADMIN: Delete company ----------------
@app.route('/admin/delete-company/<int:company_id>', methods=['POST'])
def delete_company(company_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM companies WHERE id=%s", (company_id,))
        cursor.execute("DELETE FROM applications WHERE company_name NOT IN (SELECT name FROM companies)")
        conn.commit()
        flash("✅ Company deleted successfully.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Failed to delete company: {e}", "danger")
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('admin_companies'))

@app.route('/admin/edit-company', methods=['GET', 'POST'])
def edit_company_by_name():
    company_name = request.args.get('name')
    if not company_name:
        flash("❌ No company specified.", "danger")
        return redirect(url_for('admin_companies'))

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM companies WHERE name=%s", (company_name,))
        company = cursor.fetchone()
        if not company:
            flash("❌ Company not found.", "danger")
            return redirect(url_for('admin_companies'))

        if request.method == 'POST':
            # Example: update selection_process or other fields
            selection_process = request.form.get('selection_process', '').split(',')
            cursor.execute(
                "UPDATE companies SET selection_process=%s WHERE name=%s",
                (json.dumps(selection_process), company_name)
            )
            conn.commit()
            flash("✅ Company updated successfully.", "success")
            return redirect(url_for('admin_companies'))

    finally:
        cursor.close()
        conn.close()

    return render_template('edit_company.html', company=company)


# ---------------- ADMIN: ADD COMPANY ----------------
# ---------------- ADMIN: ADD COMPANY ----------------
@app.route('/admin/add-company', methods=['GET', 'POST'])
def admin_add_company():
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            if not name:
                flash("❌ Company name is required", "danger")
                return redirect(url_for('admin_add_company'))

            job_type = request.form.get('job_type')
            package = request.form.get('package')
            location = request.form.get('location')
            drive_date = request.form.get('drive_date')
            job_description = request.form.get('job_description')

            # 🔥 FIX IS HERE
            selection_process = request.form.getlist('selection_process[]')
            selection_process = [s.strip() for s in selection_process if s.strip()]

            nomination_form = request.form.get('nomination_form')

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO companies
                (name, job_description, job_type, package,
                 drive_date, location, selection_process, nomination_form)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                name,
                job_description,
                job_type,
                package,
                drive_date,
                location,
                json.dumps(selection_process),
                nomination_form
            ))

            cursor.execute("""
                SELECT registration_number, name, cgpa, backlogs, section, specialization
                FROM students
            """)
            students = cursor.fetchall()

            for reg_no, student_name, cgpa, backlogs, section, specialization in students:
                cursor.execute("""
                    INSERT INTO applications
                    (registration_number, student_name, cgpa, backlogs,
                     company_name, section, specialization, eligible, applied)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'No','No')
                """, (
                    reg_no,
                    student_name,
                    cgpa,
                    backlogs,
                    name,
                    section,
                    specialization
                ))

            conn.commit()
            cursor.close()
            conn.close()

            flash("✅ Company added successfully", "success")
            return redirect(url_for('admin_companies'))

        except Exception as e:
            print("ADD COMPANY ERROR:", e)
            flash(f"❌ Error adding company: {e}", "danger")
            return redirect(url_for('admin_add_company'))

    return render_template('add_company.html')


@app.route('/admin/set-eligibility/<int:company_id>', methods=['GET', 'POST'])
def set_eligibility(company_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM companies WHERE id=%s", (company_id,))
    company = cursor.fetchone()

    if request.method == 'POST':
        min_cgpa = float(request.form.get('cgpa', 0))
        max_backlogs = int(request.form.get('backlogs', 0))

        eligibility_json = json.dumps({
            "cgpa": min_cgpa,
            "backlogs": max_backlogs
        })

        # Save criteria
        cursor.execute(
            "UPDATE companies SET eligibility=%s WHERE id=%s",
            (eligibility_json, company_id)
        )

        # 🔥 Apply eligibility
        cursor.execute("""
            UPDATE applications a
            JOIN students s
              ON a.registration_number = s.registration_number
            SET a.eligible =
                CASE
                    WHEN s.cgpa >= %s AND s.backlogs <= %s
                    THEN 'Yes'
                    ELSE 'No'
                END
            WHERE a.company_name = %s
        """, (min_cgpa, max_backlogs, company['name']))

        conn.commit()
        flash("✅ Eligibility evaluated successfully", "success")
        return redirect(url_for('admin_companies'))

    cursor.close()
    conn.close()
    return render_template("set_eligibility.html", company=company)



# ---------------- ADMIN: upload students (bulk) ----------------
@app.route('/admin/upload-students', methods=['GET', 'POST'])
def upload_students():

    # 🔹 STEP 1: HANDLE GET (OPEN PAGE)
    if request.method == 'GET':
        return render_template('upload_students.html')

    # 🔹 STEP 2: HANDLE POST (UPLOAD FILE)
    if 'file' not in request.files or request.files['file'].filename == '':
        flash("❌ No file uploaded. Please select a CSV or Excel file.", "danger")
        return redirect(url_for('upload_students'))

    file = request.files['file']
    filename = secure_filename(file.filename)

    if not allowed_file(filename, ALLOWED_STUDENT_EXTENSIONS):
        flash("❌ Invalid file type. Only CSV/Excel allowed.", "danger")
        return redirect(url_for('upload_students'))

    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(save_path)

    try:
        result = bulk_add_students(save_path)

        if result.get('failed', 0) == 0:
            flash(
                f"✅ Students added successfully! Inserted: {result.get('inserted', 0)}",
                "success"
            )
        else:
            flash(
                f"⚠️ Inserted: {result.get('inserted', 0)}, Failed: {result.get('failed', 0)}",
                "warning"
            )

    except Exception as e:
        flash(f"❌ Error importing students: {e}", "danger")

    finally:
        if os.path.exists(save_path):
            os.remove(save_path)

    return redirect(url_for('admin_dashboard'))





# --------------------------------------
# ADD SINGLE STUDENT - PAGE
# --------------------------------------
from db_connection import get_cursor, get_connection

@app.route('/admin/add-student', methods=['GET'])
def add_student():
    return render_template('add_student.html')


@app.route('/admin/save-student', methods=['POST'])
def save_student():
    fields = [
        'registration_number', 'name', 'email', 'phone', 'course',
        'section', 'specialization', 'semester', 'marks_10th', 'marks_12th',
        'department', 'cgpa', 'backlogs', 'current_stage', 'status', 'roll_no'
    ]

    data = {field: request.form.get(field) or None for field in fields}

    if not data['registration_number'] or not data['name']:
        flash("❌ Registration Number & Name are required.", "danger")
        return redirect(url_for('add_student'))

    cursor, conn = None, None

    try:
        cursor, conn = get_cursor()

        sql = """
            INSERT INTO students (
                registration_number, name, email, phone, course, section, specialization,
                semester, marks_10th, marks_12th, department, cgpa, backlogs,
                current_stage, status, roll_no
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        cursor.execute(sql, tuple(data.values()))
        conn.commit()

        flash("✅ Student added successfully!", "success")
        return redirect(url_for('admin_dashboard'))

    except mysql.connector.errors.IntegrityError:
        flash("⚠️ Student with this Registration Number already exists.", "warning")
        if conn:
            conn.rollback()
        return redirect(url_for('add_student'))

    except Exception as e:
        flash(f"❌ Error adding student: {str(e)}", "danger")
        if conn:
            conn.rollback()
        return redirect(url_for('add_student'))

    finally:
        try:
            if cursor: cursor.close()
            if conn: conn.close()
        except:
            pass


# ---------------- ADMIN: Add Tutor ----------------
@app.route('/admin/add-tutor', methods=['GET', 'POST'])
def add_tutor():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        program = request.form.get('program')
        semester = request.form.get('semester')
        section = request.form.get('section')
        specialization = request.form.get('specialization')
        strength = request.form.get('strength')

        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO tutors (name, email, program, semester, section, specialization, strength)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (name, email, program, semester, section, specialization, strength))
            conn.commit()
            flash("✅ Tutor added successfully.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"❌ Failed to add tutor: {e}", "danger")
        finally:
            cursor.close()
            conn.close()
        return redirect(url_for('add_tutor'))
    return render_template('add_tutor.html')


# ---------------- TUTOR LOGIN ----------------
@app.route('/tutor/login', methods=['GET', 'POST'])
def tutor_login():
    if request.method == 'POST':
        email = request.form.get('email')
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM tutors WHERE email=%s", (email,))
        tutor = cursor.fetchone()
        cursor.close()
        conn.close()

        if tutor:
            session['tutor_id'] = tutor.get('id')
            session['tutor_email'] = tutor.get('email')
            flash(f"Welcome {tutor['name']}!", "success")
            return redirect(url_for('tutor_dashboard'))
        else:
            flash("Tutor not found.", "danger")
            return redirect(url_for('tutor_login'))

    return render_template('tutor_login.html')



# ---------------- TUTOR DASHBOARD ----------------
@app.route('/tutor/dashboard')
def tutor_dashboard():
    if 'tutor_email' not in session:
        flash("Please login first", "warning")
        return redirect(url_for('tutor_login'))

    tutor_email = session.get('tutor_email')
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM tutors WHERE email=%s", (tutor_email,))
    tutor = cursor.fetchone()

    if not tutor:
        cursor.close()
        conn.close()
        flash("Tutor not found", "danger")
        return redirect(url_for('tutor_login'))

    cursor.execute("""
        SELECT * FROM students
        WHERE section = %s AND specialization = %s
        ORDER BY name ASC
    """, (tutor.get('section'), tutor.get('specialization')))
    students = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template('tutor_dashboard.html', tutor=tutor, students=students)



# ---------------- TUTOR: Show Companies ----------------
@app.route('/tutor/companies')
def tutor_companies():
    if 'tutor_email' not in session:
        return redirect(url_for('tutor_login'))
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM tutors WHERE email=%s", (session.get('tutor_email'),))
    tutor = cursor.fetchone()
    cursor.execute("SELECT * FROM companies ORDER BY drive_date DESC")
    companies = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('tutor_companies.html', tutor=tutor, companies=companies)


# ---------------- TUTOR: Company rounds (show uploaded round files for tutors) ----------------
@app.route('/tutor/company/<int:company_id>/rounds')
def tutor_company_rounds(company_id):
    if 'tutor_email' not in session:
        flash("⚠️ Please login first", "warning")
        return redirect(url_for('tutor_login'))

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch uploaded round files for this company
    cursor.execute("""
        SELECT id, round_number, file_name, file_path, uploaded_at
        FROM uploaded_round_files
        WHERE company_id = %s
        ORDER BY round_number ASC, uploaded_at DESC
    """, (company_id,))
    uploaded_files = cursor.fetchall()

    # Normalize file_path and create a download URL for each file
    for f in uploaded_files:
        raw = (f.get('file_path') or "").replace("\\", "/").lstrip("/")

        # Remove leading 'static/' if accidentally stored
        if raw.startswith("static/"):
            raw = raw[len("static/"):]

        # Store normalized path
        f['file_path'] = raw

        # Create the download URL using the /uploads/<filename> route
        f['download_url'] = url_for('uploaded_file', filename=raw)

    # Fetch company info
    cursor.execute("SELECT * FROM companies WHERE id = %s", (company_id,))
    company = cursor.fetchone()

    cursor.close()
    conn.close()

    # Pass company and files to template
    return render_template(
        "tutor_company_rounds.html",
        company=company,
        uploaded_files=uploaded_files
    )

# ---------------- TUTOR: Download a round file by its DB id ----------------
@app.route("/tutor/download_round_file/<int:file_id>")
def tutor_download_round_file(file_id):
    if 'tutor_email' not in session:
        flash("⚠️ Please login first", "warning")
        return redirect(url_for('tutor_login'))

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM uploaded_round_files WHERE id = %s", (file_id,))
        file_rec = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if not file_rec:
        flash("❌ File record not found.", "danger")
        return redirect(request.referrer or url_for('tutor_companies'))

    # Normalize DB path
    relative_path = (file_rec.get('file_path') or "").replace("\\", "/").lstrip("/")
    if relative_path.startswith("static/"):
        relative_path = relative_path[len("static/"):]

    full_path = os.path.join(app.config['UPLOAD_FOLDER'], relative_path)

    if not os.path.exists(full_path):
        flash("❌ File not found on server.", "danger")
        return redirect(request.referrer or url_for('tutor_company_rounds', company_id=file_rec.get('company_id')))

    directory = os.path.dirname(full_path)
    filename = os.path.basename(full_path)
    return send_from_directory(directory, filename, as_attachment=True)


# ---------------- Serve uploaded file (download) ----------------
# ---------------- Serve uploaded file (download) ----------------
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    # Normalize path
    safe_filename = filename.replace("..", "").replace("\\", "/").lstrip("/")
    
    # Full path on disk
    full_path = os.path.join(app.config['UPLOAD_FOLDER'], safe_filename)
    
    if not os.path.exists(full_path):
        flash("❌ File not found on server.", "danger")
        return redirect(request.referrer or url_for('tutor_companies'))
    
    directory = os.path.dirname(full_path)
    file_name = os.path.basename(full_path)
    
    return send_from_directory(directory, file_name, as_attachment=True)




# ---------------- TUTOR: Update applied status (endpoint required by templates) ----------------
@app.route('/tutor/update-applied/<int:company_id>/<int:student_id>', methods=['POST'])
def tutor_update_applied(company_id, student_id):
    if 'tutor_email' not in session:
        flash("⚠️ Please login first", "warning")
        return redirect(url_for('tutor_login'))

    applied_value = request.form.get('applied', 'No')
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT registration_number, name FROM students WHERE id=%s", (student_id,))
        student = cursor.fetchone()
        cursor.execute("SELECT name FROM companies WHERE id=%s", (company_id,))
        company = cursor.fetchone()
        if not student or not company:
            flash("❌ Invalid student or company", "danger")
            return redirect(url_for('tutor_company_status', company_id=company_id))

        reg_no = student.get('registration_number')
        company_name = company.get('name')

        cursor.execute("SELECT * FROM applications WHERE registration_number=%s AND company_name=%s", (reg_no, company_name))
        record = cursor.fetchone()
        if record:
            cursor.execute("UPDATE applications SET applied=%s WHERE registration_number=%s AND company_name=%s",
                           (applied_value, reg_no, company_name))
        else:
            cursor.execute("INSERT INTO applications (registration_number, student_name, company_name, applied, eligible) VALUES (%s,%s,%s,%s,%s)",
                           (reg_no, student.get('name'), company_name, applied_value, 'No'))
        conn.commit()
        flash("✅ Applied status updated.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error updating applied status: {e}", "danger")
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('tutor_company_status', company_id=company_id))


# ---------------- TUTOR: Company status (per tutor's section & specialization) ----------------
@app.route('/tutor/company/<int:company_id>', methods=['GET'])
def tutor_company_status(company_id):
    if 'tutor_email' not in session:
        flash("⚠️ Please login first!", "warning")
        return redirect(url_for('tutor_login'))
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM tutors WHERE email=%s", (session.get('tutor_email'),))
    tutor = cursor.fetchone()
    if not tutor:
        cursor.close()
        conn.close()
        flash("Tutor not found", "danger")
        return redirect(url_for('tutor_login'))
    cursor.execute("SELECT * FROM companies WHERE id=%s", (company_id,))
    company = cursor.fetchone()
    if not company:
        cursor.close()
        conn.close()
        flash("Company not found", "danger")
        return redirect(url_for('tutor_companies'))

    sql = """
        SELECT
            s.id AS student_id,
            s.registration_number,
            s.name,
            s.email,
            s.cgpa,
            s.backlogs,
            COALESCE(a.applied, 'No') AS applied,
            COALESCE(a.eligible, 'No') AS eligible
        FROM students s
        LEFT JOIN applications a
          ON a.registration_number = s.registration_number
          AND a.company_name = %s
        WHERE s.section = %s AND s.specialization = %s
        ORDER BY s.name ASC
    """
    cursor.execute(sql, (company['name'], tutor.get('section'), tutor.get('specialization')))
    rows = cursor.fetchall()

    students = []
    counts = {'total': 0, 'eligible': 0, 'not_eligible': 0, 'applied': 0, 'not_applied': 0}
    for r in rows:
        counts['total'] += 1
        applied = r.get('applied') or 'No'
        eligible = r.get('eligible') or 'No'
        if eligible == 'Yes':
            counts['eligible'] += 1
        else:
            counts['not_eligible'] += 1
        if applied == 'Yes':
            counts['applied'] += 1
        else:
            counts['not_applied'] += 1

        if applied == 'Yes' and eligible == 'Yes':
            status = "Applied — Eligible"
        elif applied == 'Yes' and eligible != 'Yes':
            status = "Applied — Not Eligible"
        elif applied != 'Yes' and eligible == 'Yes':
            status = "Eligible — Not Applied"
        else:
            status = "Not Applied"
        r['application_status'] = status
        students.append(r)

    class_strength = tutor.get('strength')

    cursor.close()
    conn.close()

    stats = {
        'total_students': counts['total'],
        'eligible_students': counts['eligible'],
        'not_eligible_students': counts['not_eligible'],
        'applied_students': counts['applied'],
        'not_applied_students': counts['not_applied'],
        'class_strength': class_strength
    }

    return render_template('tutor_company_status.html', tutor=tutor, company=company, students=students, stats=stats)

@app.route('/student/signup', methods=['GET', 'POST'])
def student_signup():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        confirm = request.form.get('confirm_password', '').strip()

        if not email or not password or not confirm:
            flash("All fields are required", "danger")
            return redirect(url_for('student_signup'))

        if password != confirm:
            flash("Passwords do not match", "danger")
            return redirect(url_for('student_signup'))

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # student must exist
        cursor.execute("SELECT * FROM students WHERE email=%s", (email,))
        student = cursor.fetchone()

        if not student:
            flash("Email not found in student records", "danger")
            cursor.close()
            conn.close()
            return redirect(url_for('student_signup'))

        # already registered
        cursor.execute("SELECT * FROM student_auth WHERE email=%s", (email,))
        if cursor.fetchone():
            flash("Account already exists. Please login.", "warning")
            cursor.close()
            conn.close()
            return redirect(url_for('student_login'))

        cursor.execute(
            "INSERT INTO student_auth (email, password) VALUES (%s,%s)",
            (email, password)
        )

        conn.commit()
        cursor.close()
        conn.close()

        flash("Signup successful. Please login.", "success")
        return redirect(url_for('student_login'))

    return render_template('student_signup.html')



@app.route('/student/login', methods=['GET', 'POST'])
def student_login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        if not email or not password:
            flash("Email and password are required", "danger")
            return redirect(url_for('student_login'))

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT 
                s.registration_number,
                s.name,
                s.email
            FROM student_auth a
            JOIN students s ON a.email = s.email
            WHERE a.email = %s AND a.password = %s
        """, (email, password))

        student = cursor.fetchone()
        cursor.close()
        conn.close()

        if student:
            session.clear()   # 🔥 prevents old session conflicts
            session['student_email'] = student['email']
            session['student_reg'] = student['registration_number']
            session['student_name'] = student['name']

            flash("Login successful", "success")
            return redirect(url_for('student_dashboard'))
        else:
            flash("Invalid email or password", "danger")
            return redirect(url_for('student_login'))

    return render_template('student_login.html')



@app.route('/student/dashboard')
def student_dashboard():
    # 🔐 Login check
    if 'student_email' not in session:
        flash("Please login to continue", "warning")
        return redirect(url_for('student_login'))

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM students WHERE email = %s",
        (session['student_email'],)
    )
    student = cursor.fetchone()

    cursor.close()
    conn.close()

    # ❌ If student record not found
    if not student:
        session.clear()
        flash("Student record not found. Please contact admin.", "danger")
        return redirect(url_for('student_login'))

    # ✅ Success
    return render_template(
        'student_dashboard.html',
        student=student
    )
    
@app.route('/student/logout')
def student_logout():
    session.clear()
    flash("Logged out successfully", "success")
    return redirect(url_for('student_login'))



import json

@app.route('/student/companies')
def student_companies():
    if 'student_reg' not in session:
        flash("Please login to continue", "warning")
        return redirect(url_for('student_login'))

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            c.id AS company_id,
            c.name AS company_name,
            c.job_description,
            c.selection_process,
            c.job_type,
            c.package,
            c.location,
            c.drive_date,
            c.nomination_form,
            a.eligible,
            a.applied
        FROM applications a
        JOIN companies c
          ON a.company_name = c.name
        WHERE a.registration_number = %s
        ORDER BY c.drive_date DESC
    """, (session['student_reg'],))

    companies = cursor.fetchall()
    cursor.close()
    conn.close()

    # 🔥 PARSE selection_process HERE (NOT IN JINJA)
    for c in companies:
        sp = c.get('selection_process')
        if sp:
            try:
                parsed = json.loads(sp)
                if isinstance(parsed, list):
                    c['selection_process_list'] = parsed
                else:
                    c['selection_process_list'] = [sp]
            except Exception:
                # fallback for comma separated text
                c['selection_process_list'] = [
                    x.strip() for x in sp.split(',') if x.strip()
                ]
        else:
            c['selection_process_list'] = []

    return render_template(
        'student_companies.html',
        companies=companies
    )



@app.route('/student/apply/<company_name>', methods=['POST'])
def student_apply(company_name):
    if 'student_reg' not in session:
        return redirect(url_for('student_login'))

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE applications
        SET applied='Yes'
        WHERE registration_number=%s
          AND company_name=%s
          AND eligible='Yes'
    """, (session['student_reg'], company_name))

    conn.commit()
    cursor.close()
    conn.close()

    flash("Applied successfully", "success")
    return redirect(url_for('student_companies'))



# ---------------- MAIN ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
from werkzeug.middleware.proxy_fix import ProxyFix

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config["PREFERRED_URL_SCHEME"] = "https"

