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
import asyncio
import logging
import socket
from typing import Optional
from dataclasses import dataclass
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from enum import Enum

try:
    import serial as pyserial
except ImportError:
    pyserial = None

class SerialConnectionType(Enum):
    PHYSICAL = "physical"
    UNIX_SOCKET = "unix_socket"
    TCP_SOCKET = "tcp_socket"
    NAMED_PIPE = "named_pipe"

@dataclass
class SerialConfig:
    device: str
    baud_rate: int = 38400
    timeout: float = 0.1
    connection_type: SerialConnectionType = SerialConnectionType.PHYSICAL

class SerialConnectionInterface(ABC):
    @abstractmethod
    def read(self, size: int = 1) -> bytes:
        pass
    
    @abstractmethod
    def write(self, data: bytes) -> int:
        pass
    
    @abstractmethod
    def flush(self) -> None:
        pass
    
    @abstractmethod
    def close(self) -> None:
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        pass

class UnixSocketConnection(SerialConnectionInterface):
    def __init__(self, socket_path: str, timeout: float = 0.1):
        self.socket_path = socket_path
        self.timeout = timeout
        self.sock = None
        self.is_closed = False
        self.logger = logging.getLogger(__name__)
        self._connect()
    
    def _connect(self):
        try:
            if not os.path.exists(self.socket_path):
                raise FileNotFoundError(f"Unix socket path does not exist: {self.socket_path}")
            
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect(self.socket_path)
            self.is_closed = False
            self.logger.info(f"Unix socket serial connection opened: {self.socket_path}")
            
        except Exception as e:
            self.is_closed = True
            raise ConnectionError(f"Unexpected error connecting to Unix socket: {e}")
    
    def is_connected(self) -> bool:
        if not self.sock or self.is_closed:
            return False
        
        if not os.path.exists(self.socket_path):
            self.logger.info("Unix socket file no longer exists")
            self.close()
            return False
        
        try:
            self.sock.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT)
            return True
        except socket.timeout:
            return True
        except socket.error as e:
            if e.errno in (11, 35):
                return True
            elif e.errno in (32, 104):
                self.logger.info(f"Unix socket connection broken: {e}")
                self.close()
                return False
            else:
                self.logger.debug(f"Unix socket health check warning: {e}")
                return True
        except Exception:
            return True
    
    def read(self, size: int = 1) -> bytes:
        if not self.sock or self.is_closed:
            return b""
        
        try:
            data = self.sock.recv(size)
            if not data:
                self.logger.info("Unix socket connection closed by remote")
                self.close()
                return b""
            return data
        except socket.timeout:
            if not os.path.exists(self.socket_path):
                self.logger.info("Unix socket file removed, connection lost")
                self.close()
                return b""
            return b""
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as e:
            self.logger.info(f"Unix socket connection lost: {e}")
            self.close()
            return b""
        except Exception as e:
            self.logger.error(f"Unix socket read error: {e}")
            self.close()
            return b""
    
    def write(self, data: bytes) -> int:
        if not self.sock:
            return 0
        
        try:
            return self.sock.send(data)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as e:
            self.logger.info(f"Unix socket connection lost during write: {e}")
            self.close()
            return 0
        except Exception as e:
            self.logger.error(f"Unix socket write error: {e}")
            self.close()
            return 0
    
    def flush(self) -> None:
        pass
    
    def close(self) -> None:
        if self.sock and not self.is_closed:
            try:
                self.sock.close()
                self.logger.info("Unix socket serial connection closed")
            except Exception as e:
                self.logger.debug(f"Error closing Unix socket: {e}")
            finally:
                self.sock = None
                self.is_closed = True


class TCPSocketConnection(SerialConnectionInterface):
    def __init__(self, host: str, port: int, timeout: float = 0.1):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.is_closed = False
        self.logger = logging.getLogger(__name__)
        self._connect()
    
    def _connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect((self.host, self.port))
            self.is_closed = False
            self.logger.info(f"TCP socket serial connection opened: {self.host}:{self.port}")
            
        except Exception as e:
            self.is_closed = True
            raise ConnectionError(f"Failed to connect to TCP socket {self.host}:{self.port}: {e}")
    
    def is_connected(self) -> bool:
        if not self.sock or self.is_closed:
            return False
        
        try:
            self.sock.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT)
            return True
        except socket.error as e:
            if e.errno in (11, 35, 10035):
                return True
            elif e.errno == 10054:
                self.logger.info("TCP socket connection reset by peer")
                self.close()
                return False
            else:
                self.logger.info(f"TCP socket connection health check failed: {e}")
                self.close()
                return False
        except Exception:
            return True

    def read(self, size: int = 1) -> bytes:
        if not self.sock:
            return b""
        
        try:
            data = self.sock.recv(size)
            if not data:
                self.logger.info("TCP socket connection closed by remote")
                self.close()
                return b""
            return data
        except socket.timeout:
            return b""
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as e:
            self.logger.info(f"TCP socket connection lost: {e}")
            self.close()
            return b""
        except OSError as e:
            if e.errno == 10054:
                self.logger.info("TCP socket connection forcibly closed by remote host")
            else:
                self.logger.info(f"TCP socket connection error: {e}")
            self.close()
            return b""
        except Exception as e:
            self.logger.error(f"TCP socket read error: {e}")
            self.close()
            return b""
    
    def write(self, data: bytes) -> int:
        if not self.sock:
            return 0
        
        try:
            return self.sock.send(data)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as e:
            self.logger.info(f"TCP socket connection lost during write: {e}")
            self.close()
            return 0
        except OSError as e:
            if e.errno == 10054:
                self.logger.info("TCP socket connection forcibly closed by remote host during write")
            else:
                self.logger.info(f"TCP socket write error: {e}")
            self.close()
            return 0
        except Exception as e:
            self.logger.error(f"TCP socket write error: {e}")
            self.close()
            return 0
    
    def flush(self) -> None:
        pass
    
    def close(self) -> None:
        if self.sock and not self.is_closed:
            try:
                self.sock.close()
                self.logger.info("TCP socket serial connection closed")
            except Exception as e:
                self.logger.debug(f"Error closing TCP socket: {e}")
            finally:
                self.sock = None
                self.is_closed = True

class PhysicalSerialConnection(SerialConnectionInterface):
    def __init__(self, device: str, baud_rate: int = 38400, timeout: float = 0.1):
        self.device = device
        self.baud_rate = baud_rate
        self.timeout = timeout
        self.serial_port = None
        self.logger = logging.getLogger(__name__)
        self._connect()
    
    def _connect(self):
        if not pyserial:
            raise ImportError("pyserial library not available")
        
        try:
            self.serial_port = pyserial.Serial(
                port=self.device,
                baudrate=self.baud_rate,
                timeout=self.timeout
            )
            self.logger.info(f"Physical serial connection opened: {self.device}")
            
        except Exception as e:
            raise ConnectionError(f"Failed to open serial port {self.device}: {e}")
    
    def read(self, size: int = 1) -> bytes:
        if not self.serial_port or not self.serial_port.is_open:
            return b""
        
        try:
            if hasattr(self.serial_port, 'in_waiting'):
                if self.serial_port.in_waiting == 0:
                    data = self.serial_port.read(0)
                    if data is None:
                        self.logger.info("Physical serial device disconnected (PTY closed)")
                        self.close()
                        return b""
            
            data = self.serial_port.read(size)
            
            if not data and size > 0:
                try:
                    _ = self.serial_port.is_open
                    if hasattr(self.serial_port, 'in_waiting'):
                        _ = self.serial_port.in_waiting
                except (OSError, AttributeError) as e:
                    self.logger.info(f"Physical serial device disconnected: {e}")
                    self.close()
                    return b""
            
            return data
            
        except (OSError, AttributeError) as e:
            if "device reports readiness" in str(e) or "No such file or directory" in str(e):
                self.logger.info(f"Physical serial device disconnected (PTY closed): {e}")
            else:
                self.logger.error(f"Serial read error: {e}")
            self.close()
            return b""
        except Exception as e:
            self.logger.error(f"Serial read error: {e}")
            self.close()
            return b""
    
    def write(self, data: bytes) -> int:
        if not self.serial_port:
            return 0
        
        try:
            return self.serial_port.write(data)
        except Exception as e:
            self.logger.error(f"Serial write error: {e}")
            return 0
    
    def flush(self) -> None:
        if self.serial_port:
            try:
                self.serial_port.flush()
            except Exception as e:
                self.logger.error(f"Serial flush error: {e}")
    
    def close(self) -> None:
        if self.serial_port:
            try:
                self.serial_port.close()
                self.logger.info("Physical serial connection closed")
            except Exception as e:
                self.logger.debug(f"Error closing serial port: {e}")
            finally:
                self.serial_port = None
    
    def is_connected(self) -> bool:
        if not self.serial_port:
            return False
            
        try:
            if not self.serial_port.is_open:
                return False
            
            if hasattr(self.serial_port, 'port') and self.serial_port.port:
                if self.serial_port.port.startswith('/dev/tty'):
                    if not os.path.exists(self.serial_port.port):
                        self.logger.info(f"PTY device file no longer exists: {self.serial_port.port}")
                        self.close()
                        return False
            
            try:
                _ = self.serial_port.in_waiting
                return True
            except (OSError, AttributeError):
                self.close()
                return False
                
        except Exception as e:
            self.logger.debug(f"Serial connection check failed: {e}")
            self.close()
            return False

class SerialConnectionFactory:
    @staticmethod
    def detect_connection_type(device: str) -> SerialConnectionType:
        if device.startswith('unix:'):
            return SerialConnectionType.UNIX_SOCKET
        elif device.startswith('tcp:'):
            return SerialConnectionType.TCP_SOCKET
        elif device.startswith('COM') or device.startswith('/dev/'):
            return SerialConnectionType.PHYSICAL
        else:
            return SerialConnectionType.PHYSICAL
    
    @staticmethod
    def create_connection(config: SerialConfig) -> SerialConnectionInterface:
        if config.connection_type == SerialConnectionType.UNIX_SOCKET:
            socket_path = config.device.replace('unix:', '')
            return UnixSocketConnection(socket_path, config.timeout)
        elif config.connection_type == SerialConnectionType.PHYSICAL:
            return PhysicalSerialConnection(config.device, config.baud_rate, config.timeout)
        elif config.connection_type == SerialConnectionType.TCP_SOCKET:
            tcp_parts = config.device.replace('tcp:', '').split(':')
            if len(tcp_parts) != 2:
                raise ValueError(f"Invalid TCP socket format: {config.device}. Expected: tcp:host:port")
            host = tcp_parts[0]
            try:
                port = int(tcp_parts[1])
            except ValueError:
                raise ValueError(f"Invalid port number in TCP socket: {config.device}")
            return TCPSocketConnection(host, port, config.timeout)
        else:
            raise ValueError(f"Unsupported connection type: {config.connection_type}")

class SerialTransport:
    def __init__(self, buffer_size: int = 8192, read_timeout: float = 0.1, write_timeout: float = 5.0):
        self.buffer_size = buffer_size
        self.read_timeout = read_timeout
        self.write_timeout = write_timeout
        self.serial_connection: Optional[SerialConnectionInterface] = None
        self.read_queue: asyncio.Queue = asyncio.Queue()
        self.write_queue: asyncio.Queue = asyncio.Queue()
        self.connected = False
        self.logger = logging.getLogger(__name__)
        self._read_task: Optional[asyncio.Task] = None
        self._write_task: Optional[asyncio.Task] = None
        self._executor = ThreadPoolExecutor(max_workers=2)
    
    async def connect(self, device: str, baud_rate: int = 38400) -> None:
        try:
            self.logger.info(f"Connecting to serial device {device}")
            
            loop = asyncio.get_event_loop()
            connection_type = await loop.run_in_executor(
                self._executor,
                SerialConnectionFactory.detect_connection_type,
                device
            )
            
            self.logger.info(f"Detected connection type: {connection_type}")
            
            serial_config = SerialConfig(
                device=device,
                baud_rate=baud_rate,
                timeout=self.read_timeout,
                connection_type=connection_type
            )
            
            self.serial_connection = await loop.run_in_executor(
                self._executor,
                SerialConnectionFactory.create_connection,
                serial_config
            )
            
            self.connected = True
            
            self._read_task = asyncio.create_task(self._serial_read_loop())
            self._write_task = asyncio.create_task(self._serial_write_loop())
            
            self.logger.info(f"Connected to serial device {device}")
            
        except Exception as e:
            self.logger.error(f"Serial connection failed: {e}")
            raise
    
    async def _serial_read_loop(self) -> None:
        try:
            loop = asyncio.get_event_loop()
            consecutive_empty_reads = 0
            
            while self.connected and self.serial_connection:
                try:
                    if not self.serial_connection.is_connected():
                        self.logger.info("Serial connection lost, stopping read loop")
                        self.connected = False
                        break
                    
                    data = await loop.run_in_executor(
                        self._executor,
                        self.serial_connection.read,
                        self.buffer_size
                    )
                    
                    if data:
                        await self.read_queue.put(data)
                        consecutive_empty_reads = 0
                    else:
                        consecutive_empty_reads += 1
                        
                        if consecutive_empty_reads >= 10:
                            if not self.serial_connection.is_connected():
                                self.logger.info("Serial device disconnected (empty reads), stopping read loop")
                                self.connected = False
                                break
                            consecutive_empty_reads = 0
                        
                        await asyncio.sleep(0.01)
                        
                except Exception as e:
                    self.logger.error(f"Serial read error: {e}")
                    self.connected = False
                    break
                    
        except asyncio.CancelledError:
            self.logger.debug("Serial read loop cancelled")
        except Exception as e:
            self.logger.error(f"Serial read loop error: {e}")
            self.connected = False
    
    async def _serial_write_loop(self) -> None:
        try:
            loop = asyncio.get_event_loop()
            
            while self.connected and self.serial_connection:
                try:
                    if not self.serial_connection.is_connected():
                        self.logger.info("Serial connection lost, stopping write loop")
                        self.connected = False
                        break
                    
                    data = await asyncio.wait_for(
                        self.write_queue.get(),
                        timeout=1.0
                    )
                    
                    bytes_written = await loop.run_in_executor(
                        self._executor,
                        self.serial_connection.write,
                        data
                    )
                    
                    if bytes_written == 0 and len(data) > 0:
                        self.logger.info("Serial write failed, connection may be lost")
                        if not self.serial_connection.is_connected():
                            self.connected = False
                            break
                    
                    await loop.run_in_executor(
                        self._executor,
                        self.serial_connection.flush
                    )
                    
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    self.logger.error(f"Serial write error: {e}")
                    self.connected = False
                    break
                    
        except asyncio.CancelledError:
            self.logger.debug("Serial write loop cancelled")
        except Exception as e:
            self.logger.error(f"Serial write loop error: {e}")
            self.connected = False
    
    async def read(self, size: int = -1) -> bytes:
        if not self.connected:
            raise RuntimeError("Serial transport not connected")
        
        try:
            data = await asyncio.wait_for(
                self.read_queue.get(),
                timeout=self.read_timeout
            )
            return data
            
        except asyncio.TimeoutError:
            return b""
        except Exception as e:
            self.logger.error(f"Serial read error: {e}")
            raise
    
    async def write(self, data: bytes) -> int:
        if not self.connected:
            raise RuntimeError("Serial transport not connected")
        
        try:
            await asyncio.wait_for(
                self.write_queue.put(data),
                timeout=self.write_timeout
            )
            return len(data)
            
        except asyncio.TimeoutError:
            raise TimeoutError("Serial write timeout")
        except Exception as e:
            self.logger.error(f"Serial write error: {e}")
            raise
    
    async def close(self) -> None:
        self.connected = False
        
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        
        if self._write_task:
            self._write_task.cancel()
            try:
                await self._write_task
            except asyncio.CancelledError:
                pass
        
        if self.serial_connection:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    self._executor,
                    self.serial_connection.close
                )
            except Exception as e:
                self.logger.debug(f"Error closing serial connection: {e}")
            finally:
                self.serial_connection = None
        
        self._executor.shutdown(wait=False)
        
        self.logger.info("Serial transport closed")
    
    async def is_connected(self) -> bool:
        if not self.connected or not self.serial_connection:
            return False
        
        try:
            return self.serial_connection.is_connected()
        except Exception:
            return False
