You ran **client.py without arguments**, so it correctly complained.
Here is **exactly how to run both the server and client** on two PCs.

---

# ✅ 1. Run the QUIC server (receiver) on PC-1

Make sure **cert.pem** and **key.pem** are in the same folder.

```bash
python server.py --host 0.0.0.0 --port 4433 \
    --cert cert.pem --key key.pem
```

If using a virtual environment:

```bash
source $PYTHONBI
python server.py --host 0.0.0.0 --port 4433
```

You should see:

```
Starting QUIC server on 0.0.0.0:4433
```

Keep this running.

---

# ✅ 2. Run the QUIC client (sender) on PC-2

The client requires **two arguments**:

* `host` → IP of server PC
* `--file` → the file you want to upload

Example:

```bash
python client.py 192.168.1.20 --file myimage.jpg
```

Full format:

```bash
python client.py <SERVER_IP> --file <PATH_TO_FILE>
```

Example with virtualenv:

```bash
source $PYTHONBI
python client.py 192.168.1.20 --file ./sample.txt
```

---

# 🔍 Expected Output

### **Server (PC-1)**

```
[+] wrote received_files/stream-0.bin (12345 bytes)
```

File will be saved here:

```
received_files/stream-0.bin
```

### **Client (PC-2)**

```
[+] sending on stream 0
```

---

# ⚠️ Common mistakes to avoid

### ❌ Running client without arguments

You did:

```
python client.py
```

Correct is:

```
python client.py <SERVER_IP> --file <FILE>
```

---

# 👍 Working Example Test

### On Server PC:

```bash
python server.py --host 0.0.0.0 --port 4433
```

### On Client PC:

```bash
python client.py 10.0.0.15 --file test.pdf
```

---

If you want, I can also:

✅ Add filename transmission
✅ Add progress bar
✅ Allow multiple files
✅ Auto-create certificates
✅ Make a “drag & drop” UI in Streamlit for QUIC transfer

Just tell me!




openssl req -x509 -nodes -newkey rsa:2048 -keyout key.pem -out cert.pem \
  -days 365 -subj "/CN=quic-server.local"
