"""
Author: Antlampas
CC BY-SA 4.0
https://creativecommons.org/licenses/by-sa/4.0/
"""

import time
import statistics
import json
from gpiozero     import InputDevice,GPIOZeroError
from threading    import Thread
from module       import Module
from configLoader import ConfigLoader

class CuvetteSensor(Module):
    """
    Detects the presence of the cuvette using a Hall effect sensor.
    Inherits from the base Module class.
    """
    def __init__(self,moduleConfig,networkConfig,systemConfig):
        if moduleConfig is None:
            full_config = ConfigLoader().get_config()
            moduleConfig = full_config.get("modules", {}).get("cuvetteSensor", {})

        super().__init__("CuvetteSensor",networkConfig,systemConfig)
        self.config            = moduleConfig or {}
        self.inputPin          = self.config.get('pin')
        self.sensor            = None
        self.pollInterval      = self.config.get('poll_interval_s', 1.0)
        self.isPresent         = False
        self.numSamples        = calibrationCfg.get('samples', 0)

    def onStart(self):
        """
        Initializes the sensor and starts calibration.
        """
        self.sendMessage("EventManager", "Register")
        try:
            if self.inputPin is None:
                raise ValueError("Missing 'pin' configuration for CuvetteSensor")
            self.sensor = InputDevice(self.inputPin)
            self.log("INFO",f"Cuvette sensor initialized on pin {self.inputPin}.")
        except GPIOZeroError as e:
            self.log("ERROR",f"Could not initialize sensor on pin {self.inputPin}. Details: {e}")
            self.sensor = None
        except ValueError as e:
            self.log("ERROR", str(e))
            self.sensor = None

    def mainLoop(self):
        """
        Overrides the main loop to continuously check for presence.
        """
        if not self.sensor:
            time.sleep(1)
            return
        previousState = self.checkPresence()
        while not self.stopEvent.is_set():
            if self.sensor.is_active:
                currentState = True
            else:
                currentState = False
            if currentState != previousState:
                self.isPresent = currentState
                if self.isPresent:
                    self.sendMessage("Camera","CuvettePresent")
                    self.log("INFO","Cuvette detected.")
                else:
                    self.sendMessage("Camera","CuvetteAbsent")
                    self.log("INFO","Cuvette absent.")
                previousState = currentState
            time.sleep(self.pollInterval)