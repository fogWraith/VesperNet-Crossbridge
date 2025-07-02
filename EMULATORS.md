# VesperNet PPP Bridge: Emulator Configuration Guide

This guide provides instructions for configuring various emulators to work with the VesperNet PPP Bridge. These configurations allow you to connect your emulated environment to VesperNet for an authentic dial-up experience.

## Table of Contents

1. [QEMU](#qemu)
2. [VirtualBox](#virtualbox)
3. [Basilisk II (Mac Emulator)](#basilisk-ii-mac-emulator)
4. [86Box (PC Emulator)](#86box-pc-emulator)

**Note about QEMU, Basilisk II:**  
If your intended guest OS target is Macintosh System / OS, we highly recommend [E-Maculation](https://www.emaculation.com/doku.php)

## QEMU

### Method 1: Unix Domain Socket (Recommended for Linux/macOS)

This method provides the most stable connection and eliminates QEMU rare freezing issues experienced with PTY devices.

#### Linux/macOS

1. Start QEMU with a Unix domain socket:
   ```bash
   qemu-system-i386 -serial unix:/tmp/qemu-serial,server,nowait [other options] your_disk_image.img
   ```

2. Configure the bridge to use the Unix socket:
   ```json
   {
     "device": "unix:/tmp/qemu-serial",
     "emulate_modem": true
   }
   ```

3. Inside the guest OS, configure the serial port (typically COM1/ttyS0) for PPP or dial-up.

### Method 2: TCP Socket (Recommended for Windows)

This method works on all platforms (Linux, macOS, Windows) and allows network-transparent connections.

#### All Platforms

1. Start QEMU with a TCP socket:
   ```bash
   qemu-system-i386 -serial tcp:localhost:4555,server,nowait [other options] your_disk_image.img
   ```

2. Configure the bridge to use the TCP socket:
   ```json
   {
     "device": "tcp:localhost:4555",
     "emulate_modem": true
   }
   ```

3. Inside the guest OS, configure the serial port (typically COM1/ttyS0) for PPP or dial-up.

### Method 3: PTY Device (Legacy Method)

**Note:** This method is provided for compatibility but may cause stability issues with PPP connections. This is based on own experiences.

#### Linux/macOS

1. Start QEMU with a serial port mapped to a PTY:
   ```bash
   qemu-system-i386 -serial pty [other options] your_disk_image.img
   ```

2. QEMU will output the PTY device path it created, for example:
   ```
   char device redirected to /dev/pts/3
   ```

3. Configure the bridge to use this PTY device:
   ```json
   {
     "device": "/dev/pts/3",
     "emulate_modem": true
   }
   ```

4. Inside the guest OS, configure the serial port (typically COM1/ttyS0) for PPP or dial-up.

### Windows Host Considerations

For QEMU running on Windows hosts:

#### TCP Socket (Recap, recommended method)
```cmd
qemu-system-i386 -serial tcp:localhost:4555,server,nowait [other options] your_disk_image.img
```

Configuration:
```json
{
  "device": "tcp:localhost:4555",
  "emulate_modem": true
}
```

#### Named Pipe (Alternative)
```cmd
qemu-system-i386 -serial pipe:qemu-serial [other options] your_disk_image.img
```

This creates `\\.\pipe\qemu-serial` which can be accessed by the bridge.

#### Virtual COM Port (com0com)
With com0com installed:
```cmd
qemu-system-i386 -serial com:COM3 [other options] your_disk_image.img
```

Configuration:
```json
{
  "device": "COM3",
  "emulate_modem": true
}
```

## VirtualBox

1. Open VirtualBox Manager and select your VM

2. Go to Settings → Serial Ports

3. Check "Enable Serial Port"

4. Configure Port 1:
   - Port Number: COM1
   - Port Mode: Host Pipe (Linux/macOS) or Host Device (Windows)
   - Path/Address:
     - Linux/macOS: `/tmp/vbox-serial1`
     - Windows: `\\.\pipe\vbox-serial1` or a physical/virtual COM port

5. Click OK to save

6. Configure the bridge to use the same path/device:
   ```json
   "device": "/tmp/vbox-serial1"  # Linux/macOS
   "device": "\\.\pipe\vbox-serial1"  # Windows
   ```

7. Inside the guest OS, configure the serial port (COM1) for PPP or dial-up

## Basilisk II (Mac Emulator)

1. Edit the Basilisk II preferences file or use the GUI:

2. Set the serial port options:
   - Linux/macOS: `seriala /dev/ptmx` (for dynamic PTY allocation)
   - Windows: `seriala COM3` (or your virtual COM port)

3. For Linux/macOS, after starting Basilisk II, check which PTY device was created:
   ```bash
   ls -la /dev/pts/
   ```

4. Configure the bridge to use this device:
   ```json
   "device": "/dev/pts/3"  # Replace with your detected device
   ```

5. In the emulated MacOS, configure the PPP or modem software to use the Modem Port

## 86Box (PC Emulator)

1. In 86Box, click on Settings

2. Navigate to "Ports (COM & LPT)"

3. Configure a COM port:
   - Set "COM1" to "Enabled"
   - Set "COM1 Device" to:
     - "Serial Port" for direct connections
     - "Modem" if you want to use 86Box's internal modem emulation

4. For the "Serial Port" option, specify:
   - Linux: A PTY device like `/dev/pts/3`
   - Windows: A physical or virtual COM port like `COM3`

5. Click OK to save settings

6. Configure the bridge to use the corresponding device:
   ```json
   "device": "/dev/pts/3"  # Linux example
   "device": "COM3"  # Windows example
   ```

7. In the emulated OS, configure the modem or PPP settings to use COM1
