import numpy as np

class CoachAgent:
    """
    Coach Agent: Provides real-time audio/textual form feedback based on active joint angles 
    and 3D coordinates.
    """
    def __init__(self):
        pass
        
    def analyze_squat(self, landmarks, knee_angle, hip_angle, state):
        """
        Analyzes squat form.
        Landmarks are indexed 0-32 (MediaPipe layout).
        Knee joints: 23 (Hip), 25 (Knee), 27 (Ankle)
        """
        feedback = []
        form_score = 100
        
        # Check if landmarks are loaded
        if not landmarks or len(landmarks) < 33:
            return ["Detecting body..."], 100
            
        # 1. Knee Caving (Valgus Collapse)
        lh = landmarks[23]
        rh = landmarks[24]
        lk = landmarks[25]
        rk = landmarks[26]
        la = landmarks[27]
        ra = landmarks[28]
        
        hip_width = abs(lh['x'] - rh['x'])
        knee_width = abs(lk['x'] - rk['x'])
        
        if knee_width < 0.85 * hip_width and state in ["DOWNGOING", "DOWN", "UPGOING"]:
            feedback.append("Push your knees OUT!")
            form_score -= 20
            
        # 2. Forward Lean (chest posture)
        ls = landmarks[11]
        rs = landmarks[12]
        mid_shoulder_x = (ls['x'] + rs['x']) / 2
        mid_shoulder_y = (ls['y'] + rs['y']) / 2
        mid_hip_x = (lh['x'] + rh['x']) / 2
        mid_hip_y = (lh['y'] + rh['y']) / 2
        
        torso_dx = mid_shoulder_x - mid_hip_x
        torso_dy = mid_shoulder_y - mid_hip_y
        
        torso_angle = np.degrees(np.arctan2(abs(torso_dy), abs(torso_dx))) if torso_dy != 0 else 90.0
        
        if torso_angle < 60.0 and state in ["DOWNGOING", "DOWN"]:
            feedback.append("Keep your chest UP! Avoid leaning too forward.")
            form_score -= 15

        # 3. Squat Depth
        if state == "DOWN" and knee_angle > 100.0:
            feedback.append("Go deeper! Try to get thighs parallel to ground.")
            form_score -= 15
            
        if not feedback:
            if state == "DOWN":
                feedback.append("Excellent depth! Drive up.")
            elif state == "UP":
                feedback.append("Form looks solid. Ready for next rep.")
            else:
                feedback.append("Keep going, control the descent.")
                
        return feedback, max(30, form_score)

    def analyze_bicep_curl(self, landmarks, elbow_angle, state):
        """
        Analyzes bicep curl form.
        Shoulder: 11/12, Elbow: 13/14, Wrist: 15/16
        """
        feedback = []
        form_score = 100
        
        if not landmarks or len(landmarks) < 33:
            return ["Detecting body..."], 100
            
        ls = landmarks[11]
        le = landmarks[13]
        rs = landmarks[12]
        re = landmarks[14]
        
        # Horizontal elbow drift
        l_drift = abs(le['x'] - ls['x'])
        r_drift = abs(re['x'] - rs['x'])
        
        if max(l_drift, r_drift) > 0.15:
            feedback.append("Lock your elbows! Avoid swinging forward.")
            form_score -= 20
            
        # Check range of motion
        if state == "DOWN" and elbow_angle < 150.0:
            feedback.append("Extend fully at the bottom!")
            form_score -= 15
        elif state == "UP" and elbow_angle > 65.0:
            feedback.append("Squeeze your biceps at the top!")
            form_score -= 10
            
        if not feedback:
            if state == "UP":
                feedback.append("Great squeeze! Control the descent.")
            elif state == "DOWN":
                feedback.append("Good extension. Begin the curl.")
            else:
                feedback.append("Good tempo, keep it controlled.")
                
        return feedback, max(30, form_score)

    def analyze_bench_press(self, landmarks, elbow_angle, state):
        """
        Analyzes bench press form.
        Tracks torso stability and elbow angle.
        Shoulder: 11/12, Elbow: 13/14, Wrist: 15/16
        """
        feedback = []
        form_score = 100
        
        if not landmarks or len(landmarks) < 33:
            return ["Detecting body..."], 100
        
        ls = landmarks[11]
        rs = landmarks[12]
        le = landmarks[13]
        re = landmarks[14]
        lw = landmarks[15]
        rw = landmarks[16]
        
        # 1. Check elbow flare: elbows should not splay too wide
        # Measure horizontal distance of elbows vs shoulders
        l_flare = abs(le['x'] - ls['x'])
        r_flare = abs(re['x'] - rs['x'])
        shoulder_width = abs(ls['x'] - rs['x'])
        
        if max(l_flare, r_flare) > shoulder_width * 0.8 and state in ["DOWNGOING", "DOWN"]:
            feedback.append("Tuck your elbows! Avoid excessive flare.")
            form_score -= 20
            
        # 2. Check wrist alignment over elbows (lateral deviation)
        l_wrist_drift = abs(lw['x'] - le['x'])
        r_wrist_drift = abs(rw['x'] - re['x'])
        
        if max(l_wrist_drift, r_wrist_drift) > 0.12:
            feedback.append("Keep wrists stacked over elbows.")
            form_score -= 10
        
        # 3. Range of motion check
        if state == "DOWN" and elbow_angle > 110.0:
            feedback.append("Lower the bar more — chest touch depth!")
            form_score -= 15
        elif state == "UP" and elbow_angle < 140.0:
            feedback.append("Lock out fully at the top!")
            form_score -= 10
        
        if not feedback:
            if state == "DOWN":
                feedback.append("Good depth! Press up with power.")
            elif state == "UP":
                feedback.append("Solid lockout. Control the descent.")
            else:
                feedback.append("Smooth tempo, keep it controlled.")
        
        return feedback, max(30, form_score)

    def analyze_lateral_raise(self, landmarks, shoulder_angle, state):
        """
        Analyzes lateral raise form.
        Tracks shoulder abduction: Hip -> Shoulder -> Wrist
        """
        feedback = []
        form_score = 100
        
        if not landmarks or len(landmarks) < 33:
            return ["Detecting body..."], 100
        
        ls = landmarks[11]
        rs = landmarks[12]
        le = landmarks[13]
        re = landmarks[14]
        
        # 1. Check for shrugging (shoulders rising toward ears)
        # Nose is landmark 0; if shoulder y approaches nose y, they're shrugging
        nose = landmarks[0]
        avg_shoulder_y = (ls['y'] + rs['y']) / 2
        shrug_ratio = abs(nose['y'] - avg_shoulder_y)
        
        if shrug_ratio < 0.08 and state in ["UPGOING", "UP"]:
            feedback.append("Don't shrug! Keep shoulders down and relaxed.")
            form_score -= 20
            
        # 2. Check elbow bend (arms should be mostly straight, slight bend ok)
        l_elbow_angle = np.degrees(np.arccos(np.clip(
            np.dot(
                np.array([ls['x'] - le['x'], ls['y'] - le['y']]),
                np.array([landmarks[15]['x'] - le['x'], landmarks[15]['y'] - le['y']])
            ) / (
                np.linalg.norm([ls['x'] - le['x'], ls['y'] - le['y']]) *
                np.linalg.norm([landmarks[15]['x'] - le['x'], landmarks[15]['y'] - le['y']]) + 1e-6
            ), -1, 1
        )))
        
        if l_elbow_angle < 140.0 and state in ["UPGOING", "UP"]:
            feedback.append("Keep arms straighter — avoid bending elbows too much.")
            form_score -= 15
            
        # 3. Range check
        if state == "UP" and shoulder_angle is not None and shoulder_angle > 80.0:
            feedback.append("Raise arms higher — aim for shoulder height.")
            form_score -= 10
        
        if not feedback:
            if state == "UP":
                feedback.append("Great height! Lower with control.")
            elif state == "DOWN":
                feedback.append("Good starting position. Raise smoothly.")
            else:
                feedback.append("Controlled movement, nice tempo.")
        
        return feedback, max(30, form_score)

    def analyze_pull_up(self, landmarks, elbow_angle, state):
        """
        Analyzes pull-up form.
        Tracks elbow flexion and torso bending.
        """
        feedback = []
        form_score = 100
        
        if not landmarks or len(landmarks) < 33:
            return ["Detecting body..."], 100
        
        ls = landmarks[11]
        rs = landmarks[12]
        lh = landmarks[23]
        rh = landmarks[24]
        
        # 1. Check torso swing / kipping
        mid_shoulder_x = (ls['x'] + rs['x']) / 2
        mid_hip_x = (lh['x'] + rh['x']) / 2
        torso_lean = abs(mid_shoulder_x - mid_hip_x)
        
        if torso_lean > 0.1 and state in ["UPGOING", "UP"]:
            feedback.append("Stop swinging! Keep your body straight — no kipping.")
            form_score -= 25
            
        # 2. Check chin height relative to hands (landmark 15/16)
        nose = landmarks[0]
        avg_wrist_y = (landmarks[15]['y'] + landmarks[16]['y']) / 2
        
        if state == "UP" and nose['y'] > avg_wrist_y:
            feedback.append("Pull higher — get your chin above the bar!")
            form_score -= 15
        
        # 3. Full extension at bottom
        if state == "DOWN" and elbow_angle < 140.0:
            feedback.append("Extend fully at the bottom — dead hang.")
            form_score -= 10
        
        if not feedback:
            if state == "UP":
                feedback.append("Great pull! Lower with control.")
            elif state == "DOWN":
                feedback.append("Full extension. Pull up strong!")
            else:
                feedback.append("Controlled movement, keep it up.")
        
        return feedback, max(30, form_score)

    def check_form(self, exercise, landmarks, knee_angle, elbow_angle, state, shoulder_angle=None):
        ex = exercise.lower()
        if ex == "squat":
            return self.analyze_squat(landmarks, knee_angle, None, state)
        elif ex == "bicep_curl":
            return self.analyze_bicep_curl(landmarks, elbow_angle, state)
        elif ex == "bench_press":
            return self.analyze_bench_press(landmarks, elbow_angle, state)
        elif ex == "lateral_raise":
            return self.analyze_lateral_raise(landmarks, shoulder_angle or 180.0, state)
        elif ex == "pull_up":
            return self.analyze_pull_up(landmarks, elbow_angle, state)
        else:
            return self.analyze_bicep_curl(landmarks, elbow_angle, state)


class AnalystAgent:
    """
    Analyst Sub-Agent: Synthesizes session metrics and compiles a post-workout report card.
    """
    def __init__(self):
        pass
        
    def generate_report(self, exercise, reps):
        """
        Generates a post-workout report in Markdown.
        'reps' is a list of dictionaries with keys:
        - rep_number: int
        - duration: float
        - min_angle: float
        - max_angle: float
        - form_score: float
        - feedback: str
        """
        if not reps:
            return "### Post-Workout Report\nNo reps were recorded in this session. Keep pushing next time!"
            
        total_reps = len(reps)
        avg_score = np.mean([r['form_score'] for r in reps])
        avg_duration = np.mean([r['duration'] for r in reps])
        durations = [r['duration'] for r in reps]
        
        # Consistency is calculated as 1.0 - (standard deviation / average duration)
        std_dur = np.std(durations) if len(durations) > 1 else 0.0
        consistency_score = max(0.0, min(1.0, 1.0 - (std_dur / avg_duration if avg_duration > 0 else 0.0)))
        
        # Grade Assignment
        if avg_score >= 90:
            grade = "A+"
            grade_color = "#5A9E6F"
            summary = "Masterful form! You showed near-perfect joint mechanics and pacing. Keep this exact technique."
        elif avg_score >= 80:
            grade = "A"
            grade_color = "#81A6C6"
            summary = "Excellent effort. Your movement path is clean, with only minor form drifts. A solid session!"
        elif avg_score >= 70:
            grade = "B"
            grade_color = "#C4813D"
            summary = "Good job, but there's room for improvement. Pay attention to warnings like range of motion and joint stability."
        elif avg_score >= 60:
            grade = "C"
            grade_color = "#D2C4B4"
            summary = "Sub-optimal mechanics. Focus on lifting lighter weights to perfect your movement path first."
        else:
            grade = "D"
            grade_color = "#C05050"
            summary = "High risk of injury detected. Please slow down and focus heavily on joint alignment and locking your posture."

        ex_display = exercise.replace('_', ' ').title()

        # Compile markdown report
        report = f"""# Workout Analytics Report Card
**Exercise:** {ex_display}  
**Total Repetitions:** {total_reps}  
**Overall Grade:** <span style="color: {grade_color}; font-weight: bold; font-size: 24px;">{grade}</span> ({avg_score:.1f}% average form score)  

---

### Core Performance Metrics

| Metric | Session Value | Ideal Benchmark | Evaluation |
| :--- | :---: | :---: | :--- |
| **Pacing / Tempo** | {avg_duration:.2f} seconds | 2.5 - 3.5 seconds | {"Controlled" if 2.0 <= avg_duration <= 4.0 else "Too Fast" if avg_duration < 2.0 else "Too Slow"} |
| **Tempo Consistency** | {consistency_score:.1%} | > 85.0% | {"Excellent rhythm" if consistency_score >= 0.85 else "Needs steadier rhythm"} |
| **Average Form Quality** | {avg_score:.1f}% | > 80.0% | {"Pass (Excellent)" if avg_score >= 80 else "Needs Adjustment" if avg_score >= 60 else "High Injury Risk"} |

---

### Joint Trajectory Analysis
"""
        
        ex_lower = exercise.lower()
        min_angles = [r['min_angle'] for r in reps]
        max_angles = [r['max_angle'] for r in reps]
        avg_min_angle = np.mean(min_angles)
        avg_max_angle = np.mean(max_angles)

        if ex_lower == "squat":
            report += f"""- **Hip & Knee Hinge:** Your average knee flexion angle at the bottom of the squat was **{avg_min_angle:.1f}°**.
- **Depth Benchmark:** Target depth is $< 100°$. {"You consistently hit proper depth, engaging your glutes and hamstrings." if avg_min_angle <= 100 else "You did not go deep enough on average. Try lowering your hips until they are parallel to your knees."}
- **Torso Stability:** Evaluated via vertical alignment. {"Torso remained upright, preserving lumber spine integrity." if avg_score > 75 else "Significant torso leaning observed. Focus on core activation to protect your lower back."}
"""
        elif ex_lower == "bicep_curl":
            report += f"""- **Extension & Flexion:** Average elbow extension was **{avg_max_angle:.1f}°** and average flexion was **{avg_min_angle:.1f}°**.
- **Range of Motion:** Target extension $> 150°$ and flexion $< 60°$. {"You achieved a complete and healthy range of motion." if (avg_max_angle >= 145 and avg_min_angle <= 65) else "You did not complete the full range of motion. Focus on extending your arm fully at the bottom and squeezing at the top."}
- **Shoulder Stability:** {"Elbows remained locked at your sides, preventing momentum cheating." if avg_score > 75 else "Significant arm swinging detected. Keep your shoulders relaxed and elbows stationary."}
"""
        elif ex_lower == "bench_press":
            report += f"""- **Elbow Flexion:** Average elbow angle at the bottom was **{avg_min_angle:.1f}°** and at lockout was **{avg_max_angle:.1f}°**.
- **Range of Motion:** Target bottom angle $< 100°$ and lockout $> 145°$. {"Full range achieved — great bar path." if (avg_min_angle <= 100 and avg_max_angle >= 140) else "Incomplete range of motion. Lower the bar closer to your chest and lock out fully."}
- **Elbow Tuck:** {"Good elbow positioning — protected your shoulders." if avg_score > 75 else "Excessive elbow flare detected. Tuck elbows to 45° to protect shoulder joints."}
"""
        elif ex_lower == "lateral_raise":
            report += f"""- **Shoulder Abduction:** Average shoulder angle at the top was **{avg_min_angle:.1f}°** and at rest was **{avg_max_angle:.1f}°**.
- **Height Target:** Arms should reach shoulder height (angle $< 60°$). {"You consistently reached proper height." if avg_min_angle <= 70 else "Raise your arms higher — aim for shoulder level."}
- **Shrugging:** {"Shoulders stayed relaxed and depressed." if avg_score > 75 else "Shrugging detected — keep shoulders down and engage your deltoids."}
"""
        elif ex_lower == "pull_up":
            report += f"""- **Elbow Flexion:** Average top angle was **{avg_min_angle:.1f}°** and bottom hang was **{avg_max_angle:.1f}°**.
- **Range of Motion:** Target top angle $< 90°$ and full extension $> 145°$. {"Complete range of motion achieved." if (avg_min_angle <= 95 and avg_max_angle >= 140) else "Improve your range — pull higher and extend fully at the bottom."}
- **Body Control:** {"Clean strict reps with minimal swing." if avg_score > 75 else "Excessive kipping or swinging detected. Focus on strict form."}
"""

        # Identify major issues across reps
        issues = []
        for r in reps:
            fb = r.get('feedback', '')
            if "Push" in fb or "caves" in fb.lower() or "knees" in fb.lower():
                issues.append("Knee collapse/wobbling")
            if "chest" in fb.lower() or "lean" in fb.lower():
                issues.append("Excessive forward trunk lean")
            if "Lock" in fb or "swinging" in fb.lower() or "elbows" in fb.lower():
                issues.append("Elbow drift / momentum swing")
            if "Extend" in fb.lower():
                issues.append("Incomplete extension (half-reps at bottom)")
            if "Squeeze" in fb.lower():
                issues.append("Incomplete flexion (half-reps at top)")
            if "Tuck" in fb:
                issues.append("Excessive elbow flare")
            if "shrug" in fb.lower():
                issues.append("Shoulder shrugging")
            if "kip" in fb.lower() or "swing" in fb.lower():
                issues.append("Body swinging / kipping")
                
        unique_issues = list(set(issues))
        
        report += "\n### Posture & Alignment Breakdown\n"
        if not unique_issues:
            report += "✔ **No major form deviations detected.** Your kinetic chain remained stable and aligned throughout all reps. Outstanding work!\n"
        else:
            report += "⚠️ **Form Deviations Detected:**\n"
            for issue in unique_issues:
                report += f"- *{issue}*\n"
            report += "\n**Correction Advice:** Next time, slow down your speed by 10%. Focus on the mind-muscle connection and keep the core braced.\n"

        report += f"""
### Analyst Coach's Note
> "{summary} Focus on consistency and breathing. Looking forward to your next session!"
"""
        return report
