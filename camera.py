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
from threading import Thread
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
        self.gain     = self.config.get('gain', 1.0)
        self.exposure = self.config.get('exposure', 1000)
        self.camera   = None


    def onStart(self):
        """
        Initializes and configures the camera when the module starts.
        """
        self.sendMessage("EventManager", "Register")
        try:
            self.camera = Picamera2()
            camConfig  = self.camera.create_still_configuration({"size": self.resolution})
            self.camera.configure(camConfig)
            self.camera.set_controls({
                                        "AnalogueGain": self.gain,
                                        "ExposureTime": self.exposure,
                                    })
            self.camera.start()
            self.log("INFO",f"Camera started and configured with resolution {self.resolution}.")
        except Exception as e:
            self.log("ERROR",f"Could not initialize camera: {e}")
            self.camera = None

    def handleMessage(self,message):
        """
        Handles incoming messages.
        """
        if not self.camera:
            self.log("WARNING","Camera not available,ignoring command.")
            return

        msgType = message.get("Message",{}).get("type")

        if msgType == "CuvettePresent":
            self.log("INFO","Received 'Cuvette Present' signal. Taking a picture.")
            picture = self.takePicture()
            if picture:
                self.sendMessage("Analyze","Analyze",picture)
        elif msgType == "Take":
            self.log("INFO","Received 'Take' command. Taking a picture.")
            picture = self.takePicture()
            if picture:
                self.sendMessage("All","PictureTaken",picture)
        elif msgType == "Analyze":
            self.log("INFO","Received 'Analyze' command. Starting analysis.")
            picture = self.takePicture()
            if picture:
                self.sendMessage("Analysis","Analyze",picture)
        elif msgType == "Calibrate":
            self.log("INFO","Received 'Calibrate' command. Starting calibration.")
            self.calibrate()

    def takePicture(self):
        """
        Takes a picture and sends it to the Analysis module.
        """
        if not self.camera:
            self.log("ERROR","Cannot take picture,camera not initialized.")
            return

        try:
            self.log("INFO","Taking picture...")
            # Capture the image as a numpy array
            imageArray = self.camera.capture_array()

            # Encode the image in JPG format and then in Base64
            _,buffer = cv2.imencode('.jpg',imageArray)
            imageB64 = base64.b64encode(buffer).decode('utf-8')

            payload = {"image": imageB64}
            self.log("INFO","Picture taken")
            return payload
        except Exception as e:
            self.log("ERROR",f"ERROR while taking picture: {e}")

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
        gain_list           = [gain for gain in range(gain_min, gain_max, 0.2)]
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
                            self.camera.set_controls({"AnalogueGain": gain, "ExposureTime": exposure})
                            self.sendMessage("LightSource", "SetColor", {"r": r, "g": g, "b": b})
                            self.sendMessage("LightSource", "Dim", {"brightness": brightness})
                            time.sleep(0.001) # Wait for the LED to update
                            
                            # 2. Capture the image
                            image_array = self.camera.capture_array()
                            
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
                                best_settings["camera"]["gain"]      = gain
                                best_settings["camera"]["exposure"]  = exposure
                                best_settings["light"]["r"]          = r
                                best_settings["light"]["g"]          = g
                                best_settings["light"]["b"]          = b
                                best_settings["light"]["brightness"] = brightness
                                best_settings["score"]               = total_score

            # 7. Apply the best settings found
            if best_settings["camera"]["gain"]:
                # Set best camera settings
                self.camera.set_controls({
                    "AnalogueGain": best_settings["camera"]["gain"],
                    "ExposureTime": best_settings["camera"]["exposure"]
                })
                # Set best light settings
                self.sendMessage("LightSource", "SetColor", {
                    "r": best_settings["light"]["r"],
                    "g": best_settings["light"]["g"],
                    "b": best_settings["light"]["b"]
                })
                self.sendMessage("LightSource", "Dim", {"brightness": best_settings["light"]["brightness"]})

                # Update config in memory
                self.config.update(best_settings)

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
