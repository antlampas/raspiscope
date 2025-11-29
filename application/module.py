"""
Author: Antlampas
CC BY-SA 4.0
https://creativecommons.org/licenses/by-sa/4.0/
"""

import json
import time
from threading    import Thread, Event
from queue        import Empty, Full
from communicator import Communicator

class Module:
    """
    Abstract base class for all functional modules.
    Manages client communication,lifecycle,and message handling
    using a decoupled Communicator instance.
    """
    def __init__(self,name,networkConfig,systemConfig):
        """
        Initializes the Module.

        Args:
            name (str): The unique name of the module.
            networkConfig (dict): Dictionary with network parameters ('address','port',etc.).
            systemConfig (dict): Dictionary with system-wide parameters.
        """
        self._module_name       = name
        self.communicator       = Communicator(commType="client",name=self._module_name,config=networkConfig)
        self.stopEvent          = Event()
        self.communicatorThread = None
        self.queueTimeout       = systemConfig.get("module_message_queue_timeout_s",0.1)

    def run(self):
        """
        Starts the module's main thread and message loops.
        It orchestrates the module's lifecycle by calling onStart,
        mainLoop, and onStop methods, and manages its communication thread.
        """
        self.log("INFO",f"Module '{self._module_name}' starting.")
        self.communicatorThread = Thread(target=self.communicator.run,args=(self.stopEvent,))
        self.communicatorThread.start()

        self.onStart()
        self.mainLoop()
        self.onStop()
        
        if self.communicatorThread:
            self.communicatorThread.join()
        self.log("INFO",f"Module '{self._module_name}' terminated.")

    def mainLoop(self):
        """
        The main loop of the module.
        Fetches messages from the incomingQueue and handles them.
        """
        while not self.stopEvent.is_set():
            try:
                message = self.communicator.incomingQueue.get(block=True,timeout=self.queueTimeout)

                if message.get("Message",{}).get("type") == "Stop":
                    self.log("INFO",f"Module '{self._module_name}' received stop signal.")
                    self.stopEvent.set()
                    break
                
                self.handleMessage(message)
                self.communicator.incomingQueue.task_done()
                time.sleep(0.001)
            except Empty:
                time.sleep(0.001)
                continue
    
    def sendMessage(self,destination,msgType,payload=None):
        """
        Sends a message to the EventManager server via the outgoingQueue.
        This method is thread-safe.
        """
        message = {
            "Sender"      : self._module_name,
            "Destination" : destination,
            "Message"     : {
                                "type"    : msgType,
                                "payload" : payload if payload is not None else {}
                            }
        }
        try:
            self.communicator.outgoingQueue.put(message)
        except Full:
            pass

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
        self.sendMessage("Logger","LogMessage",payload)

    @property
    def module_name(self):
        """
        Returns the configured name of this module.
        """
        return self._module_name

    # --- Methods to be overridden in child classes ---

    def onStart(self):
        """
        Called once when the module starts.
        Useful for initializing hardware,etc.
        """
        pass

    def handleMessage(self,message):
        """
        Called whenever a message arrives from the server.
        Module-specific logic goes here.
        """
        pass

    def onStop(self):
        """
        Called before the module terminates.
        Useful for cleaning up resources (e.g.,GPIO pins,files).
        """
        pass
