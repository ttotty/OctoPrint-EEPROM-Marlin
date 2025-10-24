import copy

"""
Provide methods for parsing printer communication, specific to this plugin
"""
__license__ = "GNU Affero General Public License http://www.gnu.org/licenses/agpl.html"
__copyright__ = (
    "Copyright (C) 2020 Charlie Powell - Released under terms of the AGPLv3 License"
)

import re

from octoprint_eeprom_marlin import data

# Some regexes used for parsing. Initially borrowed from OctoPrint's comm layer
# but modified to suit the plugin better.

regex_float_pattern = r"[-+]?[0-9]*\.?[0-9]+"

regex_parameter = re.compile(r"(?P<letter>[A-Za-z])(?P<value>[-+]?[0-9]*\.?[0-9]+)")
regex_command = re.compile(r"echo:\s*(?P<gcode>M(?P<value>\d{1,3}))")

regex_stats = {
    "prints": re.compile(r"Prints: (\d*)"),
    "finished": re.compile(r"Finished: (\d*)"),
    "failed": re.compile(r"Failed: (\d*)"),
    "total_time": re.compile(r"Total time: (.*),"),
    "longest": re.compile(r"Longest job: (.*)"),
    "filament": re.compile(r"Filament used: (.*m)"),
}


class Parser:
    def __init__(self, logger):
        self._logger = logger

    def parse_eeprom_data(self, line):
        """
        Parse a received line from the printer into a dictionary of name, command, params
        Eg: `echo: M92 X80.0 Y80.0 Z800.0 E90.0`
        to {"name": steps, "command": "M92", "params": {
            "X": 80.0,
            "Y": 80.0,
            "Z": 800.0,
            "E": 90.0
        }
        :param line: line received from FW
        :return: dict: parsed values
        """

        command_match = regex_command.match(line)
        if not command_match:
            return

        command = command_match.group("gcode")

        # Identify internal data structure by command
        try:
            command_name = data.find_name_from_command(command)
        except ValueError:
            self._logger.warning("EEPROM output line not recognized, skipped")
            self._logger.warning("Line: {}".format(line.strip("\r\n ")))
            return

        data_structure = data.ALL_DATA_STRUCTURE[command_name]
        params_spec = copy.deepcopy(data_structure["params"])
        if "switches" in data_structure:
            params_spec.update({sw: {"type": "switch"} for sw in data_structure["switches"]})

        # Parse all key-value pairs like X80.0 Y80.0 etc.
        parameters = {}
        matches = regex_parameter.findall(line)
        for match in matches:
            letter = match[0].upper()
            value = match[1]

            # Only include parameters that exist in structure
            if letter not in params_spec:
                continue

            expected_type = params_spec[letter].get("type")
            # boolean values may be printed as "1.0" so use float conversion
            if expected_type == "bool":
                try:
                    v = float(value) == 1.0
                except (ValueError, TypeError):
                    # fallback: accept "1", "true" strings
                    v = str(value).strip() in ("1", "true", "True")
            elif expected_type == "switch":
                # If numeric supplied, store as int. Otherwise treat as presence flag
                try:
                    v = int(float(value))
                except (ValueError, TypeError):
                    v = 1
            else:
                try:
                    v = float(value)
                except (ValueError, TypeError):
                    # safety fallback, keep raw
                    v = value

            parameters[letter] = v

        # Handle switches that appear without numeric values.
        if "switches" in data_structure:
            switches = data_structure.get("switches", [])
            switches_not_indexed = data_structure.get("switchesNotIndexed", False)

            for sw in switches:
                # If already parsed (e.g. X229), nothing to do
                if sw in parameters:
                    continue

                # Detect a bare switch letter in the line (not followed by digit)
                # e.g. matches " M593 X F57.00" or "M569 S1 X Y Z"
                if re.search(rf"(?<!\w){sw}(?!\d)", line):
                    parameters[sw] = 1

                # If the parser accidentally produced an indexed key like "X1" and we are in
                # switchesNotIndexed mode, move that value to "X"
                if switches_not_indexed:
                    # look for e.g. "X1" / "Y1" keys that might have been created elsewhere
                    for suffix in ("1", "0"):
                        keyed = f"{sw}{suffix}"
                        if keyed in parameters:
                            parameters[sw] = parameters.pop(keyed)
                            break

        return {
            "name": command_name,
            "command": command,
            "params": parameters,
        }


    @staticmethod
    def is_marlin(name):
        return "marlin" in name.lower()

    @staticmethod
    def parse_stats_line(line):
        # Run all the regexes against the line to grab the params
        stats = {}
        for key, regex in regex_stats.items():
            match = regex.search(line)
            if match:
                stats[key] = match.group(1)

        return stats
