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
import socket
import time
import logging
import sys

DEBUG = False
IS_WINDOWS = sys.platform.startswith('win')

class HayesModem:
    def __init__(self, username, password, debug=False, connect_speed=None):
        self.username = username
        self.password = password
        self.debug = debug
        global DEBUG
        DEBUG = debug
        self.connect_speed = connect_speed or 33600

        self.socket_connection = None
        self.connected = False
        self.in_command_mode = True
        self.command_buffer = b""
        self.disconnecting = False
        
    def emulate_modem(self, serial_port, server_host, server_port):
        try:
            server_address = (server_host, server_port)
            logging.info("Modem emulation started - waiting for AT commands")
            
            while True:
                if self.in_command_mode:
                    self._handle_command_mode(serial_port, server_address)
                else:
                    if not self.connected:
                        logging.info("Returning to command mode after connection ended")
                        self.in_command_mode = True
                        self.disconnecting = False
                    else:
                        logging.warning("Unexpected state: not in command mode but in main loop")
                        self.in_command_mode = True
                
                time.sleep(0.01)
                
        except Exception as e:
            logging.error(f"Modem emulation error: {e}", exc_info=True)
        finally:
            self._cleanup_connection()
    
    def _handle_command_mode(self, serial_port, server_address):
        if serial_port.in_waiting > 0:
            data = serial_port.read(serial_port.in_waiting)
            self.command_buffer += data

            if self.connected and self.socket_connection and not self.disconnecting:
                if self._is_ppp_data(data):
                    logging.info("PPP data detected - entering data mode immediately")
                    self.socket_connection.sendall(data)
                    self.in_command_mode = False
                    
                    bridge_result = self._bridge_ppp_connection(serial_port)
                    
                    if bridge_result == "COMMAND_MODE":
                        logging.info("Returned to command mode via escape sequence")
                        self.in_command_mode = True
                    else:
                        self._handle_connection_ended(serial_port, bridge_result)
                    return

            if b"\r" in self.command_buffer:
                command_parts = self.command_buffer.split(b"\r")
                for cmd_bytes in command_parts[:-1]:
                    cmd = self._extract_at_command(cmd_bytes)
                    if not cmd:
                        continue
                        
                    logging.info(f"Processing command: {cmd}")
                    self._process_at_command(cmd, serial_port, server_address)

                self.command_buffer = command_parts[-1]

    def _handle_connection_ended(self, serial_port, reason):
        self.disconnecting = True
        
        if reason == "SERVER_CLOSED":
            logging.info("Server terminated connection - sending NO CARRIER")
            try:
                serial_port.write(b"\r\nNO CARRIER\r\n")
                serial_port.flush()
            except Exception as e:
                logging.debug(f"Error sending NO CARRIER: {e}")
        elif reason == "LCP_TERMINATE":
            logging.info("LCP termination - connection ended gracefully")
        
        self._cleanup_connection()
        self.in_command_mode = True
        self.disconnecting = False
        logging.info("Connection ended - ready for new commands")
    
    def _process_at_command(self, cmd, serial_port, server_address):
        if cmd.startswith("ATD"):
            self._handle_dial_command(cmd, serial_port, server_address)
            
        elif cmd == "ATO" and self.connected and self.socket_connection:
            self._handle_ato_command(serial_port)
            
        elif cmd in ["ATH", "ATH0"]:
            self._handle_hangup_command(serial_port)
            
        elif self._is_modem_init_command(cmd):
            self._handle_modem_init_command(cmd, serial_port)
            
        else:
            self._handle_generic_at_command(cmd, serial_port)
    
    def _handle_dial_command(self, cmd, serial_port, server_address):
        logging.info(f"Dial command: {cmd}")
        
        self._cleanup_connection()
        
        try:
            serial_port.write(b"\r\nCONNECTING\r\n")
            serial_port.flush()

            self.socket_connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket_connection.settimeout(30)
            self.socket_connection.connect(server_address)

            auth_string = f"{self.username}:{self.password}\r\n".encode()
            self.socket_connection.sendall(auth_string)
            logging.info(f"Sent authentication for user: {self.username}")

            time.sleep(1)

            self.socket_connection.settimeout(2)
            try:
                response = self.socket_connection.recv(1024)
                if b"Authentication failed" in response:
                    logging.error("Authentication failed")
                    serial_port.write(b"\r\nNO CARRIER\r\n")
                    serial_port.flush()
                    self._cleanup_connection()
                    return
            except socket.timeout:
                pass

            connect_message = f"\r\nCONNECT {self.connect_speed}\r\n".encode()
            serial_port.write(connect_message)
            serial_port.flush()
            self.connected = True
            self.in_command_mode = False
            self.disconnecting = False
            
            logging.info("Dial successful - entering PPP data mode")
            
            bridge_result = self._bridge_ppp_connection(serial_port)
            
            self._handle_connection_ended(serial_port, bridge_result)

        except Exception as e:
            logging.error(f"Dial failed: {e}")
            serial_port.write(b"\r\nNO CARRIER\r\n")
            serial_port.flush()
            self._cleanup_connection()
    
    def _handle_ato_command(self, serial_port):
        if not self.connected or not self.socket_connection:
            logging.warning("ATO command but no active connection")
            serial_port.write(b"\r\nNO CARRIER\r\n")
            serial_port.flush()
            return
            
        logging.info("ATO command - returning to online mode")
        connect_message = f"\r\nCONNECT {self.connect_speed}\r\n".encode()
        serial_port.write(connect_message)
        serial_port.flush()
        self.in_command_mode = False
        self.disconnecting = False
        
        bridge_result = self._bridge_ppp_connection(serial_port)
        self._handle_connection_ended(serial_port, bridge_result)
    
    def _handle_hangup_command(self, serial_port):
        logging.info("Hangup command received")
        
        if self.connected:
            logging.info("Terminating active connection")
            self._cleanup_connection()
        
        serial_port.write(b"\r\nOK\r\n")
        serial_port.flush()
        
        self.connected = False
        self.in_command_mode = True
        self.disconnecting = False
    
    def _handle_modem_init_command(self, cmd, serial_port):
        logging.debug(f"Modem init command: {cmd}")
        serial_port.write(b"\r\nOK\r\n")
        serial_port.flush()
    
    def _handle_generic_at_command(self, cmd, serial_port):
        logging.debug(f"Generic AT command: {cmd}")
        serial_port.write(b"\r\nOK\r\n")
        serial_port.flush()
    
    def _is_ppp_data(self, data):
        return (b'~}' in data or 
                b'\x7e' in data or 
                b'\xff\x03' in data)
    
    def _extract_at_command(self, cmd_bytes):
        cmd = cmd_bytes.strip().decode("ascii", errors="ignore").upper()
        if not cmd:
            return None
        
        if "AT" in cmd and not cmd.startswith("AT"):
            at_index = cmd.find("AT")
            if at_index >= 0:
                cmd = cmd[at_index:]
                logging.debug(f"Extracted AT command from noise: {cmd}")
        
        return cmd if cmd.startswith("AT") else None
    
    def _is_modem_init_command(self, cmd):
        return cmd in ["ATZ", "ATM1L1", "ATX3", "ATE1", "ATE0", "ATQ0", "ATV1"] or cmd.startswith("ATE")
    
    def _cleanup_connection(self):
        if self.socket_connection:
            try:
                self.socket_connection.close()
            except Exception as e:
                logging.debug(f"Error closing socket: {e}")
            finally:
                self.socket_connection = None
        
        self.connected = False

    def _bridge_ppp_connection(self, serial_port):
        try:
            platform_name = "Windows" if IS_WINDOWS else "Unix"
            logging.info(f"Starting PPP data bridging ({platform_name} mode)")
            
            self.socket_connection.settimeout(0.1)
            serial_port.timeout = 0.1
            
            escape_buffer = b""
            last_activity = time.time()
            idle_count = 0
            consecutive_errors = 0
            max_consecutive_errors = 5
            
            import crossbridge
            
            while crossbridge.running and self.connected:
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
                                _debug_ppp_protocols(data, "Client")
                            
                            try:
                                self.socket_connection.sendall(data)
                            except socket.error as e:
                                logging.error(f"Failed to send data to server: {e}")
                                return "SERVER_ERROR"
                            
                            time.sleep(0.001)
                            
                except Exception as e:
                    consecutive_errors += 1
                    logging.error(f"Error reading from serial port ({consecutive_errors}): {e}")
                    if consecutive_errors >= max_consecutive_errors:
                        return "SERIAL_ERROR"

                try:
                    data = self.socket_connection.recv(4096)
                    if data:
                        data_handled = True
                        last_activity = current_time
                        consecutive_errors = 0

                        if DEBUG:
                            logging.debug(f"Server->Serial: {len(data)} bytes: {data.hex()}")
                        
                        if (b"\xff\x03\xc0\x21\x05" in data or
                            b"\xff\x03\xc0\x21\x06" in data):
                            logging.info("LCP termination detected")
                            try:
                                serial_port.write(data)
                                serial_port.flush()
                                time.sleep(0.5)
                                serial_port.write(b"\r\nNO CARRIER\r\n")
                                serial_port.flush()
                            except Exception as e:
                                logging.debug(f"Error sending LCP termination response: {e}")
                            return "LCP_TERMINATE"
                        
                        if DEBUG:
                            _debug_ppp_protocols(data, "Server")
                        
                        try:
                            serial_port.write(data)
                            serial_port.flush()
                        except Exception as e:
                            logging.error(f"Failed to write to serial port: {e}")
                            return "SERIAL_ERROR"
                        
                        time.sleep(0.001)
                        
                    elif data == b'':
                        logging.info("Server closed connection")
                        try:
                            serial_port.write(b"\r\nNO CARRIER\r\n")
                            serial_port.flush()
                        except Exception as e:
                            logging.debug(f"Error sending NO CARRIER: {e}")
                        return "SERVER_CLOSED"
                        
                except socket.timeout:
                    pass
                except ConnectionError as e:
                    logging.error(f"Server connection lost: {e}")
                    try:
                        serial_port.write(b"\r\nNO CARRIER\r\n")
                        serial_port.flush()
                    except Exception as e:
                        logging.debug(f"Error sending NO CARRIER: {e}")
                    return "SERVER_CLOSED"
                except Exception as e:
                    consecutive_errors += 1
                    logging.error(f"Error reading from server ({consecutive_errors}): {e}")
                    if consecutive_errors >= max_consecutive_errors:
                        return "SERVER_ERROR"
                
                if current_time - last_activity > 300:
                    logging.info("Connection timeout due to inactivity")
                    try:
                        serial_port.write(b"\r\nNO CARRIER\r\n")
                        serial_port.flush()
                    except Exception as e:
                        logging.debug(f"Error sending NO CARRIER: {e}")
                    return "TIMEOUT"

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
            return "BRIDGE_ERROR"
        finally:
            logging.info(f"PPP bridge session ended ({platform_name})")

        return "DISCONNECT"

def legacy_ppp_connection(serial_port, socket_connection):
    try:
        platform_name = "Windows" if IS_WINDOWS else "Unix"
        logging.info(f"Starting PPP data bridging ({platform_name} mode)")
        
        socket_connection.settimeout(0.1)
        serial_port.timeout = 0.1
        
        escape_buffer = b""
        last_activity = time.time()
        idle_count = 0
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        import crossbridge
        
        while crossbridge.running:
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
                            _debug_ppp_protocols(data, "Client")
                        
                        try:
                            socket_connection.sendall(data)
                        except socket.error as e:
                            logging.error(f"Failed to send data to server: {e}")
                            break
                        
                        time.sleep(0.001)
                        
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
                        _debug_ppp_protocols(data, "Server")
                    
                    try:
                        serial_port.write(data)
                        serial_port.flush()
                    except Exception as e:
                        logging.error(f"Failed to write to serial port: {e}")
                        break
                    
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

    return "DISCONNECT"

def _debug_ppp_protocols(data, source):
    if b'\xff\x03\x80\x21' in data:
        logging.info(f"{source} sent IPCP packet")
    elif b'\xff\x03\xc0\x21' in data:
        lcp_start = data.find(b'\xff\x03\xc0\x21')
        if lcp_start >= 0 and len(data) > lcp_start + 4:
            lcp_type = data[lcp_start + 4]
            if lcp_type == 1:
                logging.info(f"{source} sent LCP Configure-Request")
            elif lcp_type == 2:
                logging.info(f"{source} sent LCP Configure-Ack")
            elif lcp_type == 9:
                logging.info(f"{source} sent LCP Echo-Request")
            elif lcp_type == 10:
                logging.info(f"{source} sent LCP Echo-Reply")