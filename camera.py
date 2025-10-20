"""
Author: Antlampas
CC BY-SA 4.0
https://creativecommons.org/licenses/by-sa/4.0/
"""

import numpy
import time
import cv2
import base64
import json
from picamera2 import Picamera2
from threading import Thread, Event, Lock
from module    import Module
from configLoader import ConfigLoader

class Camera(Module):
    """
    Manages the PiCamera.
    Inherits from the base Module class.
    """
    def __init__(self,moduleConfig,networkConfig,systemConfig):
        super().__init__("Camera",networkConfig,systemConfig)
        if moduleConfig is None:
            full_config = ConfigLoader().get_config()
            moduleConfig = full_config.get("modules", {}).get("camera", {})

        self.config    = moduleConfig or {}
        resolution_cfg = self.config.get('resolution', (1920, 1080))
        if isinstance(resolution_cfg, (list, tuple)) and len(resolution_cfg) == 2:
            self.resolution = (int(resolution_cfg[0]), int(resolution_cfg[1]))
        else:
            self.resolution = (1920, 1080)
        self.gain        = self._safe_float(self.config.get('gain', 1.0), fallback=1.0)
        self.exposure    = int(self._safe_float(self.config.get('exposure', 10000), fallback=10000))
        self.awb_gains   = self._parse_awb_gains(self.config.get('awb_gains'))
        self.camera      = None

        self.light_on_timeout   = self._get_duration('light_on_timeout_s', default=2.0)
        self.light_settle_time  = self._get_duration('light_settle_time_s', default=0.05)
        self.control_settle_time = self._get_duration('control_settle_time_s', default=0.02)

        self._light_ready_event     = Event()
        self._capture_lock          = Lock()
        self._manual_mode_configured = False


    def _safe_float(self, value, fallback):
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    def _parse_awb_gains(self, value):
        if isinstance(value, (list, tuple)) and len(value) == 2:
            try:
                r_gain = float(value[0])
                b_gain = float(value[1])
                if r_gain > 0 and b_gain > 0:
                    return (r_gain, b_gain)
            except (TypeError, ValueError):
                pass
        return (1.0, 1.0)

    def _get_duration(self, key, default):
        raw = self.config.get(key, default)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = default
        return max(0.0, value)

    def onStart(self):
        """
        Initializes and configures the camera when the module starts.
        """
        self.sendMessage("EventManager", "Register")
        try:
            self.camera = Picamera2()
            camConfig  = self.camera.create_still_configuration({"size": self.resolution})
            self.camera.configure(camConfig)
            self.camera.start()
            self._manual_mode_configured = False
            self._ensure_manual_mode(force=True)
            self.log("INFO",f"Camera started and configured with resolution {self.resolution}.")
        except Exception as e:
            self.log("ERROR",f"Could not initialize camera: {e}")
            self.camera = None

    def handleMessage(self,message):
        """
        Handles incoming messages.
        """
        msgType = message.get("Message",{}).get("type")
        sender = message.get("Sender")
        if sender == "LightSource" and msgType in ("TurnedOn","TurnedOff"):
            if msgType == "TurnedOn":
                self._light_ready_event.set()
            else:
                self._light_ready_event.clear()
            return

        if not self.camera:
            self.log("WARNING","Camera not available,ignoring command.")
            return

        if msgType == "CuvettePresent":
            self.log("INFO","Received 'Cuvette Present' signal. Taking a picture.")
            self._schedule_picture_capture("Analysis","Analyze","Picture taken and sent for analysis.")
        elif msgType == "Take":
            self.log("INFO","Received 'Take' command. Taking a picture.")
            self._schedule_picture_capture("All","PictureTaken","Picture taken and sent to anyone listening.")
        elif msgType == "Analyze":
            self.log("INFO","Received 'Analyze' command. Starting analysis.")
            self._schedule_picture_capture("Analysis","Analyze","Picture taken and sent for analysis.")
        elif msgType == "Calibrate":
            self.log("INFO","Received 'Calibrate' command. Starting calibration.")
            self.calibrate()

    def _schedule_picture_capture(self,destination,msg_type,success_log,failure_log="Failed to take a picture."):
        """
        Launches an asynchronous capture workflow so the main loop can keep
        processing messages (e.g., waiting for the LED to confirm it is on).
        """
        def worker():
            picture = self.takePicture()
            if picture:
                self.sendMessage(destination,msg_type,picture)
                self.log("INFO",success_log)
            else:
                self.log("ERROR",failure_log)

        capture_thread = Thread(target=worker,daemon=True)
        capture_thread.start()

    def takePicture(self):
        """
        Takes a picture and sends it to the Analysis module.
        """
        if not self.camera:
            self.log("ERROR","Cannot take picture,camera not initialized.")
            return None

        frame = None
        led_request_sent = False

        with self._capture_lock:
            self.log("INFO","Taking picture...")
            self._ensure_manual_mode()

            self._light_ready_event.clear()
            self.sendMessage("LightSource","TurnOn")
            led_request_sent = True

            light_ready = self._light_ready_event.wait(self.light_on_timeout)
            if not light_ready:
                self.log("WARNING",f"Timed out waiting for light source to turn on after {self.light_on_timeout:.2f}s; proceeding with capture.")

            if self.light_settle_time > 0:
                time.sleep(self.light_settle_time)

            self._wait_for_camera_settle()

            try:
                frame = self.camera.capture_array("main")
            except Exception as exc:
                self.log("ERROR",f"Failed to capture image: {exc}")
                frame = None
            finally:
                if led_request_sent:
                    self.sendMessage("LightSource","TurnOff")
                self._light_ready_event.clear()

        if frame is None:
            return None

        try:
            success, buffer = cv2.imencode('.jpg', frame)
        except cv2.error as exc:
            self.log("ERROR",f"Failed to encode image: {exc}")
            return None

        if not success:
            self.log("ERROR","Failed to encode image: imencode returned unsuccessful status.")
            return None

        imageB64 = base64.b64encode(buffer).decode('utf-8')
        payload = {"image": imageB64}
        self.log("INFO","Picture taken")
        return payload

    def _ensure_manual_mode(self, force=False):
        if not self.camera:
            return

        if not force and self._manual_mode_configured:
            return

        try:
            self.camera.set_controls({
                "AeEnable": False,
                "AwbEnable": False
            })
        except Exception as exc:
            self.log("WARNING",f"Failed to disable camera auto controls: {exc}")

        self._apply_camera_controls(self.gain, self.exposure, self.awb_gains)
        self._manual_mode_configured = True

    def _apply_camera_controls(self, gain, exposure, awb_gains):
        if not self.camera:
            return

        controls = {}
        if gain is not None:
            controls["AnalogueGain"] = float(gain)
        if exposure is not None:
            controls["ExposureTime"] = int(exposure)
        if awb_gains:
            controls["ColourGains"] = (float(awb_gains[0]), float(awb_gains[1]))

        if not controls:
            return

        try:
            self.camera.set_controls(controls)
        except Exception as exc:
            self.log("WARNING",f"Failed to apply manual camera controls: {exc}")
            return

        self._wait_for_camera_settle()

    def _wait_for_camera_settle(self):
        if not self.camera:
            return

        wait_for_idle = getattr(self.camera, "wait_for_idle", None)
        if callable(wait_for_idle):
            try:
                wait_for_idle()
            except Exception:
                pass

        if self.control_settle_time > 0:
            time.sleep(self.control_settle_time)

    def calibrate(self):
        """
        Performs a comprehensive automated calibration by iterating through various
        combinations of camera and RGB LED settings to find the optimal set that
        maximizes image quality, as measured by sharpness, contrast, and visible
        color spectrum.

        The process involves:
        1. Setting camera parameters (ISO, exposure).
        2. Communicating with the LightSource module to set the RGB LED color and brightness.
        3. Capturing an image and calculating a combined score based on:
           - Sharpness (using image gradient).
           - Contrast (using standard deviation).
           - Visible color band (using average saturation from the HSV color space).
        4. Storing the settings with the highest combined score.
        5. Applying the optimal settings to both the camera and the LightSource module.
        """
        if not self.camera:
            self.log("WARNING", "Cannot perform calibration, camera not initialized.")
            self.sendMessage("All", "CameraCalibrated", {"status": "error", "message": "Camera not initialized."})
            return

        self.log("INFO", "Starting camera calibration...")
        self.sendMessage("All", "CalibrationStarted", {"message": "Starting camera calibration..."})

        self._ensure_manual_mode(force=True)

        # Get valid gain range from the camera itself
        try:
            gain_min, gain_max, _ = self.camera.camera_controls['AnalogueGain']
            self.log("INFO", f"Valid AnalogueGain range: {gain_min} - {gain_max}")
        except Exception as e:
            self.log("ERROR", f"Could not get AnalogueGain range: {e}. Using default list.")
            gain_min, gain_max = 1.0, 16.0 # Fallback to a safe range

        def makeColorsList():
            from itertools import product
            return list(product(range(15,260,10), range(15,260,10), range(15,260,10)))

        # Placeholder lists for camera and LED settings
        gain_list           = numpy.arange(gain_min, gain_max, 0.2)
        exposure_list       = [microseconds * 1000 for microseconds in range(10,105,10)] # in microseconds
        rgb_colors_list     = makeColorsList()
        led_brightness_list = [light for light in range(25,260,10)] # values from 0-255

        best_settings = {
            "camera": {"gain": None, "exposure": None},
            "light":  {"r": None, "g": None, "b": None, "brightness": None},
            "score": 0
        }

        try:
            # Iterate through all combinations of camera and LED settings
            for gain in gain_list:
                for exposure in exposure_list:
                    for r, g, b in rgb_colors_list:
                        for brightness in led_brightness_list:
                            # 1. Set camera and LED parameters
                            self._apply_camera_controls(gain, exposure, self.awb_gains)
                            self.sendMessage("LightSource", "SetColor", {"r": r, "g": g, "b": b})
                            self.sendMessage("LightSource", "Dim", {"brightness": brightness})
                            time.sleep(max(0.001, self.light_settle_time)) # Wait for the LED to update
                            
                            # 2. Capture the image
                            image_array = self.camera.capture_array("main")
                            
                            # 3. Convert to grayscale and HSV for metric calculation
                            gray_image = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
                            hsv_image = cv2.cvtColor(image_array, cv2.COLOR_BGR2HSV)

                            # 4. Calculate metrics
                            # Sharpness (Gradient)
                            sobelx = cv2.Sobel(gray_image, cv2.CV_64F, 1, 0, ksize=5)
                            sobely = cv2.Sobel(gray_image, cv2.CV_64F, 0, 1, ksize=5)
                            gradient = numpy.sqrt(sobelx**2 + sobely**2).mean()

                            # Contrast (Standard Deviation)
                            contrast = numpy.std(gray_image)

                            # Visible Color Band (Average Saturation)
                            # We get the saturation channel (index 1) from the HSV image
                            saturation = hsv_image[:, :, 1]
                            avg_saturation = numpy.mean(saturation)

                            # 5. Calculate combined score
                            # A simple sum is used, but weights could be added for more specific optimization.
                            total_score = gradient + contrast + avg_saturation
                            self.log("DEBUG", f"Testing settings: Gain={gain:.2f}, Exposure={exposure}, RGB={r,g,b}, Brightness={brightness}, Score={total_score}")
                            
                            # 6. Update the best settings
                            if total_score > best_settings["score"]:
                                best_settings["camera"]["gain"]      = float(gain)
                                best_settings["camera"]["exposure"]  = int(exposure)
                                best_settings["light"]["r"]          = int(r)
                                best_settings["light"]["g"]          = int(g)
                                best_settings["light"]["b"]          = int(b)
                                best_settings["light"]["brightness"] = int(brightness)
                                best_settings["score"]               = float(total_score)

            # 7. Apply the best settings found
            if best_settings["camera"]["gain"]:
                # Set best camera settings
                self._apply_camera_controls(
                    best_settings["camera"]["gain"],
                    best_settings["camera"]["exposure"],
                    self.awb_gains
                )
                # Set best light settings
                self.sendMessage("LightSource", "SetColor", {
                    "r": best_settings["light"]["r"],
                    "g": best_settings["light"]["g"],
                    "b": best_settings["light"]["b"]
                })
                self.sendMessage("LightSource", "Dim", {"brightness": best_settings["light"]["brightness"]})

                # Update config in memory
                self.config.update(best_settings)
                self.gain     = self._safe_float(best_settings["camera"]["gain"], fallback=self.gain)
                self.exposure = int(self._safe_float(best_settings["camera"]["exposure"], fallback=self.exposure))
                self._manual_mode_configured = False
                self._ensure_manual_mode(force=True)

                # Save config to file
                try:
                    with open('config.json', 'r+') as f:
                        data = json.load(f)
                        data['modules']['camera'].update(best_settings)
                        f.seek(0)
                        json.dump(data, f, indent=2)
                        f.truncate()
                    self.log("INFO", "Calibration settings saved to config.json.")
                except (IOError, json.JSONDecodeError) as e:
                    self.log("ERROR", f"Could not save calibration settings to config.json: {e}")

                self.log("INFO", f"Calibration complete. Best settings found: {best_settings}")
                self.sendMessage("All", "CameraCalibrated", {"status": "success", "settings": best_settings})
            else:
                self.log("ERROR", "Calibration failed: could not find best settings.")
                self.sendMessage("All", "CameraCalibrated", {"status": "error", "message": "No optimal settings found."})

        except Exception as e:
            self.log("ERROR", f"An error occurred during calibration: {e}")
            self.sendMessage("All", "CameraCalibrated", {"status": "error", "message": f"Calibration failed: {e}"})
            
    def onStop(self):
        """
        Stops the camera when the module is terminated.
        """
        if self.camera and self.camera.started:
            self.camera.stop()
            self.log("INFO","Camera stopped.")
