"""
Author: Antlampas
CC BY-SA 4.0
https://creativecommons.org/licenses/by-sa/4.0/
"""

import json
import signal
import time
from multiprocessing import Process
from threading import Thread,Event
from queue import Empty, Full

from communicator import Communicator
from configLoader import ConfigLoader


class EventManager:
    """
    Orchestrates modules by running them as separate processes
    and routing messages between them based on a central configuration file.
    """
    def __init__(self,configPath="config.json"):
        """
        Initializes the EventManager.
        """
        configLoader            = ConfigLoader(configPath)
        config                  = configLoader.get_config()
        networkConfig           = config['network']
        self.name               = "EventManager"
        self.communicator       = Communicator("server",name=self.name,config=networkConfig)
        self.runningProcesses   = []
        self.registered_modules = {}
        self._stopEvent         = Event()

    def run(self):
        """Starts the communication server and all module processes."""
        commThread = Thread(target=self.communicator.run,args=(self._stopEvent,))
        commThread.start()
        try:
            while not self._stopEvent.is_set():
                self.route()
                time.sleep(0.001)
        finally:
            self._cleanup()
            commThread.join()
            self.log("INFO","EventManager terminated.")

    def route(self):
        """Pops messages from the queue and routes them."""
        try:
            message = self.communicator.incomingQueue.get(timeout=0.1)
            destination = message.get("Destination")
            sender = message.get("Sender")
            msgType = message.get("Message", {}).get("type")

            if destination == "EventManager":
                if msgType == "register":
                    self._handleRegistration(sender)
                    return
                elif msgType == "unregister":
                    self._handleUnregistration(sender)
                    return
                elif msgType == "Stop":
                    self.log("INFO",f"Stop command received from {sender}. Initiating shutdown...")
                    self.stop()
                else:
                    # Handle other commands for the EventManager here
                    self.log("INFO",f"Command '{msgType}' received for EventManager from {sender}")
            else:
                # Put into the outgoing queue for sending
                # The tuple (destination,message) is interpreted by the server's consumer
                self.log("INFO",f"Routing message from {sender} to {destination}")
                self.communicator.outgoingQueue.put((destination,message))

        except Empty:
            return # No message,continue
        except (AttributeError,TypeError) as e:
            self.log("ERROR",f"Error while routing message: {e} - Message: {message}")
    
    def _handleRegistration(self, moduleName):
        """
        Handles the registration of a new module by adding it to the
        dictionary of registered modules.
        """
        if moduleName not in self.registered_modules:
            self.log("INFO", f"Registering new module: {moduleName}")
            self.registered_modules[moduleName] = {
                "name": moduleName,
                "status": "registered",
                "registrationTime": time.time()
            }
        else:
            self.log("WARNING", f"Module '{moduleName}' is already registered.")

    def _handleUnregistration(self, moduleName):
        """
        Handles the unregistration of a module by removing it from the
        dictionary of registered modules.
        """
        if moduleName in self.registered_modules:
            self.log("INFO", f"Unregistering module: {moduleName}")
            self.registered_modules.pop(moduleName, None)
        else:
            self.log("WARNING", f"Module '{moduleName}' not found for unregistration.")

    def stop(self):
        """Stops the EventManager."""
        self.log("INFO","Shutdown signal received. Initiating termination...")
        self._stopEvent.set()

    def _cleanup(self):
        """Cleans up resources and terminates module processes."""
        self.log("INFO","Sending stop signal to all modules...")
        stopMessage = {
            "Sender": self.name,
            "Destination": "All",
            "Message": {"type": "Stop"}
        }
        self.communicator.outgoingQueue.put(("All",stopMessage))

        self.log("INFO","Terminating module processes...")
        for pInfo in self.runningProcesses:
            if pInfo['process'].is_alive():
                pInfo['process'].terminate()
                pInfo['process'].join(timeout=1)
                self.log("INFO",f"Process {pInfo['name']} terminated.")

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
        logMessage = {
            "Sender"      : self.name,
            "Destination" : "Logger",
            "Message"     : {
                                "type"    : "LogMessage",
                                "payload" : payload if payload is not None else {}
                            }
        }
        try:
            self.communicator.outgoingQueue.put(("Logger",logMessage))
        except Full:
            pass