"""
Author: Antlampas
CC BY-SA 4.0
https://creativecommons.org/licenses/by-sa/4.0/
"""

import time
from threading    import Thread
from gpiozero     import InputDevice,GPIOZeroError

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
        self.config             = moduleConfig or {}
        self.inputPin           = self.config.get('pin')
        pollInterval            = self.config.get('poll_interval_s', 1.0)
        try:
            self.pollInterval   = float(pollInterval)
        except (TypeError,ValueError):
            self.pollInterval   = 1.0
        self.isPresent          = False
        self.mode               = "Analysis"
        self.sensor             = None
        self._presence_thread   = None

    def onStart(self):
        """
        Initializes the sensor monitoring thread.
        """
        self.sendMessage("EventManager", "Register")

        if self.inputPin is None:
            self.log("ERROR","Missing 'pin' configuration for CuvetteSensor")
            return

        try:
            self.sensor = InputDevice(self.inputPin)
            self.log("INFO",f"Cuvette sensor initialized on pin {self.inputPin}.")
        except (GPIOZeroError,ValueError,RuntimeError) as exc:
            self.log("ERROR",f"Failed to initialize CuvetteSensor on pin {self.inputPin}: {exc}")
            self.sensor = None
            return

        self.isPresent = bool(self.sensor.is_active)
        self._presence_thread = Thread(target=self._presence_loop,daemon=True)
        self._presence_thread.start()

    def _presence_loop(self):
        if self.sensor is None:
            return

        previous_active = bool(self.sensor.is_active)
        self.isPresent = previous_active
        poll_interval = self.pollInterval if self.pollInterval > 0 else 0.01

        try:
            while not self.stopEvent.is_set():
                current_active = bool(self.sensor.is_active)
                if current_active != previous_active:
                    self._handle_presence_transition(previous_active,current_active)
                    previous_active = current_active
                time.sleep(poll_interval)
        except Exception as exc:
            self.log("ERROR",f"Presence loop error: {exc}")
        finally:
            self.isPresent = previous_active

    def _handle_presence_transition(self,was_active,is_active):
        if was_active and not is_active:
            self._on_presence_detected()
        elif not was_active and is_active:
            self._on_presence_lost()

    def _on_presence_detected(self):
        self.isPresent = True
        mode = (self.mode or "").lower()
        if mode == "analysis":
            self.sendMessage("Camera","CuvettePresent")
            self.log("INFO","CuvettePresent")
        elif mode == "addsubstance":
            self.sendMessage("Analysis","AddSubstance")
            self.log("INFO","AddSubstance")
        else:
            self.log("WARNING",f"Presence detected in unexpected mode '{self.mode}'.")

    def _on_presence_lost(self):
        self.isPresent = False
        self.sendMessage("All","CuvetteAbsent")
        self.log("INFO","CuvetteAbsent")

    def handleMessage(self,message):
        """
        Handles incoming messages.
        """
        msgType = message.get("Message",{}).get("type")

        if msgType == "Analysis":
            self.log("INFO","Received 'Analysis' signal. Switch to Analysis mode.")
            self.mode = "Analysis"
            self.sendMessage("All","ModeChanged",{"mode": self.mode})
            self.log("INFO","Switched to Analysis mode.")
        elif msgType == "AddSubstance":
            self.log("INFO","Received 'AddSubstance' signal. Switch to AddSubstance mode.")
            self.mode = "AddSubstance"
            self.sendMessage("All","ModeChanged",{"mode": self.mode})
            self.log("INFO","Switched to AddSubstance mode.")

    def onStop(self):
        """
        Ensures the presence monitoring thread is terminated cleanly.
        """
        self.stopEvent.set()

        if self._presence_thread and self._presence_thread.is_alive():
            self._presence_thread.join(timeout=max(1.0,self.pollInterval * 2.0))
        self._presence_thread = None

        if self.sensor is not None:
            try:
                self.sensor.close()
            except Exception:
                pass
            self.sensor = None
