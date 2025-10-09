import unittest
from unittest.mock import MagicMock, patch, mock_open, call
import json
import time
import signal
from functools import wraps

# Mock the dependencies before importing the class under test
from module import Module
from logger import Logger

class TestLogger(unittest.TestCase):

    @patch('logger.ConfigLoader')
    def setUp(self, mockConfigLoader):
        self.mockConfig = {
            "network": {"address": "localhost", "port": 12345},
            "system": {"module_message_queue_timeout_s": 0.1},
            "modules": {
                "logger": {
                    "destination": "stdout",
                    "path": "test.log"
                }
            }
        }
        mockConfigLoader.return_value.get_config.return_value = self.mockConfig

        # We patch the Communicator inside the Module's __init__ via the logger
        with patch('module.Communicator') as self.mockCommunicator:
            self.mockCommInstance = MagicMock()
            self.mockCommunicator.return_value = self.mockCommInstance
            self.logger = Logger(self.mockConfig['network'], self.mockConfig['system'])

    def test_initializationSingleDestination(self):
        """
        Tests logger initialization with a single destination string.
        """
        self.assertEqual(self.logger.module_name, "Logger")
        self.assertIsInstance(self.logger.communicator, MagicMock)
        self.assertEqual(self.logger.destinations, ["stdout"])

    @patch('logger.ConfigLoader')
    def test_initializationMultipleDestinations(self, mockConfigLoader):
        """
        Tests logger initialization with a list of destinations.
        """
        self.mockConfig['modules']['logger']['destination'] = ["file", "websocket"]
        mockConfigLoader.return_value.get_config.return_value = self.mockConfig
        with patch('module.Communicator'):
            logger = Logger(self.mockConfig['network'], self.mockConfig['system'])
            self.assertEqual(logger.destinations, ["file", "websocket"])

    @patch("builtins.open", new_callable=mock_open)
    def test_onStartFileDestination(self, mockFile):
        """
        Tests that onStart opens a file when 'file' is a destination.
        """
        self.logger.destinations = ["file"]
        self.logger.onStart()
        
        mockFile.assert_called_once_with("test.log", "a")
        self.assertIsNotNone(self.logger.log_file)
        self.mockCommInstance.outgoingQueue.put.assert_any_call(
            unittest.mock.ANY
        )
        sentMessage = self.mockCommInstance.outgoingQueue.put.call_args[0][0]
        self.assertEqual(sentMessage['Destination'], 'EventManager')

    @patch("builtins.open", side_effect=IOError("Permission denied"))
    def test_onStartFileOpenError(self, mockFile):
        """
        Tests that an error during file opening is handled correctly.
        """
        self.logger.destinations = ["file"]
        self.logger.onStart()
        
        self.assertIsNone(self.logger.log_file)
        self.assertIn("stdout", self.logger.destinations)
        self.assertNotIn("file", self.logger.destinations)
        sentMessage = self.mockCommInstance.outgoingQueue.put.call_args[0][0]
        self.assertEqual(sentMessage['Message']['payload']['level'], 'ERROR')
        self.assertIn("Could not open log file", sentMessage['Message']['payload']['message'])

    @patch('time.strftime', return_value="2023-10-27 10:00:00")
    @patch('builtins.print')
    def test_handleMessageLogToStdout(self, mockPrint, mockTime):
        """
        Tests that a LogMessage is correctly printed to stdout.
        """
        self.logger.destinations = ["stdout"]
        logMessage = {
            "Sender": "TestModule",
            "Message": {
                "type": "LogMessage",
                "payload": {"level": "DEBUG", "message": "A debug message"}
            }
        }
        self.logger.handleMessage(logMessage)
        
        expectedOutput = "[2023-10-27 10:00:00] [TestModule] (DEBUG): A debug message"
        mockPrint.assert_called_once_with(expectedOutput)

    @patch('time.strftime', return_value="2023-10-27 10:00:00")
    @patch("builtins.open", new_callable=mock_open)
    def test_handleMessageLogToFile(self, mockFile, mockTime):
        """
        Tests that a LogMessage is correctly written to a file.
        """
        self.logger.destinations = ["file"]
        self.logger.log_file = mockFile()

        logMessage = {
            "Sender": "TestModule",
            "Message": {
                "type": "LogMessage",
                "payload": {"level": "WARNING", "message": "A warning"}
            }
        }
        self.logger.handleMessage(logMessage)

        expectedLogEntry = {
            "timestamp": "2023-10-27 10:00:00",
            "sender": "TestModule",
            "level": "WARNING",
            "message": "A warning"
        }
        
        mockFile().write.assert_any_call(json.dumps(expectedLogEntry))
        mockFile().write.assert_any_call('\n')
        mockFile().flush.assert_called_once()

    @patch('time.strftime', return_value="2023-10-27 10:00:00")
    @patch('builtins.print')
    def test_handleMessageLogToWebsocket(self, mockPrint, mockTime):
        """
        Tests the fallback behavior for the websocket destination.
        """
        self.logger.destinations = ["websocket"]
        logMessage = {
            "Sender": "TestModule",
            "Message": {
                "type": "LogMessage",
                "payload": {"level": "INFO", "message": "WebSocket test"}
            }
        }
        self.logger.handleMessage(logMessage)
        
        expectedOutput = "[2023-10-27 10:00:00] [TestModule] (INFO): WebSocket test [Via WebSocket]"
        mockPrint.assert_called_once_with(expectedOutput)

    @patch('builtins.print')
    def test_handleNonLogMessage(self, mockPrint):
        """
        Tests that non-LogMessage types are handled as generic events.
        """
        self.logger.destinations = ["stdout"]
        eventMessage = {
            "Sender": "OtherModule",
            "Message": {"type": "CustomEvent"}
        }
        self.logger.handleMessage(eventMessage)
        mockPrint.assert_called_once_with("[OtherModule] - Received event 'CustomEvent'")

    def test_onStopClosesFile(self):
        """
        Tests that onStop closes the log file if it is open.
        """
        self.logger.destinations = ["file"]
        self.logger.log_file = MagicMock()
        self.logger.onStop()
        self.logger.log_file.close.assert_called_once()

    def test_onStopNoFile(self):
        """
        Tests that onStop does not error if the file is not open.
        """
        self.logger.destinations = ["stdout"]
        self.logger.log_file = None
        try:
            self.logger.onStop()
        except Exception as e:
            self.fail(f"onStop() raised an exception unexpectedly: {e}")
