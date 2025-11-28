import streamlit as st
import requests
import os
from helper import read_env_file

# Page configuration
st.set_page_config(
    page_title="QUIC File Transfer",
    page_icon="📁",
    layout="wide"
)

# API Configuration
API_BASE_URL = "http://localhost:5000"  # Flask API URL

def load_config():
    """Load configuration from .env file"""
    try:
        env = read_env_file()
        return env
    except Exception as e:
        st.error(f"Error loading configuration: {e}")
        return None


def call_api(endpoint, data):
    """Make API call to Flask server"""
    try:
        response = requests.post(f"{API_BASE_URL}/{endpoint}", json=data)
        response.raise_for_status()
        return response.json(), None
    except requests.exceptions.RequestException as e:
        return None, str(e)


# Main UI
st.title("📁 QUIC File Transfer Manager")
st.markdown("---")

# Load configuration
config = load_config()

if config:
    # Display connection info
    with st.sidebar:
        st.header("⚙️ Configuration")
        st.info(f"""
        **Host:** {config.get('host', 'N/A')}  
        **Port:** {config.get('port', 'N/A')}  
        **Cert:** {config.get('certi', 'N/A')}  
        **Output Dir:** {config.get('out_dir', 'N/A')}
        """)
        
        st.markdown("---")
        
        # API Server Status
        st.subheader("🔌 API Server")
        try:
            health_response = requests.get(f"{API_BASE_URL}/health", timeout=2)
            if health_response.status_code == 200:
                st.success("✅ Connected")
            else:
                st.error("❌ Not responding")
        except:
            st.error("❌ Disconnected")
        
        st.caption(f"API URL: {API_BASE_URL}")
        st.caption("Configuration loaded from .env file")

    # Create tabs for different operations
    tab1, tab2, tab3, tab4 = st.tabs(["📋 Copy", "🔄 Move", "➕ Create", "🗑️ Delete"])
    
    # Copy Tab
    with tab1:
        st.header("Copy File")
        st.markdown("Upload and copy a file to the server")
        
        uploaded_file = st.file_uploader("Choose a file to copy", key="copy_file")
        dest_copy = st.text_input(
            "Destination folder (optional)", 
            value=config.get('out_dir', ''),
            key="copy_dest",
            help="Leave empty to use default output directory"
        )
        
        if st.button("Copy File", type="primary", key="copy_btn"):
            if uploaded_file:
                try:
                    # Save uploaded file temporarily
                    temp_path = f"temp_{uploaded_file.name}"
                    with open(temp_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    
                    with st.spinner("Copying file..."):
                        # Call API
                        data = {
                            "src": temp_path,
                            "dest": dest_copy if dest_copy else None
                        }
                        result, error = call_api("copy", data)
                        
                        if error:
                            st.error(f"❌ Error: {error}")
                        else:
                            st.success(f"✅ {result.get('message', 'Successfully copied file')}")
                    
                    # Clean up temp file
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                        
                except Exception as e:
                    st.error(f"❌ Error: {e}")
                    # Clean up on error
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
            else:
                st.warning("Please select a file to copy")

    # Move Tab
    with tab2:
        st.header("Move File")
        st.markdown("Upload and move a file to the server")
        
        uploaded_file_move = st.file_uploader("Choose a file to move", key="move_file")
        dest_move = st.text_input(
            "Destination folder (optional)", 
            value=config.get('out_dir', ''),
            key="move_dest",
            help="Leave empty to use default output directory"
        )
        
        if st.button("Move File", type="primary", key="move_btn"):
            if uploaded_file_move:
                try:
                    # Save uploaded file temporarily
                    temp_path = f"temp_{uploaded_file_move.name}"
                    with open(temp_path, "wb") as f:
                        f.write(uploaded_file_move.getbuffer())
                    
                    with st.spinner("Moving file..."):
                        # Call API
                        data = {
                            "src": temp_path,
                            "dest": dest_move if dest_move else None
                        }
                        result, error = call_api("move", data)
                        
                        if error:
                            st.error(f"❌ Error: {error}")
                        else:
                            st.success(f"✅ {result.get('message', 'Successfully moved file')}")
                    
                    # Clean up temp file
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                        
                except Exception as e:
                    st.error(f"❌ Error: {e}")
                    # Clean up on error
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
            else:
                st.warning("Please select a file to move")
    
    # Create Tab
    with tab3:
        st.header("Create Empty File")
        st.markdown("Create an empty file on the server")
        
        filename_create = st.text_input(
            "Filename", 
            placeholder="example.txt",
            key="create_name"
        )
        
        if st.button("Create File", type="primary", key="create_btn"):
            if filename_create:
                try:
                    with st.spinner("Creating file..."):
                        # Call API
                        data = {"src": filename_create}
                        result, error = call_api("create", data)
                        
                        if error:
                            st.error(f"❌ Error: {error}")
                        else:
                            st.success(f"✅ {result.get('message', 'Successfully created file')}")
                            
                except Exception as e:
                    st.error(f"❌ Error: {e}")
            else:
                st.warning("Please enter a filename")
    
    # Delete Tab
    with tab4:
        st.header("Delete File")
        st.markdown("Delete a file from the server")
        
        filename_delete = st.text_input(
            "Filename", 
            placeholder="example.txt",
            key="delete_name"
        )
        
        st.warning("⚠️ This action cannot be undone!")
        
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("Delete File", type="secondary", key="delete_btn"):
                if filename_delete:
                    try:
                        with st.spinner("Deleting file..."):
                            # Call API
                            data = {"src": filename_delete}
                            result, error = call_api("delete", data)
                            
                            if error:
                                st.error(f"❌ Error: {error}")
                            else:
                                st.success(f"✅ {result.get('message', 'Successfully deleted file')}")
                                
                    except Exception as e:
                        st.error(f"❌ Error: {e}")
                else:
                    st.warning("Please enter a filename")

else:
    st.error("❌ Failed to load configuration. Please check your .env file.")
    st.info("""
    Make sure your .env file contains:
    - HOST
    - PORT
    - CERTI
    - OUT_DIR
    - KEY
    """)

# Footer
st.markdown("---")
st.caption("QUIC File Transfer Manager | Built with Streamlit")