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
import serial
import select

running = True
IS_WINDOWS = sys.platform.startswith('win')

class PPPFrameBuffer:
    def __init__(self):
        self.buffer = b""
        self.frame_start_index = -1

    def add_data(self, data):
        self.buffer += data

    def extract_frames(self):
        frames = []

        start_index = 0
        while True:
            if start_index >= len(self.buffer):
                break

            start = self.buffer.find(b'\x7e', start_index)
            if start == -1:
                break

            end = self.buffer.find(b'\x7e', start + 1)
            if end == -1:
                self.buffer = self.buffer[start:]
                break

            frame = self.buffer[start:end+1]
            frames.append(frame)

            start_index = end + 1

        if start_index > 0 and start_index < len(self.buffer):
            self.buffer = self.buffer[start_index:]

        return frames

def load_config(config_path=None):
    import json

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

def signal_handler(signum):
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

        while running:
            if in_command_mode:
                if serial_port.in_waiting > 0:
                    data = serial_port.read(serial_port.in_waiting)
                    command_buffer += data

                    if b"\r" in command_buffer:
                        command_parts = command_buffer.split(b"\r")
                        for i, cmd_bytes in enumerate(command_parts[:-1]):
                            cmd = cmd_bytes.strip().decode("ascii", errors="ignore").upper()
                            logging.info(f"Modem command: {cmd}")

                            if "AT" in cmd:
                                if not cmd.startswith("AT"):
                                    at_index = cmd.find("AT")
                                    if at_index >= 0:
                                        cmd = cmd[at_index:]
                                        logging.info(f"Extracted AT command from noise: {cmd}")

                                if cmd.startswith("ATD"):
                                    serial_port.write(b"\r\nCONNECTING\r\n")
                                    serial_port.flush()

                                    try:
                                        socket_connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                                        socket_connection.settimeout(30)
                                        socket_connection.connect(server_address)

                                        auth_string = f"{USER_NAME}:{USER_PASSWORD}\r\n".encode()
                                        socket_connection.sendall(auth_string)
                                        logging.info(f"Sent authentication: {USER_NAME}:****")

                                        time.sleep(2)

                                        serial_port.write(b"\r\nCONNECT 33600\r\n")
                                        serial_port.flush()
                                        in_command_mode = False
                                        connected = True

                                        bridge_result = None
                                        if IS_WINDOWS:
                                            bridge_result = bridge_ppp_connection_windows(serial_port, socket_connection)
                                        else:
                                            bridge_result = bridge_ppp_connection(serial_port, socket_connection)

                                        if bridge_result == "COMMAND_MODE":
                                            logging.info("Returned to command mode")
                                            in_command_mode = True
                                            connected = True
                                        else:
                                            if socket_connection:
                                                socket_connection.close()
                                                socket_connection = None
                                            connected = False
                                            return

                                    except Exception as e:
                                        logging.error(f"Connection failed: {e}")
                                        serial_port.write(b"\r\nNO CARRIER\r\n")
                                        serial_port.flush()
                                        if socket_connection:
                                            socket_connection.close()
                                            socket_connection = None

                                elif cmd == "ATO" and connected and socket_connection:
                                    logging.info("ATO command - returning to online mode")
                                    serial_port.write(b"\r\nCONNECT 33600\r\n")
                                    serial_port.flush()
                                    in_command_mode = False

                                    bridge_result = None
                                    if IS_WINDOWS:
                                        bridge_result = bridge_ppp_connection_windows(serial_port, socket_connection)
                                    else:
                                        bridge_result = bridge_ppp_connection(serial_port, socket_connection)
                                    
                                    if bridge_result == "COMMAND_MODE":
                                        logging.info("Returned to command mode.")
                                        in_command_mode = True
                                    else:
                                        if socket_connection:
                                            socket_connection.close()
                                            socket_connection = None
                                        connected = False
                                        return

                                elif cmd == "ATH" or cmd == "ATH0":
                                    serial_port.write(b"\r\nOK\r\n")
                                    serial_port.flush()
                                    if socket_connection:
                                        socket_connection.close()
                                        socket_connection = None
                                        connected = False

                                else:
                                    serial_port.write(b"\r\nOK\r\n")
                                    serial_port.flush()

                            else:
                                serial_port.write(b"\r\nERROR\r\n")
                                serial_port.flush()

                        command_buffer = command_parts[-1]

                time.sleep(0.1)

            else:
                in_command_mode = True
                if socket_connection:
                    socket_connection.close()
                    socket_connection = None
                    connected = False

    except Exception as e:
        logging.error(f"Modem emulation error: {e}", exc_info=True)
        if socket_connection:
            try:
                socket_connection.close()
            except:
                pass

def bridge_ppp_connection(serial_port, socket_connection):
    serial_buffer = PPPFrameBuffer()
    socket_buffer = PPPFrameBuffer()

    try:
        serial_port.timeout = 0
        socket_connection.setblocking(False)

        escape_buffer = b""
        last_activity = time.time()
        last_data_from_server = time.time()
        last_data_from_serial = time.time()

        logging.info("Starting PPP data bridging (Unix mode)")

        consecutive_errors = 0
        max_consecutive_errors = 3

        while running:
            try:
                rlist, _, xlist = select.select([serial_port, socket_connection], [], [serial_port, socket_connection], 1.0)
            except (select.error, ValueError) as e:
                logging.error(f"Select error: {e}")
                break

            if xlist:
                logging.error("Exception condition on socket or serial port")
                break

            # Client to Server
            if serial_port in rlist:
                try:
                    data = serial_port.read(max(1, serial_port.in_waiting))
                    if data:
                        last_activity = time.time()
                        last_data_from_serial = time.time()

                        escape_buffer += data

                        if b"+++" in escape_buffer[-10:]:
                            if escape_buffer[-3:] == b"+++":
                                time.sleep(1)
                                if serial_port.in_waiting == 0:
                                    logging.info("Hayes escape sequence detected")
                                    serial_port.write(b"\r\nOK\r\n")
                                    serial_port.flush()
                                    return "COMMAND_MODE"

                        if b"~." in escape_buffer[-10:]:
                            logging.info("PPP escape sequence detected")
                            serial_port.write(b"\r\nNO CARRIER\r\n")
                            serial_port.flush()
                            break

                        if len(escape_buffer) > 20:
                            escape_buffer = escape_buffer[-20:]

                        logging.debug(f"Serial → Socket: {len(data)} bytes")

                        serial_buffer.add_data(data)
                        frames = serial_buffer.extract_frames()
                        if frames:
                            for frame in frames:
                                socket_connection.sendall(frame)
                        else:
                            socket_connection.sendall(data)
                except Exception as e:
                    logging.error(f"Error: {e}")
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        break
                    time.sleep(0.5)
                    continue

            # Server to Client
            if socket_connection in rlist:
                try:
                    data = socket_connection.recv(4096)
                    if data:
                        last_activity = time.time()
                        last_data_from_server = time.time()

                        if (b"\xff\x03\xc0\x21\x05" in data or  # LCP Terminate-Request
                            b"\xff\x03\xc0\x21\x06" in data):   # LCP Terminate-Ack
                            logging.info("LCP termination detected")
                            serial_port.write(data)
                            serial_port.flush()
                            time.sleep(0.5)
                            serial_port.write(b"\r\nNO CARRIER\r\n")
                            serial_port.flush()
                            break
                        
                        frames = socket_buffer.extract_frames()
                        if frames:
                            for frame in frames:
                                logging.debug(f"Socket → Serial: {len(frame)} bytes frame")
                                
                                serial_port.write(frame)
                                serial_port.flush()
                        else:
                            logging.debug(f"Socket → Serial: {len(data)} bytes")
                            
                            serial_port.write(data)
                            serial_port.flush()
                    else:
                        logging.info("Server closed connection")
                        serial_port.write(b"\r\nNO CARRIER\r\n")
                        serial_port.flush()
                        break
                except BlockingIOError:
                    pass
                except Exception as e:
                    logging.error(f"Error reading from socket: {e}")
                    break

            current_time = time.time()

            if current_time - last_activity > 300:
                logging.info("Connection timeout due to inactivity (5 minutes)")
                serial_port.write(b"\r\nNO CARRIER\r\n")
                serial_port.flush()
                break

            if current_time - last_data_from_server > 60 and current_time - last_data_from_serial < 30:
                logging.warning("Server timeout - no data received for 60 seconds")
                serial_port.write(b"\r\nNO CARRIER\r\n")
                serial_port.flush()
                break

    except Exception as e:
        logging.error(f"Bridge error: {e}", exc_info=True)

    finally:
        logging.info("Ending PPP bridge session")
        try:
            socket_connection.close()
        except:
            pass

    return "DISCONNECT"

def bridge_ppp_connection_windows(serial_port, socket_connection):
    serial_buffer = PPPFrameBuffer()
    socket_buffer = PPPFrameBuffer()

    try:
        serial_port.timeout = 0.1
        socket_connection.settimeout(0.1)
        
        escape_buffer = b""
        last_activity = time.time()
        last_data_from_server = time.time()
        last_data_from_serial = time.time()
        
        logging.info("Starting PPP data bridging (Windows mode)")
        logging.info("Sending PPP flag sequence for Windows compatibility")
        serial_port.write(b'\xff\xff\xff\x7e\xff\x7e\xff\x7e')
        ipcp_config = b'\xff\x03\x80\x21\x01\x01\x00\x10\x03\x06\x0a\x00\x00\x01\x02\x06\x00\x00\x00\x00'
        serial_port.write(ipcp_config)
        serial_port.flush()
        time.sleep(0.5)

        while running:
            if serial_port.in_waiting > 0:
                try:
                    data = serial_port.read(serial_port.in_waiting)
                    if data:
                        last_activity = time.time()
                        last_data_from_serial = time.time()

                        escape_buffer += data

                        if b"+++" in escape_buffer[-10:]:
                            if escape_buffer[-3:] == b"+++":
                                time.sleep(1)
                                if serial_port.in_waiting == 0:
                                    logging.info("Hayes escape sequence detected")
                                    serial_port.write(b"\r\nOK\r\n")
                                    serial_port.flush()
                                    return "COMMAND_MODE"

                        if b"~." in escape_buffer[-10:]:
                            logging.info("PPP escape sequence detected")
                            serial_port.write(b"\r\nNO CARRIER\r\n")
                            serial_port.flush()
                            break


                        if len(escape_buffer) > 20:
                            escape_buffer = escape_buffer[-20:]

                        serial_buffer.add_data(data)
                        frames = serial_buffer.extract_frames()

                        if frames:
                            for frame in frames:
                                logging.debug(f"Serial → Socket: {len(frame)} bytes frame")
                                socket_connection.sendall(frame)
                        else:
                            logging.debug(f"Serial → Socket: {len(data)} bytes raw")
                            socket_connection.sendall(data)
                except Exception as e:
                    logging.error(f"Error reading from serial: {e}")
                    break

            try:
                data = socket_connection.recv(4096)
                if data:
                    last_activity = time.time()
                    last_data_from_server = time.time()

                    socket_buffer.add_data(data)

                    if (b"\xff\x03\xc0\x21\x05" in data or  # LCP Terminate-Request
                        b"\xff\x03\xc0\x21\x06" in data):   # LCP Terminate-Ack
                        logging.info("LCP termination detected")
                        serial_port.write(data)
                        serial_port.flush()
                        time.sleep(0.5)
                        serial_port.write(b"\r\nNO CARRIER\r\n")
                        serial_port.flush()
                        break

                    frames = socket_buffer.extract_frames()

                    if frames:
                        for frame in frames:
                            logging.debug(f"Socket → Serial: {len(frame)} bytes frame")
                            serial_port.write(frame)
                            serial_port.flush()
                    else:
                        logging.debug(f"Socket → Serial: {len(data)} bytes raw")
                        serial_port.write(data)
                        serial_port.flush()

                elif data == b'':
                    logging.info("Server closed connection")
                    serial_port.write(b"\r\nNO CARRIER\r\n")
                    serial_port.flush()
                    break
            except socket.timeout:
                pass
            except BlockingIOError:
                pass
            except ConnectionError as e:
                logging.error(f"Socket connection error: {e}")
                break
            except Exception as e:
                logging.error(f"Error reading from socket: {e}")
                break

            current_time = time.time()

            if current_time - last_activity > 300:
                logging.info("Connection timeout due to inactivity (5 minutes)")
                serial_port.write(b"\r\nNO CARRIER\r\n")
                serial_port.flush()
                break
            
            if current_time - last_data_from_server > 60 and current_time - last_data_from_serial < 30:
                logging.warning("Server timeout - no data received for 60 seconds")
                serial_port.write(b"\r\nNO CARRIER\r\n")
                serial_port.flush()
                break

            # Windows fix
            time.sleep(0.01)

    except Exception as e:
        logging.error(f"Bridge error: {e}", exc_info=True)

    finally:
        logging.info("Ending PPP bridge session (Windows)")
        try:
            socket_connection.close()
        except:
            pass

    return "DISCONNECT"

def main():
    """Main program entry point with configuration file support."""
    parser = argparse.ArgumentParser(description="VesperNet PPP Bridge",
                                    epilog="Connect vintage systems to VesperNet PPP services")

    server_group = parser.add_argument_group('Server Connection')
    server_group.add_argument("server_addr", nargs='?', help="Server address in format host:port")
    server_group.add_argument("-u", "--username", help="Username for authentication")
    server_group.add_argument("-p", "--password", help="Password for authentication")
    server_group.add_argument("-r", "--retries", type=int, help="Number of connection retries")

    serial_group = parser.add_argument_group('Serial Port')
    serial_group.add_argument("-d", "--device", help="Serial device path")
    serial_group.add_argument("-b", "--baud", type=int, help="Baud rate")
    serial_group.add_argument("-e", "--emulate", action="store_true", 
                            help="Emulate a modem with AT commands")

    advanced_group = parser.add_argument_group('Advanced Options')
    advanced_group.add_argument("-c", "--config", help="Path to configuration file")
    advanced_group.add_argument("-t", "--timeout", type=int,
                              help="Inactivity timeout in seconds")
    advanced_group.add_argument("-v", "--verbose", action="store_true",
                              help="Enable verbose debug logging")
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

    logging.info(f"VesperNet PPP Bridge v1.0 starting")
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

    device = args.device or config.get('device', '')
    if not device:
        logging.error("No serial device specified. Use -d/--device option or set 'device' in config file.")
        return 1

    baud_rate = args.baud or config.get('baud_rate', 115200)
    emu_modem = args.emulate or config.get('emulate_modem', False)
    connection_retries = args.retries or config.get('connection_retries', 3)

    setup_signal_handlers()

    serial_port = None

    try:
        try:
            serial_port = serial.Serial(
                port=device,
                baudrate=baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1.0
            )

            logging.info(f"Opened {device} at {baud_rate} baud")
        except serial.SerialException as e:
            logging.error(f"Failed to open serial port {device}: {e}")
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

                    if IS_WINDOWS:
                        bridge_ppp_connection_windows(serial_port, socket_connection)
                    else:
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