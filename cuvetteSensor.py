"""
Author: Antlampas
CC BY-SA 4.0
https://creativecommons.org/licenses/by-sa/4.0/
"""

import time
from multiprocessing import Process, Pipe
from gpiozero     import InputDevice,GPIOZeroError
from threading    import Thread

from module       import Module
from configLoader import ConfigLoader


def _presence_monitor(conn,inputPin,pollInterval,initialMode):
    """Process target that monitors the Hall effect sensor."""
    mode = initialMode
    try:
        if inputPin is None:
            raise ValueError("Missing 'pin' configuration for CuvetteSensor")
        sensor = InputDevice(inputPin)
        try:
            conn.send({
                "type"    : "log",
                "level"   : "INFO",
                "message" : f"Cuvette sensor initialized on pin {inputPin}."
            })
        except Exception:
            pass
        try:
            conn.send({"type": "status","status": "ready"})
        except Exception:
            pass
    except (GPIOZeroError,ValueError) as exc:
        try:
            conn.send({
                "type"    : "log",
                "level"   : "ERROR",
                "message" : str(exc)
            })
        except Exception:
            pass
        try:
            conn.send({"type": "status","status": "error"})
        except Exception:
            pass
        conn.close()
        return

    previousState = not sensor.is_active
    running = True

    try:
        while running:
            try:
                while conn.poll():
                    command = conn.recv()
                    if not isinstance(command,dict):
                        continue
                    cmdType = command.get("type")
                    if cmdType == "stop":
                        running = False
                        break
                    if cmdType == "mode":
                        mode = command.get("mode",mode)
                if not running:
                    break
            except EOFError:
                break

            currentState = not sensor.is_active
            if currentState != previousState:
                try:
                    conn.send({
                        "type"    : "state_change",
                        "present" : currentState,
                        "mode"    : mode
                    })
                except Exception:
                    running = False
                    break
                previousState = currentState
            time.sleep(pollInterval)
    except Exception as exc:
        try:
            conn.send({
                "type"    : "log",
                "level"   : "ERROR",
                "message" : f"Presence loop error: {exc}"
            })
        except Exception:
            pass
        try:
            conn.send({"type": "status","status": "error"})
        except Exception:
            pass
    finally:
        try:
            conn.send({"type": "status","status": "stopped"})
        except Exception:
            pass
        conn.close()


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
        self._presence_process  = None
        self._presence_conn     = None
        self._presence_listener = None

    def onStart(self):
        """
        Initializes the sensor monitoring process and supporting listener.
        """
        self.sendMessage("EventManager", "Register")

        if self.inputPin is None:
            self.log("ERROR","Missing 'pin' configuration for CuvetteSensor")
            return

        parent_conn, child_conn = Pipe()
        self._presence_conn = parent_conn

        try:
            self._presence_process = Process(
                target=_presence_monitor,
                args=(child_conn,self.inputPin,self.pollInterval,self.mode)
            )
            self._presence_process.daemon = True
            self._presence_process.start()
            child_conn.close()
        except Exception as exc:
            self.log("ERROR",f"Failed to start presence monitoring process: {exc}")
            self._presence_conn = None
            self._presence_process = None
            try:
                child_conn.close()
            except Exception:
                pass
            return

        self._presence_listener = Thread(target=self._presence_listener_loop,daemon=True)
        self._presence_listener.start()

        self._notify_presence_mode_change()

    def _presence_listener_loop(self):
        """
        Listens for updates from the presence monitoring process.
        """
        while not self.stopEvent.is_set():
            conn = self._presence_conn
            if not conn:
                time.sleep(0.1)
                continue
            try:
                if conn.poll(0.1):
                    payload = conn.recv()
                    self._process_presence_message(payload)
            except (EOFError,BrokenPipeError,OSError):
                self._handle_presence_disconnection()
                break

    def _process_presence_message(self,payload):
        if not isinstance(payload,dict):
            return

        msgType = payload.get("type")
        if msgType == "log":
            level   = payload.get("level","INFO")
            message = payload.get("message","")
            if message:
                self.log(level,message)
        elif msgType == "state_change":
            present = bool(payload.get("present"))
            mode    = payload.get("mode") or self.mode
            self._handle_presence_event(present,mode)
        elif msgType == "status":
            status = payload.get("status")
            if status == "ready":
                pass
            elif status == "error":
                self.log("ERROR","Presence monitoring process reported an error.")
                self._handle_presence_disconnection()
            elif status == "stopped":
                self._handle_presence_disconnection()

    def _handle_presence_event(self,isPresent,mode):
        self.isPresent = isPresent
        if self.isPresent:
            if mode == "Analysis":
                self.sendMessage("Camera","CuvettePresent")
                self.log("INFO","Cuvette detected.")
            elif mode == "AddSubstance":
                self.sendMessage("Analysis","AddSubstance")
                self.log("INFO","Add Substance requested.")
        else:
            if mode == "Analysis":
                self.sendMessage("Camera","CuvetteAbsent")
            elif mode == "AddSubstance":
                self.sendMessage("Analysis","CuvetteAbsent")
            self.log("INFO","Cuvette absent.")

    def _notify_presence_mode_change(self):
        self._send_to_presence_process({"type": "mode","mode": self.mode})

    def _send_to_presence_process(self,message):
        if not self._presence_conn:
            return
        try:
            self._presence_conn.send(message)
        except (BrokenPipeError,EOFError,OSError):
            self._handle_presence_disconnection()

    def _handle_presence_disconnection(self):
        if self._presence_conn:
            try:
                self._presence_conn.close()
            except OSError:
                pass
            self._presence_conn = None

        if self._presence_process:
            self._presence_process.join(timeout=0.5)
            if self._presence_process.is_alive():
                self._presence_process.terminate()
            self._presence_process = None

    def _stop_presence_process(self):
        if self._presence_conn:
            self._send_to_presence_process({"type": "stop"})

        if self._presence_listener and self._presence_listener.is_alive():
            self._presence_listener.join(timeout=1.0)

        self._handle_presence_disconnection()
        self._presence_listener = None

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
            self._notify_presence_mode_change()
        elif msgType == "AddSubstance":
            self.log("INFO","Received 'AddSubstance' signal. Switch to AddSubstance mode.")
            self.mode = "AddSubstance"
            self.sendMessage("All","ModeChanged",{"mode": self.mode})
            self.log("INFO","Switched to AddSubstance mode.")
            self._notify_presence_mode_change()

    def onStop(self):
        """
        Ensures the presence monitoring process is terminated cleanly.
        """
        self._stop_presence_process()
