"""
Author: Antlampas
CC BY-SA 4.0
https://creativecommons.org/licenses/by-sa/4.0/
"""

from threading    import Thread
from module       import Module
from configLoader import ConfigLoader

class CLI(Module):
    def __init__(self,moduleConfig,networkConfig,systemConfig):
        if moduleConfig is None:
            full_config = ConfigLoader().get_config()
            moduleConfig = full_config.get("modules", {}).get("cli", {})

        super().__init__("CLI",networkConfig,systemConfig)
        self.config       = moduleConfig or {}
        self.promptThread = None

    def _promptLoop(self):
        while not self.stopEvent.is_set():
            try:
                command = input("Prompt: ").strip().lower()
            except EOFError:
                self.stopEvent.set()
                break
            except KeyboardInterrupt:
                self.stopEvent.set()
                break

            if not command:
                continue

            if command in {"takePicture"}:
                self.sendMessage("Camera","Take")
            elif command in {"analyze","analysis"}:
                self.sendMessage("Camera","Analyze")
            elif command in {"calibrateCamera"}:
                self.sendMessage("Camera","Calibrate")
            elif command in {"calibrateSensor"}:
                self.sendMessage("CuvetteSensor","Calibrate")
            elif command in {"quit","exit"}:
                self.stopEvent.set()
            else:
                print(f"Unknown command: {command}")

    def onStart(self):
        """
        Initializes and configures the command line module.
        """
        self.sendMessage("EventManager", "Register")
        self.promptThread = Thread(target=self._promptLoop,daemon=True)
        self.promptThread.start()

    def handleMessage(self,message):
        """
        Handles incoming messages.
        """
        msgType = message.get("Message",{}).get("type")
        payload = message.get("Message",{}).get("payload",{})
        if msgType == "PictureTaken":
            self.log("INFO","Picture captured.")
            if payload and payload.get("image"):
                print("Picture received")
        elif msgType == "AnalysisComplete":
            self.log("INFO","Analysis results available.")
            if payload:
                print("Analysis results:",payload)
        elif msgType == "AnalysisError":
            self.log("ERROR",payload.get("message","Unknown analysis error."))

    def onStop(self):
        self.stopEvent.set()
        if self.promptThread and self.promptThread.is_alive():
            self.promptThread.join(timeout=1)
