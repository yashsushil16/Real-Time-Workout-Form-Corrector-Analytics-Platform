import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gym_corrector.db")

def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Create sessions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        exercise TEXT NOT NULL,
        rep_count INTEGER DEFAULT 0,
        avg_tempo REAL DEFAULT 0.0,
        avg_form_score REAL DEFAULT 0.0,
        analyst_feedback TEXT
    )
    """)
    
    # Create reps table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER,
        rep_number INTEGER NOT NULL,
        duration REAL NOT NULL,
        min_angle REAL NOT NULL,
        max_angle REAL NOT NULL,
        form_score REAL NOT NULL,
        feedback TEXT,
        FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
    )
    """)
    
    conn.commit()
    conn.close()

def create_session(exercise):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO sessions (exercise) VALUES (?)",
        (exercise,)
    )
    session_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return session_id

def log_rep(session_id, rep_number, duration, min_angle, max_angle, form_score, feedback):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reps (session_id, rep_number, duration, min_angle, max_angle, form_score, feedback)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (session_id, rep_number, duration, min_angle, max_angle, form_score, feedback))
    conn.commit()
    conn.close()

def finalize_session(session_id, rep_count, avg_tempo, avg_form_score, analyst_feedback):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE sessions
        SET rep_count = ?, avg_tempo = ?, avg_form_score = ?, analyst_feedback = ?
        WHERE id = ?
    """, (rep_count, avg_tempo, avg_form_score, analyst_feedback, session_id))
    conn.commit()
    conn.close()

def get_all_sessions():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sessions ORDER BY date DESC")
    rows = cursor.fetchall()
    
    sessions = []
    for r in rows:
        session = dict(r)
        # Fetch reps for this session
        cursor.execute("SELECT * FROM reps WHERE session_id = ? ORDER BY rep_number ASC", (r['id'],))
        reps = [dict(rep_row) for rep_row in cursor.fetchall()]
        session['reps'] = reps
        sessions.append(session)
        
    conn.close()
    return sessions

def get_session_details(session_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    session = dict(row)
    cursor.execute("SELECT * FROM reps WHERE session_id = ? ORDER BY rep_number ASC", (session_id,))
    session['reps'] = [dict(rep_row) for rep_row in cursor.fetchall()]
    conn.close()
    return session

# Initialize DB on import
init_db()
