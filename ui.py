import streamlit as st
import requests
import os
from pathlib import Path
from startsetup import load_env_vars

st.set_page_config(page_title="QUIC File Transfer", page_icon="📁", layout="wide")

st.markdown("""
<style>
    .stButton button { width: 100%; }
    .tree-indent { padding-left: 16px; border-left: 1px dashed #e0e0e0; margin-left: 4px; }
    .muted { color: #6b7280; font-size: 0.85em; }
</style>
""", unsafe_allow_html=True)

# ---------- Helpers ----------
def load_config():
    try:
        env = load_env_vars()
        return env
    except Exception as e:
        st.error(f"Error loading configuration: {e}")
        return {}

def call_api(endpoint, data, base_url):
    try:
        if not base_url:
            return None, f"Base URL not configured for endpoint {endpoint}"
        url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        response = requests.post(url, json=data, timeout=10)
        response.raise_for_status()
        try:
            return response.json(), None
        except ValueError:
            return None, f"Invalid JSON response from {url}"
    except requests.exceptions.RequestException as e:
        return None, str(e)

def format_size(size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"

# render_tree: path_state_key is the session_state key name (e.g. "local_path" or "remote_path")
def render_tree(base_url, path_state_key, key_prefix, selected_key):
    """
    Render a folder/file tree for the path stored in st.session_state[path_state_key].
    Clicking a folder puts its path into <path_state_key>_pending and triggers a rerun.
    The pending value is moved to the widget-backed key at the top of the next run.
    """
    try:
        current_path = st.session_state.get(path_state_key, "")
        if not current_path:
            st.info("No path set")
            return

        # Up button + path display
        parent = os.path.dirname(current_path.rstrip("/"))
        cols = st.columns([1, 9])
        with cols[0]:
            if parent and st.button(".. (up)", key=f"{key_prefix}_up_{current_path}"):
                # write directly to the named session-state key for local nav; for remote we use pending
                # if this is remote (path_state_key == "remote_path") we should set pending as well
                if path_state_key == "remote_path":
                    st.session_state["remote_path_pending"] = parent or "/"
                    st.experimental_rerun()
                else:
                    st.session_state[path_state_key] = parent or "/"
                    st.experimental_rerun()
        with cols[1]:
            st.markdown(f"**{current_path}**")

        resp, err = call_api("listdir", {"cdir": current_path}, base_url)
        if err:
            st.error(f"Listing failed: {err}  \n(API: {base_url}, path: {current_path})")
            return
        items = resp.get("files", [])
        if not items:
            st.info("Empty directory")
            return

        # ensure selected list exists
        if selected_key not in st.session_state:
            st.session_state[selected_key] = []

        for item in sorted(items):
            full_path = os.path.join(current_path, item)
            # probe to check if folder (call listdir and see if files list exists)
            probe, probe_err = call_api("listdir", {"cdir": full_path}, base_url)
            if not probe_err and isinstance(probe.get("files"), list):
                btn_key = f"{key_prefix}_folder_{full_path}"
                if st.button(f"📁 {item}", key=btn_key, use_container_width=True):
                    # For remote, set pending and rerun; local can write directly
                    if path_state_key == "remote_path":
                        st.session_state["remote_path_pending"] = full_path
                        st.experimental_rerun()
                    else:
                        st.session_state[path_state_key] = full_path
                        st.experimental_rerun()
            else:
                cb_key = f"{key_prefix}_file_{full_path}"
                checked = st.checkbox(f"📄 {item}", key=cb_key,
                                      value=(full_path in st.session_state[selected_key]))
                if checked and full_path not in st.session_state[selected_key]:
                    st.session_state[selected_key].append(full_path)
                if (not checked) and (full_path in st.session_state[selected_key]):
                    st.session_state[selected_key].remove(full_path)
    except Exception as e:
        st.error(f"Error rendering tree: {e}")

# ---------- Session state init ----------
if "local_path" not in st.session_state:
    st.session_state.local_path = str(Path.home())
if "remote_path" not in st.session_state:
    st.session_state.remote_path = ""  # canonical remote value
if "remote_dest_input" not in st.session_state:
    st.session_state.remote_dest_input = ""  # widget-backed key
if "selected_local_files" not in st.session_state:
    st.session_state.selected_local_files = []
if "selected_remote_files" not in st.session_state:
    st.session_state.selected_remote_files = []

# ---------- Load config ----------
config = load_config()
# normalize config keys (support uppercase env names)
host_ip = config.get("HOST_IP") or config.get("host_ip") or config.get("host")
dest_host = config.get("DEST_HOST") or config.get("dest_host") or config.get("dest")
out_dir = config.get("OUT_DIR") or config.get("out_dir") or config.get("OUT") or ""

LOCAL_API = f"http://{host_ip}:5000" if host_ip else ""
REMOTE_API = f"http://{dest_host}:5000" if dest_host else ""

# Initialize remote_path from config if empty and no widget yet
if not st.session_state.remote_path and out_dir:
    st.session_state.remote_path = out_dir

# Apply pending updates BEFORE any widget with the same key is created.
# When render_tree sets "remote_path_pending", it triggers an immediate rerun.
# On the next run we move pending into the widget-backed key BEFORE creating the widget.
if "remote_path_pending" in st.session_state:
    st.session_state["remote_dest_input"] = st.session_state.pop("remote_path_pending")
    # Also keep canonical remote_path in sync
    st.session_state["remote_path"] = st.session_state["remote_dest_input"]

# If the widget value is empty but canonical remote_path is set, populate the widget key
if not st.session_state.get("remote_dest_input") and st.session_state.get("remote_path"):
    st.session_state["remote_dest_input"] = st.session_state["remote_path"]

# ---------- UI ----------
st.title("📁 QUIC File Transfer Manager")

if not config:
    st.error("❌ Failed to load configuration. Please check your .env file.")
    st.stop()

# Debug expander (optional)
with st.expander("Debug: config / endpoints"):
    st.json(config)
    st.write("LOCAL_API:", LOCAL_API)
    st.write("REMOTE_API:", REMOTE_API)
    st.write("session remote_path:", st.session_state.get("remote_path"))
    st.write("widget remote_dest_input:", st.session_state.get("remote_dest_input"))

col_local, col_actions, col_remote = st.columns([5, 2, 5])

with col_local:
    st.subheader("💻 Local Files")
    render_tree(LOCAL_API, "local_path", "local", "selected_local_files")

with col_actions:
    st.subheader("⚡ Actions")

    # Create the textbox widget using the widget-backed key "remote_dest_input".
    # Because we applied any pending value above, this widget is instantiated with the correct value.
    remote_dest = st.text_input(
        "Remote Destination",
        value=st.session_state.get("remote_dest_input", ""),
        key="remote_dest_input"
    )

    # Keep canonical remote_path synced to the widget value for other code paths.
    st.session_state["remote_path"] = st.session_state.get("remote_dest_input", "")

    # Buttons use the value from the widget (remote_dest_input)
    if st.button("📋 Copy →", use_container_width=True, type="primary"):
        if not st.session_state.get("remote_dest_input"):
            st.error("Remote destination is empty.")
        else:
            for full in list(st.session_state.selected_local_files):
                filename = os.path.basename(full)
                data = {"src": full, "dest": st.session_state["remote_dest_input"], "filename": filename}
                result, error = call_api("copy", data, LOCAL_API)
                if error:
                    st.error(f"{filename}: {error}")
                else:
                    st.success(f"Copied {filename}")

    if st.button("🔄 Move →", use_container_width=True):
        if not st.session_state.get("remote_dest_input"):
            st.error("Remote destination is empty.")
        else:
            for full in list(st.session_state.selected_local_files):
                filename = os.path.basename(full)
                data = {"src": full, "dest": st.session_state["remote_dest_input"], "filename": filename}
                result, error = call_api("move", data, LOCAL_API)
                if error:
                    st.error(f"{filename}: {error}")
                else:
                    st.success(f"Moved {filename}")
            st.session_state.selected_local_files = []

with col_remote:
    st.subheader("☁️ Remote Files")
    st.markdown(f"*API:* `{REMOTE_API or 'not configured'}`")
    # Render remote tree; when folders are clicked it sets remote_path_pending and reruns
    render_tree(REMOTE_API, "remote_path", "remote", "selected_remote_files")
