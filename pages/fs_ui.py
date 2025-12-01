# pages/2_File_Manager.py
import streamlit as st
import requests
import os
from pathlib import Path
from startsetup import load_env_vars
from dotenv import load_dotenv

st.set_page_config(page_title="QUIC File Transfer", page_icon="📁", layout="wide")
load_dotenv()

st.markdown("""
<style>
    .stButton button { width: 100%; }
</style>
""", unsafe_allow_html=True)


def load_config():
    """Load environment/config via startsetup.load_env_vars()"""
    try:
        env = load_env_vars()
        if not isinstance(env, dict):
            return {}
        return env
    except Exception:
        return {}


def call_api(endpoint, data, base_url):
    """Make API call to peer"""
    if not base_url:
        return None, f"Base URL not configured for endpoint {endpoint}"
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    try:
        resp = requests.post(url, json=data, timeout=10)
        resp.raise_for_status()
        try:
            return resp.json(), None
        except ValueError:
            return None, f"Invalid JSON response from {url}"
    except requests.exceptions.RequestException as e:
        return None, str(e)


def format_size(size):
    """Format file size"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def render_tree(base_url, path_state_key, key_prefix, selected_key):
    """Render file tree for a peer"""
    try:
        current_path = st.session_state.get(path_state_key, "/")
        if not current_path:
            current_path = "/"
            st.session_state[path_state_key] = current_path

        # Parent navigation
        parent = os.path.dirname(current_path.rstrip("/"))
        cols = st.columns([1, 9])
        with cols[0]:
            if parent and st.button("⬆️", key=f"{key_prefix}_up_{current_path}", help="Go up"):
                st.session_state[path_state_key] = parent or "/"
                st.rerun()
        with cols[1]:
            st.markdown(f"**`{current_path}`**")

        if not base_url:
            st.warning("API endpoint not configured")
            return

        # List directory
        resp, err = call_api("listdir", {"path": current_path}, base_url)
        if err:
            st.error(f"Failed to list directory: {err}")
            return
        
        items = resp.get("files", []) if isinstance(resp, dict) else []
        if not items:
            st.info("📂 Empty directory")
            return

        if selected_key not in st.session_state:
            st.session_state[selected_key] = []

        # Render items
        for item in sorted(items):
            full_path = os.path.join(current_path, item)
            
            # Check if it's a directory
            probe, probe_err = call_api("listdir", {"path": full_path}, base_url)
            is_directory = (not probe_err and isinstance(probe, dict) and 
                          probe.get("type") == "directory")

            if is_directory:
                btn_key = f"{key_prefix}_folder_{full_path}"
                if st.button(f"📁 {item}", key=btn_key, use_container_width=True):
                    st.session_state[path_state_key] = full_path
                    st.rerun()
            else:
                cb_key = f"{key_prefix}_file_{full_path}"
                checked = st.checkbox(
                    f"📄 {item}", 
                    key=cb_key,
                    value=(full_path in st.session_state[selected_key])
                )
                if checked and full_path not in st.session_state[selected_key]:
                    st.session_state[selected_key].append(full_path)
                if (not checked) and (full_path in st.session_state[selected_key]):
                    st.session_state[selected_key].remove(full_path)
                    
    except Exception as e:
        st.error(f"Error rendering tree: {e}")


# ---------- Session State Init ----------
if "local_path" not in st.session_state:
    st.session_state.local_path = str(Path.home())

if "remote_path" not in st.session_state:
    st.session_state.remote_path = "/"

if "selected_local_files" not in st.session_state:
    st.session_state.selected_local_files = []

if "selected_remote_files" not in st.session_state:
    st.session_state.selected_remote_files = []

if "_config" not in st.session_state:
    st.session_state._config = load_config()

# Handle navigation from host selector
if st.session_state.get("goto_page") == "file_manager":
    remote = st.session_state.get("REMOTE_HOST") or os.environ.get("DEST_HOST")
    if remote:
        st.session_state["remote_override_api"] = f"http://{remote}:5000"
    st.session_state.pop("goto_page", None)

# ---------- Load Config ----------
config = st.session_state._config or {}
host_ip = config.get("host") or config.get("host_ip") or ""
dest_host = (config.get("dest_host") or config.get("dest") or 
             os.environ.get("DEST_HOST") or "")

# API endpoints
LOCAL_API = (st.session_state.get("local_override_api") or 
             (f"http://{host_ip}:5000" if host_ip else ""))
REMOTE_API = (st.session_state.get("remote_override_api") or 
              (f"http://{dest_host}:5000" if dest_host else ""))

# ---------- UI ----------
st.title("📁 Bidirectional QUIC File Transfer")

# Navigation bar
nav_col1, nav_col2 = st.columns([1, 9])
with nav_col1:
    if st.button("⬅️ Change Host"):
        for k in ("REMOTE_HOST", "REMOTE_USER", "REMOTE_PASS", "remote_override_api"):
            st.session_state.pop(k, None)
        try:
            st.switch_page("1_Select_Host")
        except Exception:
            st.session_state["goto_page"] = "host_selector"
            st.rerun()
with nav_col2:
    st.markdown(f"**Local:** `{host_ip or 'localhost'}` ⟷ **Remote:** `{dest_host or 'Not set'}`")

# Debug info
with st.expander("🔧 Debug Info"):
    st.json({
        "local_api": LOCAL_API,
        "remote_api": REMOTE_API,
        "local_path": st.session_state.get("local_path"),
        "remote_path": st.session_state.get("remote_path"),
        "selected_local": len(st.session_state.get("selected_local_files", [])),
        "selected_remote": len(st.session_state.get("selected_remote_files", []))
    })

# Main layout
col_local, col_actions, col_remote = st.columns([5, 2, 5])

with col_local:
    st.subheader("💻 Local Files")
    st.caption(f"API: {LOCAL_API or 'Not configured'}")
    render_tree(LOCAL_API, "local_path", "local", "selected_local_files")
    
    if st.session_state.selected_local_files:
        st.info(f"✅ {len(st.session_state.selected_local_files)} file(s) selected")

with col_actions:
    st.subheader("⚡ Actions")
    
    # Copy Local → Remote
    st.markdown("**Copy/Move TO Remote:**")
    st.code(st.session_state.get("remote_path", "/"), language=None)
    
    if st.button("📋 Copy →", use_container_width=True, key="copy_to_remote"):
        remote_dest = st.session_state.get("remote_path", "/")
        if not remote_dest:
            st.error("Remote path not set")
        elif not st.session_state.selected_local_files:
            st.warning("No local files selected")
        else:
            for src_path in list(st.session_state.selected_local_files):
                data = {"src": src_path, "dest": remote_dest}
                result, error = call_api("copy", data, LOCAL_API)
                if error:
                    st.error(f"❌ {os.path.basename(src_path)}: {error}")
                else:
                    st.success(f"✅ Copied {os.path.basename(src_path)}")
            st.session_state.selected_local_files = []
            st.rerun()

    if st.button("🔄 Move →", use_container_width=True, key="move_to_remote"):
        remote_dest = st.session_state.get("remote_path", "/")
        if not remote_dest:
            st.error("Remote path not set")
        elif not st.session_state.selected_local_files:
            st.warning("No local files selected")
        else:
            for src_path in list(st.session_state.selected_local_files):
                data = {"src": src_path, "dest": remote_dest}
                result, error = call_api("move", data, LOCAL_API)
                if error:
                    st.error(f"❌ {os.path.basename(src_path)}: {error}")
                else:
                    st.success(f"✅ Moved {os.path.basename(src_path)}")
            st.session_state.selected_local_files = []
            st.rerun()

    st.divider()

    # Copy Remote → Local
    st.markdown("**Copy/Move FROM Remote:**")
    st.code(st.session_state.get("local_path", str(Path.home())), language=None)
    
    if st.button("← 📋 Copy", use_container_width=True, key="copy_from_remote"):
        local_dest = st.session_state.get("local_path", str(Path.home()))
        if not local_dest:
            st.error("Local path not set")
        elif not st.session_state.selected_remote_files:
            st.warning("No remote files selected")
        else:
            for src_path in list(st.session_state.selected_remote_files):
                data = {"src": src_path, "dest": local_dest}
                result, error = call_api("copy", data, REMOTE_API)
                if error:
                    st.error(f"❌ {os.path.basename(src_path)}: {error}")
                else:
                    st.success(f"✅ Copied {os.path.basename(src_path)}")
            st.session_state.selected_remote_files = []
            st.rerun()

    if st.button("← 🔄 Move", use_container_width=True, key="move_from_remote"):
        local_dest = st.session_state.get("local_path", str(Path.home()))
        if not local_dest:
            st.error("Local path not set")
        elif not st.session_state.selected_remote_files:
            st.warning("No remote files selected")
        else:
            for src_path in list(st.session_state.selected_remote_files):
                data = {"src": src_path, "dest": local_dest}
                result, error = call_api("move", data, REMOTE_API)
                if error:
                    st.error(f"❌ {os.path.basename(src_path)}: {error}")
                else:
                    st.success(f"✅ Moved {os.path.basename(src_path)}")
            st.session_state.selected_remote_files = []
            st.rerun()

    st.divider()

    # Delete operations
    if st.button("🗑️ Delete Local", use_container_width=True, key="delete_local"):
        if not st.session_state.selected_local_files:
            st.warning("No local files selected")
        else:
            for src_path in list(st.session_state.selected_local_files):
                data = {"src": src_path}
                result, error = call_api("delete_local", data, LOCAL_API)
                if error:
                    st.error(f"❌ {os.path.basename(src_path)}: {error}")
                else:
                    st.success(f"✅ Deleted {os.path.basename(src_path)}")
            st.session_state.selected_local_files = []
            st.rerun()

    if st.button("🗑️ Delete Remote", use_container_width=True, key="delete_remote"):
        if not st.session_state.selected_remote_files:
            st.warning("No remote files selected")
        else:
            for src_path in list(st.session_state.selected_remote_files):
                data = {"src": src_path}
                result, error = call_api("delete", data, REMOTE_API)
                if error:
                    st.error(f"❌ {os.path.basename(src_path)}: {error}")
                else:
                    st.success(f"✅ Deleted {os.path.basename(src_path)}")
            st.session_state.selected_remote_files = []
            st.rerun()

with col_remote:
    st.subheader("☁️ Remote Files")
    st.caption(f"API: {REMOTE_API or 'Not configured'}")
    render_tree(REMOTE_API, "remote_path", "remote", "selected_remote_files")
    
    if st.session_state.selected_remote_files:
        st.info(f"✅ {len(st.session_state.selected_remote_files)} file(s) selected")