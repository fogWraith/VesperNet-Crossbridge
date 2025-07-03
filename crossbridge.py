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
import signal
import socket
import argparse
import sys
import time
import logging
import serial as pyserial
import json

DEBUG = False
USER_NAME = ""
USER_PASSWORD = ""
IS_WINDOWS = sys.platform.startswith('win')

running = True

def load_config(config_path=None):
    default_config = {
        "username": "",
        "password": "",
        "server_host": "",
        "server_port": 6060,
        "device": "",
        "baud_rate": 115200,
        "emulate_modem": False,
        "inactivity_timeout": 300,
        "connection_retries": 3,
        "debug": False,
        "log_file": "crossbridge.log"
    }

    if not config_path:
        possible_locations = []

        if IS_WINDOWS:
            appdata = os.environ.get('APPDATA', '')
            if appdata:
                possible_locations.append(os.path.join(appdata, 'VesperNet', 'config.json'))
            possible_locations.append('bridge-config.json')
        else:
            home = os.environ.get('HOME', '')
            if home:
                possible_locations.append(os.path.join(home, '.vespernet', 'config.json'))
                possible_locations.append(os.path.join(home, '.config', 'vespernet', 'config.json'))
            possible_locations.append('/etc/vespernet/config.json')
            possible_locations.append('bridge-config.json')

        for location in possible_locations:
            if os.path.exists(location):
                config_path = location
                break

    if not config_path or not os.path.exists(config_path):
        logging.info("No configuration file found, using defaults")
        return default_config

    try:
        with open(config_path, 'r') as f:
            config = json.load(f)

        merged_config = {**default_config, **config}
        logging.info(f"Loaded configuration from {config_path}")

        if 'server_port' in config:
            merged_config['server_port'] = int(config['server_port'])
        if 'baud_rate' in config:
            merged_config['baud_rate'] = int(config['baud_rate'])
        if 'inactivity_timeout' in config:
            merged_config['inactivity_timeout'] = int(config['inactivity_timeout'])
        if 'connection_retries' in config:
            merged_config['connection_retries'] = int(config['connection_retries'])

        return merged_config

    except Exception as e:
        logging.error(f"Error loading configuration file: {e}")
        return default_config

def signal_handler(signum, frame):
    global running
    logging.info(f"Received signal {signum}, shutting down...")
    running = False
    sys.exit(0)

def setup_signal_handlers():
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

def emulate_modem(serial_port, server_host, server_port):
    try:
        server_address = (server_host, server_port)
        socket_connection = None
        connected = False
        in_command_mode = True
        command_buffer = b""
        connection_established = False
        dial_count = 0
        ppp_data_received = False
        first_connect_time = 0
        
        while running:
            if in_command_mode:
                if serial_port.in_waiting > 0:
                    data = serial_port.read(serial_port.in_waiting)
                    command_buffer += data

                    if connection_established and not ppp_data_received:
                        if b'~}' in data or b'\x7e' in data or b'\xff\x03' in data:
                            logging.info("PPP data detected in command mode - client starting PPP negotiation")
                            ppp_data_received = True
                            
                            if socket_connection:
                                socket_connection.sendall(data)
                                in_command_mode = False
                                logging.info("Entering PPP data mode due to client-initiated PPP negotiation")
                                
                                bridge_result = bridge_ppp_connection(serial_port, socket_connection)
                                
                                if bridge_result == "COMMAND_MODE":
                                    logging.info("Returned to command mode")
                                    in_command_mode = True
                                    ppp_data_received = False
                                else:
                                    if socket_connection:
                                        socket_connection.close()
                                        socket_connection = None
                                    connected = False
                                    connection_established = False
                                    dial_count = 0
                                    ppp_data_received = False
                                    first_connect_time = 0
                                    return
                            continue

                    if b"\r" in command_buffer:
                        command_parts = command_buffer.split(b"\r")
                        for i, cmd_bytes in enumerate(command_parts[:-1]):
                            cmd = cmd_bytes.strip().decode("ascii", errors="ignore").upper()
                            
                            if not cmd:
                                continue
                                
                            logging.info(f"Modem command: {cmd}")

                            if "AT" in cmd:
                                if not cmd.startswith("AT"):
                                    at_index = cmd.find("AT")
                                    if at_index >= 0:
                                        cmd = cmd[at_index:]
                                        logging.info(f"Extracted AT command from noise: {cmd}")

                                if cmd.startswith("ATD"):
                                    dial_count += 1
                                    logging.info(f"Dial attempt #{dial_count}: {cmd}")
                                    
                                    if not connection_established:
                                        serial_port.write(b"\r\nCONNECTING\r\n")
                                        serial_port.flush()

                                        try:
                                            if socket_connection:
                                                socket_connection.close()
                                            
                                            socket_connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                                            socket_connection.settimeout(30)
                                            socket_connection.connect(server_address)

                                            auth_string = f"{USER_NAME}:{USER_PASSWORD}\r\n".encode()
                                            socket_connection.sendall(auth_string)
                                            logging.info(f"Sent authentication: {USER_NAME}:****")

                                            time.sleep(1)

                                            socket_connection.settimeout(2)
                                            try:
                                                response = socket_connection.recv(1024)
                                                if b"Authentication failed" in response:
                                                    logging.error("Authentication failed")
                                                    serial_port.write(b"\r\nNO CARRIER\r\n")
                                                    serial_port.flush()
                                                    socket_connection.close()
                                                    socket_connection = None
                                                    continue
                                            except socket.timeout:
                                                pass

                                            serial_port.write(b"\r\nCONNECT 33600\r\n")
                                            serial_port.flush()
                                            connection_established = True
                                            connected = True
                                            first_connect_time = time.time()
                                            
                                            logging.info("Connection established, monitoring for PPP data or second dial")

                                        except Exception as e:
                                            logging.error(f"Connection failed: {e}")
                                            serial_port.write(b"\r\nNO CARRIER\r\n")
                                            serial_port.flush()
                                            if socket_connection:
                                                socket_connection.close()
                                                socket_connection = None
                                            connection_established = False
                                            dial_count = 0

                                    else:
                                        logging.info("Second dial detected - starting PPP data mode")
                                        serial_port.write(b"\r\nCONNECT 33600\r\n")
                                        serial_port.flush()
                                        in_command_mode = False

                                        if socket_connection:
                                            bridge_result = bridge_ppp_connection(serial_port, socket_connection)

                                            if bridge_result == "COMMAND_MODE":
                                                logging.info("Returned to command mode")
                                                in_command_mode = True
                                            else:
                                                if socket_connection:
                                                    socket_connection.close()
                                                    socket_connection = None
                                                connected = False
                                                connection_established = False
                                                dial_count = 0
                                                ppp_data_received = False
                                                first_connect_time = 0
                                                return

                                elif cmd == "ATO" and connected and socket_connection:
                                    logging.info("ATO command - returning to online mode")
                                    serial_port.write(b"\r\nCONNECT 33600\r\n")
                                    serial_port.flush()
                                    in_command_mode = False

                                    bridge_result = bridge_ppp_connection(serial_port, socket_connection)
                                    
                                    if bridge_result == "COMMAND_MODE":
                                        logging.info("Returned to command mode")
                                        in_command_mode = True
                                    else:
                                        if socket_connection:
                                            socket_connection.close()
                                            socket_connection = None
                                        connected = False
                                        connection_established = False
                                        dial_count = 0
                                        ppp_data_received = False
                                        first_connect_time = 0
                                        return

                                elif cmd == "ATH" or cmd == "ATH0":
                                    logging.info("Hangup command received")
                                    serial_port.write(b"\r\nOK\r\n")
                                    serial_port.flush()
                                    if socket_connection:
                                        socket_connection.close()
                                        socket_connection = None
                                    connected = False
                                    connection_established = False
                                    dial_count = 0
                                    ppp_data_received = False
                                    first_connect_time = 0

                                elif cmd in ["ATZ", "ATM1L1", "ATX3", "ATE1", "ATE0", "ATQ0", "ATV1"]:
                                    logging.debug(f"Modem init command: {cmd}")
                                    serial_port.write(b"\r\nOK\r\n")
                                    serial_port.flush()

                                elif cmd.startswith("ATE"):
                                    logging.debug(f"Echo control command: {cmd}")
                                    serial_port.write(b"\r\nOK\r\n")
                                    serial_port.flush()

                                else:
                                    logging.debug(f"Generic AT command: {cmd}")
                                    serial_port.write(b"\r\nOK\r\n")
                                    serial_port.flush()

                            else:
                                if connection_established and (b'~}' in cmd.encode() or b'\x7e' in cmd.encode()):
                                    logging.info("PPP-like data in non-AT command - treating as PPP start")
                                    ppp_data_received = True
                                    
                                    if socket_connection:
                                        socket_connection.sendall(cmd_bytes + b'\r')
                                        in_command_mode = False
                                        
                                        bridge_result = bridge_ppp_connection(serial_port, socket_connection)
                                        
                                        if bridge_result == "COMMAND_MODE":
                                            in_command_mode = True
                                            ppp_data_received = False
                                        else:
                                            if socket_connection:
                                                socket_connection.close()
                                                socket_connection = None
                                            connected = False
                                            connection_established = False
                                            dial_count = 0
                                            ppp_data_received = False
                                            first_connect_time = 0
                                            return
                                else:
                                    logging.warning(f"Non-AT command received: {repr(cmd)}")
                                    serial_port.write(b"\r\nERROR\r\n")
                                    serial_port.flush()

                        command_buffer = command_parts[-1]

                if (connection_established and not ppp_data_received and 
                    first_connect_time > 0 and (time.time() - first_connect_time) > 10):
                    
                    logging.info("Timeout waiting for second dial - assuming client wants immediate PPP mode")
                    in_command_mode = False
                    ppp_data_received = True
                    
                    if socket_connection:
                        bridge_result = bridge_ppp_connection(serial_port, socket_connection)
                        
                        if bridge_result == "COMMAND_MODE":
                            in_command_mode = True
                            ppp_data_received = False
                        else:
                            if socket_connection:
                                socket_connection.close()
                                socket_connection = None
                            connected = False
                            connection_established = False
                            dial_count = 0
                            ppp_data_received = False
                            first_connect_time = 0
                            return

                time.sleep(0.1)

            else:
                logging.warning("Unexpected transition to data mode (report this to fogWraith)")
                in_command_mode = True

    except Exception as e:
        logging.error(f"Modem emulation error: {e}", exc_info=True)
        if socket_connection:
            try:
                socket_connection.close()
            except:
                pass

def bridge_ppp_connection(serial_port, socket_connection):
    try:
        platform_name = "Windows" if IS_WINDOWS else "Unix"
        logging.info(f"Starting PPP data bridging ({platform_name} mode)")
        
        serial_port.timeout = 0.1
        socket_connection.settimeout(0.1)
        
        escape_buffer = b""
        last_activity = time.time()
        idle_count = 0

        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while running:
            data_handled = False
            current_time = time.time()

            try:
                if serial_port.in_waiting > 0:
                    if hasattr(serial_port, 'sock'):
                        data = serial_port.read(4096)
                    else:
                        data = serial_port.read(serial_port.in_waiting)

                    if data:
                        data_handled = True
                        last_activity = current_time
                        consecutive_errors = 0
                        
                        if DEBUG:
                            logging.debug(f"Serial->Server: {len(data)} bytes: {data.hex()}")
                        elif len(data) > 100:
                            logging.info(f"Read {len(data)} bytes from {'socket' if hasattr(serial_port, 'sock') else 'serial'}")

                        escape_buffer += data
                        if len(escape_buffer) > 20:
                            escape_buffer = escape_buffer[-20:]

                        if b"+++" in escape_buffer[-10:]:
                            plus_index = escape_buffer.rfind(b"+++")
                            if plus_index >= 0:
                                remaining = escape_buffer[plus_index + 3:]
                                if len(remaining) == 0:
                                    time.sleep(1)
                                    if serial_port.in_waiting == 0:
                                        logging.info("Hayes escape sequence detected")
                                        serial_port.write(b"\r\nOK\r\n")
                                        serial_port.flush()
                                        return "COMMAND_MODE"
                        
                        if DEBUG:
                            if b'\xff\x03\x80\x21' in data:
                                logging.info("Client sent IPCP packet")
                            elif b'\xff\x03\xc0\x21' in data:
                                lcp_start = data.find(b'\xff\x03\xc0\x21')
                                if lcp_start >= 0 and len(data) > lcp_start + 4:
                                    lcp_type = data[lcp_start + 4]
                                    if lcp_type == 1:
                                        logging.info("Client sent LCP Configure-Request")
                                    elif lcp_type == 2:
                                        logging.info("Client sent LCP Configure-Ack")
                                    elif lcp_type == 9:
                                        logging.info("Client sent LCP Echo-Request")
                        
                        socket_connection.sendall(data)
                        time.sleep(0.001)
                        
            except pyserial.SerialTimeoutException:
                pass
            except pyserial.SerialException as e:
                consecutive_errors += 1
                logging.error(f"Serial port error ({consecutive_errors}/{max_consecutive_errors}): {e}")
                if consecutive_errors >= max_consecutive_errors:
                    logging.error("Too many serial errors, disconnecting")
                    break
            except Exception as e:
                consecutive_errors += 1
                logging.error(f"Error reading from serial port ({consecutive_errors}): {e}")
                if consecutive_errors >= max_consecutive_errors:
                    break
            
            try:
                data = socket_connection.recv(4096)
                if data:
                    data_handled = True
                    last_activity = current_time
                    consecutive_errors = 0
                    
                    if DEBUG:
                        logging.debug(f"Server->Serial: {len(data)} bytes: {data.hex()}")
                    
                    if (b"\xff\x03\xc0\x21\x05" in data or
                        b"\xff\x03\xc0\x21\x06" in data):
                        logging.info("LCP termination detected")
                        serial_port.write(data)
                        serial_port.flush()
                        time.sleep(0.5)
                        serial_port.write(b"\r\nNO CARRIER\r\n")
                        serial_port.flush()
                        break
                    
                    if DEBUG:
                        if b'\xff\x03\xc0\x21' in data:
                            lcp_start = data.find(b'\xff\x03\xc0\x21')
                            if lcp_start >= 0 and len(data) > lcp_start + 4:
                                lcp_type = data[lcp_start + 4]
                                if lcp_type == 1:
                                    logging.info("Server sent LCP Configure-Request")
                                elif lcp_type == 2:
                                    logging.info("Server sent LCP Configure-Ack")
                                elif lcp_type == 10:
                                    logging.info("Server sent LCP Echo-Reply")
                    
                    serial_port.write(data)
                    serial_port.flush()
                    time.sleep(0.001)
                    
                elif data == b'':
                    logging.info("Server closed connection")
                    serial_port.write(b"\r\nNO CARRIER\r\n")
                    serial_port.flush()
                    break
                    
            except socket.timeout:
                pass
            except ConnectionError as e:
                logging.error(f"Server connection lost: {e}")
                serial_port.write(b"\r\nNO CARRIER\r\n")
                serial_port.flush()
                break
            except Exception as e:
                consecutive_errors += 1
                logging.error(f"Error reading from server ({consecutive_errors}): {e}")
                if consecutive_errors >= max_consecutive_errors:
                    break
            
            if current_time - last_activity > 300:
                logging.info("Connection timeout due to inactivity")
                serial_port.write(b"\r\nNO CARRIER\r\n")
                serial_port.flush()
                break

            if not data_handled:
                idle_count += 1
                if idle_count < 10:
                    time.sleep(0.01)
                elif idle_count < 50:
                    time.sleep(0.02)
                else:
                    time.sleep(0.05)
            else:
                idle_count = 0
                time.sleep(0.002)

    except Exception as e:
        logging.error(f"Bridge error: {e}")
        try:
            serial_port.write(b"\r\nNO CARRIER\r\n")
            serial_port.flush()
        except:
            pass
    finally:
        logging.info(f"PPP bridge session ended ({platform_name})")
        try:
            socket_connection.close()
        except:
            pass

    return "DISCONNECT"

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
                        raise pyserial.SerialException(f"Device {device} does not exist. Windows COM ports should be like COM1, COM2, etc.")
                else:
                    raise pyserial.SerialException(f"Device {device} does not exist. Check device path and connection.")
        
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
                raise pyserial.SerialException(f"Permission denied accessing {device}. Another program may be using this port or you need Administrator privileges")
            else:
                raise pyserial.SerialException(f"Permission denied accessing {device}. Another program may be using this port or your user potentially needs to be in the 'dialout' group")
        
        elif "device or resource busy" in error_msg or "resource busy" in error_msg:
            raise pyserial.SerialException(f"Device {device} is busy. Another program is currently using this serial port. Close other serial programs and try again")
        
        elif "no such file or directory" in error_msg:
            if IS_WINDOWS:
                try:
                    import serial.tools.list_ports
                    available_ports = [port.device for port in serial.tools.list_ports.comports()]
                    ports_msg = f"Available ports: {', '.join(available_ports)}" if available_ports else "No COM ports detected"
                except:
                    ports_msg = "Check Device Manager for available COM ports"
                
                raise pyserial.SerialException(f"COM port {device} not found. {ports_msg}")
            else:
                raise pyserial.SerialException(f"Device {device} not found. Check connection and device path")
        
        elif "invalid argument" in error_msg or "invalid baud rate" in error_msg:
            raise pyserial.SerialException(f"Invalid configuration for {device}. Try a different baud rate (9600, 19200, 38400, 57600, 115200, etc.)")
        
        else:
            raise pyserial.SerialException(f"Failed to open {device}: {e}")

def open_unix_socket(socket_path, baud_rate):
    import socket as sock
    import select
    
    class UnixSocketSerial:
        def __init__(self, socket_path):
            self.socket_path = socket_path
            self.sock = None
            self.timeout = 0.1
            self._connect()
        
        def _connect(self):
            self.sock = sock.socket(sock.AF_UNIX, sock.SOCK_STREAM)
            self.sock.connect(self.socket_path)
            self.sock.settimeout(self.timeout)
        
        def read(self, size=1):
            try:
                data = self.sock.recv(size)
                return data if data else b''
            except sock.timeout:
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
    
    return UnixSocketSerial(socket_path)

def open_tcp_socket(host, port, baud_rate):
    import socket as sock
    
    class TcpSocketSerial:
        def __init__(self, host, port):
            self.host = host
            self.port = port
            self.sock = None
            self.timeout = 0.1
            self._data_available = False
            self._connect()
        
        def _connect(self):
            self.sock = sock.socket(sock.AF_INET, sock.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            self.sock.settimeout(self.timeout)
        
        def read(self, size=1):
            try:
                data = self.sock.recv(size)
                if data:
                    self._data_available = False
                    return data
                else:
                    return b''
            except sock.timeout:
                self._data_available = False
                return b''
            except Exception:
                self._data_available = False
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
                
                data = self.sock.recv(1, sock.MSG_PEEK)
                
                self.sock.settimeout(original_timeout)
                
                if data:
                    return 4096
                else:
                    return 0
                    
            except sock.timeout:
                self.sock.settimeout(original_timeout)
                return 0
            except sock.error:
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
    
    return TcpSocketSerial(host, port)

def main():
    parser = argparse.ArgumentParser(description="VesperNet PPP Bridge", epilog="Connect vintage systems to VesperNet PPP services")

    server_group = parser.add_argument_group('Server Connection')
    server_group.add_argument("server_addr", nargs='?', help="Server address in format host:port")
    server_group.add_argument("-u", "--username", help="Username for authentication")
    server_group.add_argument("-p", "--password", help="Password for authentication")
    server_group.add_argument("-r", "--retries", type=int, help="Number of connection retries")

    serial_group = parser.add_argument_group('Serial Port')
    serial_group.add_argument("-d", "--device", help="Serial device path")
    serial_group.add_argument("-b", "--baud", type=int, help="Baud rate")
    serial_group.add_argument("-e", "--emulate", action="store_true", help="Emulate a modem with AT commands")

    advanced_group = parser.add_argument_group('Advanced Options')
    advanced_group.add_argument("-c", "--config", help="Path to configuration file")
    advanced_group.add_argument("-t", "--timeout", type=int, help="Inactivity timeout in seconds")
    advanced_group.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")
    advanced_group.add_argument("--log", help="Log file path")

    args = parser.parse_args()

    config = load_config(args.config)

    log_level = logging.DEBUG if args.verbose or config.get('debug', False) else logging.INFO
    log_file = args.log or config.get('log_file', 'crossbridge.log')

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(log_level)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logging.info(f"VesperNet PPP Bridge v1.3 starting")
    logging.info(f"Platform: {sys.platform}")

    global USER_NAME, USER_PASSWORD, DEBUG
    DEBUG = args.verbose or config.get('debug', False)
    USER_NAME = args.username or config.get('username', '')
    USER_PASSWORD = args.password or config.get('password', '')

    server_addr = args.server_addr or f"{config.get('server_host', 'localhost')}:{config.get('server_port', 6060)}"

    if ":" in server_addr:
        server_host, port_str = server_addr.split(":", 1)
        try:
            server_port = int(port_str)
        except ValueError:
            logging.error(f"Invalid port number: {port_str}")
            return 1
    else:
        server_host = server_addr
        server_port = config.get('server_port', 6060)

    baud_rate = args.baud or config.get('baud_rate', 115200)
    emu_modem = args.emulate or config.get('emulate_modem', False)
    connection_retries = args.retries or config.get('connection_retries', 3)

    setup_signal_handlers()

    serial_port = None

    try:
        device = args.device or config.get('device', '')
        if not device:
            logging.error("No serial device specified. Use -d/--device option or set 'device' in config file.")
            return 1
        
        if not check_serial(device):
            logging.warning("Serial port appears to be in use by another program. Close other serial programs and try again.")
        
        if device.startswith('tcp:'):
            try:
                _, host_port = device.split(':', 1)
                if ':' in host_port:
                    host, port_str = host_port.rsplit(':', 1)
                    port = int(port_str)
                else:
                    host = host_port
                    port = 23
                
                logging.info(f"Connecting to TCP socket {host}:{port}...")
                serial_port = open_tcp_socket(host, port, baud_rate)
                logging.info(f"Successfully connected to TCP socket {host}:{port}")
            except Exception as e:
                logging.error(f"Failed to open TCP socket {device}: {e}")
                return 1
            
        elif device.startswith('unix:'):
            try:
                socket_path = device.replace('unix:', '')
                logging.info(f"Connecting to Unix socket {socket_path}...")
                serial_port = open_unix_socket(socket_path, baud_rate)
                logging.info(f"Successfully connected to Unix socket {socket_path}")
            except Exception as e:
                logging.error(f"Failed to open Unix socket {device}: {e}")
                return 1
        else:
            try:
                logging.info(f"Opening serial port {device} at {baud_rate} baud...")
                serial_port = open_serial(device, baud_rate)
            except pyserial.SerialException as e:
                logging.error(f"{e}")
                return 1

        if emu_modem:
            emulate_modem(serial_port, server_host, server_port)
        else:
            retry_count = 0
            socket_connection = None

            while retry_count < connection_retries:
                try:
                    socket_connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    socket_connection.settimeout(30)
                    logging.info(f"Connecting to {server_host}:{server_port} (attempt {retry_count+1}/{connection_retries})")
                    socket_connection.connect((server_host, server_port))

                    auth_string = f"{USER_NAME}:{USER_PASSWORD}\r\n".encode()
                    socket_connection.sendall(auth_string)

                    time.sleep(1)

                    socket_connection.settimeout(5)
                    try:
                        response = socket_connection.recv(1024)
                        if b"Authentication failed" in response:
                            logging.error("Authentication failed")
                            socket_connection.close()
                            return 1
                    except socket.timeout:
                        pass

                    bridge_ppp_connection(serial_port, socket_connection)

                    socket_connection.close()
                    break

                except socket.timeout:
                    logging.error("Connection timed out")
                    if socket_connection:
                        socket_connection.close()
                except socket.error as e:
                    logging.error(f"Socket error: {e}")
                    if socket_connection:
                        socket_connection.close()

                retry_count += 1
                if retry_count < connection_retries:
                    wait_time = 2 ** retry_count
                    logging.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)

    except KeyboardInterrupt:
        logging.info("Operation interrupted by user")
    except Exception as e:
        logging.error(f"Unexpected error: {e}", exc_info=True)

    finally:
        logging.info("Bridge shutdown complete")
        try:
            if serial_port:
                serial_port.close()
                logging.info(f"Closed serial port {device}")
        except:
            pass

        return 0

if __name__ == "__main__":
    main()
