# VesperNet PPP Bridge Setup Guide

This guide provides instructions for setting up and running the VesperNet PPP Bridge on Linux, macOS, and Windows systems.  
The bridge allows vintage computers / emulated environments to connect to the VesperNet PPP service for an authentic dial-up internet experience.

## System Requirements

### Linux/macOS
- Python 3.8 or newer
- Physical serial port or USB-to-Serial adapter
- or
- For emulation: PTY / TCP Socket / Unix Socket

### Windows
- Python 3.8 or newer
- Physical serial port or USB-to-Serial adapter
- or
- For emulation: Null-modem emulator (com0com, com2tcp, or similar)

## Setting Up the Python Environment

### Linux/macOS

1. Install Python if not already installed:

   **Ubuntu/Debian:**
   ```bash
   sudo apt update
   sudo apt install python3 python3-pip python3-venv
   ```

   **macOS (using Homebrew):**
   ```bash
   brew install python3
   ```

2. Create a virtual environment:
   ```bash
   mkdir -p ~/vespernet
   cd ~/vespernet
   python3 -m venv .venv
   ```

3. Activate the virtual environment:
   ```bash
   source .venv/bin/activate
   ```

### Windows

1. Download and install Python from [python.org](https://www.python.org/downloads/windows/)
   - Make sure to check "Add Python to PATH" during installation

2. Open Command Prompt as Administrator

3. Create a virtual environment:
   ```cmd
   mkdir %USERPROFILE%\vespernet
   cd %USERPROFILE%\vespernet
   python -m venv .venv
   ```

4. Activate the virtual environment:
   ```cmd
   .venv\Scripts\activate
   ```

## Installing Required Packages

With your virtual environment activated, install the required packages:

```bash
# For Linux/macOS
pip install pyserial

# For Windows
pip install pyserial
```

## Installing Optional Packages

With your virtual environment activated, install the optional packages:

```bash
# For Linux/macOS
pip install uvloop

# For Windows
pip install winloop
```

## Bridge Configuration

0. Modify the supplied bridge-config.json and keep it next to crossbridge.py - or continue with steps 1 and 2 below.

1. Create a configuration file named bridge-config.json:

   ```bash
   # Linux/macOS
   nano ~/vespernet/bridge-config.json
   
   # Windows (using Notepad)
   notepad %USERPROFILE%\vespernet\bridge-config.json
   ```

   **Note** This configuration file can also be placed in the same folder as crossbridge.py.

2. Add the following configuration, adjusting values as needed:

   ```json
   {
       "username": "your_username",
       "password": "your_password",
       "server_host": "5.75.159.139",
       "server_port": 6060,
       "device": "/dev/ttyUSB0",
       "baud_rate": 38400,
       "connect_speed": 33600,
       "emulate_modem": true,
       "inactivity_timeout": 300,
       "connection_retries": 3,
       "debug": false,
       "log_file": "crossbridge.log"
   }
   ```

   **Note for Windows users:** Use COM port notation for the device, e.g., `"device": "COM3"`.

## Running the Bridge

### Modem Emulation / Direct Bridge Mode (No Modem Emulation)

Direct bridge mode is suitable when connecting directly to a computer that has PPP client software, while modem emulation mode is for vintage hardware / emulated environments that expect to dial in. Adjust the bridge-config.json accordingly.

For Direct Bridge Mode, set `emulate_modem` to `false` in the bridge-config.json file, or `true` to emulate a modem.

```bash
# Linux/macOS
cd ~/vespernet
source .venv/bin/activate
python crossbridge.py

# Windows
cd %USERPROFILE%\vespernet
.venv\Scripts\activate
python crossbridge.py
```

## Windows-Specific Setup for Emulation

When using modem emulation on Windows, you'll need a null-modem emulator to create virtual serial ports:

1. Download and install [com0com](https://sourceforge.net/projects/com0com/)

2. Using the com0com setup tool:
   - Create a pair of virtual serial ports (e.g., COM3 and COM4)
   - Make sure to install unsigned drivers if prompted

3. Configure the bridge to use one of the virtual ports:
   ```json
   "device": "COM3"
   ```

4. Configure your vintage hardware or emulator to use the other port (e.g., COM4)

5. Run the bridge with modem emulation enabled:
   ```cmd
   python crossbridge.py
   ```

6. Your vintage hardware can now dial using standard AT commands (e.g., `ATDT`)

## Connecting Physical Vintage Hardware

### Hardware Requirements

1. **USB-to-Serial Adapter**: If your modern computer doesn't have a serial port
2. **NULL Modem Cable or Adapter**: Required when connecting two DTE devices
3. **Serial Cable**: DB9 or DB25 depending on what you actually need

### Wiring Diagram for NULL Modem Connection

```
PC/Bridge Side             Vintage Hardware Side
(DB9 Female)               (DB9 Female)
     
     RXD 2 ──────────────── 3 TXD
     TXD 3 ──────────────── 2 RXD
     GND 5 ──────────────── 5 GND
     DTR 4 ──────────────── 6 DSR
     DSR 6 ──────────────── 4 DTR
     RTS 7 ──────────────── 8 CTS
     CTS 8 ──────────────── 7 RTS
```

**Note for Mac Users:** You may need a Mini-DIN-8 to DB9 adapter cable. These are often marketed as "Macintosh to PC" null modem cable.

## Troubleshooting

### Connection Issues

1. **Verify Port Configuration**:
   ```bash
   # Linux/macOS
   ls -l /dev/tty*
   
   # Windows
   mode
   ```

2. **Test Serial Port**:
   ```bash
   # Linux/macOS
   screen /dev/ttyUSB0 115200
   
   # Windows (using PuTTY)
   # Configure for your COM port and test
   ```

### Log Analysis

Check the log file for detailed error information:
```bash
# Tail the log file
tail -f crossbridge.log
```

## Additional Resources

- [VesperNet Website](http://vespernet.net)

---

For support or questions, please reach out to the VesperNet community or open an issue on our GitHub repository.
