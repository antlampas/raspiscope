import unittest
from unittest.mock import MagicMock, patch, mock_open, call
import json
import signal
from functools import wraps
import sys
import time
import statistics

# Mock hardware dependencies before import
mockInputDevice = MagicMock()
sys_modules = {
    'gpiozero': MagicMock(InputDevice=mockInputDevice, GPIOZeroError=Exception)
}

with patch.dict('sys.modules', sys_modules):
    from cuvetteSensor import CuvetteSensor

class TestCuvetteSensor(unittest.TestCase):

    @patch('cuvetteSensor.ConfigLoader')
    def setUp(self, mockConfigLoader):
        self.mockConfig = {
            "network": {"address": "localhost", "port": 12345},
            "system": {"module_message_queue_timeout_s": 0.1},
            "modules": {
                "cuvetteSensor": {
                    "pin": 17,
                    "poll_interval_s": 0.05,
                    "calibration": {
                        "samples": 5,
                        "threshold_span": 0.1
                    }
                }
            }
        }
        mockConfigLoader.return_value.get_config.return_value = self.mockConfig

        with patch('module.Communicator') as self.mockCommunicator:
            self.mockCommInstance = MagicMock()
            self.mockCommunicator.return_value = self.mockCommInstance
            self.sensorModule = CuvetteSensor(self.mockConfig['network'], self.mockConfig['system'])
            self.mockSensorDevice = MagicMock()
            mockInputDevice.return_value = self.mockSensorDevice

    def test_initialization(self):
        """
        Tests that the CuvetteSensor is initialized with correct config values.
        """
        self.assertEqual(self.sensorModule.module_name, "CuvetteSensor")
        self.assertEqual(self.sensorModule.inputPin, 17)
        self.assertEqual(self.sensorModule.pollInterval, 0.05)
        self.assertEqual(self.sensorModule.numSamples, 5)
        self.assertIsNone(self.sensorModule.sensor)

    def test_onStartSuccess(self):
        """
        Tests the successful startup sequence.
        """
        self.sensorModule.onStart()
        mockInputDevice.assert_called_once_with(17)
        self.assertIsNotNone(self.sensorModule.sensor)
        self.mockCommInstance.outgoingQueue.put.assert_any_call(unittest.mock.ANY)

    def test_onStartFailure(self):
        """
        Tests the startup sequence when InputDevice initialization fails.
        """
        mockInputDevice.side_effect = Exception("GPIO error")
        self.sensorModule.onStart()
        self.assertIsNone(self.sensorModule.sensor)
        logCall = self.mockCommInstance.outgoingQueue.put.call_args[0][0]
        self.assertEqual(logCall['Message']['payload']['level'], 'ERROR')
        self.assertIn("Could not initialize sensor", logCall['Message']['payload']['message'])

    def test_checkPresenceBecomesPresent(self):
        """
        Tests the state change from absent to present.
        """
        self.sensorModule.sensor = self.mockSensorDevice
        self.sensorModule.presenceThreshold = 0.5
        self.sensorModule.isPresent = False
        self.mockSensorDevice.value = 0.2 # Below threshold

        self.sensorModule.checkPresence()

        self.assertTrue(self.sensorModule.isPresent)
        sentMessage = self.mockCommInstance.outgoingQueue.put.call_args[0][0]
        self.assertEqual(sentMessage['Destination'], 'Camera')
        self.assertEqual(sentMessage['Message']['type'], 'CuvettePresent')

    def test_checkPresenceBecomesAbsent(self):
        """
        Tests the state change from present to absent.
        """
        self.sensorModule.sensor = self.mockSensorDevice
        self.sensorModule.presenceThreshold = 0.5
        self.sensorModule.isPresent = True
        self.mockSensorDevice.value = 0.8 # Above threshold

        self.sensorModule.checkPresence()

        self.assertFalse(self.sensorModule.isPresent)
        sentMessage = self.mockCommInstance.outgoingQueue.put.call_args[0][0]
        self.assertEqual(sentMessage['Destination'], 'Camera')
        self.assertEqual(sentMessage['Message']['type'], 'CuvetteAbsent')

    def test_checkPresenceNoChange(self):
        """
        Tests that no message is sent when the state does not change.
        """
        self.sensorModule.sensor = self.mockSensorDevice
        self.sensorModule.presenceThreshold = 0.5
        self.sensorModule.isPresent = True
        self.mockSensorDevice.value = 0.2 # Still present

        self.sensorModule.checkPresence()

        self.mockCommInstance.outgoingQueue.put.assert_not_called()

    @patch('time.sleep')
    @patch('statistics.mean', return_value=0.8)
    @patch("builtins.open", new_callable=mock_open, read_data=json.dumps({"modules": {"cuvetteSensor": {}}}))
    def test_calibrateSuccess(self, mockFile, mockMean, mockSleep):
        """
        Tests the successful calibration sequence.
        """
        self.sensorModule.sensor = self.mockSensorDevice
        self.mockSensorDevice.value = 0.8 # Simulate sensor reading
        self.sensorModule.numSamples = 5

        self.sensorModule.calibrate()

        self.assertEqual(mockSleep.call_count, 5)
        self.assertEqual(len(mockMean.call_args[0][0]), 5) # 5 samples
        self.assertEqual(self.sensorModule.presenceThreshold, 0.8 - self.sensorModule.thresholdSpan)

        # Check for correct messages
        self.assertIn(call(('All', {'Sender': 'CuvetteSensor', 'Destination': 'All', 'Message': {'type': 'CalibrationStarted', 'payload': {'message': 'Starting cuvette sensor calibration (5 samples).'}}})), self.mockCommInstance.outgoingQueue.put.call_args_list)
        self.assertIn(call(('All', {'Sender': 'CuvetteSensor', 'Destination': 'All', 'Message': {'type': 'CalibrationComplete', 'payload': {'threshold': self.sensorModule.presenceThreshold, 'message': 'Calibration complete.'}}})), self.mockCommInstance.outgoingQueue.put.call_args_list)

        # Check that config saving was attempted
        mockFile.assert_called_with('config.json', 'r+')
        mockFile().seek.assert_called_once_with(0)
        mockFile().truncate.assert_called_once()

    def test_calibrateNoSensor(self):
        """
        Tests that calibrate sends an error if the sensor is not initialized.
        """
        self.sensorModule.sensor = None
        self.sensorModule.calibrate()

        sentMessage = self.mockCommInstance.outgoingQueue.put.call_args[0][0]
        self.assertEqual(sentMessage[0], 'All')
        self.assertEqual(sentMessage[1]['Message']['type'], 'CalibrationError')
        self.assertIn("sensor not initialized", sentMessage[1]['Message']['payload']['message'])
