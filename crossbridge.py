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
import json

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

try:
    from modem_utils import HayesModem, legacy_ppp_connection
except ImportError as e:
    print(f"Error: Missing required module 'modem_utils.py'")
    print("")
    print(f"Make sure modem_utils.py is in the same directory as crossbridge.py")
    print("This module can be found in the VesperNet GitHub repository.")
    print("")
    print(f"Details: {e}")
    sys.exit(1)

try:
    from serial_utils import check_serial, open_serial, open_unix_socket, open_tcp_socket
except ImportError as e:
    print(f"Error: Missing required module 'serial_utils.py'")
    print("")
    print(f"Make sure serial_utils.py is in the same directory as crossbridge.py")
    print("This module can be found in the VesperNet GitHub repository.")
    print("")
    print(f"Details: {e}")
    sys.exit(1)

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
        "baud_rate": 38400,
        "connect_speed": 33600,
        "emulate_modem": True,
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

        for key in ['server_port', 'baud_rate', 'connect_speed', 'inactivity_timeout', 'connection_retries']:
            if key in config:
                merged_config[key] = int(config[key])

        return merged_config

    except Exception as e:
        logging.error(f"Error loading configuration file: {e}")
        return default_config


def signal_handler(signum, frame):
    global running
    logging.info(f"Received signal {signum}, shutting down ...")
    running = False
    sys.exit(0)

def setup_signal_handlers():
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


def setup_logging(log_level, log_file):
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

def run_direct_bridge(serial_port, server_host, server_port, username, password, connection_retries):
    retry_count = 0
    socket_connection = None

    while retry_count < connection_retries:
        try:
            socket_connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            socket_connection.settimeout(30)
            logging.info(f"Connecting to {server_host}:{server_port} (attempt {retry_count+1}/{connection_retries})")
            socket_connection.connect((server_host, server_port))

            auth_string = f"{username}:{password}\r\n".encode()
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

            legacy_ppp_connection(serial_port, socket_connection)
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

    if retry_count >= connection_retries:
        logging.error("Maximum connection retries reached")
        return 1
    
    return 0

def main():
    parser = argparse.ArgumentParser(
        description="VesperNet PPP Bridge", 
        epilog="Connect vintage systems to VesperNet PPP services"
    )

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
    advanced_group.add_argument("--speed", type=int, help="Reported connection speed (default: 33600)")
    advanced_group.add_argument("-t", "--timeout", type=int, help="Inactivity timeout in seconds")
    advanced_group.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")
    advanced_group.add_argument("--log", help="Log file path")

    args = parser.parse_args()

    config = load_config(args.config)

    log_level = logging.DEBUG if args.verbose or config.get('debug', False) else logging.INFO
    log_file = args.log or config.get('log_file', 'crossbridge.log')
    setup_logging(log_level, log_file)

    logging.info(f"VesperNet PPP Bridge v1.5 starting")
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

    baud_rate = args.baud or config.get('baud_rate', 38400)
    connect_speed = args.speed or config.get('connect_speed', 33600)
    emu_modem = args.emulate or config.get('emulate_modem', True)
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
                
                logging.info(f"Connecting to TCP socket {host}:{port} ...")
                serial_port = open_tcp_socket(host, port, baud_rate)
                logging.info(f"Successfully connected to TCP socket {host}:{port}")
            except Exception as e:
                logging.error(f"Failed to open TCP socket {device}: {e}")
                return 1
            
        elif device.startswith('unix:'):
            try:
                socket_path = device.replace('unix:', '')
                logging.info(f"Connecting to Unix socket {socket_path} ...")
                serial_port = open_unix_socket(socket_path, baud_rate)
                logging.info(f"Successfully connected to Unix socket {socket_path}")
            except Exception as e:
                logging.error(f"Failed to open Unix socket {device}: {e}")
                return 1
        else:
            try:
                logging.info(f"Opening serial port {device} at {baud_rate} baud ...")
                serial_port = open_serial(device, baud_rate)
            except pyserial.SerialException as e:
                logging.error(f"{e}")
                return 1

        if emu_modem:
            modem = HayesModem(USER_NAME, USER_PASSWORD, DEBUG, connect_speed)
            modem.emulate_modem(serial_port, server_host, server_port)
        else:
            result = run_direct_bridge(serial_port, server_host, server_port, USER_NAME, USER_PASSWORD, connection_retries)
            return result

    except KeyboardInterrupt:
        logging.info("Operation interrupted by user")
    except Exception as e:
        logging.error(f"Unexpected error: {e}", exc_info=True)
        return 1

    finally:
        logging.info("Bridge shutdown complete")
        try:
            if serial_port:
                serial_port.close()
                logging.info(f"Closed serial port")
        except:
            pass

    return 0

if __name__ == "__main__":
    sys.exit(main())
