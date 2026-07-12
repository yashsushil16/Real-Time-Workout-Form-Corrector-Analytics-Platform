import socketio
import fastapi
from fastapi.middleware.cors import CORSMiddleware
import time
import os
import uvicorn
import cv2

from .database import create_session, log_rep, finalize_session, get_all_sessions, get_session_details
from .cv_engine import decode_base64_image, calculate_angle, WorkoutFSM, PoseTracker
from .agents import CoachAgent, AnalystAgent

# Initialize FastAPI app
app = fastapi.FastAPI(title="Gym Form Corrector API")

# Add CORS Middleware to support local react native / expo fetches
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Socket.IO AsyncServer
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)

# Initialize global tracking utilities
pose_tracker = PoseTracker()
coach_agent = CoachAgent()
analyst_agent = AnalystAgent()

# Global tracking dictionary for room sessions: room_id -> session_dict
room_sessions = {}

@app.get("/ip")
async def get_ip():
    """Dynamically detects the server's local network IP address."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return {"ip": ip}

@app.get("/history")
async def get_history():
    """Fetches list of all previous workout sessions from database."""
    try:
        sessions = get_all_sessions()
        return {"sessions": sessions}
    except Exception as e:
        return {"error": str(e)}, 500

@app.get("/history/{session_id}")
async def get_details(session_id: int):
    """Fetches details and rep metrics for a single workout session."""
    session = get_session_details(session_id)
    if not session:
        return {"error": "Session not found"}, 404
    return {"session": session}

# Socket.IO Event Handlers
@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")
    await sio.save_session(sid, {
        "room": sid,
        "role": "desktop"
    })

@sio.event
async def disconnect(sid):
    print(f"Client disconnected: {sid}")
    client_session = await sio.get_session(sid)
    if client_session:
        room = client_session.get("room")
        role = client_session.get("role")
        if room:
            await sio.emit("peer_disconnected", {"role": role, "sid": sid}, room=room)

@sio.event
async def pair(sid, data):
    """
    Pairs a client with a room.
    data: {"room": "desktop_socket_id", "role": "phone" | "desktop"}
    """
    room = data.get("room")
    role = data.get("role", "phone")
    if room:
        print(f"Client {sid} pairing as {role} for room {room}")
        await sio.enter_room(sid, room)
        
        session = await sio.get_session(sid)
        if not session:
            session = {}
        session["room"] = room
        session["role"] = role
        await sio.save_session(sid, session)
        
        await sio.emit("peer_connected", {"role": role, "sid": sid}, room=room)
        if role == "phone":
            await sio.emit("peer_connected", {"role": "desktop"}, room=sid)

@sio.event
async def start_workout(sid, data):
    """
    Starts a new workout session for a room.
    data: {"exercise": "squat" | "bicep_curl", "room": "room_id"}
    """
    exercise = data.get("exercise", "squat").lower()
    client_session = await sio.get_session(sid)
    room_id = data.get("room") or (client_session.get("room") if client_session else sid)
    
    print(f"Starting {exercise} session for room {room_id}")
    
    try:
        session_id = create_session(exercise)
        fsm = WorkoutFSM(exercise)
        
        # Reset tracking history to prevent position drift from previous sessions
        pose_tracker.reset()
        
        room_sessions[room_id] = {
            "workout_active": True,
            "exercise": exercise,
            "session_id": session_id,
            "fsm": fsm,
            "reps_logged": [],
            "frame_index": 0
        }
        
        await sio.emit("workout_started", {
            "session_id": session_id,
            "exercise": exercise
        }, room=room_id)
        
    except Exception as e:
        print(f"Error starting workout: {e}")
        await sio.emit("error", {"message": f"Could not create database session: {str(e)}"}, room=sid)

@sio.event
async def stream_frame(sid, data):
    """
    Streams a single image frame, decodes and returns CV metrics.
    data: {
      "frame": "data:image/jpeg;base64,...",
      "use_simulation": bool (force mock simulation for testing/demo)
    }
    """
    client_session = await sio.get_session(sid)
    room_id = client_session.get("room") if client_session else sid
    
    room_session = room_sessions.get(room_id)
    if not room_session or not room_session.get("workout_active"):
        return
        
    exercise = room_session["exercise"]
    session_id = room_session["session_id"]
    fsm = room_session["fsm"]
    frame_index = room_session["frame_index"]
    reps_logged = room_session["reps_logged"]
    
    use_simulation = data.get("use_simulation", False)
    frame_data = data.get("frame")
    
    landmarks = None
    knee_angle = None
    elbow_angle = None
    
    # 1. Processing frame (either CV model or simulator fallback)
    if not use_simulation and frame_data:
        try:
            image = decode_base64_image(frame_data)
            if image is not None:
                # Resize to standard processing shape for CPU speedup
                h, w, _ = image.shape
                if w > 640:
                    scale = 640.0 / w
                    image = cv2.resize(image, (640, int(h * scale)))
                landmarks = pose_tracker.process_frame(image)
        except Exception as e:
            print(f"Error processing frame: {e}")
            
    # 2. Heuristics fallback / simulation / no person detected
    if landmarks is None:
        if use_simulation:
            # Fallback to simulated pose coordinates to run a clean demo
            landmarks, simulated_angle = pose_tracker.generate_mock_landmarks(exercise, frame_index)
            if exercise == "squat":
                knee_angle = simulated_angle
            else:
                elbow_angle = simulated_angle
            room_session["frame_index"] += 1
        else:
            # Real camera mode: do NOT do mock fallback. Emit warning.
            response_payload = {
                "landmarks": None,
                "angles": {
                    "knee": None,
                    "elbow": None
                },
                "state": fsm.state,
                "rep_count": fsm.rep_count,
                "feedback": ["Adjust camera: No person detected"],
                "form_score": 100,
                "rep_completed": False,
                "latest_rep": None
            }
            await sio.emit("metrics_update", response_payload, room=room_id)
            return
    else:
        # Calculate active joint angles using NumPy vectors (checking both left and right sides)
        shoulder_angle = None
        try:
            if exercise == "squat":
                left_knee = calculate_angle(landmarks[23], landmarks[25], landmarks[27])
                right_knee = calculate_angle(landmarks[24], landmarks[26], landmarks[28])
                knee_angle = min(left_knee, right_knee)
            elif exercise == "bicep_curl":
                left_elbow = calculate_angle(landmarks[11], landmarks[13], landmarks[15])
                right_elbow = calculate_angle(landmarks[12], landmarks[14], landmarks[16])
                elbow_angle = min(left_elbow, right_elbow)
            elif exercise == "bench_press":
                left_elbow = calculate_angle(landmarks[11], landmarks[13], landmarks[15])
                right_elbow = calculate_angle(landmarks[12], landmarks[14], landmarks[16])
                elbow_angle = min(left_elbow, right_elbow)
            elif exercise == "lateral_raise":
                # Shoulder abduction: Hip -> Shoulder -> Wrist
                left_shoulder = calculate_angle(landmarks[23], landmarks[11], landmarks[15])
                right_shoulder = calculate_angle(landmarks[24], landmarks[12], landmarks[16])
                shoulder_angle = min(left_shoulder, right_shoulder)
            elif exercise == "pull_up":
                left_elbow = calculate_angle(landmarks[11], landmarks[13], landmarks[15])
                right_elbow = calculate_angle(landmarks[12], landmarks[14], landmarks[16])
                elbow_angle = min(left_elbow, right_elbow)
        except Exception as e:
            print(f"Error calculating joint angle: {e}")
            
    # Select the active angle for the FSM based on exercise
    if exercise == "squat":
        active_angle = knee_angle
    elif exercise == "lateral_raise":
        active_angle = shoulder_angle
    else:
        active_angle = elbow_angle
    
    if active_angle is None:
        active_angle = 180.0
    
    # 3. Update Finite State Machine (FSM)
    rep_completed, rep_info = fsm.update(active_angle)
    
    # 4. Invoke Coach Agent for dynamic form analysis
    feedback, form_score = coach_agent.check_form(
        exercise, landmarks,
        knee_angle or 180.0,
        elbow_angle or 180.0,
        fsm.state,
        shoulder_angle=shoulder_angle
    )
    
    # 5. Handle completed repetition
    if rep_completed and rep_info:
        # Override baseline score with Coach Agent's qualitative assessment
        rep_info["form_score"] = form_score
        rep_info["feedback"] = ", ".join(feedback)
        
        # Save to SQLite database
        try:
            log_rep(
                session_id=session_id,
                rep_number=rep_info["rep_number"],
                duration=rep_info["duration"],
                min_angle=rep_info["min_angle"],
                max_angle=rep_info["max_angle"],
                form_score=rep_info["form_score"],
                feedback=rep_info["feedback"]
            )
            reps_logged.append(rep_info)
        except Exception as e:
            print(f"Error logging rep to DB: {e}")
            
    # Send metrics update packet to room
    response_payload = {
        "landmarks": landmarks,
        "angles": {
            "knee": round(knee_angle, 1) if knee_angle is not None else None,
            "elbow": round(elbow_angle, 1) if elbow_angle is not None else None,
            "shoulder": round(shoulder_angle, 1) if shoulder_angle is not None else None
        },
        "state": fsm.state,
        "rep_count": fsm.rep_count,
        "feedback": feedback,
        "form_score": form_score,
        "rep_completed": rep_completed,
        "latest_rep": rep_info
    }
    
    await sio.emit("metrics_update", response_payload, room=room_id)

@sio.event
async def end_workout(sid):
    """
    Concludes workout session. Invokes Analyst agent to generate post-workout report card,
    updates database session columns, and sends final report.
    """
    client_session = await sio.get_session(sid)
    room_id = client_session.get("room") if client_session else sid
    
    room_session = room_sessions.get(room_id)
    if not room_session or not room_session.get("workout_active"):
        await sio.emit("error", {"message": "No active workout found"}, room=sid)
        return
        
    exercise = room_session["exercise"]
    session_id = room_session["session_id"]
    fsm = room_session["fsm"]
    reps_logged = room_session["reps_logged"]
    
    print(f"Ending {exercise} workout session {session_id} for room {room_id}")
    
    # Calculate aggregate session averages
    rep_count = fsm.rep_count
    
    avg_tempo = 0.0
    avg_form_score = 0.0
    report_markdown = "No reps completed in this session."
    
    if reps_logged:
        avg_tempo = sum(r["duration"] for r in reps_logged) / len(reps_logged)
        avg_form_score = sum(r["form_score"] for r in reps_logged) / len(reps_logged)
        
        # Invoke Analyst Agent
        try:
            report_markdown = analyst_agent.generate_report(exercise, reps_logged)
        except Exception as e:
            print(f"Error compiling post-workout report: {e}")
            report_markdown = f"Error generating report: {e}"
            
    # Save aggregates in SQLite
    try:
        finalize_session(
            session_id=session_id,
            rep_count=rep_count,
            avg_tempo=round(avg_tempo, 2),
            avg_form_score=round(avg_form_score, 1),
            analyst_feedback=report_markdown
        )
    except Exception as e:
        print(f"Error saving session aggregates to DB: {e}")
        
    # Reset workout state
    if room_id in room_sessions:
        del room_sessions[room_id]
    
    # Emit final workout report card to room
    await sio.emit("workout_ended", {
        "session_id": session_id,
        "rep_count": rep_count,
        "avg_tempo": round(avg_tempo, 2),
        "avg_form_score": round(avg_form_score, 1),
        "report": report_markdown
    }, room=room_id)

if __name__ == "__main__":
    # Resolve paths relative to backend/
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    key_path = os.path.join(base_dir, "key.pem")
    cert_path = os.path.join(base_dir, "cert.pem")
    
    if os.path.exists(key_path) and os.path.exists(cert_path):
        print(f"Starting server with HTTPS (SSL) at https://0.0.0.0:8000")
        uvicorn.run(socket_app, host="0.0.0.0", port=8000, ssl_keyfile=key_path, ssl_certfile=cert_path)
    else:
        print(f"Starting server with HTTP (No SSL) at http://0.0.0.0:8000")
        uvicorn.run(socket_app, host="0.0.0.0", port=8000)
