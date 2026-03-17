import time
import platform
import threading
import queue
import streamlit as st
import pytesseract
from PIL import ImageGrab
from datetime import datetime

# On Windows, uncomment and set your Tesseract path:
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

OS = platform.system()

# ── Page config ───────────────────────────────────────────
st.set_page_config(
    page_title="Screen Watcher",
    page_icon="👁",
    layout="centered",
)

# ── Styling ───────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
}

.stApp {
    background-color: #0d0f12;
    color: #e2e8f0;
}

h1, h2, h3 {
    font-family: 'IBM Plex Mono', monospace !important;
    letter-spacing: -0.02em;
}

.status-card {
    background: #161a22;
    border: 1px solid #2d3748;
    border-radius: 12px;
    padding: 20px 24px;
    margin: 12px 0;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 13px;
}

.status-watching {
    border-left: 4px solid #48bb78;
    animation: pulse-green 2s infinite;
}

.status-idle {
    border-left: 4px solid #718096;
}

.status-found {
    border-left: 4px solid #f6ad55;
    background: #1a1600;
    animation: pulse-amber 1.5s infinite;
}

@keyframes pulse-green {
    0%, 100% { box-shadow: 0 0 0 0 rgba(72,187,120,0.0); }
    50% { box-shadow: 0 0 0 6px rgba(72,187,120,0.08); }
}

@keyframes pulse-amber {
    0%, 100% { box-shadow: 0 0 0 0 rgba(246,173,85,0.0); }
    50% { box-shadow: 0 0 0 8px rgba(246,173,85,0.10); }
}

.log-entry {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    padding: 4px 0;
    border-bottom: 1px solid #1e2535;
    color: #94a3b8;
}

.log-entry.match {
    color: #f6ad55;
    font-weight: 600;
}

.log-entry.error {
    color: #fc8181;
}

.badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 11px;
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}

.badge-green  { background: #1a3a2a; color: #68d391; border: 1px solid #2f6b45; }
.badge-gray   { background: #1e2535; color: #94a3b8; border: 1px solid #2d3748; }
.badge-amber  { background: #2a1f00; color: #f6ad55; border: 1px solid #5a3e00; }

.metric-row {
    display: flex;
    gap: 16px;
    margin: 16px 0;
}

.metric-box {
    flex: 1;
    background: #161a22;
    border: 1px solid #2d3748;
    border-radius: 10px;
    padding: 14px 18px;
    text-align: center;
}

.metric-value {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 28px;
    font-weight: 600;
    color: #e2e8f0;
    line-height: 1.1;
}

.metric-label {
    font-size: 11px;
    color: #718096;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-top: 4px;
}

div[data-testid="stButton"] > button {
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 600;
    border-radius: 8px;
    border: 1px solid #2d3748;
    background: #161a22;
    color: #e2e8f0;
    transition: all 0.2s;
    width: 100%;
    padding: 0.6rem 1rem;
}

div[data-testid="stButton"] > button:hover {
    border-color: #48bb78;
    color: #48bb78;
    background: #0f1f18;
}

div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input {
    font-family: 'IBM Plex Mono', monospace;
    background: #161a22;
    border: 1px solid #2d3748;
    border-radius: 8px;
    color: #e2e8f0;
}

div[data-testid="stCheckbox"] label {
    font-family: 'IBM Plex Sans', sans-serif;
    color: #94a3b8;
}

footer { visibility: hidden; }
#MainMenu { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ── Notification sender ───────────────────────────────────
def send_notification(target: str):
    title   = "Screen Watcher — Match Found!"
    message = f'Found: "{target}"'

    if OS == "Windows":
        try:
            from windows_toasts import Toast, WindowsToaster
            toaster = WindowsToaster("Screen Watcher")
            toast = Toast()
            toast.text_fields = [title, message]
            toaster.show_toast(toast)
            return
        except ImportError:
            pass

    if OS == "Darwin":
        import subprocess
        script = f'display notification "{message}" with title "{title}" sound name "Glass"'
        subprocess.run(["osascript", "-e", script])
        return

    if OS == "Linux":
        import subprocess
        subprocess.run(["notify-send", title, message, "-i", "dialog-information", "-t", "8000"])
        return

    # Fallback
    try:
        from plyer import notification
        notification.notify(title=title, message=message, timeout=10)
    except Exception:
        pass


# ── OCR helpers ───────────────────────────────────────────
def capture_screen_text() -> str:
    screenshot = ImageGrab.grab()
    return pytesseract.image_to_string(screenshot)


def text_matches(screen_text: str, target: str, case_sensitive: bool) -> bool:
    if not case_sensitive:
        return target.lower() in screen_text.lower()
    return target in screen_text


# ── Session state init ────────────────────────────────────
defaults = {
    "watching":      False,
    "checks":        0,
    "matches":       0,
    "log":           [],
    "last_status":   "idle",
    "stop_event":    None,
    "watcher_thread": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ── Watcher thread ────────────────────────────────────────
def watcher_loop(target, interval, case_sensitive, stop_event, log_queue):
    notified = False
    while not stop_event.is_set():
        try:
            screen_text = capture_screen_text()
            found = text_matches(screen_text, target, case_sensitive)
            ts = datetime.now().strftime("%H:%M:%S")

            if found and not notified:
                send_notification(target)
                notified = True
                log_queue.put(("match", ts, f'MATCH — "{target}" found on screen'))
            elif found:
                log_queue.put(("info", ts, f'Still visible: "{target}"'))
            else:
                notified = False
                log_queue.put(("info", ts, "No match"))

        except Exception as e:
            ts = datetime.now().strftime("%H:%M:%S")
            log_queue.put(("error", ts, str(e)))

        stop_event.wait(interval)


# ── UI ────────────────────────────────────────────────────
st.markdown("# 👁 Screen Watcher")
st.markdown(
    "<p style='color:#718096;font-size:14px;margin-top:-8px;margin-bottom:24px;'>"
    "Monitors your screen via OCR and fires a desktop notification when your target text appears.</p>",
    unsafe_allow_html=True,
)

# Config panel
with st.expander("⚙️ Configuration", expanded=not st.session_state.watching):
    target_text = st.text_input(
        "Target text",
        value=st.session_state.get("target_text", ""),
        placeholder="Text to watch for...",
        disabled=st.session_state.watching,
    )
    col1, col2 = st.columns(2)
    with col1:
        interval = st.number_input(
            "Check interval (seconds)",
            min_value=1, max_value=60, value=5,
            disabled=st.session_state.watching,
        )
    with col2:
        case_sensitive = st.checkbox(
            "Case sensitive",
            value=False,
            disabled=st.session_state.watching,
        )

# Controls
col_start, col_stop = st.columns(2)
with col_start:
    if st.button("▶ Start Watching", disabled=st.session_state.watching):
        if not target_text.strip():
            st.warning("Please enter a target text first.")
        else:
            st.session_state.target_text  = target_text
            st.session_state.watching     = True
            st.session_state.checks       = 0
            st.session_state.matches      = 0
            st.session_state.log          = []
            st.session_state.last_status  = "watching"
            st.session_state.log_queue    = queue.Queue()

            stop_event = threading.Event()
            st.session_state.stop_event   = stop_event

            t = threading.Thread(
                target=watcher_loop,
                args=(target_text, interval, case_sensitive,
                      stop_event, st.session_state.log_queue),
                daemon=True,
            )
            t.start()
            st.session_state.watcher_thread = t
            st.rerun()

with col_stop:
    if st.button("■ Stop", disabled=not st.session_state.watching):
        if st.session_state.stop_event:
            st.session_state.stop_event.set()
        st.session_state.watching    = False
        st.session_state.last_status = "idle"
        st.rerun()

# Drain log queue into session state
if st.session_state.watching and "log_queue" in st.session_state:
    q = st.session_state.log_queue
    while not q.empty():
        kind, ts, msg = q.get_nowait()
        st.session_state.log.append((kind, ts, msg))
        st.session_state.checks += 1
        if kind == "match":
            st.session_state.matches += 1

# Status card
if st.session_state.last_status == "watching":
    badge = '<span class="badge badge-green">● WATCHING</span>'
    card_class = "status-card status-watching"
elif st.session_state.last_status == "found":
    badge = '<span class="badge badge-amber">★ MATCH FOUND</span>'
    card_class = "status-card status-found"
else:
    badge = '<span class="badge badge-gray">○ IDLE</span>'
    card_class = "status-card status-idle"

target_display = st.session_state.get("target_text", "—")
st.markdown(f"""
<div class="{card_class}">
  {badge}
  <div style="margin-top:10px;color:#cbd5e0;">
    Target: <span style="color:#e2e8f0;font-weight:600;">"{target_display}"</span>
  </div>
  <div style="margin-top:4px;color:#718096;font-size:12px;">OS: {OS}</div>
</div>
""", unsafe_allow_html=True)

# Metrics
checks  = st.session_state.checks
matches = st.session_state.matches
rate    = f"{(matches/checks*100):.0f}%" if checks else "—"

st.markdown(f"""
<div class="metric-row">
  <div class="metric-box">
    <div class="metric-value">{checks}</div>
    <div class="metric-label">Checks</div>
  </div>
  <div class="metric-box">
    <div class="metric-value" style="color:#f6ad55">{matches}</div>
    <div class="metric-label">Matches</div>
  </div>
  <div class="metric-box">
    <div class="metric-value">{rate}</div>
    <div class="metric-label">Match rate</div>
  </div>
</div>
""", unsafe_allow_html=True)

# Log
st.markdown("### Activity Log")
log = st.session_state.log[-30:][::-1]  # latest first, max 30

if not log:
    st.markdown(
        "<div class='log-entry' style='color:#4a5568;'>No activity yet...</div>",
        unsafe_allow_html=True,
    )
else:
    log_html = ""
    for kind, ts, msg in log:
        css = "log-entry match" if kind == "match" else ("log-entry error" if kind == "error" else "log-entry")
        icon = "★" if kind == "match" else ("✕" if kind == "error" else "·")
        log_html += f'<div class="{css}">{icon} [{ts}] {msg}</div>'
    st.markdown(log_html, unsafe_allow_html=True)

# Auto-refresh while watching
if st.session_state.watching:
    time.sleep(1)
    st.rerun()
