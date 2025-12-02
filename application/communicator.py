"""
Author: Antlampas
CC BY-SA 4.0
https://creativecommons.org/licenses/by-sa/4.0/
"""

import json
import socket
import time
from threading import Thread, Event
from queue     import Queue, Empty, Full

class Communicator:
    """
    Handles inter-process communication (IPC) for modules and the EventManager.
    It works as either a server (for the EventManager) or a client (for modules),
    using a network socket to send and receive JSON-formatted messages.

    The event format is a JSON dictionary with the following mandatory keys:

    - **"Sender"** (str): The unique name of the module that sent the message (e.g., "CuvetteSensor").
    - **"Destination"** (str): The unique name of the target module. "All" can be used for broadcast messages.
    - **"Message"** (dict): A nested dictionary containing the message details.
      - **"type"** (str): A string representing the type of event (e.g., "CuvettePresent", "TurnOn", "LogMessage").
      - **"payload"** (dict, optional): A dictionary containing the data associated with the event. The structure of this dictionary depends on the `type` of the message. This field is optional and can be an empty dictionary if no data is needed.
    """
    def __init__(self, commType, name, config):
        """
        Initializes the Communicator instance.

        Args:
            commType (str): "server" for the EventManager or "client" for a Module.
            name (str): The name of the module or "Server" for the EventManager.
            config (dict): The network configuration with 'address' and 'port'.
        """
        self.commType = commType
        self.name = name
        self.config = config
        self.conn = None
        self.server_socket = None
        self.incomingQueue = Queue()
        self.outgoingQueue = Queue()
        self.client_threads = []
        self.client_sockets = {}

    def run(self, stopEvent=None):
        """
        Starts the communication loop. The behavior depends on whether the
        instance is a server or a client.
        """
        if self.commType == "server":
            self._initializeServer(stopEvent)
            self._runServer(stopEvent)
        elif self.commType == "client":
            self._runClient(stopEvent)
        else:
            self.log("ERROR",f"Unknown communicator type '{self.commType}'")

    def _initializeServer(self, stopEvent):
        """
        Initializes the server socket.

        This method creates the server socket, sets socket options for address reuse,
        and binds it to the address and port specified in the configuration.
        It then starts listening for incoming connections and launches a separate
        thread to handle the outgoing message queue.

        Args:
            stopEvent (threading.Event): An event to signal when to stop the server.
        """
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.settimeout(1.0)  # To allow graceful exit

        try:
            self.server_socket.bind((self.config['address'], self.config['port']))
            self.server_socket.listen(5)
            self.log("INFO",f"Server started on {self.config['address']}:{self.config['port']}")
        except OSError as e:
            self.log("ERROR",f"Could not start server. Details: {e}")
            return

        # Start a dedicated thread for sending messages from the outgoing queue
        send_thread = Thread(target=self._serverSendLoop, args=(stopEvent,))
        send_thread.daemon = True
        send_thread.start()

    # --- Server-side methods ---
    def _runServer(self, stopEvent):
        """
        Runs the server loop for the EventManager.
        Accepts connections and manages threads for each client.
        """
        while not stopEvent.is_set():
            try:
                conn, addr = self.server_socket.accept()
                self.log("INFO",f"Accepted connection from {addr}")

                # Identify client by its initial message
                initial_msg_data = conn.recv(1024).decode('utf-8')
                initial_msg = json.loads(initial_msg_data)
                client_name = initial_msg.get('name')

                if client_name:
                    self.client_sockets[client_name] = conn
                    conn.settimeout(1.0)
                    client_thread = Thread(target=self._serverHandleClient, args=(client_name, conn, stopEvent))
                    client_thread.daemon = True
                    self.client_threads.append(client_thread)
                    client_thread.start()
                    self.log("INFO",f"Client thread started for '{client_name}'")
                else:
                    conn.close()
                    self.log("WARNING","Received connection from unknown client. Connection closed.")
                time.sleep(0.001)
            except socket.timeout:
                continue
            except Exception as e:
                self.log("ERROR",f"Server error: {e}")

        # Cleanup
        if send_thread.is_alive():
            send_thread.join(timeout=1.0)
        for client_thread in self.client_threads:
            if client_thread.is_alive():
                client_thread.join(timeout=1.0)
        self.server_socket.close()

    def _serverSendLoop(self, stopEvent):
        """
        (SERVER-SIDE) Processes the outgoing queue to send messages to clients.
        This loop is responsible for the actual message routing.
        """
        while not stopEvent.is_set():
            try:
                # EventManager puts tuples of (destination, message) in the queue
                destination, message = self.outgoingQueue.get(block=True, timeout=1.0)
                json_message = json.dumps(message) + '\n'  # Add a delimiter

                if destination == "All":
                    # Broadcast to all connected clients, EXCLUDING the sender
                    sender = message.get("Sender")
                    for name, sock in list(self.client_sockets.items()):
                        if name != sender:
                            try:
                                sock.sendall(json_message.encode('utf-8'))
                            except (socket.error, BrokenPipeError):
                                self.log("WARNING",f"Failed to send to client '{name}'. Removing.")
                                self.client_sockets.pop(name, None)
                elif destination in self.client_sockets:
                    # Unicast message to a specific client
                    try:
                        sock = self.client_sockets[destination]
                        sock.sendall(json_message.encode('utf-8'))
                    except (socket.error, BrokenPipeError):
                        self.log("WARNING",f"Failed to send to client '{destination}'. Removing.")
                        self.client_sockets.pop(destination, None)
                else:
                    self.log("WARNING",f"Destination '{destination}' not found for message.")
                self.outgoingQueue.task_done()
                time.sleep(0.001)
            except Empty:
                time.sleep(0.001)
                continue  # No message to send, continue the loop
            except Exception as e:
                self.log("ERROR",f"Error in server send loop: {e}")
                break

    def _serverHandleClient(self, client_name, conn, stopEvent):
        """
        Thread-specific loop for handling a single client connection.
        """
        buffer = ""
        while not stopEvent.is_set():
            try:
                data = conn.recv(4096).decode('utf-8')
                if data:
                    buffer += data
                    while '\n' in buffer:
                        message_str, buffer = buffer.split('\n', 1)
                        if message_str:
                            messages = self._parseMessages(message_str)
                            for message in messages:
                                self.incomingQueue.put(message)
                else:  # Client disconnected
                    self.log("INFO",f"Client '{client_name}' disconnected.")
                    self.client_sockets.pop(client_name, None)  # Remove the socket
                    break
                time.sleep(0.001)
            except socket.timeout:
                time.sleep(0.001)
                continue
            except (socket.error, ConnectionResetError):
                self.log("WARNING",f"Client '{client_name}' connection lost.")
                self.client_sockets.pop(client_name, None)  # Remove the socket
                break
            except Exception as e:
                self.log("ERROR",f"Error handling client '{client_name}': {e}")
                self.client_sockets.pop(client_name, None)  # Remove the socket
                break

    # --- Client-side methods ---
    def _runClient(self, stopEvent):
        """
        Runs the client loop for a module.
        Manages connection to the server and message exchange.
        """
        while not stopEvent.is_set():
            try:
                self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.conn.connect((self.config['address'], self.config['port']))
                self.conn.settimeout(1.0)
                # Send name for identification
                initial_msg = json.dumps({"name": self.name}) + '\n'
                self.conn.sendall(initial_msg.encode('utf-8'))
                self.log("INFO",f"Client '{self.name}' connected to server.")
                # Start a separate thread to handle sending messages
                send_thread = Thread(target=self._clientSendLoop, args=(stopEvent,))
                send_thread.daemon = True
                send_thread.start()
                self._clientReceiveLoop(stopEvent)
                send_thread.join()
                time.sleep(0.001)
            except (ConnectionRefusedError, socket.timeout):
                reconnect_delay = self.config.get('client_reconnect_delay_s', 3)
                self.log("WARNING",f"Connection failed. Retrying in {reconnect_delay} seconds...")
                if self.conn:
                    self.conn.close()
                    self.conn = None # Set to None after closing
                time.sleep(reconnect_delay)
            except Exception as e:
                self.log("ERROR",f"Client '{self.name}' error: {e}")
                if self.conn:
                    self.conn.close()
                    self.conn = None # Set to None after closing
                break

        if self.conn:
            self.conn.close()
            self.conn = None # Set to None after closing

    def _clientReceiveLoop(self, stopEvent):
        """
        Receives messages from the server and puts them in the incoming queue.
        """
        buffer = ""
        while not stopEvent.is_set():
            try:
                data = self.conn.recv(4096).decode('utf-8')
                if data:
                    buffer += data
                    while '\n' in buffer:
                        message_str, buffer = buffer.split('\n', 1)
                        if message_str:
                            messages = self._parseMessages(message_str)
                            for message in messages:
                                self.incomingQueue.put(message)
                else:
                    self.log("INFO","Server disconnected.")
                    break
                time.sleep(0.001)
            except socket.timeout:
                time.sleep(0.001)
                continue
            except (socket.error, ConnectionResetError):
                self.log("WARNING","Connection to server lost.")
                break
            except Exception as e:
                self.log("ERROR",f"Error receiving data: {e}")
                break

    def _clientSendLoop(self, stopEvent):
        """
        Sends messages from the outgoing queue to the server.
        """
        while not stopEvent.is_set():
            try:
                message = self.outgoingQueue.get(block=True, timeout=1.0)
                json_data = json.dumps(message) + '\n'
                self.conn.sendall(json_data.encode('utf-8'))
                self.outgoingQueue.task_done()
                time.sleep(0.001)
            except Empty:
                time.sleep(0.001)
                continue
            except (socket.error, ConnectionResetError):
                self.log("ERROR","Failed to send message: connection lost.")
                break
            except Exception as e:
                self.log("ERROR",f"Error sending message: {e}")
                break

    # --- Utility methods ---
    def _parseMessages(self, data):
        """
        Parses a raw data string into a list of JSON messages.
        """
        messages = []
        try:
            # A single, complete JSON string is expected here
            messages.append(json.loads(data))
        except json.JSONDecodeError as e:
            self.log("ERROR",f"JSON parsing error: {e} in data: '{data}'")
        return messages

    def log(self,level,message):
        """
        Sends a log message to the Logger module.

        Args:
            level (str): The log level (e.g., "INFO","ERROR","DEBUG").
            message (str): The text of the log message.
        """
        payload = {
            "level"   : level,
            "message" : message
        }
        log_message = {
            "Sender"      : self.name,
            "Destination" : "Logger",
            "Message"     : {
                                "type"    : "LogMessage",
                                "payload" : payload if payload is not None else {}
                            }
        }
        try:
            if self.commType == "server":
                self.outgoingQueue.put(("Logger", log_message))
            else:
                self.outgoingQueue.put(log_message)
        except Full:
            pass