# VesperNet PPP Bridge
# Copyright (C) 2025 Christian "fogWraith" Bergman
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <https://www.gnu.org/licenses/>.
###
import os
import sys
import socket
import logging
try:
    import serial as pyserial
except ImportError as e:
    print(f"Error: Missing required module 'pyserial'")
    print("")
    print(f"Make sure you have the pyserial module installed.")
    print(f"Install with: pip install pyserial")
    print("")
    print(f"Details: {e}")
    sys.exit(1)

IS_WINDOWS = sys.platform.startswith('win')

if not IS_WINDOWS:
    import select

def check_serial(device):
    if device.startswith(('tcp:', 'unix:')):
        return True
    
    if IS_WINDOWS:
        return True
    
    try:
        import subprocess
        result = subprocess.run(['lsof', device], capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split('\n')[1:]
            processes = []
            for line in lines:
                parts = line.split()
                if len(parts) >= 2:
                    processes.append(f"{parts[0]} (PID: {parts[1]})")
            
            if processes:
                logging.warning(f"Serial port {device} appears to be in use by: {', '.join(processes)}")
                return False
        
        return True
        
    except subprocess.TimeoutExpired:
        logging.debug("lsof check timed out")
        return True
    except FileNotFoundError:
        logging.debug("lsof not available")
        return True
    except Exception as e:
        logging.debug(f"Could not check port usage: {e}")
        return True

def open_serial(device, baud_rate):
    try:
        if not device.startswith(('tcp:', 'unix:')):
            if not os.path.exists(device):
                if IS_WINDOWS:
                    if not device.upper().startswith('COM'):
                        raise pyserial.SerialException(
                            f"Device {device} does not exist. Windows COM ports should be like COM1, COM2, etc."
                        )
                else:
                    raise pyserial.SerialException(
                        f"Device {device} does not exist. Check device path and connection."
                    )
        
        serial_port = pyserial.Serial(
            port=device,
            baudrate=baud_rate,
            bytesize=pyserial.EIGHTBITS,
            parity=pyserial.PARITY_NONE,
            stopbits=pyserial.STOPBITS_ONE,
            timeout=1.0
        )
        
        logging.info(f"Successfully opened serial port {device} at {baud_rate} baud")
        return serial_port
        
    except pyserial.SerialException as e:
        error_msg = str(e).lower()
        
        if "permission denied" in error_msg or "access is denied" in error_msg:
            if IS_WINDOWS:
                raise pyserial.SerialException(
                    f"Permission denied accessing {device}. Another program may be using this port "
                    f"or you need Administrator privileges"
                )
            else:
                raise pyserial.SerialException(
                    f"Permission denied accessing {device}. Another program may be using this port "
                    f"or your user potentially needs to be in the 'dialout' group"
                )
        
        elif "device or resource busy" in error_msg or "resource busy" in error_msg:
            raise pyserial.SerialException(
                f"Device {device} is busy. Another program is currently using this serial port. "
                f"Close other serial programs and try again"
            )
        
        elif "no such file or directory" in error_msg:
            if IS_WINDOWS:
                try:
                    import serial.tools.list_ports
                    available_ports = [port.device for port in serial.tools.list_ports.comports()]
                    ports_msg = (f"Available ports: {', '.join(available_ports)}" 
                               if available_ports else "No COM ports detected")
                except:
                    ports_msg = "Check Device Manager for available COM ports"
                
                raise pyserial.SerialException(f"COM port {device} not found. {ports_msg}")
            else:
                raise pyserial.SerialException(
                    f"Device {device} not found. Check connection and device path"
                )
        
        elif "invalid argument" in error_msg or "invalid baud rate" in error_msg:
            raise pyserial.SerialException(
                f"Invalid configuration for {device}. Try a different baud rate "
                f"(9600, 19200, 38400, 57600, 115200, etc.)"
            )
        
        else:
            raise pyserial.SerialException(f"Failed to open {device}: {e}")

class UnixSocketSerial:
    def __init__(self, socket_path):
        self.socket_path = socket_path
        self.sock = None
        self.timeout = 0.1
        self._connect()
    
    def _connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socket_path)
        self.sock.settimeout(self.timeout)
    
    def read(self, size=1):
        try:
            data = self.sock.recv(size)
            return data if data else b''
        except socket.timeout:
            return b''
        except Exception:
            return b''
    
    def write(self, data):
        try:
            return self.sock.send(data)
        except Exception:
            return 0
    
    def flush(self):
        pass
    
    @property
    def in_waiting(self):
        try:
            ready, _, _ = select.select([self.sock], [], [], 0)
            if ready:
                return 4096
            return 0
        except Exception:
            return 0
    
    def close(self):
        if self.sock:
            self.sock.close()

class TcpSocketSerial:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = None
        self.timeout = 0.1
        self._connect()
    
    def _connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.host, self.port))
        self.sock.settimeout(self.timeout)
    
    def read(self, size=1):
        try:
            data = self.sock.recv(size)
            return data if data else b''
        except socket.timeout:
            return b''
        except Exception:
            return b''
    
    def write(self, data):
        try:
            return self.sock.send(data)
        except Exception:
            return 0
    
    def flush(self):
        pass
    
    @property
    def in_waiting(self):
        try:
            original_timeout = self.sock.gettimeout()
            self.sock.settimeout(0.001)
            
            data = self.sock.recv(1, socket.MSG_PEEK)
            self.sock.settimeout(original_timeout)
            
            return 4096 if data else 0
                    
        except socket.timeout:
            try:
                self.sock.settimeout(original_timeout)
            except:
                pass
            return 0
        except socket.error:
            try:
                self.sock.settimeout(original_timeout)
            except:
                pass
            return 0
        except Exception:
            return 0
    
    def close(self):
        if self.sock:
            self.sock.close()

def open_unix_socket(socket_path, baud_rate):
    if IS_WINDOWS:
        raise RuntimeError("Unix domain sockets are not supported on Windows.")
    return UnixSocketSerial(socket_path)

def open_tcp_socket(host, port, baud_rate):
    return TcpSocketSerial(host, port)