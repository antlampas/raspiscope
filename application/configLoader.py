"""
Author: Antlampas
CC BY-SA 4.0
https://creativecommons.org/licenses/by-sa/4.0/
"""

import json
import sys

class ConfigLoader:
    """
    Loads, parses, and manages the configuration from a JSON file.
    The result is stored as an instance attribute to avoid
    multiple reads.
    """
    def __init__(self, config_path="config.json"):
        """
        Initializes the configuration loader.

        Args:
            config_path (str): The path to the JSON configuration file.
        """
        self._config_path = config_path
        self._config      = None
        self._load()

    def _load(self):
        """
        Private method to load and validate the configuration.
        Terminates the application in case of critical errors, maintaining
        the original logic.
        """
        try:
            with open(self._config_path, 'r') as f:
                config_data = json.load(f)
        except FileNotFoundError:
            print(f"CRITICAL ERROR: The configuration file '{self._config_path}' was not found.", file=sys.stderr)
            sys.exit(1)
            return
        except json.JSONDecodeError as e:
            print(f"CRITICAL ERROR: The configuration file '{self._config_path}' is not a valid JSON file.", file=sys.stderr)
            print(f"Error details: {e}", file=sys.stderr)
            sys.exit(1)
            return
        except Exception as e:
            print(f"CRITICAL ERROR: An unexpected error occurred while reading '{self._config_path}'.", file=sys.stderr)
            print(f"Details: {e}", file=sys.stderr)
            sys.exit(1)
            return

        # Validation for the presence of main keys
        required_keys = ["network", "system", "modules"]
        for key in required_keys:
            if key not in config_data:
                if key == "network":
                    print(f"CRITICAL ERROR: The configuration file '{self._config_path}' is not a valid JSON file.", file=sys.stderr)
                    sys.exit(1)
                    return
                print(f"CRITICAL ERROR: The required key '{key}' is missing from the configuration file.", file=sys.stderr)
                sys.exit(1)
                return

        self._config = config_data

    def get_config(self):
        """
        Returns the loaded configuration dictionary.

        Returns:
            dict: The complete configuration.
        """
        return self._config
