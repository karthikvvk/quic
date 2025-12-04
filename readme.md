# **QUIC File Transfer System**

A lightweight QUIC-based file transfer system using Python, Flask, and Streamlit.
This project enables fast, direct file transfers within a local network using QUIC (UDP) as the underlying transport protocol.

---

## **📂 Project Structure**

```
.File Sharing application or can also said as Wrapper protocol that leverage the power of QUIC by reducing TCP HOL


├── server.py           # QUIC sender & receiver
├── client.py           # TCP communicator
├── scanner.py          # Local network scanner
├── host_selecter.py    # Selecting hosts UI
├── pages/fs_ui.py      # File manager UI (Actual FS UI)
├── startsetup.py       # Environment setup script
├── host_list.json      # Auto-generated host list
├── ipsn.txt            # Detected IPs (auto-generated)
├── cert.pem            # TLS certificate (auto-generated)
├── key.pem             # TLS private key (auto-generated)
├── requirement.txtt    # Python dependencies
└── readme.md           # Project documentation
```

---

## **⚙️ Prerequisites**

Before running the project, ensure the following:

1. **Your system must be connected to a network** (WiFi or LAN).
2. **Windows users must use Python ≤ 3.11**

   * Python 3.12+ does **NOT** support required QUIC libraries.
3. **Be patient when running commands**

   * QUIC uses UDP and may take a moment to initialize.

---

## **📦 Installation**

### **1. Install Python dependencies**

```sh
pip install -r requirement.txtt
```

### **2. Run setup**

```sh
python startsetup.py
```

This script generates environment files, writes keys, and prepares necessary configuration for the system.

---

## **Running the System**

You must use **three terminals**:

---

### **Terminal 1 — Start QUIC Server (Receiver)**

```sh
python server.py
```

---

### **Terminal 2 — Start QUIC Client (Sender)**

```sh
python client.py
```

---

### **Terminal 3 — Start Host Selection UI (Streamlit)**

```sh
streamlit run host_selecter.py
```

This UI allows you to:

* Scan for devices in the local network
* View available IP addresses
* Choose a target host
* Initiate file transfers

---
