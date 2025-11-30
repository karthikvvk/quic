from dotenv import load_dotenv
import os

CHUNK_SIZE = 64 * 1024  # 64KB
ENV_FILE = ".env"


def write_env_file(host, port, certi, out_dir=None, src=None, key=None):
    with open(ENV_FILE, "w") as f:
        f.write(f"HOST={host}\n")
        f.write(f"PORT={port}\n")
        f.write(f"CERTI={certi}\n")
        if out_dir:
            f.write(f"OUT_DIR={out_dir}\n")
        if src:
            f.write(f"SRC={src}\n")
        if key:
            f.write(f"KEY={key}\n")


# -------------------------------
# Function to read environment variables from .env file
# -------------------------------
def load_env_vars():
    load_dotenv(ENV_FILE)
    env_vars = {
        "host": os.getenv("HOST"),
        "port": int(os.getenv("PORT", "4433")),  # default 4433 if not set
        "certi": os.getenv("CERTI"),
        "out_dir": os.getenv("OUT_DIR"),
        "src": os.getenv("SRC"),
        "key": os.getenv("KEY"),
    }
    return env_vars