import socketio
import asyncio
import time

sio = socketio.AsyncClient()

@sio.event
async def connect():
    print("[TEST] Connected to server successfully!")

@sio.event
async def disconnect():
    print("[TEST] Disconnected from server.")

@sio.event
async def workout_started(data):
    print(f"[TEST] Workout started event received: {data}")

@sio.event
async def metrics_update(data):
    print(f"[TEST] Metrics update: Reps={data['rep_count']}, State={data['state']}, FormScore={data['form_score']}, Active KneeAngle={data['angles']['knee']}°")
    if data['rep_completed']:
        print(f"[TEST] Rep completed notification received: {data['latest_rep']}")

@sio.event
async def workout_ended(data):
    print(f"[TEST] Workout ended event received!")
    print(f"[TEST] Total Reps: {data['rep_count']}")
    print(f"[TEST] Avg Form Score: {data['avg_form_score']}%")
    print(f"[TEST] Report Markdown:\n{data['report'][:300]}...\n")

async def run_test():
    print("[TEST] Connecting to Socket.IO server at http://localhost:8000...")
    try:
        await sio.connect("http://localhost:8000", transports=['websocket'])
    except Exception as e:
        print(f"[TEST] Connection failed: {e}. Make sure the server is running.")
        return

    # Start workout
    print("[TEST] Emitting start_workout for squat...")
    await sio.emit("start_workout", {"exercise": "squat"})
    await asyncio.sleep(0.5)

    # Stream 65 simulated frames (to cross FSM boundaries: UP -> DOWNGOING -> DOWN -> UPGOING -> UP)
    # The FSM tracks angles. Our mock generator cycles angle based on frame index.
    # A cycle has 60 frames. 65 frames will take it deep into the DOWN state and back up, triggering 1 rep.
    print("[TEST] Streaming 65 frames with simulation mode enabled...")
    for i in range(65):
        await sio.emit("stream_frame", {"use_simulation": True, "frame": None})
        await asyncio.sleep(0.05) # 50ms tick rate

    # Wait for FSM processing
    await asyncio.sleep(0.5)

    # End workout
    print("[TEST] Emitting end_workout...")
    await sio.emit("end_workout")
    await asyncio.sleep(1.0)

    print("[TEST] Closing connection...")
    await sio.disconnect()

if __name__ == "__main__":
    asyncio.run(run_test())
