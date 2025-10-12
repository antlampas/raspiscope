"""
Author: Antlampas
CC BY-SA 4.0
https://creativecommons.org/licenses/by-sa/4.0/
"""

import time
from rpi_ws281x   import PixelStrip,Color
from module       import Module
from configLoader import ConfigLoader

class LightSource(Module):
    """
    Manages an RGB LED
    Inherits from the base Module class.
    """
    def __init__(self,moduleConfig,networkConfig,systemConfig):
        """
        Initializes the LightSource module.
        """
        if moduleConfig is None:
            full_config = ConfigLoader().get_config()
            moduleConfig = full_config.get("modules", {}).get("lightSource", {})

        super().__init__("LightSource",networkConfig,systemConfig)
        self.config     = moduleConfig or {}
        self.pin        = self.config.get('pin')
        self.dma        = self.config.get('dma')
        # The library wants a value from 0-255
        brightness      = self.config.get('brightness', 0)
        self.brightness = int(brightness * 255) if isinstance(brightness, (int, float)) else 0
        self.pwmChannel = self.config.get('pwm_channel')
        self.led        = None
        self.whiteColor = Color(255,255,255)
        self.r          = self.config.get('r', 255)
        self.g          = self.config.get('g', 255)
        self.b          = self.config.get('b', 255)
        self.color      = Color(self.b,self.g,self.r)
        self.is_on      = False


    def onStart(self):
        """
        Initializes the LED strip.
        """
        self.sendMessage("EventManager", "Register")
        if self.pin is None or self.dma is None or self.pwmChannel is None:
            self.log("ERROR","LightSource configuration missing required parameters (pin, dma, pwm_channel).")
            return
        try:
            # The rpi_ws281x library requires root privileges to run
            self.led = PixelStrip(
                1,self.pin,800000,self.dma,False,self.brightness,self.pwmChannel
            )
            self.led.begin()
            self.turnOff() # Ensure the LED is off on startup
            self.log("INFO","Light source initialized.")
        except Exception as e:
            self.log("ERROR",f"Could not initialize light source. Run as root? Details: {e}")
            self.led = None

    def handleMessage(self,message):
        """
        Handles incoming messages from the event system.
        Acts as a dispatcher that invokes the appropriate methods.
        """
        if not self.led:
            self.log("WARNING","Light source not available,command ignored.")
            return

        msgType = message.get("Message",{}).get("type")
        payload = message.get("Message",{}).get("payload",{})

        if msgType == "TurnOn" or msgType == "CuvettePresent":
            self.turnOn()
        elif msgType == "TurnOff" or msgType == "CuvetteAbsent":
            self.turnOff()
        elif msgType == "Dim":
            newBrightness = payload.get("brightness")
            if isinstance(newBrightness,int) and 0 <= newBrightness <= 255:
                self.dim(newBrightness)
            else:
                self.log("WARNING",f"'Dim' command received with invalid payload: {payload}")
        elif msgType == "SetColor":
            self.setColor(payload.get("r"),payload.get("g"),payload.get("b"))

    def turnOn(self):
        """
        Turns the LED on. Emits events before and after the action.
        """
        if not self.led: return
        self.log("INFO","Turning on light source...")
        self.sendMessage("All","TurningOn")

        self.led.setPixelColor(0,self.color)
        self.led.show()
        self.is_on = True

        self.sendMessage("All","TurnedOn")
        self.log("INFO","Light source turned on.")

    def turnOff(self,initial=False):
        """
        Turns the LED off. Emits events before and after the action.

        Args:
            initial (bool): If True,does not send events (used only in on_start).
        """
        if not self.led: return
        if not initial:
            self.log("INFO","Turning off light source...")
            self.sendMessage("All","TurningOff")

        self.led.setPixelColor(0,Color(0,0,0))
        self.led.show()
        self.is_on = False

        if not initial:
            self.sendMessage("All","TurnedOff")
            self.log("INFO","Light source turned off.")

    def dim(self,brightness):
        """
        Adjusts the global brightness of the LED.

        Args:
            brightness (int): New brightness level (0-255).
        """
        if not self.led: return
        self.log("INFO",f"Adjusting brightness to {brightness}...")
        self.sendMessage("All","Dimming",{"brightness": brightness})

        self.brightness = brightness
        self.led.setBrightness(self.brightness)
        if self.is_on:
            self.led.show() # Immediately applies the new brightness if the LED is on

        self.sendMessage("All","Dimmed",{"brightness": self.brightness})
        self.log("INFO",f"Brightness set to {self.brightness}.")

    def setColor(self, r, g, b):
        """
        Sets the RGB color of the LED.

        Args:
            r (int): The red color component (0-255).
            g (int): The green color component (0-255).
            b (int): The blue color component (0-255).
        """
        if not self.led:
            self.log("WARNING", "Cannot set color, light source not available.")
            return

        self.log("INFO", f"Setting LED color to R:{r}, G:{g}, B:{b}...")
        self.r, self.g, self.b = r, g, b
        self.color = Color(self.b,self.g,self.r)
        self.led.setPixelColor(0,self.color)
        self.led.show()
        self.is_on = True

        self.sendMessage("All", "ColorSet", {"r": r, "g": g, "b": b})
        self.log("INFO", "LED color set successfully.")

    def onStop(self):
        """
        Ensures the LED is turned off when the module terminates.
        """
        self.log("INFO","Stopping LightSource module...")
        if self.led:
            self.turnOff(initial=True) # Turns off without sending events
