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
    """Load environment/config via startsetup.load_env_vars().
    This function never raises: it returns a dict (possibly empty).
    """
    try:
        env = load_env_vars()
        if not isinstance(env, dict):
            return {}
        return env
    except Exception:
        return {}


def call_api(endpoint, data, base_url):
    """POST JSON to base_url/endpoint. Returns (json_or_none, error_or_none).

    If base_url is empty, return a clear error string (so UI can react via buttons).
    """
    if not base_url:
        return None, f"Base URL not configured for endpoint {endpoint}"
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/') }"
    try:
        resp = requests.post(url, json=data, timeout=10)
        resp.raise_for_status()
        try:
            return resp.json(), None
        except ValueError:
            return None, f"Invalid JSON response from {url} (status {resp.status_code})"
    except requests.exceptions.RequestException as e:
        return None, str(e)


def format_size(size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def render_tree(base_url, path_state_key, key_prefix, selected_key):
    """Render a folder/file tree for the path stored in st.session_state[path_state_key].

    When base_url is empty, show action buttons (no manual inputs) so the user can
    pick a sensible fallback (use localhost) or retry loading config.
    """
    try:
        current_path = st.session_state.get(path_state_key, "")
        if not current_path:
            st.info("No path set")
            return

        # Show up button + path display
        parent = os.path.dirname(current_path.rstrip("/"))
        cols = st.columns([1, 9])
        with cols[0]:
            if parent and st.button(".. (up)", key=f"{key_prefix}_up_{current_path}"):
                st.session_state[path_state_key] = parent or "/"
                st.rerun()
        with cols[1]:
            st.markdown(f"**{current_path}**")

        if not base_url:
            st.warning("API endpoint for this panel is not configured.")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Use loopback defaults for this panel", key=f"{key_prefix}_use_localhost"):
                    # set a panel-specific override
                    st.session_state[f"{key_prefix}_override_api"] = "http://127.0.0.1:5000"
                    st.rerun()
            with col2:
                if st.button("Retry loading config", key=f"{key_prefix}_retry_config"):
                    st.session_state._config = load_config()
                    st.rerun()
            return

        resp, err = call_api("listdir", {"cdir": current_path}, base_url)
        if err:
            st.error(f"Listing failed: {err}  \n(API: {base_url}, path: {current_path})")
            return
        items = resp.get("files", []) if isinstance(resp, dict) else []
        if not items:
            st.info("Empty directory")
            return

        # ensure selected list exists
        if selected_key not in st.session_state:
            st.session_state[selected_key] = []

        for item in sorted(items):
            full_path = os.path.join(current_path, item)
            # probe to check if folder
            probe, probe_err = call_api("listdir", {"cdir": full_path}, base_url)
            if not probe_err and isinstance(probe.get("files"), list):
                btn_key = f"{key_prefix}_folder_{full_path}"
                if st.button(f"📁 {item}", key=btn_key, use_container_width=True):
                    st.session_state[path_state_key] = full_path
                    st.rerun()
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
    st.session_state.remote_path = ""
if "selected_local_files" not in st.session_state:
    st.session_state.selected_local_files = []
if "selected_remote_files" not in st.session_state:
    st.session_state.selected_remote_files = []

# allow storing a loaded config in session so Retry button works
if "_config" not in st.session_state:
    st.session_state._config = load_config()

# ---------- Load config (prefer session override) ----------
config = st.session_state._config or {}
host_ip = config.get("host") or config.get("host_ip") or ""
dest_host = config.get("dest_host") or config.get("dest") or ""
out_dir = config.get("out_dir") or config.get("out") or ""

# Panel-specific overrides (set via buttons)
LOCAL_API = st.session_state.get("local_override_api") or st.session_state.get("local_override_api")
# backward-compat: check keys set by render_tree buttons
LOCAL_API = st.session_state.get("local_override_api") or st.session_state.get("local_override_api")

# derive from config unless override set via session_state
if not LOCAL_API:
    LOCAL_API = f"http://{host_ip}:5000" if host_ip else ""

REMOTE_API = st.session_state.get("remote_override_api") or (f"http://{dest_host}:5000" if dest_host else "")

# Support the render_tree button which sets keys like "local_override_api" using f-strings
# ensure that if render_tree set an override with key prefix like "local_override_api" it is used
if "local_override_api" in st.session_state:
    LOCAL_API = st.session_state["local_override_api"]
if "remote_override_api" in st.session_state:
    REMOTE_API = st.session_state["remote_override_api"]

# also support keys set using other prefixes (compat)
for k in ("local_override_api", "remote_override_api"):
    if k in st.session_state:
        if k.startswith("local"):
            LOCAL_API = st.session_state[k]
        else:
            REMOTE_API = st.session_state[k]

# Initialize remote paths from config if empty
if not st.session_state.remote_path and out_dir:
    st.session_state.remote_path = out_dir

# ---------- UI ----------
st.title("📁 QUIC File Transfer Manager")

if not config:
    st.warning("Configuration not found or failed to load. Use buttons below to continue (no manual input required).")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Retry load .env/config", key="retry_load_config"):
            st.session_state._config = load_config()
            st.rerun()
    with c2:
        if st.button("Use loopback defaults (127.0.0.1)", key="use_loopback_defaults"):
            st.session_state["local_override_api"] = "http://127.0.0.1:5000"
            st.session_state["remote_override_api"] = "http://127.0.0.1:5000"
            # also set a sane remote_path
            st.session_state.remote_path = "/tmp"
            st.rerun()
    with c3:
        if st.button("Set as read-only demo (no APIs)", key="demo_no_api"):
            st.session_state["local_override_api"] = ""
            st.session_state["remote_override_api"] = ""
            st.session_state.remote_path = ""
            st.rerun()

# Debug expander
with st.expander("Debug: config / endpoints"):
    st.json(config)
    st.write("LOCAL_API:", LOCAL_API)
    st.write("REMOTE_API:", REMOTE_API)
    st.write("session remote_path:", st.session_state.get("remote_path"))

col_local, col_actions, col_remote = st.columns([5, 2, 5])

with col_local:
    st.subheader("💻 Local Files")
    # allow render_tree to pick the correct API, prefer per-panel override
    panel_local_api = st.session_state.get("local_override_api") or LOCAL_API
    render_tree(panel_local_api, "local_path", "local", "selected_local_files")

with col_actions:
    st.subheader("⚡ Actions")

    # Display current remote destination (read-only)
    st.markdown("**Remote Destination:**")
    st.code(st.session_state.get("remote_path", "Not set"), language=None)

    if st.button("📋 Copy →", use_container_width=True, key="action_copy"):
        remote_dest = st.session_state.get("remote_path")
        if not remote_dest:
            st.error("Remote destination is empty. Navigate to a folder in Remote Files.")
        else:
            for full in list(st.session_state.selected_local_files):
                filename = os.path.basename(full)
                data = {"src": full, "dest": remote_dest, "filename": filename}
                result, error = call_api("copy", data, panel_local_api)
                if error:
                    st.error(f"{filename}: {error}")
                else:
                    st.success(f"Copied {filename}")

    if st.button("🔄 Move →", use_container_width=True, key="action_move"):
        remote_dest = st.session_state.get("remote_path")
        if not remote_dest:
            st.error("Remote destination is empty. Navigate to a folder in Remote Files.")
        else:
            for full in list(st.session_state.selected_local_files):
                filename = os.path.basename(full)
                data = {"src": full, "dest": remote_dest, "filename": filename}
                result, error = call_api("move", data, panel_local_api)
                if error:
                    st.error(f"{filename}: {error}")
                else:
                    st.success(f"Moved {filename}")
            st.session_state.selected_local_files = []

    if st.button("🗑️ Delete Selected Local", use_container_width=True, key="action_delete_local"):
        for full in list(st.session_state.selected_local_files):
            filename = os.path.basename(full)
            data = {"src": full}
            result, error = call_api("delete", data, panel_local_api)
            if error:
                st.error(f"{filename}: {error}")
            else:
                st.success(f"Deleted {filename}")
        st.session_state.selected_local_files = []

with col_remote:
    st.subheader("☁️ Remote Files")
    st.markdown(f"*API:* `{REMOTE_API or 'not configured'}`")
    panel_remote_api = st.session_state.get("remote_override_api") or REMOTE_API
    render_tree(panel_remote_api, "remote_path", "remote", "selected_remote_files")

# end of file
