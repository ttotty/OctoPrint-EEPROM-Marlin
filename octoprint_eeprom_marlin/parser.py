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
        command_match = regex_command.match(line)
        if not command_match:
            return

        command = command_match.group("gcode")

        try:
            command_name = data.find_name_from_command(command)
        except ValueError:
            self._logger.warning(f"EEPROM output line not recognized: {line.strip()}")
            return

        data_structure = data.ALL_DATA_STRUCTURE[command_name]
        params = copy.deepcopy(data_structure["params"])
        switches = data_structure.get("switches", [])
        switches_indexable = data_structure.get("switchesIndexable", True)

        if switches:
            params.update({sw: {"type": "switch"} for sw in switches})

        parameters = {}
        matches = regex_parameter.findall(line)

        for match in matches:
            letter = match[0].upper()
            value = match[1]
            if letter in params.keys():
                param_type = params[letter]["type"]
                if param_type == "bool":
                    v = True if float(value) == 1.0 else False
                elif param_type == "switch":
                    v = int(value)
                else:
                    v = float(value)
                parameters[letter] = v

        # Handle switches according to switchesIndexable flag
        if switches:
            if not switches_indexable:
                # Non-indexable: plain axis letters (like M593 X/Y)
                for sw in switches:
                    if re.search(rf"\b{sw}\b", line):
                        parameters[sw] = parameters.get(sw, 1)
            else:
                # Indexable: numeric switches (like M906 I1, T0)
                for match in regex_parameter.findall(line):
                    letter = match[0].upper()
                    value = match[1]
                    if letter in switches:
                        try:
                            parameters[f"{letter}{int(float(value))}"] = 1
                        except ValueError:
                            continue

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
