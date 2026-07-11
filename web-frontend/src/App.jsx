import React, { useState, useEffect, useRef } from 'react';
import { io } from 'socket.io-client';
import QRCode from 'qrcode';
import { 
  Play, 
  Square, 
  Activity, 
  AlertCircle,
  Smartphone,
  CheckCircle
} from 'lucide-react';

const BACKEND_URL = `${window.location.protocol}//${window.location.hostname}:8000`;

const EXERCISES = [
  { key: 'squat', label: 'Squats' },
  { key: 'bicep_curl', label: 'Bicep Curls' },
  { key: 'bench_press', label: 'Bench Press' },
  { key: 'lateral_raise', label: 'Lateral Raises' },
  { key: 'pull_up', label: 'Pull-Ups' },
];

export default function App() {
  // Check role & room from URL query parameters
  const queryParams = new URLSearchParams(window.location.search);
  const isPhone = queryParams.get('role') === 'phone';
  const urlRoom = queryParams.get('room');

  const [roomCode] = useState(() => {
    const queryParams = new URLSearchParams(window.location.search);
    const room = queryParams.get('room');
    return room || Math.random().toString(36).substring(2, 8).toUpperCase();
  });

  const [exercise, setExercise] = useState('squat');
  const [workoutActive, setWorkoutActive] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [isSimulation, setIsSimulation] = useState(false);
  const [peerConnected, setPeerConnected] = useState(false);
  
  // Local network IP address for pairing QR code
  const [localIp, setLocalIp] = useState(typeof __DEV_IP__ !== 'undefined' ? __DEV_IP__ : window.location.hostname);
  const [socketId, setSocketId] = useState('');
  const [qrCodeDataUrl, setQrCodeDataUrl] = useState('');
  
  // Real-time tracking metrics
  const [repCount, setRepCount] = useState(0);
  const [fsmState, setFsmState] = useState('READY');
  const [activeAngle, setActiveAngle] = useState(null);
  const [feedbackList, setFeedbackList] = useState(['Choose an exercise and hit start']);
  const [formScore, setFormScore] = useState(100);
  const [landmarks, setLandmarks] = useState(null);
  const [isPersonDetected, setIsPersonDetected] = useState(true);

  // Modals / Analytics state
  const [showReportModal, setShowReportModal] = useState(false);
  const [modalReportContent, setModalReportContent] = useState('');
  
  // Sessions history
  const [historyList, setHistoryList] = useState([]);

  const socketRef = useRef(null);
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const captureIntervalRef = useRef(null);
  
  // Track if a rep completed for HUD animation
  const [repCompletedTrigger, setRepCompletedTrigger] = useState(false);

  // 1. Fetch backend host IP to construct valid LAN pairing URL
  useEffect(() => {
    fetch(`${BACKEND_URL}/ip`)
      .then(res => res.json())
      .then(data => {
        if (data.ip) setLocalIp(data.ip);
      })
      .catch(err => console.log("Error fetching local IP:", err));
  }, []);

  // 2. Initialize Socket.IO Client connection
  useEffect(() => {
    console.log("Connecting to Socket.IO backend:", BACKEND_URL);
    const socket = io(BACKEND_URL, {
      transports: ['websocket'],
      forceNew: true
    });

    socket.on('connect', () => {
      console.log('Socket.IO Connected! ID:', socket.id);
      setIsConnected(true);
      setSocketId(socket.id);

      // Auto-pair based on URL roles
      if (isPhone && urlRoom) {
        socket.emit('pair', { room: urlRoom, role: 'phone' });
        setPeerConnected(true);
      } else {
        // Desktop pairs with the generated room code
        socket.emit('pair', { room: roomCode, role: 'desktop' });
      }
    });

    socket.on('disconnect', () => {
      console.log('Socket.IO Disconnected!');
      setIsConnected(false);
      setWorkoutActive(false);
      setPeerConnected(false);
      stopCamera();
      stopCaptureLoop();
    });

    socket.on('peer_connected', (data) => {
      console.log("Peer connected:", data);
      if (isPhone && data.role === 'desktop') {
        setPeerConnected(true);
      } else if (!isPhone && data.role === 'phone') {
        setPeerConnected(true);
      }
    });

    socket.on('peer_disconnected', (data) => {
      console.log("Peer disconnected:", data);
      if (isPhone && data.role === 'desktop') {
        setPeerConnected(false);
        setWorkoutActive(false);
        stopCamera();
        stopCaptureLoop();
      } else if (!isPhone && data.role === 'phone') {
        setPeerConnected(false);
        setWorkoutActive(false);
      }
    });

    socket.on('workout_started', (data) => {
      console.log('Workout started:', data);
      setRepCount(0);
      setFsmState('READY');
      setFeedbackList(['Session started. Align body in camera.']);
      setFormScore(100);
      setLandmarks(null);
      setIsPersonDetected(true);
      setWorkoutActive(true);
      
      // If workout starts and we are the camera streaming phone, launch the capture loop
      if (isPhone) {
        startCaptureLoop();
      }
    });

    socket.on('metrics_update', (data) => {
      setRepCount(data.rep_count);
      setFsmState(data.state);
      setFeedbackList(data.feedback);
      setFormScore(data.form_score);
      setLandmarks(data.landmarks);
      
      if (data.landmarks === null && data.feedback.some(f => f.includes("No person detected"))) {
        setIsPersonDetected(false);
        setActiveAngle(null);
      } else {
        setIsPersonDetected(true);
        // Pick the correct angle based on exercise type
        const angles = data.angles || {};
        const angle = angles.knee || angles.elbow || angles.shoulder || null;
        setActiveAngle(angle);
      }

      if (data.rep_completed) {
        setRepCompletedTrigger(true);
        setTimeout(() => setRepCompletedTrigger(false), 800);
      }
    });

    socket.on('workout_ended', (data) => {
      console.log('Workout ended report:', data);
      setWorkoutActive(false);
      setModalReportContent(data.report);
      setShowReportModal(true);
      setLandmarks(null);
      
      if (isPhone) {
        stopCamera();
        stopCaptureLoop();
      }
      fetchHistory();
    });

    socketRef.current = socket;
    fetchHistory();

    return () => {
      socket.disconnect();
      stopCamera();
      stopCaptureLoop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exercise, isPhone, urlRoom]);

  // Generate pairing QR code for phone controller
  useEffect(() => {
    if (!isPhone) {
      const pairingUrl = `https://${localIp}:5173/?role=phone&room=${roomCode}`;
      QRCode.toDataURL(pairingUrl, { width: 250, margin: 2 })
        .then(url => setQrCodeDataUrl(url))
        .catch(err => console.error("QR Code Generation Error:", err));
    }
  }, [localIp, isPhone, roomCode]);

  // Connect video stream to ref once workout becomes active and video element renders
  useEffect(() => {
    if (workoutActive && videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
    }
  }, [workoutActive]);

  // Fetch session history list from backend SQLite
  const fetchHistory = async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/history`);
      const data = await response.json();
      if (data.sessions) {
        setHistoryList(data.sessions);
      }
    } catch (err) {
      console.log("Error loading workout logs:", err);
    }
  };

  // Start Camera on Phone
  const startCamera = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480, facingMode: "environment" },
        audio: false
      });
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
      }
      streamRef.current = stream;
      return true;
    } catch (err) {
      alert("Camera access denied or unavailable. Please enable camera permissions.");
      console.error(err);
      return false;
    }
  };

  // Start Workout session (normally triggered from Phone Controller)
  const startWorkout = async () => {
    if (!isConnected) {
      alert("Cannot connect to server. Check backend logs.");
      return;
    }

    if (isPhone && !isSimulation) {
      const success = await startCamera();
      if (!success) return;
    }

    const room = isPhone ? urlRoom : socketId;
    socketRef.current.emit('start_workout', { exercise, room });
  };

  // End active Workout session
  const endWorkout = () => {
    if (socketRef.current) {
      socketRef.current.emit('end_workout');
    }
  };

  // Frame capture loop (only runs on Phone Controller)
  const startCaptureLoop = () => {
    stopCaptureLoop();
    
    const canvas = document.createElement('canvas');
    canvas.width = 320;
    canvas.height = 240;
    const ctx = canvas.getContext('2d');

    captureIntervalRef.current = setInterval(() => {
      if (isSimulation) {
        socketRef.current.emit('stream_frame', { use_simulation: true });
      } else {
        if (videoRef.current && streamRef.current && socketRef.current) {
          try {
            ctx.drawImage(videoRef.current, 0, 0, canvas.width, canvas.height);
            const dataUrl = canvas.toDataURL('image/jpeg', 0.25);
            socketRef.current.emit('stream_frame', {
              frame: dataUrl,
              use_simulation: false
            });
          } catch (err) {
            console.log("Frame capture error:", err);
          }
        }
      }
    }, 100);
  };

  const stopCaptureLoop = () => {
    if (captureIntervalRef.current) {
      clearInterval(captureIntervalRef.current);
      captureIntervalRef.current = null;
    }
  };

  const stopCamera = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }
  };

  // Convert Markdown syntax elements into standard HTML blocks for report layout
  const parseMarkdown = (markdownText) => {
    if (!markdownText) return '';
    
    let html = markdownText;
    
    // Bold matches
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // Inline code blocks
    html = html.replace(/`/g, '');
    
    // Headers matching
    html = html.replace(/^# (.*?)$/gm, '<h1>$1</h1>');
    html = html.replace(/^## (.*?)$/gm, '<h2>$1</h2>');
    html = html.replace(/^### (.*?)$/gm, '<h3>$1</h3>');
    
    // Blockquotes
    html = html.replace(/^> (.*?)$/gm, '<blockquote>$1</blockquote>');
    
    // Markdown table translation
    const lines = html.split('\n');
    let inTable = false;
    let tableHtml = '<table>';
    
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      if (line.startsWith('|')) {
        if (!inTable) {
          inTable = true;
          tableHtml = '<table>';
        }
        
        if (line.includes(':---') || line.includes('---:')) {
          continue;
        }
        
        const cells = line.split('|').map(c => c.trim()).filter((c, idx, arr) => idx > 0 && idx < arr.length - 1);
        const cellTag = tableHtml.includes('<thead>') ? 'td' : 'th';
        
        let rowHtml = '<tr>';
        cells.forEach(cell => {
          rowHtml += `<${cellTag}>${cell}</${cellTag}>`;
        });
        rowHtml += '</tr>';
        
        if (cellTag === 'th') {
          tableHtml += '<thead>' + rowHtml + '</thead><tbody>';
        } else {
          tableHtml += rowHtml;
        }
      } else {
        if (inTable) {
          inTable = false;
          tableHtml += '</tbody></table>';
          lines[i - 1] = tableHtml;
        }
      }
    }
    
    html = lines.join('\n');
    
    // Bullet list elements
    html = html.replace(/^- (.*?)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*?<\/li>)/gs, '<ul>$1</ul>');
    html = html.replace(/<\/ul>\n<ul>/g, '');
    html = html.replace(/\n/g, '<br/>');
    
    return <div className="report-markdown" dangerouslySetInnerHTML={{ __html: html }} />;
  };

  // Draw overlay skeleton linkage vectors
  const renderSkeletonOverlay = () => {
    if (!landmarks || landmarks.length < 33) return null;
    
    const getCoords = (idx) => {
      const lm = landmarks[idx];
      return {
        x: lm.x * 100,
        y: lm.y * 100
      };
    };

    const joints = [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28];
    const connections = [
      [11, 12], // shoulders
      [11, 13], [13, 15], // left arm
      [12, 14], [14, 16], // right arm
      [11, 23], [12, 24], // sides
      [23, 24], // hips
      [23, 25], [25, 27], // left leg
      [24, 26], [26, 28]  // right leg
    ];

    return (
      <svg className="skeleton-overlay" viewBox="0 0 100 100" preserveAspectRatio="none">
        {connections.map(([a, b], idx) => {
          const ptA = getCoords(a);
          const ptB = getCoords(b);
          return (
            <line 
              key={`line-${idx}`} 
              x1={`${ptA.x}%`} 
              y1={`${ptA.y}%`} 
              x2={`${ptB.x}%`} 
              y2={`${ptB.y}%`} 
              stroke="#81A6C6" 
              strokeWidth="1.5" 
              strokeOpacity="0.9"
            />
          );
        })}
        {joints.map(jointIdx => {
          const pt = getCoords(jointIdx);
          return (
            <circle 
              key={`joint-${jointIdx}`} 
              cx={`${pt.x}%`} 
              cy={`${pt.y}%`} 
              r="2" 
              fill="#D2C4B4" 
              stroke="#81A6C6" 
              strokeWidth="0.6"
            />
          );
        })}
      </svg>
    );
  };

  // ==========================================
  // Geometric Decoration SVG Elements
  // ==========================================
  const GeoShapes = () => (
    <svg className="geo-deco" style={{ position: 'fixed', top: 0, left: 0, width: '100%', height: '100%', pointerEvents: 'none', zIndex: 0 }}>
      {/* Hexagon top-left */}
      <polygon points="80,30 110,15 140,30 140,60 110,75 80,60" fill="none" stroke="#AACDDC" strokeWidth="2" opacity="0.12" />
      {/* Triangle mid-right */}
      <polygon points="90,50 115,10 140,50" fill="none" stroke="#D2C4B4" strokeWidth="2" opacity="0.08" transform="translate(800, 200)" />
      {/* Circle bottom-left */}
      <circle cx="150" cy="700" r="40" fill="none" stroke="#81A6C6" strokeWidth="2" opacity="0.1" />
      {/* Small rotated square */}
      <rect x="900" y="500" width="30" height="30" fill="none" stroke="#AACDDC" strokeWidth="2" opacity="0.1" transform="rotate(45 915 515)" />
    </svg>
  );

  // ==========================================
  // VIEW RENDERER 1: Phone Controller UI
  // ==========================================
  if (isPhone) {
    return (
      <div className="mobile-controller">
        <header className="mobile-header">
          <h2 className="logo" style={{ fontSize: '16px' }}>Yash <span>Gym Trainer</span></h2>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <span className={`peer-badge ${peerConnected ? 'active' : 'inactive'}`}>
              {peerConnected ? 'PC ACTIVE' : 'WAITING FOR PC'}
            </span>
            <div className={`status-dot ${isConnected ? 'connected' : 'disconnected'}`}></div>
          </div>
        </header>

        {!isConnected && (
          <div style={{ background: 'rgba(192, 80, 80, 0.08)', border: '2px solid rgba(192, 80, 80, 0.2)', padding: '15px', borderRadius: '12px', color: 'var(--danger)', fontSize: '13px', lineHeight: '20px', textAlign: 'center' }}>
            <AlertCircle size={20} style={{ margin: '0 auto 8px', color: 'var(--danger)' }} />
            <strong>Backend Connection Blocked:</strong><br/>
            Open <a href={BACKEND_URL} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-steel)', textDecoration: 'underline' }}>{BACKEND_URL}</a> in a new tab on your phone, click &quot;Advanced&quot;, and choose &quot;Proceed&quot; (unsafe). Then return here and refresh.
          </div>
        )}

        {workoutActive ? (
          <>
            {/* Camera feed & skeleton tracking */}
            <div className="mobile-camera-card">
              {isSimulation ? (
                <div className="simulation-placeholder" style={{ padding: '10px' }}>
                  <div className="pulse-spinner"></div>
                  <p style={{ fontSize: '13px' }}>STREAMING MOCK COORDINATES</p>
                </div>
              ) : (
                <>
                  <video ref={videoRef} className="camera-feed" autoPlay playsInline muted />
                  {renderSkeletonOverlay()}
                  {!isPersonDetected && (
                    <div className="mobile-no-human-overlay">
                      <AlertCircle size={36} />
                      <h3 style={{ margin: '10px 0 5px' }}>NO PERSON DETECTED</h3>
                      <p style={{ fontSize: '13px' }}>Adjust camera positioning to fit body in frame</p>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Mobile HUD */}
            <div className="mobile-hud">
              <div className="mobile-hud-cell">
                <span className="hud-label">REPS</span>
                <span className="mobile-hud-val">{repCount}</span>
              </div>
              <div className="mobile-hud-cell">
                <span className="hud-label">STATE</span>
                <span className="hud-val-small">{fsmState}</span>
              </div>
            </div>

            <button className="primary-btn stop" onClick={endWorkout}>
              <Square size={16} fill="#fff" /> FINISH WORKOUT
            </button>
          </>
        ) : (
          <>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: '20px', padding: '10px 0' }}>
              <div style={{ textAlign: 'center', color: 'var(--text-secondary)' }}>
                <Smartphone size={48} strokeWidth={1.5} style={{ margin: '0 auto 10px', color: 'var(--accent-steel)' }} />
                <h3 style={{ color: 'var(--text-primary)', marginBottom: '4px' }}>Wireless Camera Mode</h3>
                <p style={{ fontSize: '13px' }}>Point this camera at your body to scan repetitions.</p>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <label style={{ fontSize: '11px', fontWeight: '800', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '1px' }}>Exercise</label>
                <div className="selector-group">
                  {EXERCISES.map(ex => (
                    <button 
                      key={ex.key}
                      className={`selector-btn ${exercise === ex.key ? 'active' : ''}`}
                      onClick={() => setExercise(ex.key)}
                    >
                      {ex.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="switch-container">
                <div className="switch-details">
                  <h4 style={{ fontSize: '14px' }}>Mock Simulator</h4>
                  <p style={{ fontSize: '11px' }}>Stream simulated coordinates</p>
                </div>
                <label className="switch">
                  <input 
                    type="checkbox" 
                    checked={isSimulation} 
                    onChange={(e) => setIsSimulation(e.target.checked)} 
                  />
                  <span className="slider"></span>
                </label>
              </div>
            </div>

            <button 
              className="primary-btn start" 
              onClick={startWorkout}
              disabled={!peerConnected}
              style={{ opacity: peerConnected ? 1 : 0.5, cursor: peerConnected ? 'pointer' : 'not-allowed' }}
            >
              <Play size={18} /> Start Workout
            </button>
          </>
        )}
      </div>
    );
  }

  // ==========================================
  // VIEW RENDERER 2: Desktop Dashboard UI
  // ==========================================
  return (
    <div className="app-container">
      <GeoShapes />

      {/* Navigation Header */}
      <header className="app-header">
        <h1 className="logo">YASH GYM TRAINER</h1>
        <div style={{ display: 'flex', gap: '15px' }}>
          <div className={`connection-badge phone-badge ${peerConnected ? 'active' : 'inactive'}`}>
            <span className="phone-icon-wrapper" style={{ display: 'flex', alignItems: 'center' }}>
              {peerConnected ? (
                <svg width="14" height="20" viewBox="0 0 14 20" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="1" y="1" width="12" height="18" rx="2" />
                  <path d="M5 16h4" />
                </svg>
              ) : (
                <svg width="14" height="20" viewBox="0 0 14 20" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="1" y="1" width="12" height="18" rx="2" />
                  <path d="M4 7l6 6M10 7l-6 6" strokeWidth="1.5" />
                </svg>
              )}
            </span>
            <span>{peerConnected ? 'PHONE: ACTIVE' : 'PHONE: NOT FOUND'}</span>
          </div>

          <div className={`connection-badge server-badge ${isConnected ? 'live' : 'offline'}`}>
            <span className="status-dot-indicator"></span>
            <span>{isConnected ? 'SERVER LIVE' : 'SERVER OFFLINE'}</span>
          </div>
        </div>
      </header>

      {/* Main Grid View */}
      <main className="dashboard-grid">
        
        {/* Skeleton Canvas Section */}
        <section className={`video-card ${workoutActive ? 'active' : ''}`}>
          {workoutActive ? (
            <div className="desktop-skeleton-backdrop">
              <div className="cyber-grid"></div>
              {renderSkeletonOverlay()}
              {landmarks ? (
                <div style={{ position: 'absolute', bottom: '20px', left: '20px', display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--success)', fontSize: '12px', fontWeight: 'bold' }}>
                  <Activity style={{ width: '16px', height: '16px' }} /> LIVE BIOMETRIC FEED
                </div>
              ) : (
                <div className="simulation-placeholder">
                  <div className="pulse-spinner"></div>
                  <p>WAITING FOR PHONE VIDEO FEED...</p>
                </div>
              )}
            </div>
          ) : (
            /* Pairing screen when workout is not active */
            <div className="pairing-container" style={{ width: '100%', height: '100%', border: 'none' }}>
              {/* Abstract backgrounds */}
              <svg className="bg-deco-squares" width="100" height="100" viewBox="0 0 100 100" fill="none" stroke="#E2E8F0" strokeWidth="1.5" style={{ position: 'absolute', top: '20px', left: '20px', pointerEvents: 'none' }}>
                <rect x="10" y="10" width="60" height="60" rx="4" transform="rotate(15 40 40)" />
                <rect x="25" y="25" width="60" height="60" rx="4" transform="rotate(-5 55 55)" />
              </svg>
              <svg className="bg-deco-circuit" width="120" height="120" viewBox="0 0 120 120" fill="none" stroke="#E2E8F0" strokeWidth="1.5" style={{ position: 'absolute', bottom: '10px', left: '10px', pointerEvents: 'none' }}>
                <path d="M10 110h40l20-20V50" />
                <circle cx="70" cy="50" r="4" fill="#E2E8F0" />
                <path d="M30 110v-30h30" />
                <circle cx="64" cy="80" r="3" fill="#E2E8F0" />
              </svg>
              <svg className="bg-deco-muscle" width="140" height="140" viewBox="0 0 100 100" fill="none" stroke="#E2E8F0" strokeWidth="1.2" style={{ position: 'absolute', bottom: '0', right: '0', pointerEvents: 'none' }}>
                <path d="M100 100 C 60 90, 40 60, 50 20 C 65 50, 85 75, 100 100 Z" />
                <path d="M100 100 C 70 85, 55 60, 65 30 C 75 55, 90 75, 100 100 Z" />
                <path d="M100 100 C 80 80, 70 60, 80 40 C 85 58, 92 78, 100 100 Z" />
              </svg>

              <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="#94A3B8" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ marginBottom: '16px', position: 'relative', zIndex: 1 }}>
                <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
                <circle cx="12" cy="13" r="4" />
              </svg>

              <h3 style={{ fontSize: '22px', fontWeight: 800, position: 'relative', zIndex: 1 }}>Connect Wireless Mobile Camera</h3>
              <p style={{ maxWidth: '400px', fontSize: '13px', color: 'var(--text-secondary)', lineHeight: '20px', position: 'relative', zIndex: 1 }}>
                Scan the QR code below on your phone to link it as a wireless camera controller.
              </p>
              
              {qrCodeDataUrl ? (
                <div className="qr-code-wrapper" style={{ position: 'relative', zIndex: 1 }}>
                  <img src={qrCodeDataUrl} className="qr-code-img" alt="Pairing QR Code" />
                </div>
              ) : (
                <div className="pulse-spinner"></div>
              )}

              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', width: '100%', maxWidth: '450px', position: 'relative', zIndex: 1 }}>
                <span style={{ fontSize: '11px', fontWeight: 'bold', color: 'var(--text-primary)', letterSpacing: '0.5px' }}>DIRECT PAIRING URL</span>
                <div className="pairing-url-text">
                  https://{localIp}:5173/?role=phone&room={roomCode}
                </div>
              </div>

              {!isConnected && (
                <div style={{ background: 'rgba(192, 80, 80, 0.06)', border: '2px solid rgba(192, 80, 80, 0.2)', padding: '15px', borderRadius: '12px', color: 'var(--danger)', fontSize: '13px', maxWidth: '450px', lineHeight: '20px', textAlign: 'left', position: 'relative', zIndex: 1 }}>
                  <AlertCircle size={16} style={{ display: 'inline', marginRight: '6px', verticalAlign: 'text-bottom' }} />
                  <strong>FastAPI Backend is Offline or Blocked:</strong><br/>
                  1. Double-click <code>start.bat</code> to start uvicorn.<br/>
                  2. If running, open <a href={BACKEND_URL} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-steel)', textDecoration: 'underline' }}>{BACKEND_URL}</a> in a new tab, click &quot;Advanced&quot;, and choose &quot;Proceed&quot; (unsafe).
                </div>
              )}
            </div>
          )}
        </section>

        {/* Dashboard Panels Section */}
        <section className="control-card">
          
          {/* Settings panel / Active state */}
          {!workoutActive ? (
            <>
              <h2 className="card-title">Training Setup</h2>
              
              <div className="steps-container">
                <h4 className="steps-title">Steps to Begin:</h4>
                <ol className="steps-list">
                  <li>Connect your phone to the same Wi-Fi.</li>
                  <li>Scan the QR code with your phone.</li>
                  <li>Accept the self-signed SSL certificate if prompted.</li>
                  <li>Choose your exercise and start workout on the phone.</li>
                </ol>
              </div>

              {peerConnected && (
                <div style={{ background: 'rgba(90, 158, 111, 0.08)', border: '2px solid rgba(90, 158, 111, 0.2)', padding: '15px', borderRadius: '12px', display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--success)', fontSize: '13px', fontWeight: 'bold' }}>
                  <CheckCircle size={16} /> Phone Linked! Select exercise and start workout on your mobile.
                </div>
              )}
            </>
          ) : (
            <>
              {/* Active Hud Panel */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h2 className="card-title" style={{ borderLeftColor: 'var(--success)' }}>
                  {exercise.replace('_', ' ').toUpperCase()} ANALYTICS
                </h2>
                <span className="peer-badge active">
                  TRACKING VIA MOBILE
                </span>
              </div>

              <div className="hud-metrics">
                <div className="hud-cell">
                  <span className="hud-label">REPS</span>
                  <span className={`hud-val ${repCompletedTrigger ? 'pulsing' : ''}`}>
                    {repCount}
                  </span>
                </div>
                <div className="hud-cell" style={{ borderLeft: '2px solid var(--border-color)', borderRight: '2px solid var(--border-color)' }}>
                  <span className="hud-label">STATE</span>
                  <span className="hud-val-small">{fsmState}</span>
                </div>
                <div className="hud-cell">
                  <span className="hud-label">ANGLE</span>
                  <span className="hud-val">{activeAngle !== null ? `${activeAngle}°` : '--'}</span>
                </div>
              </div>

              {/* Dynamic Feedback Alerts */}
              <div className={`feedback-panel ${formScore < 85 ? 'warning' : 'good'}`}>
                <div className="feedback-header">
                  {formScore < 85 ? '⚠ FORM DEVIATION WARNING' : '✔ LIVE COACH FEEDBACK'}
                </div>
                {feedbackList.map((feedback, idx) => (
                  <div key={idx} className="feedback-bullet">
                    • {feedback}
                  </div>
                ))}
              </div>
            </>
          )}

          {/* History Drawer */}
          {!workoutActive && (
            <>
              <h2 className="card-title" style={{ borderLeftColor: 'var(--accent-blue)' }}>
                Session History
              </h2>
              {historyList.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '20px', color: 'var(--text-secondary)', fontSize: '13px' }}>
                  No workout logs recorded yet. Start training!
                </div>
              ) : (
                <div className="history-list">
                  {historyList.map((session) => (
                    <div 
                      key={session.id} 
                      className="history-item"
                      onClick={() => {
                        setModalReportContent(session.analyst_feedback);
                        setShowReportModal(true);
                      }}
                    >
                      <div className="history-row">
                        <span className="history-name">{session.exercise.replace('_', ' ').toUpperCase()}</span>
                        <span className="history-date">{new Date(session.date).toLocaleDateString()}</span>
                      </div>
                      <div className="history-stats">
                        <div className="history-stat">
                          Reps: <span>{session.rep_count}</span>
                        </div>
                        <div className="history-stat">
                          Avg Tempo: <span>{session.avg_tempo}s</span>
                        </div>
                        <div className="history-stat">
                          Form Quality: <span style={{ color: session.avg_form_score >= 80 ? 'var(--success)' : session.avg_form_score >= 60 ? 'var(--warning)' : 'var(--danger)' }}>
                            {session.avg_form_score}%
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

        </section>
      </main>

      {/* Post Workout / Analyst report modal */}
      {showReportModal && (
        <div className="modal-overlay" onClick={() => setShowReportModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="close-modal-btn" onClick={() => setShowReportModal(false)}>×</button>
            {parseMarkdown(modalReportContent)}
          </div>
        </div>
      )}
    </div>
  );
}
