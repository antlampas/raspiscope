import unittest
from unittest.mock import MagicMock, patch, mock_open, call
import json
import numpy
import base64
import signal
from functools import wraps
import sys

# Mock hardware/heavy dependencies before import
mockPicamera2 = MagicMock()
mockCv2 = MagicMock()
mockBase64 = MagicMock()

sys_modules = {
    'picamera2': MagicMock(Picamera2=mockPicamera2),
    'cv2': mockCv2,
    'base64': mockBase64
}

with patch.dict('sys.modules', sys_modules):
    from camera import Camera

class TestCamera(unittest.TestCase):

    def setUp(self):
        self.mockConfig = {
            "network": {"address": "localhost", "port": 12345},
            "system": {"module_message_queue_timeout_s": 0.1},
            "modules": {
                "camera": {
                    "resolution": [1920, 1080],
                    "gain": 1.0,
                    "exposure": 10000
                }
            }
        }
        # The Camera module uses open() directly, so we mock it here
        mo = mock_open(read_data=json.dumps(self.mockConfig))
        with patch("builtins.open", mo):
            with patch('module.Communicator') as self.mockCommunicator:
                self.mockCommInstance = MagicMock()
                self.mockCommunicator.return_value = self.mockCommInstance
                self.cameraModule = Camera(self.mockConfig['network'], self.mockConfig['system'])

        # Reset mocks and setup mock instances for camera hardware
        mockPicamera2.reset_mock()
        self.mockCameraInstance = MagicMock()
        mockPicamera2.return_value = self.mockCameraInstance

    def test_initialization(self):
        """
        Tests that the Camera module is initialized with correct config values.
        """
        self.assertEqual(self.cameraModule.module_name, "Camera")
        self.assertEqual(self.cameraModule.resolution, [1920, 1080])
        self.assertEqual(self.cameraModule.gain, 1.0)
        self.assertEqual(self.cameraModule.exposure, 10000)
        self.assertIsNone(self.cameraModule.camera)

    def test_onStartSuccess(self):
        """
        Tests the successful camera startup sequence.
        """
        self.cameraModule.onStart()
        self.mockCameraInstance.create_still_configuration.assert_called_once()
        self.mockCameraInstance.configure.assert_called_once()
        self.mockCameraInstance.start.assert_called_once()
        self.assertIsNotNone(self.cameraModule.camera)
        self.mockCommInstance.outgoingQueue.put.assert_any_call(unittest.mock.ANY)

    def test_onStartFailure(self):
        """
        Tests the startup sequence when Picamera2 initialization fails.
        """
        self.mockCameraInstance.start.side_effect = Exception("Camera hardware error")
        self.cameraModule.onStart()
        self.assertIsNone(self.cameraModule.camera)
        logCall = self.mockCommInstance.outgoingQueue.put.call_args[0][0]
        self.assertEqual(logCall['Message']['payload']['level'], 'ERROR')
        self.assertIn("Could not initialize camera", logCall['Message']['payload']['message'])

    @patch('camera.Camera.takePicture')
    def test_handleMessageCuvettePresent(self, mockTakePicture):
        """
        Tests that a 'CuvettePresent' message triggers a picture.
        """
        self.cameraModule.camera = self.mockCameraInstance
        self.cameraModule.handleMessage({"Message": {"type": "CuvettePresent"}})
        mockTakePicture.assert_called_once()

    @patch('camera.Camera.takePicture')
    def test_handleMessageTake(self, mockTakePicture):
        """
        Tests that a 'Take' message triggers a picture.
        """
        self.cameraModule.camera = self.mockCameraInstance
        self.cameraModule.handleMessage({"Message": {"type": "Take"}})
        mockTakePicture.assert_called_once()

    def test_takePictureSuccess(self):
        """
        Tests the successful image capture and sending process.
        """
        self.cameraModule.camera = self.mockCameraInstance
        mockImageArray = numpy.zeros((10, 10, 3), dtype=numpy.uint8)
        self.mockCameraInstance.capture_array.return_value = mockImageArray
        
        # Mock cv2 and base64 behavior
        mockCv2.imencode.return_value = (True, b'fakedata')
        mockBase64.b64encode.return_value.decode.return_value = 'ZmFrZWRhdGE='

        self.cameraModule.takePicture()

        self.mockCameraInstance.capture_array.assert_called_once()
        mockCv2.imencode.assert_called_once_with('.jpg', mockImageArray)
        mockBase64.b64encode.assert_called_once_with(b'fakedata')
        
        # Check that the message was sent to Analysis
        sentMessage = self.mockCommInstance.outgoingQueue.put.call_args[0][0]
        self.assertEqual(sentMessage['Destination'], 'Analysis')
        self.assertEqual(sentMessage['Message']['type'], 'Analyze')
        self.assertEqual(sentMessage['Message']['payload']['image'], 'ZmFrZWRhdGE=')

    def test_takePictureNoCamera(self):
        """
        Tests that takePicture logs an error if the camera is not initialized.
        """
        self.cameraModule.camera = None
        self.cameraModule.takePicture()
        logCall = self.mockCommInstance.outgoingQueue.put.call_args[0][0]
        self.assertEqual(logCall['Message']['payload']['level'], 'ERROR')
        self.assertIn("camera not initialized", logCall['Message']['payload']['message'])

    def test_onStop(self):
        """
        Tests that onStop stops the camera if it is running.
        """
        self.cameraModule.camera = self.mockCameraInstance
        self.mockCameraInstance.started = True
        self.cameraModule.onStop()
        self.mockCameraInstance.stop.assert_called_once()

    def test_onStopNotStarted(self):
        """
        Tests that onStop does not call stop if camera isn't running.
        """
        self.cameraModule.camera = self.mockCameraInstance
        self.mockCameraInstance.started = False
        self.cameraModule.onStop()
        self.mockCameraInstance.stop.assert_not_called()
