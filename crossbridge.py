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
from __future__ import annotations

import os
import sys
import asyncio
import logging
import json
from typing import Optional, TYPE_CHECKING, Any
from dataclasses import dataclass
from enum import Enum

class MissingDependencyError(ImportError):
    pass

SerialTransport = None
ModemEmulator = None
ModemConfig = None

if TYPE_CHECKING:
    from serial_utils import SerialTransport as SerialTransportProtocol
    from modem_utils import ModemEmulator as ModemEmulatorProtocol, ModemConfig as ModemConfigProtocol
else:
    SerialTransportProtocol = Any
    ModemEmulatorProtocol = Any
    ModemConfigProtocol = Any

def check_required_modules() -> None:
    global SerialTransport, ModemEmulator, ModemConfig

    missing_modules = []

    try:
        from modem_utils import ModemEmulator as _ModemEmulator, ModemConfig as _ModemConfig
    except ImportError as e:
        missing_modules.append(("modem_utils.py", "ModemEmulator, ModemConfig", str(e)))
    else:
        ModemEmulator = _ModemEmulator
        ModemConfig = _ModemConfig

    try:
        from serial_utils import SerialTransport as _SerialTransport
    except ImportError as e:
        missing_modules.append(("serial_utils.py", "SerialTransport", str(e)))
    else:
        SerialTransport = _SerialTransport

    if missing_modules:
        message_lines = ["","=" * 60,
                         "Missing Required VesperNet Modules",
                         "=" * 60,
                         ""]
        for module_file, components, error in missing_modules:
            message_lines.append(f"• Missing: {module_file}")
            message_lines.append(f"  Components: {components}")
            message_lines.append(f"  Error: {error}")
            message_lines.append("")

        message_lines.extend([
            "SOLUTION:",
            "  1. Download the complete VesperNet PPP Bridge package",
            "  2. Ensure all .py files are in the same directory",
            "  3. Required files: crossbridge.py, modem_utils.py, serial_utils.py",
            "",
            "Get the complete package from:",
            "  https://github.com/fogWraith/VesperNet-Crossbridge",
            "=" * 60,
        ])

        raise MissingDependencyError("\n".join(message_lines))

class EventLoopRunner:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.winloop_available = False
        self.uvloop_available = False
        
        if sys.platform in ('win32', 'cygwin', 'cli'):
            try:
                import winloop
                self.winloop_available = True
                self.logger.debug("winloop available for Windows")
            except ImportError:
                self.logger.debug("winloop not available")
        else:
            try:
                import uvloop
                self.uvloop_available = True
                self.logger.debug("uvloop available for Unix/Linux")
            except ImportError:
                self.logger.debug("uvloop not available")
    
    def run_loop(self, main_coro):
        if sys.platform in ('win32', 'cygwin', 'cli'):
            if self.winloop_available:
                try:
                    from winloop import run
                    self.logger.info("Using winloop for enhanced Windows performance")
                    return run(main_coro)
                except Exception as e:
                    self.logger.debug(f"Failed to use winloop: {e}")

            return self._run_windows(main_coro)
        else:
            if self.uvloop_available:
                try:
                    from uvloop import run
                    self.logger.info("Using uvloop for enhanced Unix/Linux performance")
                    return run(main_coro)
                except Exception as e:
                    self.logger.debug(f"Failed to use uvloop: {e}")

            self.logger.info("Using standard asyncio event loop")
            return asyncio.run(main_coro)

    def _run_windows(self, main_coro):
        python_version = sys.version_info
        if python_version >= (3, 14):
            self.logger.info("Using asyncio.Runner")
            policy = asyncio.WindowsProactorEventLoopPolicy()
            loop_factory = policy.new_event_loop
            try:
                with asyncio.Runner(loop_factory=loop_factory) as runner:
                    return runner.run(main_coro)
            except Exception as e:
                self.logger.error(f"Runner execution failed: {e}")
                raise
        else:
            self.logger.info("Using WindowsProactorEventLoopPolicy")
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            return asyncio.run(main_coro)

@dataclass
class PPPBridgeConfig:
    username: str
    password: str
    server_host: str
    server_port: int
    device: str
    baud_rate: int = 38400
    connect_speed: int = 33600
    emulate_modem: bool = True
    inactivity_timeout: int = 300
    connection_retries: int = 3
    debug: bool = False
    log_file: str = "crossbridge.log"
    is_windows: bool = False
    running: bool = True

class ConfigurationManager:
    def __init__(self, is_windows: bool = False):
        self.is_windows = is_windows
        self.logger = logging.getLogger(__name__)
    
    def load_config(self, config_file: str = "bridge-config.json") -> PPPBridgeConfig:
        try:
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config_data = json.load(f)
                
                self.logger.info(f"Loaded configuration from {config_file}")
                
                config = PPPBridgeConfig(
                    username=config_data.get('username', ''),
                    password=config_data.get('password', ''),
                    server_host=config_data.get('server_host', ''),
                    server_port=config_data.get('server_port', 6060),
                    device=config_data.get('device', ''),
                    baud_rate=config_data.get('baud_rate', 38400),
                    connect_speed=config_data.get('connect_speed', 33600),
                    emulate_modem=config_data.get('emulate_modem', True),
                    inactivity_timeout=config_data.get('inactivity_timeout', 300),
                    connection_retries=config_data.get('connection_retries', 3),
                    debug=config_data.get('debug', False),
                    log_file=config_data.get('log_file', 'crossbridge.log'),
                    is_windows=self.is_windows
                )
                
                return config
            else:
                raise FileNotFoundError(f"Configuration file {config_file} not found")
                
        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            raise

class TransportType(Enum):
    SOCKET = "socket"
    SERIAL = "serial"
    PIPE = "pipe"

@dataclass
class BridgeConfig:
    bridge_config: PPPBridgeConfig
    buffer_size: int = 16384
    read_timeout: float = 0.1
    write_timeout: float = 5.0
    heartbeat_interval: float = 30.0
    connection_check_interval: float = 5.0
    max_concurrent_connections: int = 10
    enable_flow_control: bool = True
    enable_compression: bool = False
    
    def __post_init__(self):
        if self.buffer_size <= 0:
            raise ValueError("Buffer size must be positive")
        if self.read_timeout <= 0:
            raise ValueError("Read timeout must be positive")
        if self.write_timeout <= 0:
            raise ValueError("Write timeout must be positive")

class SocketTransport:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self.bridge_config = config.bridge_config
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.connected = False
        self.logger = logging.getLogger(__name__)
    
    async def connect(self, host: str, port: int) -> None:
        try:
            self.logger.info(f"Connecting to {host}:{port}")
            
            future = asyncio.open_connection(host, port)
            self.reader, self.writer = await asyncio.wait_for(
                future, 
                timeout=30.0
            )
            
            self.connected = True
            self.logger.info(f"Connected to {host}:{port}")
            
        except asyncio.TimeoutError:
            raise TimeoutError(f"Connection timeout to {host}:{port}")
        except ConnectionRefusedError:
            raise ConnectionRefusedError(f"Connection refused by {host}:{port}")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to {host}:{port}: {e}")
    
    async def read(self, size: int = -1) -> bytes:
        if not self.reader:
            raise RuntimeError("Transport not connected")
        
        try:
            if size == -1:
                size = self.config.buffer_size
            
            timeout = 0.1
            
            data = await asyncio.wait_for(
                self.reader.read(size),
                timeout=timeout
            )
            
            if not data:
                self.connected = False
                self.logger.info("Remote connection closed")
            
            return data
            
        except asyncio.TimeoutError:
            return b""
        except Exception as e:
            self.logger.error(f"Socket read error: {e}")
            self.connected = False
            raise
    
    async def write(self, data: bytes) -> int:
        if not self.writer:
            raise RuntimeError("Transport not connected")
        
        try:
            if len(data) < 8192:
                self.writer.write(data)
                await asyncio.wait_for(
                    self.writer.drain(),
                    timeout=self.config.write_timeout
                )
                return len(data)
            
            chunk_size = 8192
            bytes_written = 0
            
            for i in range(0, len(data), chunk_size):
                chunk = data[i:i + chunk_size]
                self.writer.write(chunk)
                
                try:
                    await asyncio.wait_for(
                        self.writer.drain(),
                        timeout=self.config.write_timeout
                    )
                except asyncio.TimeoutError:
                    try:
                        await asyncio.wait_for(
                            self.writer.drain(),
                            timeout=self.config.write_timeout * 2
                        )
                    except asyncio.TimeoutError:
                        raise TimeoutError("Write timeout on transfer")
                
                bytes_written += len(chunk)
            
            return bytes_written
            
        except asyncio.TimeoutError:
            raise TimeoutError("Write timeout")
        except Exception as e:
            self.logger.error(f"Socket write error: {e}")
            self.connected = False
            raise
    
    async def close(self) -> None:
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception as e:
                self.logger.debug(f"Error closing writer: {e}")
            finally:
                self.writer = None
                self.reader = None
        
        self.connected = False
        self.logger.info("Socket transport closed")
    
    async def is_connected(self) -> bool:
        return self.connected and self.writer is not None
    
    @property
    def transport_type(self) -> TransportType:
        return TransportType.SOCKET

class PPPBridge:
    def __init__(self, config: BridgeConfig):
        check_required_modules()
        self.config = config
        self.bridge_config = config.bridge_config
        self.logger = logging.getLogger(__name__)
        self.running = True
    
    async def run_modem_emulation(self) -> int:
        try:
            self.logger.info("Starting modem emulation")
            
            serial_transport = SerialTransport(
                buffer_size=self.config.buffer_size,
                read_timeout=self.config.read_timeout,
                write_timeout=self.config.write_timeout
            )
            await serial_transport.connect(
                self.bridge_config.device,
                self.bridge_config.baud_rate
            )
            
            modem_config = ModemConfig(
                username=self.bridge_config.username,
                password=self.bridge_config.password,
                debug=self.bridge_config.debug,
                connect_speed=self.bridge_config.connect_speed,
                baud_rate=self.bridge_config.baud_rate
            )
            
            modem_emulator = ModemEmulator(modem_config, self.bridge_config.is_windows)
            
            await modem_emulator.emulate_modem(
                serial_transport,
                self.bridge_config.server_host,
                self.bridge_config.server_port
            )
            
            return 0
            
        except Exception as e:
            self.logger.error(f"Modem emulation failed: {e}")
            return 1
        finally:
            if 'serial_transport' in locals():
                await serial_transport.close()
    
    async def run_direct_bridge(self) -> int:
        try:
            self.logger.info("Starting direct bridge")
            
            serial_transport = SerialTransport(
                buffer_size=self.config.buffer_size,
                read_timeout=self.config.read_timeout,
                write_timeout=self.config.write_timeout
            )
            await serial_transport.connect(
                self.bridge_config.device,
                self.bridge_config.baud_rate
            )
            
            socket_transport = SocketTransport(self.config)
            await socket_transport.connect(
                self.bridge_config.server_host,
                self.bridge_config.server_port
            )
            
            if not await self._authenticate_direct(socket_transport):
                return 1
            
            if not await self._speed_negotiation_direct(socket_transport):
                return 1
            
            self.logger.info("Direct bridge ready - starting PPP data bridging")
            
            await self._bridge_connections(serial_transport, socket_transport)
            
            return 0
            
        except Exception as e:
            self.logger.error(f"Direct bridge failed: {e}")
            return 1
        finally:
            if 'serial_transport' in locals():
                await serial_transport.close()
            if 'socket_transport' in locals():
                await socket_transport.close()
    
    async def _authenticate_direct(self, socket_transport: SocketTransport) -> bool:
        try:
            auth_string = f"{self.bridge_config.username}:{self.bridge_config.password}\r\n".encode()
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
            self.logger.error(f"Direct bridge authentication failed: {e}")
            return False
    
    async def _speed_negotiation_direct(self, socket_transport: SocketTransport) -> bool:
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
                                        self.logger.info(f"Speed negotiation successful for direct bridge: {speed} bps ({connection_type})")
                                        
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
    
    async def _bridge_connections(self, serial_transport: SerialTransportProtocol, socket_transport: SocketTransport) -> None:
        try:
            serial_to_socket_task = asyncio.create_task(
                self._bridge_serial_to_socket(serial_transport, socket_transport)
            )
            
            socket_to_serial_task = asyncio.create_task(
                self._bridge_socket_to_serial(socket_transport, serial_transport)
            )
            
            done, pending = await asyncio.wait(
                [serial_to_socket_task, socket_to_serial_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            
            self.logger.info("Bridge connections ended")
            
        except Exception as e:
            self.logger.error(f"Bridge connections error: {e}")
    
    async def _bridge_serial_to_socket(self, serial_transport: SerialTransportProtocol, socket_transport: SocketTransport) -> None:
        try:
            data_count = 0
            no_data_count = 0
            
            while self.running:
                try:
                    data = await serial_transport.read()
                    if data:
                        data_count += 1
                        no_data_count = 0
                        self.logger.debug(f"Serial->Socket #{data_count}: {len(data)} bytes: {data[:20]}...")
                        await socket_transport.write(data)
                    else:
                        no_data_count += 1
                        if no_data_count % 3000 == 0:
                            self.logger.debug(f"No serial data for {no_data_count/1000:.1f} seconds")
                        await asyncio.sleep(0.001)
                        
                except Exception as e:
                    if "semaphore timeout" in str(e).lower() or "winerror 121" in str(e).lower():
                        self.logger.warning("Semaphore timeout detected, applying brief flow control...")
                        await asyncio.sleep(0.01)
                        continue
                    else:
                        self.logger.error(f"Serial->Socket error: {e}")
                        raise
                    
        except Exception as e:
            self.logger.debug(f"Serial to socket bridge ended: {e}")
    
    async def _bridge_socket_to_serial(self, socket_transport: SocketTransport, serial_transport: SerialTransportProtocol) -> None:
        try:
            data_count = 0
            no_data_count = 0
            
            while self.running:
                try:
                    data = await socket_transport.read()
                    if data:
                        data_count += 1
                        no_data_count = 0
                        self.logger.debug(f"Socket->Serial #{data_count}: {len(data)} bytes: {data[:20]}...")
                        await serial_transport.write(data)
                    else:
                        if not await socket_transport.is_connected():
                            self.logger.info("Socket closed, ending bridge")
                            break
                        else:
                            no_data_count += 1
                            if no_data_count % 1000 == 0:
                                self.logger.debug(f"No socket data for {no_data_count/1000:.1f} seconds")
                            await asyncio.sleep(0.001)
                            
                except Exception as e:
                    if "semaphore timeout" in str(e).lower() or "winerror 121" in str(e).lower():
                        self.logger.warning("Semaphore timeout detected, applying brief flow control...")
                        await asyncio.sleep(0.01)
                        continue
                    else:
                        self.logger.error(f"Socket->Serial error: {e}")
                        raise
                    
        except Exception as e:
            self.logger.debug(f"Socket to serial bridge ended: {e}")

def create_bridge_config(bridge_config: PPPBridgeConfig) -> BridgeConfig:
    return BridgeConfig(
        bridge_config=bridge_config,
        buffer_size=16384,
        read_timeout=0.1,
        write_timeout=5.0,
        heartbeat_interval=30.0,
        connection_check_interval=5.0,
        max_concurrent_connections=10,
        enable_flow_control=True,
        enable_compression=False
    )

async def main():
    try:
        check_required_modules()

        config_manager = ConfigurationManager(is_windows=sys.platform.startswith('win'))
        bridge_config = config_manager.load_config()
        
        config = create_bridge_config(bridge_config)
        
        bridge = PPPBridge(config)
        
        if bridge_config.emulate_modem:
            return await bridge.run_modem_emulation()
        else:
            return await bridge.run_direct_bridge()
            
    except MissingDependencyError as exc:
        logging.error(str(exc))
        return 1
    except Exception as e:
        logging.error(f"Bridge failed: {e}")
        return 1

if __name__ == "__main__":
    try:
        config_manager = ConfigurationManager(is_windows=sys.platform.startswith('win'))
        bridge_config = config_manager.load_config()
        debug_enabled = bridge_config.debug
        log_file = bridge_config.log_file
    except Exception:
        debug_enabled = False
        log_file = None
    
    log_level = logging.DEBUG if debug_enabled else logging.INFO
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s" if debug_enabled else "[%(levelname)s] %(message)s"

    log_handlers = [logging.StreamHandler()]
    if log_file:
        try:
            log_handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
        except Exception as log_exc:
            logging.basicConfig(level=log_level, format=log_format)
            logging.getLogger(__name__).warning(f"Failed to open log file {log_file}: {log_exc}")
        else:
            logging.basicConfig(level=log_level, format=log_format, handlers=log_handlers)
    else:
        logging.basicConfig(level=log_level, format=log_format)
    
    try:
        logging.info("VesperNet PPP Bridge v2.0.2 starting")
        runner = EventLoopRunner()
        result = runner.run_loop(main())
        sys.exit(result)
    except MissingDependencyError as exc:
        logging.error(str(exc))
        sys.exit(1)
    except KeyboardInterrupt:
        logging.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        sys.exit(1)
