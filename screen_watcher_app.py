import os
import time
import streamlit as st
import pytesseract
from PIL import Image
from datetime import datetime
import io

# Fix for Streamlit Cloud: Tesseract requires no display server
os.environ["DISPLAY"] = ""
os.environ["OMP_THREAD_LIMIT"] = "1"

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

html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
.stApp { background-color: #0d0f12; color: #e2e8f0; }
h1, h2, h3 { font-family: 'IBM Plex Mono', monospace !important; letter-spacing: -0.02em; }

.status-card {
    background: #161a22; border: 1px solid #2d3748;
    border-radius: 12px; padding: 20px 24px; margin: 12px 0;
    font-family: 'IBM Plex Mono', monospace; font-size: 13px;
}
.status-watching { border-left: 4px solid #48bb78; }
.status-found    { border-left: 4px solid #f6ad55; background: #1a1600; }
.status-notfound { border-left: 4px solid #718096; }
.status-idle     { border-left: 4px solid #2d3748; }

.log-entry {
    font-family: 'IBM Plex Mono', monospace; font-size: 12px;
    padding: 5px 0; border-bottom: 1px solid #1e2535; color: #94a3b8;
}
.log-entry.match    { color: #f6ad55; font-weight: 600; }
.log-entry.notfound { color: #718096; }
.log-entry.error    { color: #fc8181; }

.badge {
    display: inline-block; padding: 2px 10px; border-radius: 999px;
    font-size: 11px; font-family: 'IBM Plex Mono', monospace;
    font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase;
}
.badge-green { background: #1a3a2a; color: #68d391; border: 1px solid #2f6b45; }
.badge-gray  { background: #1e2535; color: #94a3b8; border: 1px solid #2d3748; }
.badge-amber { background: #2a1f00; color: #f6ad55; border: 1px solid #5a3e00; }
.badge-red   { background: #2a0a0a; color: #fc8181; border: 1px solid #5a1a1a; }

.metric-row { display: flex; gap: 16px; margin: 16px 0; }
.metric-box {
    flex: 1; background: #161a22; border: 1px solid #2d3748;
    border-radius: 10px; padding: 14px 18px; text-align: center;
}
.metric-value {
    font-family: 'IBM Plex Mono', monospace; font-size: 28px;
    font-weight: 600; color: #e2e8f0; line-height: 1.1;
}
.metric-label {
    font-size: 11px; color: #718096;
    text-transform: uppercase; letter-spacing: 0.08em; margin-top: 4px;
}

div[data-testid="stButton"] > button {
    font-family: 'IBM Plex Mono', monospace; font-weight: 600;
    border-radius: 8px; border: 1px solid #2d3748;
    background: #161a22; color: #e2e8f0;
    transition: all 0.2s; width: 100%; padding: 0.6rem 1rem;
}
div[data-testid="stButton"] > button:hover {
    border-color: #48bb78; color: #48bb78; background: #0f1f18;
}
div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input {
    font-family: 'IBM Plex Mono', monospace; background: #161a22;
    border: 1px solid #2d3748; border-radius: 8px; color: #e2e8f0;
}
div[data-testid="stCheckbox"] label { font-family: 'IBM Plex Sans', sans-serif; color: #94a3b8; }
footer { visibility: hidden; }
#MainMenu { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────
defaults = {
    "watching": False,
    "checks": 0,
    "matches": 0,
    "log": [],
    "last_result": None,   # "found" | "notfound" | None
    "last_image_id": None, # track if a new image was uploaded
    "notified": False,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Helpers ───────────────────────────────────────────────
def scan_image(image, target_text, case_sensitive):
    extracted = pytesseract.image_to_string(image)
    needle   = target_text if case_sensitive else target_text.lower()
    haystack = extracted   if case_sensitive else extracted.lower()
    return needle in haystack, extracted

# ── Header ────────────────────────────────────────────────
st.markdown("# 👁 Screen Watcher")
st.markdown(
    "<p style='color:#718096;font-size:14px;margin-top:-8px;margin-bottom:24px;'>"
    "Upload screenshots continuously — the watcher scans each one and alerts you when the target text appears.</p>",
    unsafe_allow_html=True,
)

# ── Config ────────────────────────────────────────────────
with st.expander("⚙️ Configuration", expanded=not st.session_state.watching):
    target_text    = st.text_input("Target text", value="hello world", placeholder="Text to search for...", disabled=st.session_state.watching)
    case_sensitive = st.checkbox("Case sensitive", value=False, disabled=st.session_state.watching)
    interval       = st.number_input("Auto-rescan interval (seconds)", min_value=2, max_value=60, value=5, disabled=st.session_state.watching)

# ── Start / Stop controls ─────────────────────────────────
col1, col2 = st.columns(2)
with col1:
    if st.button("▶ Start Watching", disabled=st.session_state.watching):
        if not target_text.strip():
            st.warning("Please enter a target text first.")
        else:
            st.session_state.watching   = True
            st.session_state.notified   = False
            st.session_state.last_result = None
            st.rerun()

with col2:
    if st.button("■ Stop", disabled=not st.session_state.watching):
        st.session_state.watching    = False
        st.session_state.last_result = None
        st.rerun()

# ── Status card ───────────────────────────────────────────
if st.session_state.watching:
    if st.session_state.last_result == "found":
        badge      = '<span class="badge badge-amber">★ MATCH FOUND</span>'
        card_class = "status-card status-found"
        status_msg = f'<span style="color:#f6ad55;font-weight:600;">"{target_text}"</span> detected in last scan.'
    else:
        badge      = '<span class="badge badge-green">● WATCHING</span>'
        card_class = "status-card status-watching"
        status_msg = f'Scanning every upload for <span style="color:#e2e8f0;">"{target_text}"</span>...'
else:
    badge      = '<span class="badge badge-gray">○ IDLE</span>'
    card_class = "status-card status-idle"
    status_msg = 'Press <b>Start Watching</b> then upload screenshots below.'

st.markdown(f"""
<div class="{card_class}">
  {badge}
  <div style="margin-top:10px;color:#94a3b8;">{status_msg}</div>
</div>
""", unsafe_allow_html=True)

# ── Upload area ───────────────────────────────────────────
st.markdown("### Upload Screenshot")
if not st.session_state.watching:
    st.markdown("<p style='color:#4a5568;font-size:13px;'>Start watching first, then upload screenshots to scan.</p>", unsafe_allow_html=True)

uploaded_file = st.file_uploader(
    "Drop a screenshot here to scan",
    type=["png", "jpg", "jpeg", "bmp", "webp"],
    label_visibility="collapsed",
    disabled=not st.session_state.watching,
)

# ── Auto-scan on upload ───────────────────────────────────
if st.session_state.watching and uploaded_file is not None:
    # Use file id to avoid rescanning same upload on every rerun
    file_id = f"{uploaded_file.name}-{uploaded_file.size}"

    if file_id != st.session_state.last_image_id:
        st.session_state.last_image_id = file_id
        ts = datetime.now().strftime("%H:%M:%S")

        try:
            image = Image.open(io.BytesIO(uploaded_file.read()))
            found, extracted = scan_image(image, target_text, case_sensitive)

            st.session_state.checks += 1

            if found:
                st.session_state.matches     += 1
                st.session_state.last_result  = "found"
                st.session_state.notified     = True
                st.session_state.log.append(("match",    ts, f'MATCH — "{target_text}" found'))
                st.balloons()
            else:
                st.session_state.last_result = "notfound"
                st.session_state.log.append(("notfound", ts, f'No match for "{target_text}"'))

            # Show result inline
            if found:
                st.success(f'✅ Found **"{target_text}"** in this screenshot!')
            else:
                st.info(f'🔍 **"{target_text}"** not found in this screenshot.')

            with st.expander("📄 Extracted text (OCR output)"):
                st.code(extracted or "(no text detected)", language=None)

            with st.expander("🖼 Image preview"):
                st.image(image, use_column_width=True)

        except Exception as e:
            ts = datetime.now().strftime("%H:%M:%S")
            st.session_state.log.append(("error", ts, str(e)))
            st.error(f"Scan error: {e}")

    # Auto-rerun after interval so the UI stays live
    time.sleep(interval)
    st.rerun()

# ── Metrics ───────────────────────────────────────────────
checks  = st.session_state.checks
matches = st.session_state.matches
rate    = f"{(matches / checks * 100):.0f}%" if checks else "—"

st.markdown(f"""
<div class="metric-row">
  <div class="metric-box">
    <div class="metric-value">{checks}</div>
    <div class="metric-label">Scans</div>
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

# ── Log ───────────────────────────────────────────────────
st.markdown("### Scan Log")
log = st.session_state.log[-30:][::-1]

if not log:
    st.markdown("<div class='log-entry' style='color:#4a5568;'>No scans yet...</div>", unsafe_allow_html=True)
else:
    log_html = ""
    for kind, ts, msg in log:
        icon = "★" if kind == "match" else ("✕" if kind == "error" else "·")
        log_html += f'<div class="log-entry {kind}">{icon} [{ts}] {msg}</div>'
    st.markdown(log_html, unsafe_allow_html=True)

if st.session_state.log:
    if st.button("🗑 Clear log"):
        st.session_state.log     = []
        st.session_state.checks  = 0
        st.session_state.matches = 0
        st.rerun()
