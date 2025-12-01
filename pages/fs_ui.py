# pages/2_File_Manager.py
import streamlit as st
import requests
import os
from pathlib import Path
from startsetup import load_env_vars
from dotenv import load_dotenv
import json

st.set_page_config(page_title="QUIC File Transfer", page_icon="📁", layout="wide")
load_dotenv()

# ---------- Helpers ----------
st.markdown("""
<style>
    .stButton button { width: 100%; }
</style>
""", unsafe_allow_html=True)


def load_config():
    """Load environment/config via startsetup.load_env_vars(). Safe: returns dict."""
    try:
        env = load_env_vars()
        if not isinstance(env, dict):
            return {}
        return env
    except Exception:
        return {}


def call_api(endpoint, data, base_url):
    if not base_url:
        return None, f"Base URL not configured for endpoint {endpoint}"
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
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
    try:
        current_path = st.session_state.get(path_state_key, "")
        if not current_path:
            st.info("No path set")
            return

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
                    st.session_state[f"{key_prefix}_override_api"] = "http://127.0.0.1:5000"
                    st.rerun()
            with col2:
                if st.button("Retry loading config", key=f"{key_prefix}_retry_config"):
                    st.session_state._config = load_config()
                    st.rerun()
            return

        resp, err = call_api("listdir", {"path": current_path}, base_url)
        if err:
            st.error(f"Listing failed: {err}  \n(API: {base_url}, path: {current_path})")
            return
        items = resp.get("files", []) if isinstance(resp, dict) else []
        if not items:
            st.info("Empty directory")
            return

        if selected_key not in st.session_state:
            st.session_state[selected_key] = []

        for item in sorted(items):
            full_path = os.path.join(current_path, item)
            probe, probe_err = call_api("listdir", {"path": full_path}, base_url)
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
if "_config" not in st.session_state:
    st.session_state._config = load_config()

# ---------- Allow navigation from selector ----------
# If selector set an immediate override, use it
if st.session_state.get("remote_override_api"):
    # keep as-is
    pass

# If goto flag present from fallback navigation, apply override and clear flag
if st.session_state.get("goto_page") == "file_manager":
    remote = st.session_state.get("REMOTE_HOST") or os.environ.get("DEST_HOST")
    if remote:
        st.session_state["remote_override_api"] = f"http://{remote}:5000"
        if not st.session_state.get("remote_path"):
            # prefer OUTDIR from .env if present
            env_out = os.environ.get("OUTDIR") or os.environ.get("SRCDIR") or ""
            if env_out:
                st.session_state["remote_path"] = env_out
    st.session_state.pop("goto_page", None)

# ---------- Load config & endpoints ----------
config = st.session_state._config or {}
host_ip = config.get("host") or config.get("host_ip") or ""
dest_host = config.get("dest_host") or config.get("dest") or os.environ.get("DEST_HOST") or ""
out_dir = config.get("out_dir") or config.get("out") or os.environ.get("OUTDIR") or ""

# Panel overrides from session_state
LOCAL_API = st.session_state.get("local_override_api") or (f"http://{host_ip}:5000" if host_ip else "")
REMOTE_API = st.session_state.get("remote_override_api") or (f"http://{dest_host}:5000" if dest_host else "")

# ensure remote_path init from env/out_dir
if not st.session_state.remote_path and out_dir:
    st.session_state.remote_path = out_dir

# ---------- UI ----------
st.title("📁 QUIC File Transfer Manager")

# Top navigation: change host button
nav_col1, nav_col2 = st.columns([1, 9])
with nav_col1:
    if st.button("⬅️ Change Host"):
        # clear immediate overrides and go back to selector
        for k in ("REMOTE_HOST", "REMOTE_USER", "REMOTE_PASS", "remote_override_api"):
            st.session_state.pop(k, None)
        try:
            st.switch_page("1_Select_Host")
        except Exception:
            st.session_state["goto_page"] = "host_selector"
            st.rerun()
with nav_col2:
    st.markdown("**Remote Host:** " + (os.environ.get("DEST_HOST") or dest_host or "Not set"))

if not config:
    st.warning("Configuration not found. Use the buttons below to continue.")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Retry load .env/config", key="retry_load_config"):
            st.session_state._config = load_config()
            st.rerun()
    with c2:
        if st.button("Use loopback defaults (127.0.0.1)", key="use_loopback_defaults"):
            st.session_state["local_override_api"] = "http://127.0.0.1:5000"
            st.session_state["remote_override_api"] = "http://127.0.0.1:5000"
            st.session_state.remote_path = "/tmp"
            st.rerun()
    with c3:
        if st.button("Set demo (no APIs)", key="demo_no_api"):
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
    panel_local_api = st.session_state.get("local_override_api") or LOCAL_API
    render_tree(panel_local_api, "local_path", "local", "selected_local_files")

with col_actions:
    st.subheader("⚡ Actions")
    st.markdown("**Remote Destination:**")
    st.code(st.session_state.get("remote_path", "Not set"), language=None)

    panel_local_api = st.session_state.get("local_override_api") or LOCAL_API
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

# end
