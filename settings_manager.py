# settings_manager.py
# Handles reading and writing the persistent settings file.
#
# Settings are stored as simple CSV lines, one per setting:
#   si,<syringe_id_mm>
#   sv,<syringe_volume_ml>
#   cg,<cal_gas_index>
#   iv,<igniter_voltage>
#


import os

SETTINGS_FILE = "/home/cams/LS_APGD/LSAPGD_SAVE.txt"

# Fallback defaults used if the file is missing or corrupt
DEFAULTS = {
    "si": "14.0",   # syringe inner diameter mm
    "sv": "10.0",   # syringe volume ml
    "cg": "0",      # calibration gas index (0=Air)
    "iv": "2000",   # igniter voltage
}


class Settings:
    """Simple container for application settings."""
    def __init__(self):
        self.syringe_id      = float(DEFAULTS["si"])
        self.syringe_volume  = float(DEFAULTS["sv"])
        self.cal_gas_index   = int(DEFAULTS["cg"])
        self.igniter_voltage = int(DEFAULTS["iv"])


def read_settings():
    """
    Read settings from the save file and return a Settings object.
    If the file is missing or unreadable, returns default values and
    prints a warning – this is non-fatal so the app can still start.
    """
    s = Settings()

    if not os.path.exists(SETTINGS_FILE):
        print(f"Settings file not found at '{SETTINGS_FILE}'. Using defaults.")
        return s

    try:
        with open(SETTINGS_FILE, "r") as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()
            if not line or ',' not in line:
                continue
            key, _, value = line.partition(',')
            key   = key.strip()
            value = value.strip()

            if key == "si":
                s.syringe_id = float(value)
            elif key == "sv":
                s.syringe_volume = float(value)
            elif key == "cg":
                idx = int(value)
                s.cal_gas_index = max(0, min(7, idx))  # clamp to valid range
            elif key == "iv":
                voltage = int(value)
                s.igniter_voltage = max(1500, min(5000, voltage))  # clamp to safe range

    except (OSError, ValueError) as e:
        print(f"Warning: could not read settings file: {e}. Using defaults.")

    return s


def write_settings(syringe_id, syringe_volume, cal_gas_index, igniter_voltage):
    """
    Write settings to the save file.
    All values are validated before writing.

    syringe_id      – float, inner diameter in mm
    syringe_volume  – float, volume in mL
    cal_gas_index   – int 0-7
    igniter_voltage – int 1500-5000
    """
    # Validate / clamp values
    try:
        sid  = float(syringe_id)
        svol = float(syringe_volume)
        cg   = max(0, min(7, int(cal_gas_index)))
        iv   = max(1500, min(5000, int(igniter_voltage)))
    except (ValueError, TypeError) as e:
        print(f"Settings write error – invalid value: {e}")
        return False

    # Ensure the directory exists
    directory = os.path.dirname(SETTINGS_FILE)
    if directory and not os.path.exists(directory):
        try:
            os.makedirs(directory)
        except OSError as e:
            print(f"Settings write error – cannot create directory: {e}")
            return False

    try:
        with open(SETTINGS_FILE, "w") as f:
            f.write(f"si,{sid}\n")
            f.write(f"sv,{svol}\n")
            f.write(f"cg,{cg}\n")
            f.write(f"iv,{iv}\n")
        return True
    except OSError as e:
        print(f"Settings write error: {e}")
        return False
