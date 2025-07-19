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
import asyncio
import logging
import zlib
import random
from typing import Optional
from dataclasses import dataclass

from serial_utils import SerialTransport

class SimpleCompression:
    def __init__(self):
        self.compression_enabled = False
        self.compression_level = 1
        self.compression_ratio = 0.0
        self.bytes_compressed = 0
        self.bytes_original = 0
        self.logger = logging.getLogger(__name__)
    
    def enable_compression(self, level: int = 1) -> None:
        self.compression_enabled = True
        self.compression_level = max(1, min(9, level))
        self.logger.info(f"Compression enabled (level {self.compression_level})")
    
    def disable_compression(self) -> None:
        self.compression_enabled = False
        self.logger.info("Compression disabled")
    
    async def compress_data(self, data: bytes) -> bytes:
        if not self.compression_enabled or len(data) < 64:
            return data
        
        try:
            compressed = zlib.compress(data, level=self.compression_level)
            
            if len(compressed) < len(data) * 0.8:
                self.bytes_original += len(data)
                self.bytes_compressed += len(compressed)
                self.compression_ratio = (1.0 - (self.bytes_compressed / self.bytes_original)) * 100
                
                return b'\x1b\x43' + compressed
            else:
                return data
                
        except Exception as e:
            self.logger.error(f"Compression error: {e}")
            return data
    
    async def decompress_data(self, data: bytes) -> bytes:
        if not data or len(data) < 3:
            return data
        
        try:
            if data[:2] == b'\x1b\x43':
                compressed_data = data[2:]
                decompressed = zlib.decompress(compressed_data)
                self.logger.debug(f"Decompressed {len(compressed_data)} -> {len(decompressed)} bytes")
                return decompressed
            else:
                return data
                
        except Exception as e:
            self.logger.error(f"Decompression error: {e}")
            return data
    
    def get_compression_stats(self) -> dict:
        return {
            'enabled': self.compression_enabled,
            'level': self.compression_level,
            'ratio': self.compression_ratio,
            'bytes_original': self.bytes_original,
            'bytes_compressed': self.bytes_compressed
        }

@dataclass
class ModemConfig:
    username: str
    password: str
    debug: bool = False
    connect_speed: int = 33600
    baud_rate: int = 38400

class ConnectionState:
    def __init__(self):
        self.connected = False
        self.in_command_mode = True
        self.socket_connection = None

class CommandProcessor:
    def __init__(self, username: str, password: str, connect_speed: int = 33600):
        self.username = username
        self.password = password
        self.connect_speed = connect_speed
        self.logger = logging.getLogger(__name__)
        
        self.echo_enabled = True
        self.verbose_responses = True
        self.speaker_volume = 2
        self.speaker_control = 1
        self.auto_answer = 0
        self.compression_enabled = False
        self.error_correction_enabled = False
        self.dtr_action = 2
        self.dcd_action = 0
        
        self.s_registers = {
            0: 0,
            1: 0,
            2: 43,
            3: 13,
            4: 10,
            5: 8,
            6: 2,
            7: 50,
            8: 2,
            9: 6,
            10: 14,
            11: 95,
            12: 50,
        }
        
        self.signal_strength = random.randint(85, 100)
        self.line_quality = random.randint(92, 100)
        self.connection_type = self._determine_connection_type(connect_speed)
        self.last_connect_speed = connect_speed
    
    def _determine_connection_type(self, speed: int) -> str:
        if speed <= 9600:
            connection_types = ["V.32", "V.22bis", "Bell 212A"]
            return random.choice(connection_types)
        elif speed <= 14400:
            connection_types = ["V.32bis", "V.17"]
            return random.choice(connection_types)
        elif speed <= 28800:
            connection_types = ["V.34", "V.FC"]
            return random.choice(connection_types)
        elif speed <= 33600:
            connection_types = ["V.34+", "K56flex"]
            return random.choice(connection_types)
        elif speed <= 56000:
            connection_types = ["V.90", "V.92", "PSTN", "Dialup"]
            return random.choice(connection_types)
        elif speed <= 128000:
            connection_types = ["ISDN", "ISDN-128", "BRI-ISDN"]
            return random.choice(connection_types)
        elif speed <= 256000:
            connection_types = ["ISDN-256"]
            return random.choice(connection_types)
    
    def extract_command(self, data: bytes) -> Optional[str]:
        try:
            command = data.decode('utf-8', errors='ignore').strip().upper()
            if command.startswith('AT'):
                return command
            return None
        except:
            return None
    
    async def process_basic_command(self, command: str, serial_transport: SerialTransport) -> bool:
        try:
            if command == "AT":
                await self._send_response(serial_transport, "OK")
                return True
            
            elif command == "ATI" or command == "ATI0":
                await self._send_response(serial_transport, "VesperNet PPP Bridge v2.0.0")
                await self._send_response(serial_transport, "OK")
                return True
            elif command == "ATI1":
                await self._send_response(serial_transport, "VesperNet Bridge ROM v2.0")
                await self._send_response(serial_transport, "OK")
                return True
            elif command == "ATI2":
                await self._send_response(serial_transport, "ROM checksum: A5B2C3D4")
                await self._send_response(serial_transport, "OK")
                return True
            elif command == "ATI3":
                await self._send_response(serial_transport, f"VesperNet PPP Bridge v2.0.0 - Signal: {self.signal_strength}%")
                await self._send_response(serial_transport, "OK")
                return True
            elif command == "ATI4":
                await self._send_response(serial_transport, "VesperNet Bridge - Enhanced Hayes Compatible")
                await self._send_response(serial_transport, "OK")
                return True
            
            elif command == "ATZ" or command == "ATZ0":
                await self._reset_modem_settings()
                await self._send_response(serial_transport, "OK")
                return True
            
            elif command == "ATE0":
                self.echo_enabled = False
                await self._send_response(serial_transport, "OK")
                return True
            elif command == "ATE1":
                self.echo_enabled = True
                await self._send_response(serial_transport, "OK")
                return True
            
            elif command == "ATV0":
                self.verbose_responses = False
                await self._send_response(serial_transport, "0")
                return True
            elif command == "ATV1":
                self.verbose_responses = True
                await self._send_response(serial_transport, "OK")
                return True
            
            elif command.startswith("ATM"):
                volume = command[3:] if len(command) > 3 else "1"
                try:
                    self.speaker_control = int(volume)
                    await self._send_response(serial_transport, "OK")
                except ValueError:
                    await self._send_response(serial_transport, "ERROR")
                return True
            
            elif command.startswith("ATL"):
                volume = command[3:] if len(command) > 3 else "2"
                try:
                    self.speaker_volume = int(volume)
                    await self._send_response(serial_transport, "OK")
                except ValueError:
                    await self._send_response(serial_transport, "ERROR")
                return True
            
            elif command.startswith("ATS"):
                return await self._handle_s_register_command(command, serial_transport)
            
            elif command.startswith("ATA"):
                await self._send_response(serial_transport, "NO CARRIER")
                return True
            
            elif command.startswith("AT&D"):
                dtr_setting = command[4:] if len(command) > 4 else "2"
                try:
                    self.dtr_action = int(dtr_setting)
                    await self._send_response(serial_transport, "OK")
                except ValueError:
                    await self._send_response(serial_transport, "ERROR")
                return True
            
            elif command.startswith("AT&C"):
                dcd_setting = command[4:] if len(command) > 4 else "1"
                try:
                    self.dcd_action = int(dcd_setting)
                    await self._send_response(serial_transport, "OK")
                except ValueError:
                    await self._send_response(serial_transport, "ERROR")
                return True
            
            # Flow control (acknowledge but don't implement)
            elif command.startswith("AT&K"):
                await self._send_response(serial_transport, "OK")
                return True
            elif command.startswith("AT&R"):
                await self._send_response(serial_transport, "OK")
                return True
            elif command.startswith("AT&S"):
                await self._send_response(serial_transport, "OK")
                return True
            
            elif command.startswith("AT%C"):
                compression_setting = command[4:] if len(command) > 4 else "0"
                if compression_setting == "1":
                    self.compression_enabled = True
                    await self._send_response(serial_transport, "OK")
                elif compression_setting == "0":
                    self.compression_enabled = False
                    await self._send_response(serial_transport, "OK")
                else:
                    await self._send_response(serial_transport, "ERROR")
                return True
            
            elif command.startswith("AT&Q"):
                error_correction = command[4:] if len(command) > 4 else "0"
                if error_correction == "5":
                    self.error_correction_enabled = True
                    await self._send_response(serial_transport, "OK")
                elif error_correction == "0":
                    self.error_correction_enabled = False
                    await self._send_response(serial_transport, "OK")
                else:
                    await self._send_response(serial_transport, "ERROR")
                return True
            
            elif command == "AT+CSQ":
                rssi = min(31, max(0, self.signal_strength // 3))
                await self._send_response(serial_transport, f"+CSQ: {rssi},99")
                await self._send_response(serial_transport, "OK")
                return True
            
            elif command == "AT+CGMI":
                await self._send_response(serial_transport, "VesperNet")
                await self._send_response(serial_transport, "OK")
                return True
            
            elif command == "AT+CGMM":
                await self._send_response(serial_transport, "PPP Bridge v2.0")
                await self._send_response(serial_transport, "OK")
                return True
            
            elif command == "AT+CGMR":
                await self._send_response(serial_transport, "2.0.0")
                await self._send_response(serial_transport, "OK")
                return True
            
            elif command == "AT&T":
                await self._send_response(serial_transport, f"Line Quality: {self.line_quality}%")
                await self._send_response(serial_transport, "OK")
                return True
            
            elif command == "AT*L":
                await self._send_response(serial_transport, f"Last connection: {self.last_connect_speed} bps ({self.connection_type})")
                await self._send_response(serial_transport, "OK")
                return True
            
            elif command == "AT&F" or command == "AT&F0":
                await self._reset_to_factory_defaults()
                await self._send_response(serial_transport, "OK")
                return True
            
            else:
                await self._send_response(serial_transport, "OK")
                return True
                
        except Exception as e:
            self.logger.error(f"Enhanced command processing error: {e}")
            await self._send_response(serial_transport, "ERROR")
            return False
    
    async def _send_response(self, serial_transport: SerialTransport, response: str) -> None:
        if self.verbose_responses:
            formatted_response = f"\r\n{response}\r\n"
        else:
            if response == "OK":
                formatted_response = "0\r"
            elif response == "ERROR":
                formatted_response = "4\r"
            elif response == "NO CARRIER":
                formatted_response = "3\r"
            elif response == "BUSY":
                formatted_response = "7\r"
            elif response == "NO DIALTONE":
                formatted_response = "6\r"
            else:
                formatted_response = f"\r\n{response}\r\n"
        
        await serial_transport.write(formatted_response.encode())
    
    async def _handle_s_register_command(self, command: str, serial_transport: SerialTransport) -> bool:
        try:
            if '=' in command:
                parts = command[3:].split('=')
                if len(parts) == 2:
                    register_num = int(parts[0])
                    value = int(parts[1])
                    if 0 <= register_num <= 255:
                        self.s_registers[register_num] = value
                        await self._send_response(serial_transport, "OK")
                    else:
                        await self._send_response(serial_transport, "ERROR")
                else:
                    await self._send_response(serial_transport, "ERROR")
            elif '?' in command:
                register_num = int(command[3:-1])
                if register_num in self.s_registers:
                    value = self.s_registers[register_num]
                    await self._send_response(serial_transport, f"{value:03d}")
                    await self._send_response(serial_transport, "OK")
                else:
                    await self._send_response(serial_transport, "ERROR")
            else:
                await self._send_response(serial_transport, "OK")
            return True
        except (ValueError, IndexError):
            await self._send_response(serial_transport, "ERROR")
            return False
    
    async def _reset_modem_settings(self) -> None:
        self.echo_enabled = True
        self.verbose_responses = True
        self.speaker_volume = 2
        self.speaker_control = 1
        self.auto_answer = 0
        self.dtr_action = 2
        self.dcd_action = 0
        self.s_registers.update({
            0: 0,
            7: 50,
            12: 50,
        })
        self.logger.debug("Modem settings reset to defaults")
    
    async def _reset_to_factory_defaults(self) -> None:
        await self._reset_modem_settings()
        self.compression_enabled = False
        self.error_correction_enabled = False
        self.logger.info("Modem reset to factory defaults")

class ModemEmulator:
    def __init__(self, modem_config: ModemConfig, is_windows: bool = False):
        self.modem_config = modem_config
        self.is_windows = is_windows
        self.connection_state = ConnectionState()
        self.logger = logging.getLogger(__name__)
        
        self.compression = SimpleCompression()
        
        self.command_processor = CommandProcessor(
            username=self.modem_config.username,
            password=self.modem_config.password,
            connect_speed=self.modem_config.connect_speed
        )
        
        connection_type = self.command_processor._determine_connection_type(self.modem_config.connect_speed)
        self.connection_quality = {
            'signal_strength': random.randint(85, 100),
            'line_quality': random.randint(90, 100),
            'error_rate': random.uniform(0.0001, 0.002),
            'throughput': self.modem_config.connect_speed,
            'connection_type': connection_type
        }
    
    def update_connection_quality(self, **kwargs) -> None:
        self.connection_quality.update(kwargs)
        self.command_processor.signal_strength = self.connection_quality['signal_strength']
        self.command_processor.line_quality = self.connection_quality['line_quality']
        self.command_processor.connection_type = self.connection_quality['connection_type']
    
    def get_connection_stats(self) -> dict:
        stats = {
            'connection_quality': self.connection_quality.copy(),
            'compression': self.compression.get_compression_stats(),
            'modem_settings': {
                'echo_enabled': self.command_processor.echo_enabled,
                'verbose_responses': self.command_processor.verbose_responses,
                'compression_enabled': self.command_processor.compression_enabled,
                'error_correction_enabled': self.command_processor.error_correction_enabled,
            }
        }
        return stats
    
    async def emulate_modem(self, serial_transport: SerialTransport, server_host: str, server_port: int) -> None:
        try:
            self.logger.info("Starting modem emulation")

            command_task = asyncio.create_task(
                self._command_processing_loop(serial_transport, server_host, server_port)
            )
            
            await asyncio.gather(command_task)
            
        except Exception as e:
            self.logger.error(f"Modem emulation failed: {e}")
            raise
    
    async def _command_processing_loop(self, serial_transport: SerialTransport, server_host: str, server_port: int) -> None:
        command_buffer = b""
        
        try:
            while await serial_transport.is_connected():
                if self.connection_state.in_command_mode:
                    data = await serial_transport.read()
                    if not data:
                        await asyncio.sleep(0.001)
                        continue
                    
                    command_buffer += data
                    
                    while b'\r' in command_buffer or b'\n' in command_buffer:
                        if b'\r' in command_buffer:
                            cmd_bytes, command_buffer = command_buffer.split(b'\r', 1)
                        else:
                            cmd_bytes, command_buffer = command_buffer.split(b'\n', 1)
                        
                        command = self.command_processor.extract_command(cmd_bytes)
                        if command:
                            await self._process_command(command, serial_transport, server_host, server_port)
                
                elif self.connection_state.connected:
                    await self._bridge_ppp_data(serial_transport)
                
                await asyncio.sleep(0.001)
                
        except Exception as e:
            self.logger.error(f"Command processing loop error: {e}")
    
    async def _process_command(self, command: str, serial_transport: SerialTransport, server_host: str, server_port: int) -> None:
        try:
            if command.startswith("ATDT") or command.startswith("ATD"):
                await self._handle_dial_command(command, serial_transport, server_host, server_port)
                return
            
            if command.startswith("ATH"):
                await self._handle_hangup_command(serial_transport)
                return
            
            await self.command_processor.process_basic_command(command, serial_transport)
            
        except Exception as e:
            self.logger.error(f"Command processing error: {e}")
    
    async def _handle_hangup_command(self, serial_transport: SerialTransport) -> None:
        try:
            self.logger.info("Hangup command received")
            
            if hasattr(self.connection_state, 'socket_connection') and self.connection_state.socket_connection:
                await self.connection_state.socket_connection.close()
                self.connection_state.socket_connection = None
            
            self.connection_state.connected = False
            self.connection_state.in_command_mode = True
            
            await serial_transport.write(b"\r\nOK\r\n")
            
        except Exception as e:
            self.logger.error(f"Hangup command error: {e}")
            await serial_transport.write(b"\r\nERROR\r\n")
    
    async def _handle_dial_command(self, command: str, serial_transport: SerialTransport, server_host: str, server_port: int) -> None:
        try:
            from crossbridge import SocketTransport, BridgeConfig, PPPBridgeConfig
            
            if command.startswith("ATDT"):
                phone_number = command[4:].strip() if len(command) > 4 else ""
            elif command.startswith("ATD"):
                phone_number = command[3:].strip() if len(command) > 3 else ""
            else:
                phone_number = ""
                
            self.logger.info(f"Dial command: {phone_number}")
            
            bridge_config = PPPBridgeConfig(
                username=self.modem_config.username,
                password=self.modem_config.password,
                server_host=server_host,
                server_port=server_port,
                device="",
                baud_rate=self.modem_config.baud_rate,
                connect_speed=self.modem_config.connect_speed,
                is_windows=self.is_windows
            )
            
            config = BridgeConfig(bridge_config=bridge_config)
            
            socket_transport = SocketTransport(config)
            
            try:
                await socket_transport.connect(server_host, server_port)
                
                if not await self._authenticate(socket_transport):
                    await socket_transport.close()
                    await serial_transport.write(b"\r\nNO CARRIER\r\n")
                    return

                await self._send_connection_sequence(serial_transport)
                
                if not await self._speed_negotiation(socket_transport):
                    await socket_transport.close()
                    await serial_transport.write(b"\r\nNO CARRIER\r\n")
                    return
                
                self.connection_state.connected = True
                self.connection_state.in_command_mode = False
                self.connection_state.socket_connection = socket_transport
                
                self.logger.info("Connection established, switching to data mode")
                
            except Exception as e:
                self.logger.error(f"Dial command failed: {e}")
                await serial_transport.write(b"\r\nNO CARRIER\r\n")
                await socket_transport.close()
                
        except Exception as e:
            self.logger.error(f"Dial command error: {e}")

    async def _authenticate(self, socket_transport) -> bool:
        try:
            auth_string = f"{self.modem_config.username}:{self.modem_config.password}\r\n".encode()
            self.logger.debug(f"Sending authentication: {auth_string}")
            await socket_transport.write(auth_string)
            
            await asyncio.sleep(0.5)
            
            try:
                response = await asyncio.wait_for(
                    socket_transport.read(1024),
                    timeout=2.0
                )
                
                self.logger.debug(f"Authentication response: {response}")
                
                if b"Authentication failed" in response:
                    self.logger.error("Authentication failed")
                    return False
                    
                self.logger.info("Authentication successful")
                return True
                    
            except asyncio.TimeoutError:
                self.logger.debug("Authentication timeout, assuming success")
                return True
            
        except Exception as e:
            self.logger.error(f"Authentication failed: {e}")
            return False
    
    async def _send_connection_sequence(self, serial_transport: SerialTransport) -> None:
        try:
            if not self.is_windows:
                await serial_transport.write(b"\r\nDialing...\r\n")
                await asyncio.sleep(0.1)
                
                await serial_transport.write(b"\r\nRinging...\r\n")
                await asyncio.sleep(0.1)
                
                signal_msg = f"\r\nSignal Quality: {self.connection_quality['signal_strength']}%\r\n"
                await serial_transport.write(signal_msg.encode())
                await asyncio.sleep(0.1)
                
                await serial_transport.write(b"\r\nCarrier detected\r\n")
                await asyncio.sleep(0.1)
                
                line_msg = f"\r\nLine Quality: {self.connection_quality['line_quality']}%\r\n"
                await serial_transport.write(line_msg.encode())
                await asyncio.sleep(0.1)
                
                type_msg = f"\r\nConnection Type: {self.connection_quality['connection_type']}\r\n"
                await serial_transport.write(type_msg.encode())
                await asyncio.sleep(0.1)

            if self.command_processor.compression_enabled:
                compression_status = " COMPRESSION"
            else:
                compression_status = ""
            
            if self.command_processor.error_correction_enabled:
                error_correction_status = " ERROR_CORRECTION"
            else:
                error_correction_status = ""
            
            connect_msg = f"\r\nCONNECT {self.modem_config.connect_speed}{compression_status}{error_correction_status}\r\n"
            await serial_transport.write(connect_msg.encode())
            
            self.command_processor.last_connect_speed = self.modem_config.connect_speed
            self.command_processor.connection_type = self.connection_quality['connection_type']
            
            self.logger.info(f"Enhanced connection sequence sent - Speed: {self.modem_config.connect_speed}, Quality: {self.connection_quality['signal_strength']}%, Type: {self.connection_quality['connection_type']}")
            
        except Exception as e:
            self.logger.error(f"Connection sequence error: {e}")
    
    async def _speed_negotiation(self, socket_transport) -> bool:
        try:
            self.logger.info("Waiting for speed negotiation ...")
            
            start_time = asyncio.get_event_loop().time()
            timeout = 10.0
            
            while (asyncio.get_event_loop().time() - start_time) < timeout:
                try:
                    data = await asyncio.wait_for(
                        socket_transport.read(1024),
                        timeout=1.0
                    )
                    
                    if data:
                        response = data.decode('utf-8', errors='ignore')
                        self.logger.debug(f"Speed negotiation data: {response}")
                        
                        if "NEGOTIATE:" in response:
                            lines = response.split('\n')
                            for line in lines:
                                if "NEGOTIATE:" in line:
                                    parts = line.strip().split(":")
                                    if len(parts) >= 2:
                                        speed = parts[1].strip()
                                        connection_type = parts[2].strip() if len(parts) > 2 else "Unknown"
                                        
                                        self.logger.info(f"Received speed negotiation: {speed} bps ({connection_type})")
                                        self.logger.info(f"Speed negotiation successful: {speed} bps ({connection_type})")
                                        
                                        self.logger.info(f"Dial successful - DTE: {self.modem_config.baud_rate}, DCE: {speed}, Negotiated: {speed} ({connection_type})")
                                        
                                        return True
                
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    self.logger.debug(f"Speed negotiation read error: {e}")
                    continue
            
            self.logger.error("Speed negotiation timeout")
            return False
            
        except Exception as e:
            self.logger.error(f"Speed negotiation failed: {e}")
            return False

    async def _bridge_ppp_data(self, serial_transport: SerialTransport) -> None:
        try:
            if not self.connection_state.socket_connection:
                self.logger.warning("No socket connection available for PPP bridging")
                self.connection_state.connected = False
                self.connection_state.in_command_mode = True
                return
            
            socket_transport = self.connection_state.socket_connection
            self.logger.info("Starting PPP data bridging")
            
            if not await socket_transport.is_connected():
                self.logger.error("Socket connection lost before PPP bridging")
                self.connection_state.connected = False
                self.connection_state.in_command_mode = True
                return
            
            serial_to_socket_task = asyncio.create_task(
                self._bridge_serial_to_socket(serial_transport, socket_transport)
            )
            
            socket_to_serial_task = asyncio.create_task(
                self._bridge_socket_to_serial(socket_transport, serial_transport)
            )
            
            self.logger.debug("PPP bridging tasks created")
            
            done, pending = await asyncio.wait(
                [serial_to_socket_task, socket_to_serial_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            self.logger.info("PPP bridging task completed")
            
            for task in done:
                try:
                    result = await task
                    self.logger.debug(f"Bridging task result: {result}")
                except Exception as e:
                    self.logger.error(f"Bridging task failed: {e}")
            
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            
            if self.connection_state.in_command_mode:
                self.logger.info("PPP data bridging ended - returning to command mode")
                return
            else:
                self.logger.info("PPP data bridging ended - disconnecting")
                self.connection_state.connected = False
                self.connection_state.in_command_mode = True
                
                await socket_transport.close()
                await serial_transport.write(b"\r\nNO CARRIER\r\n")
            
        except Exception as e:
            self.logger.error(f"PPP data bridging error: {e}")
            self.connection_state.connected = False
            self.connection_state.in_command_mode = True
    
    async def _bridge_serial_to_socket(self, serial_transport: SerialTransport, socket_transport) -> None:
        try:
            self.logger.debug("Starting serial to socket bridge")
            data_count = 0
            no_data_count = 0
            escape_buffer = b""
            
            if self.command_processor.compression_enabled:
                self.compression.enable_compression()
            
            while self.connection_state.connected:
                data = await serial_transport.read()
                if data:
                    data_count += 1
                    no_data_count = 0
                    
                    escape_buffer += data
                    
                    if b"+++" in escape_buffer:
                        self.logger.info("Escape sequence detected - entering command mode")
                        self.connection_state.in_command_mode = True
                        self.connection_state.connected = False
                        break
                    
                    if len(escape_buffer) > 10:
                        escape_buffer = escape_buffer[-10:]
                    
                    compressed_data = await self.compression.compress_data(data)
                    
                    self.logger.debug(f"Serial->Socket #{data_count}: {len(data)} bytes -> {len(compressed_data)} bytes: {data[:20]}...")
                    await socket_transport.write(compressed_data)
                else:
                    no_data_count += 1
                    if no_data_count % 3000 == 0:
                        self.logger.warning(f"No serial data for {no_data_count/1000:.1f} seconds")
                    await asyncio.sleep(0.001)
                    
        except Exception as e:
            self.logger.error(f"Serial to socket bridge error: {e}")
            raise
    
    async def _bridge_socket_to_serial(self, socket_transport, serial_transport: SerialTransport) -> None:
        try:
            self.logger.debug("Starting socket to serial bridge")
            data_count = 0
            no_data_count = 0
            
            while self.connection_state.connected:
                data = await socket_transport.read()
                if data:
                    data_count += 1
                    no_data_count = 0
                    
                    decompressed_data = await self.compression.decompress_data(data)
                    
                    self.logger.debug(f"Socket->Serial #{data_count}: {len(data)} bytes -> {len(decompressed_data)} bytes: {data[:20]}...")
                    await serial_transport.write(decompressed_data)
                else:
                    if not await socket_transport.is_connected():
                        self.logger.info("Socket closed, ending bridge")
                        self.connection_state.connected = False
                        break
                    else:
                        no_data_count += 1
                        if no_data_count % 1000 == 0:
                            self.logger.debug(f"No socket data for {no_data_count/1000:.1f} seconds")
                        await asyncio.sleep(0.001)
                    
        except Exception as e:
            self.logger.error(f"Socket to serial bridge error: {e}")
            raise
