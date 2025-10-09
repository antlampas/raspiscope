import unittest
from unittest.mock import MagicMock, patch, call
import signal
from functools import wraps
import sys

# Mock hardware dependencies before importing the class
mockPixelStrip = MagicMock()
mockColor = MagicMock(side_effect=lambda r, g, b: (r, g, b))
sys_modules = {
    'rpi_ws281x': MagicMock(PixelStrip=mockPixelStrip, Color=mockColor)
}

with patch.dict('sys.modules', sys_modules):
    from lightSource import LightSource

class TestLightSource(unittest.TestCase):

    @patch('lightSource.ConfigLoader')
    def setUp(self, mockConfigLoader):
        self.mockConfig = {
            'network': {'address': 'localhost', 'port': 12345},
            'system': {'module_message_queue_timeout_s': 0.1},
            'pin': 18,
            'dma': 10,
            'brightness': 0.5,
            'pwm_channel': 0,
            'r': 255, 'g': 0, 'b': 0
        }
        mockConfigLoader.return_value.get_config.return_value = self.mockConfig

        with patch('module.Communicator') as self.mockCommunicator:
            self.mockCommInstance = MagicMock()
            self.mockCommunicator.return_value = self.mockCommInstance
            self.lightSource = LightSource(self.mockConfig['network'], self.mockConfig['system'])
            self.mockLed = MagicMock()
            mockPixelStrip.return_value = self.mockLed

    def test_initialization(self):
        """
        Tests that the LightSource module is initialized with correct config values.
        """
        self.assertEqual(self.lightSource.module_name, "LightSource")
        self.assertEqual(self.lightSource.pin, 18)
        self.assertEqual(self.lightSource.brightness, 127) # 0.5 * 255
        self.assertEqual(self.lightSource.color, (255, 0, 0))
        self.assertIsNone(self.lightSource.led)

    def test_onStartSuccess(self):
        """
        Tests the successful startup sequence.
        """
        self.lightSource.onStart()
        
        mockPixelStrip.assert_called_once_with(1, 18, 800000, 10, False, 127, 0)
        self.mockLed.begin.assert_called_once()
        # onStart calls turnOff, which calls setPixelColor and show
        self.mockLed.setPixelColor.assert_called_once_with(0, (0, 0, 0))
        self.mockLed.show.assert_called_once()
        self.mockCommInstance.outgoingQueue.put.assert_any_call(unittest.mock.ANY)

    def test_onStartFailure(self):
        """
        Tests the startup sequence when PixelStrip initialization fails.
        """
        mockPixelStrip.side_effect = Exception("Hardware error")
        self.lightSource.onStart()
        
        self.assertIsNone(self.lightSource.led)
        # Check that an error was logged
        logCall = self.mockCommInstance.outgoingQueue.put.call_args[0][0]
        self.assertEqual(logCall['Message']['payload']['level'], 'ERROR')
        self.assertIn("Could not initialize light source", logCall['Message']['payload']['message'])

    def test_handleMessageTurnOn(self):
        """
        Tests handling of a 'TurnOn' message.
        """
        self.lightSource.led = self.mockLed
        self.lightSource.color = (100, 150, 200)
        message = {"Message": {"type": "TurnOn"}}
        
        self.lightSource.handleMessage(message)
        
        self.mockLed.setPixelColor.assert_called_with(0, (100, 150, 200))
        self.mockLed.show.assert_called_once()
        self.assertTrue(self.lightSource.is_on)
        # Should send TurningOn and TurnedOn messages
        self.assertEqual(self.mockCommInstance.outgoingQueue.put.call_count, 3) # log + 2 messages

    def test_handleMessageTurnOff(self):
        """
        Tests handling of a 'TurnOff' message.
        """
        self.lightSource.led = self.mockLed
        self.lightSource.is_on = True
        message = {"Message": {"type": "TurnOff"}}
        
        self.lightSource.handleMessage(message)
        
        self.mockLed.setPixelColor.assert_called_with(0, (0, 0, 0))
        self.mockLed.show.assert_called_once()
        self.assertFalse(self.lightSource.is_on)

    def test_handleMessageDim(self):
        """
        Tests handling of a 'Dim' message.
        """
        self.lightSource.led = self.mockLed
        self.lightSource.is_on = True
        message = {"Message": {"type": "Dim", "payload": {"brightness": 50}}}
        
        self.lightSource.handleMessage(message)
        
        self.assertEqual(self.lightSource.brightness, 50)
        self.mockLed.setBrightness.assert_called_once_with(50)
        self.mockLed.show.assert_called_once() # Should be called if light is on

    def test_handleMessageDimInvalidPayload(self):
        """
        Tests that a 'Dim' message with invalid payload is ignored.
        """
        self.lightSource.led = self.mockLed
        message = {"Message": {"type": "Dim", "payload": {"brightness": "not a number"}}}
        
        self.lightSource.handleMessage(message)
        
        self.mockLed.setBrightness.assert_not_called()
        # Check that a warning was logged
        logCall = self.mockCommInstance.outgoingQueue.put.call_args[0][0]
        self.assertEqual(logCall['Message']['payload']['level'], 'WARNING')

    def test_handleMessageSetColor(self):
        """
        Tests handling of a 'SetColor' message.
        """
        self.lightSource.led = self.mockLed
        message = {"Message": {"type": "SetColor", "payload": {"r": 10, "g": 20, "b": 30}}}
        
        self.lightSource.handleMessage(message)
        
        self.assertEqual(self.lightSource.color, (10, 20, 30))
        self.mockLed.setPixelColor.assert_called_with(0, (10, 20, 30))
        self.mockLed.show.assert_called_once()

    def test_handleMessageNoLed(self):
        """
        Tests that messages are ignored if the LED is not initialized.
        """
        self.lightSource.led = None
        message = {"Message": {"type": "TurnOn"}}
        
        self.lightSource.handleMessage(message)
        
        self.mockLed.setPixelColor.assert_not_called()
        # Check that a warning was logged
        logCall = self.mockCommInstance.outgoingQueue.put.call_args[0][0]
        self.assertEqual(logCall['Message']['payload']['level'], 'WARNING')
        self.assertIn("not available", logCall['Message']['payload']['message'])

    def test_onStop(self):
        """
        Tests that onStop turns the light off.
        """
        self.lightSource.led = self.mockLed
        self.lightSource.onStop()
        
        self.mockLed.setPixelColor.assert_called_with(0, (0, 0, 0))
        self.mockLed.show.assert_called_once()
