# gui_pages.py
# Builds all six notebook tabs and owns the periodic sensor-update loop.
#
# Calibration constants (updated 2026-03-09):
#   Voltage CH1: kv = (0.2486 * raw) - 12.183
#   Voltage CH2: kv = (0.2484 * raw) - 11.429
#   Current CH1: ma = (-0.048651 * raw) + 100.250
#   Current CH2: ma = (-0.048777 * raw) + 100.660

import time
import types
import tkinter as tk
from tkinter import ttk

import hardware
import pump as pump_module
import gas as gas_module
import settings_manager
from dialogs import number_pad_dialog, show_message


# ---------------------------------------------------------------------------
# Tkinter style
# ---------------------------------------------------------------------------
def apply_style():
    style = ttk.Style()
    style.theme_create("MyStyle", parent="alt", settings={
        "TNotebook": {
            "configure": {"tabmargins": [4, 5, 4, 2]}
        },
        "TNotebook.Tab": {
            "configure": {
                "font": "Times 18",
                "padding": [10, 10, 10, 5],
                "background": "gray65"
            },
            "map": {
                "background": [("selected", "gray85")],
                "expand":     [("selected", [1, 1, 1, 0])]
            }
        },
        "TLabelFrame.Text": {
            "configure": {"font": "Times 30"}
        }
    })
    style.theme_use("MyStyle")


# ---------------------------------------------------------------------------
# App – main application class
# ---------------------------------------------------------------------------
class App:
    """
    Creates the root Tk window, builds all tabs, and runs the main loop.
    Requires open serial connections for the pump and gas valve,
    and hardware already initialised via hardware.hardware_setup().
    """

    def __init__(self, pump_serial, gas_serial, sensor_poller=None, gas_poller=None):
        self.pump_serial  = pump_serial
        self.gas_serial   = gas_serial
        self.gas_poller   = gas_poller

        # Shared application state
        self.power_state  = "OFF"
        self.gas_state    = "OFF"
        self.ch1_set      = 0
        self.ch2_set      = 0
        self.kv_1 = self.kv_2 = 0
        self.ma_1 = self.ma_2 = 0
        self.error_count  = 0
        self.sensor_cycle = 0  # used to stagger slower sensor reads

        # Background sensor poller (never blocks the UI thread)
        self.sensor_poller = sensor_poller

        # Load saved settings
        self.settings = settings_manager.read_settings()

        # Build UI
        self.root = tk.Tk()
        self.root.title('LS-APGD')
        self.root.config(cursor="none")
        self.root.resizable(False, False)
        self.root.overrideredirect(True)
        self.root.geometry('853x480+0+0')

        apply_style()

        # Configure root grid to fill window
        for i in range(50):
            self.root.rowconfigure(i, weight=1)
            self.root.columnconfigure(i, weight=1)

        # Notebook
        self.nb = ttk.Notebook(self.root)
        self.nb.grid(row=1, column=0, columnspan=50, rowspan=49, sticky='NESW')

        # Build all tabs
        self._build_home_tab()
        self._build_current_tab()
        self._build_gas_tab()
        self._build_liquid_tab()
        self._build_settings_tab()
        self._build_shutdown_tab()

        # Apply settings to UI and hardware
        self._apply_loaded_settings()

        # Start sensor update loop
        self.root.after(200, self._sensor_loop)

    def run(self):
        self.root.mainloop()

    # -----------------------------------------------------------------------
    # Settings helpers
    # -----------------------------------------------------------------------
    def _apply_loaded_settings(self):
        """Push loaded settings into UI widgets and hardware."""
        s = self.settings

        self.syringe_id_var.set(s.syringe_id)
        self.syringe_volume_var.set(s.syringe_volume)
        self.igniter_voltage_var.set(s.igniter_voltage)

        volume_ul = int(s.syringe_volume * 1000)
        self.liquid_volume_lbl.config(text=str(volume_ul))
        self.volume_sensorhome_lbl.config(text=str(volume_ul))
        self.syringe_diameter_lbl.config(text=str(s.syringe_id))
        self.diameterhome_value_lbl.config(text=str(s.syringe_id))

        # Clamp gas index and select in list
        idx = max(0, min(7, s.cal_gas_index))
        self.cal_gas_list.selection_clear(0, tk.END)
        self.cal_gas_list.selection_set(idx)

    def _save_settings(self):
        """Read current UI values, send to hardware, and write to file."""
        # Stop pump before changing syringe parameters
        pump_module.stop_pump(self.pump_serial)

        sid  = self.syringe_id_var.get()
        svol = self.syringe_volume_var.get()
        iv   = self.igniter_voltage_var.get()

        # Cal gas index from listbox
        sel = self.cal_gas_list.curselection()
        cg  = int(sel[0]) if sel else 0

        # Send volume to pump (convert ml → μL)
        volume_ul = int(float(svol) * 1000)
        confirmed_vol_str = pump_module.set_volume(self.pump_serial, volume_ul)
        try:
            confirmed_vol = float(int(confirmed_vol_str) / 1000)
        except (ValueError, TypeError):
            confirmed_vol = float(svol)

        self.liquid_volume_lbl.config(text=str(volume_ul))
        self.volume_sensorhome_lbl.config(text=str(volume_ul))
        self.syringe_volume_var.set(confirmed_vol)

        # Send diameter to pump
        confirmed_id = pump_module.set_diameter(self.pump_serial, sid)
        self.syringe_id_var.set(confirmed_id)
        self.syringe_diameter_lbl.config(text=str(sid))
        self.diameterhome_value_lbl.config(text=str(sid))

        # Send cal gas to valve controller
        gas_module.set_cal_gas(self.gas_serial, cg)

        # Persist to file
        settings_manager.write_settings(sid, confirmed_vol, cg, iv)

        # Re-apply flow rate with current slider value
        self._set_liquid_flow()

    # -----------------------------------------------------------------------
    # Hardware control helpers
    # -----------------------------------------------------------------------
    def _psupply_on(self):
        if self.gas_state == 'OFF':
            show_message(self.root, 'Warning!', 'Must turn on gas first')
            return
        hardware.power_supply_on()
        self.power_state = "ON"
        self.p_on_btn.config(relief=tk.SUNKEN)
        self.p_off_btn.config(relief=tk.RAISED)

    def _psupply_off(self):
        hardware.power_supply_off()
        self.power_state = "OFF"
        self.p_off_btn.config(relief=tk.SUNKEN)
        self.p_on_btn.config(relief=tk.RAISED)

    def _gas_on(self):
        ml = self.gas_sl.get()
        gas_module.set_flow(self.gas_serial, ml)
        self.gas_state = "ON"
        self.gas_on_btn.config(relief=tk.SUNKEN)
        self.gas_off_btn.config(relief=tk.RAISED)

    def _gas_off(self):
        if self.power_state == 'ON':
            show_message(self.root, 'Warning!', 'Must turn off power supply first')
            return
        gas_module.stop_flow(self.gas_serial)
        self.gas_state = "OFF"
        self.gas_off_btn.config(relief=tk.SUNKEN)
        self.gas_on_btn.config(relief=tk.RAISED)

    def _set_gas_flow(self, *_):
        if self.gas_state == 'ON':
            gas_module.set_flow(self.gas_serial, self.gas_sl.get())

    def _set_liquid_flow(self, *_):
        rate = self.liquid_sl.get()
        pump_module.set_rate(self.pump_serial, rate)

    def _pump_start(self):
        self.lstart_btn.config(relief=tk.SUNKEN)
        self.lstop_btn.config(relief=tk.RAISED)
        self.lpause_btn.config(relief=tk.RAISED)
        self._set_liquid_flow()
        pump_module.start_pump(self.pump_serial)

    def _pump_pause(self):
        self.lstart_btn.config(relief=tk.RAISED)
        self.lstop_btn.config(relief=tk.RAISED)
        self.lpause_btn.config(relief=tk.SUNKEN)
        pump_module.pause_pump(self.pump_serial)

    def _pump_stop(self):
        self.lstart_btn.config(relief=tk.RAISED)
        self.lstop_btn.config(relief=tk.SUNKEN)
        self.lpause_btn.config(relief=tk.RAISED)
        pump_module.stop_pump(self.pump_serial)

    def _set_current(self, *_):
        """Calculate and apply DAC values for the currently selected channel."""
        ma    = self.current_sl.get()
        setv1 = int((int(ma) * 41.59) + 0.05)
        setv2 = int((int(ma) * 41.30) + 0.05)
        ch    = self.channel_var.get()

        if ch == 'ch1':
            hardware.set_ch1_current(setv1)
            self.ch1_set = ma
            self.ch1_set_lbl.config(text=ma)
            self.ch1_set_home_lbl.config(text=ma)
        elif ch == 'ch2':
            hardware.set_ch2_current(setv2)
            self.ch2_set = ma
            self.ch2_set_lbl.config(text=ma)
            self.ch2_set_home_lbl.config(text=ma)
        elif ch == 'both':
            hardware.set_both_current(setv1, setv2)
            self.ch1_set = self.ch2_set = ma
            self.ch1_set_lbl.config(text=ma)
            self.ch2_set_lbl.config(text=ma)
            self.ch1_set_home_lbl.config(text=ma)
            self.ch2_set_home_lbl.config(text=ma)

    def _channel_changed(self):
        """When the channel radio button changes, sync the slider to that channel's setpoint."""
        ch = self.channel_var.get()
        if ch == 'ch1':
            self.current_sl.set(self.ch1_set)
        elif ch == 'ch2':
            self.current_sl.set(self.ch2_set)
        elif ch == 'both':
            # Use the lower of the two setpoints to avoid overdriving either channel
            lower = min(int(self.ch1_set), int(self.ch2_set))
            self.current_sl.set(lower)
            self.ch1_set = self.ch2_set = lower
        self._set_current()

    def _igniter_sequence(self):
        """Run the igniter start-up sequence with a warning popup."""
        popup = tk.Toplevel(self.root)
        popup.resizable(False, False)
        popup.overrideredirect(True)
        popup.config(cursor="none")
        w, h = 470, 170
        ws = self.root.winfo_screenwidth()
        hs = self.root.winfo_screenheight()
        popup.geometry(f"{w}x{h}+{(ws//2)-(w//2)}+{(hs//2)-(h//2)}")
        popup.config(bg="gray65")
        tk.Label(popup, text="Warning!",        bg="gray65", font=('Times', 20)).pack()
        tk.Label(popup, text="Igniter Started", bg="gray65", font=('Times', 20)).pack()
        self.root.update_idletasks()

        self._psupply_on()
        time.sleep(0.3)
        self.root.update_idletasks()

        # Calculate PWM duty cycle from igniter voltage setting
        voltage    = self.igniter_voltage_var.get()
        temp_v     = int(voltage) / 1000
        duty_cycle = int(((0.05333 * float(temp_v)) - 0.0711) * 1_000_000)
        hardware.pwm_set(duty_cycle)

        time.sleep(5)
        hardware.pwm_off()
        popup.destroy()

    # -----------------------------------------------------------------------
    # +/- slider helpers
    # -----------------------------------------------------------------------
    def _increment(self, slider, amount, callback):
        slider.set(slider.get() + amount)
        callback()

    def _decrement(self, slider, amount, callback):
        slider.set(slider.get() - amount)
        callback()

    # Home tab routes +/- to the selected device slider
    def _system_up(self):
        dev = self.device_var.get()
        if dev == 'currentsl':
            self._increment(self.current_sl, 1, self._set_current)
        elif dev == 'gas_sl':
            self._increment(self.gas_sl, 10, self._set_gas_flow)
        elif dev == 'liquid_sl':
            self._increment(self.liquid_sl, 1, self._set_liquid_flow)

    def _system_down(self):
        dev = self.device_var.get()
        if dev == 'currentsl':
            self._decrement(self.current_sl, 1, self._set_current)
        elif dev == 'gas_sl':
            self._decrement(self.gas_sl, 10, self._set_gas_flow)
        elif dev == 'liquid_sl':
            self._decrement(self.liquid_sl, 1, self._set_liquid_flow)

    def _system_start(self):
        dev = self.device_var.get()
        if dev == 'currentsl':   self._psupply_on()
        elif dev == 'gas_sl':    self._gas_on()
        elif dev == 'liquid_sl': self._pump_start()

    def _system_pause(self):
        dev = self.device_var.get()
        if dev == 'currentsl':   self._psupply_off()
        elif dev == 'gas_sl':    self._gas_off()
        elif dev == 'liquid_sl': self._pump_pause()

    def _system_stop(self):
        dev = self.device_var.get()
        if dev == 'currentsl':   self._psupply_off()
        elif dev == 'gas_sl':    self._gas_off()
        elif dev == 'liquid_sl': self._pump_stop()

    # -----------------------------------------------------------------------
    # Settings dialog callbacks
    # -----------------------------------------------------------------------
    def _ask_syringe_id(self):
        val = number_pad_dialog(self.root, title="Set ID")
        if val:
            try:
                self.syringe_id_var.set(float(val))
                self._save_settings()
            except ValueError:
                show_message(self.root, "Invalid value", "Please enter a number")

    def _ask_syringe_volume(self):
        val = number_pad_dialog(self.root, title="Set Volume")
        if val:
            try:
                self.syringe_volume_var.set(float(val))
                self._save_settings()
            except ValueError:
                show_message(self.root, "Invalid value", "Please enter a number")

    def _ask_igniter_voltage(self):
        val = number_pad_dialog(self.root, title="Igniter Voltage")
        if val:
            try:
                v = int(val)
                v = max(1500, min(5000, v))  # clamp to safe range
                self.igniter_voltage_var.set(v)
                self._save_settings()
            except ValueError:
                show_message(self.root, "Invalid value", "Enter a number between 1500-5000")

    # -----------------------------------------------------------------------
    # Shutdown / exit
    # -----------------------------------------------------------------------
    def _shutdown_system(self):
        import os

        # --- Status popup ---
        ws = self.root.winfo_screenwidth()
        hs = self.root.winfo_screenheight()
        self._save_settings()
        hardware.zero_outputs()

        status = tk.Toplevel(self.root)
        status.resizable(False, False)
        status.overrideredirect(True)
        status.config(cursor="none")
        w, h = 520, 200
        status.geometry(f"{w}x{h}+{(ws//2)-(w//2)}+{(hs//2)-(h//2)}")
        status.config(bg="gray65")
        status.grab_set()

        tk.Label(status, text="Shutting Down...",
                 bg="gray65", font=('Times', 24)).pack(pady=(20, 6))
        tk.Label(status, text="Purging gas line. Please wait.",
                 bg="gray65", font=('Times', 17)).pack()
        tk.Label(status, text="Do not remove power — system will",
                 bg="gray65", font=('Times', 17)).pack()
        tk.Label(status, text="turn off automatically after shutdown.",
                 bg="gray65", font=('Times', 17)).pack()

        status.focus_force()
        status.lift()
        self.root.update()
        # Pump a few event cycles to ensure Wayland renders the window
        for _ in range(10):
            self.root.update()
            time.sleep(0.02)

        hardware.power_supply_off()
        pump_module.stop_pump(self.pump_serial)

        # Purge sequence: high flow for 100 s then low standby flow
        gas_module.set_flow(self.gas_serial, 1000)  # max purge
        time.sleep(100)
        gas_module.set_flow(self.gas_serial, 2)     # low standby
        time.sleep(1)

        self.root.update_idletasks()
        # Drive shutdown pin HIGH and leave it — OS will reset GPIO on shutdown
        # Arduino detects rising edge, waits 20s then cuts power
        # OS shutdown takes ~10s so power cuts cleanly after filesystem unmount
        hardware.trigger_shutdown_pin()
        os.system('sudo shutdown now')

    def _exit_program(self):
        self._save_settings()
        hardware.zero_outputs()
        pump_module.stop_pump(self.pump_serial)
        hardware.power_supply_off()
        gas_module.stop_flow(self.gas_serial)
        pump_module.close_pump(self.pump_serial)
        gas_module.close_gas_valve(self.gas_serial)
        hardware.hardware_cleanup()
        self.root.destroy()

    # -----------------------------------------------------------------------
    # Sensor update loop  (called every 200 ms via root.after)
    # -----------------------------------------------------------------------
    def _sensor_loop(self):
        # Get latest cached readings — never blocks UI thread
        data = self.sensor_poller.get() if self.sensor_poller else {}

        self._update_voltage_display(data)
        self._update_current_display(data)
        self._update_plasma_display()
        self._update_setpoint_display()

        self.sensor_cycle += 1
        if self.sensor_cycle == 3:
            self._update_volume_display()
        if self.sensor_cycle == 4:
            self._update_gas_display()
            self.sensor_cycle = 0

        if self.error_count >= 20:
            self._psupply_off()
            show_message(self.root, "COMMUNICATION ERROR", "PLEASE RESTART")
            self.error_count = 0

        self.root.after(200, self._sensor_loop)

    def _update_voltage_display(self, data):
        if self.power_state == "ON":
            raw1 = data.get("ch1_voltage", -1)
            if raw1 == -1:
                self.kvsensor_1_lbl.config(text="0")
                self.kvsensor_1_home_lbl.config(text="0")
                self.error_count += 1
            else:
                kv = (0.2486 * raw1) - 12.183
                val = max(0, int(kv))
                self.kvsensor_1_lbl.config(text=val)
                self.kvsensor_1_home_lbl.config(text=val)
                self.kv_1 = kv

            raw2 = data.get("ch2_voltage", -1)
            if raw2 == -1:
                self.kvsensor_2_lbl.config(text="0")
                self.kvsensor_2_home_lbl.config(text="0")
                self.error_count += 1
            else:
                kv = (0.2484 * raw2) - 11.429
                val = max(0, int(kv))
                self.kvsensor_2_lbl.config(text=val)
                self.kvsensor_2_home_lbl.config(text=val)
                self.kv_2 = kv

            self.error_count = 0
        else:
            # Power off: read ADS1115 directly on main thread (not thread-safe)
            try:
                raw = hardware.adc_read_reference()
            except Exception:
                raw = 0
            kv  = raw / 8.844
            val = max(0, int(kv))
            self.kv_1 = self.kv_2 = kv
            for lbl in (self.kvsensor_1_lbl, self.kvsensor_1_home_lbl,
                        self.kvsensor_2_lbl, self.kvsensor_2_home_lbl):
                lbl.config(text=val)

    def _update_current_display(self, data):
        raw1 = data.get("ch1_current", -1)
        if raw1 == -1:
            self.masensor_1_lbl.config(text=int(self.ma_1))
            self.masensor_1_home_lbl.config(text="0")
            self.error_count += 1
        else:
            ma = (-0.048651 * raw1) + 100.250
            if ma >= 70:
                self._pump_stop()
                self._psupply_off()
                show_message(self.root, "ERROR 5-1 CALL", "509-713-3009")
            self.ma_1 = ma
            self.masensor_1_lbl.config(text=int(ma))
            self.masensor_1_home_lbl.config(text=int(ma))

        raw2 = data.get("ch2_current", -1)
        if raw2 == -1:
            self.masensor_2_lbl.config(text=int(self.ma_2))
            self.masensor_2_home_lbl.config(text="0")
            self.error_count += 1
        else:
            ma = (-0.048777 * raw2) + 100.660
            if ma >= 70:
                self._pump_stop()
                self._psupply_off()
                show_message(self.root, "ERROR 5-2 CALL", "509-713-3009")
            self.ma_2 = ma
            self.masensor_2_lbl.config(text=int(ma))
            self.masensor_2_home_lbl.config(text=int(ma))

        if raw1 != -1 and raw2 != -1:
            self.error_count = 0

    def _update_plasma_display(self):
        pl1 = max(0, int(self.kv_1) - (int(self.ma_1) * 10))
        pl2 = max(0, int(self.kv_2) - (int(self.ma_2) * 10))
        self.plasmaw_1_lbl.config(text=pl1)
        self.plasmaw_1_home_lbl.config(text=pl1)
        self.plasmaw_2_lbl.config(text=pl2)
        self.plasmaw_2_home_lbl.config(text=pl2)

    def _update_setpoint_display(self):
        self.gassetphome_lbl.config(text=self.gas_sl.get())
        self.liquidlblhome_lbl.config(text=self.liquid_sl.get())

    def _update_volume_display(self):
        response = pump_module.get_dispensed_volume(self.pump_serial)
        if response and (1 <= len(response) <= 8):
            try:
                val = "%0.2f" % float(response)
                self.liquid_sensorhome_lbl.config(text=val)
                self.liquid_sensor_lbl.config(text=val)
            except ValueError:
                pass

    def _update_gas_display(self):
        # Use cached poller data — never blocks the UI thread
        if self.gas_poller:
            data = self.gas_poller.get()
            if data["ok"]:
                status_str = (
                    f"Temp: {data['temp_c']:.1f}\u00b0C    "
                    f"Actual: {data['actual']:.3f} L/min"
                )
                if data["flags"]:
                    status_str += f"    [{data['flags']}]"
                self.gas_sensor_lbl.config(text=status_str)
                self.gas_sensorhome_lbl.config(text=f"{data['actual']:.3f}")
            elif data["raw"]:
                self.gas_sensor_lbl.config(text=data["raw"])
        else:
            # Fallback: direct serial read (blocking — only if no poller)
            raw, flow_val = gas_module.read_flow_data(self.gas_serial)
            if raw:
                parts = raw.split()
                if len(parts) >= 7 and parts[0] == 'A':
                    try:
                        temp_c = float(parts[1])
                        actual = float(parts[2])
                        flags  = ' '.join(parts[7:]) if len(parts) > 7 else ''
                        status_str = (
                            f"Temp: {temp_c:.1f}\u00b0C    "
                            f"Actual: {actual:.3f} L/min"
                        )
                        if flags:
                            status_str += f"    [{flags}]"
                        self.gas_sensor_lbl.config(text=status_str)
                    except (ValueError, IndexError):
                        self.gas_sensor_lbl.config(text=raw)
                else:
                    self.gas_sensor_lbl.config(text=raw)
            if flow_val:
                self.gas_sensorhome_lbl.config(text=flow_val)

    # =======================================================================
    # Tab builders
    # =======================================================================

    # -----------------------------------------------------------------------
    # HOME tab
    # -----------------------------------------------------------------------
    def _build_home_tab(self):
        home = ttk.Frame(self.nb)
        self.nb.add(home, text='  Home  ')

        home.columnconfigure(0, minsize=260, weight=2)
        home.columnconfigure(1, minsize=230, weight=1)
        home.columnconfigure(2, minsize=260, weight=2)
        home.rowconfigure(0, minsize=40)
        home.rowconfigure(1, minsize=260)

        # --- control buttons row ---
        btn_frame = tk.Frame(home)
        self.device_var = tk.StringVar(value='currentsl')

        start_btn = tk.Button(btn_frame, text="Start", width=6,
                              command=self._system_start,
                              relief="raised", bd=3, bg='green',
                              activebackground='green', font=("Times", 25))
        pause_btn = tk.Button(btn_frame, text="Pause", width=6,
                              command=self._system_pause,
                              bg='orange', relief="raised", bd=3,
                              activebackground='orange', font=("Times", 25))
        stop_btn  = tk.Button(btn_frame, text="Stop",  width=6,
                              command=self._system_stop,
                              bg='red', relief="raised", bd=3,
                              activebackground='red', font=("Times", 25))
        down_btn  = tk.Button(btn_frame, text="-", width=2,
                              command=self._system_down,
                              relief="raised", bd=3, font=("Times", 25))
        up_btn    = tk.Button(btn_frame, text="+", width=2,
                              command=self._system_up,
                              relief="raised", bd=3, font=("Times", 25))

        g1 = tk.Radiobutton(btn_frame, text="Current",     variable=self.device_var, value='currentsl', font=('Times', 18))
        g2 = tk.Radiobutton(btn_frame, text="Gas Flow",    variable=self.device_var, value='gas_sl',    font=('Times', 18))
        g3 = tk.Radiobutton(btn_frame, text="Liquid Flow", variable=self.device_var, value='liquid_sl', font=('Times', 18))

        btn_frame.grid(column=0, row=3, columnspan=4, sticky='NSEW')
        btn_frame.columnconfigure(3, minsize=50)
        start_btn.grid(column=0, row=0, rowspan=3)
        pause_btn.grid(column=1, row=0, rowspan=3)
        stop_btn.grid( column=2, row=0, rowspan=3)
        down_btn.grid( column=4, row=0, rowspan=3)
        up_btn.grid(   column=6, row=0, rowspan=3)
        g1.grid(column=5, row=0)
        g2.grid(column=5, row=1)
        g3.grid(column=5, row=2)

        # --- Current display panel ---
        currentframe = tk.Frame(home, borderwidth=5, relief="ridge",
                                width=260, height=40, bg='white')
        currenthome  = tk.Frame(home, borderwidth=5, relief="ridge",
                                width=260, height=260, bg='white')
        tk.Label(currentframe, text="Current", justify=tk.CENTER,
                 bg='white', font=("Times", 25)).pack()
        currentframe.grid(column=0, row=0, sticky='NSEW')
        currenthome.grid( column=0, row=1, sticky='NSEW')
        self._build_current_home_panel(currenthome)

        # --- Gas display panel ---
        gasframe = tk.Frame(home, borderwidth=5, relief="ridge",
                            width=230, height=40, bg='white')
        gashome  = tk.Frame(home, borderwidth=5, relief="ridge",
                            width=230, height=260, bg='white')
        tk.Label(gasframe, text="Gas Flow", justify=tk.CENTER,
                 bg='white', font=("Times", 25)).pack()
        gasframe.grid(column=1, row=0, sticky='NSEW')
        gashome.grid( column=1, row=1, sticky='NSEW')
        self._build_gas_home_panel(gashome)

        # --- Liquid display panel ---
        liquidframe = tk.Frame(home, borderwidth=5, relief="ridge",
                               width=260, height=40, bg='white')
        liquidhome  = tk.Frame(home, borderwidth=5, relief="ridge",
                               width=260, height=260, bg='white')
        tk.Label(liquidframe, text="Liquid Flow", justify=tk.CENTER,
                 bg='white', font=("Times", 25)).pack()
        liquidframe.grid(column=2, row=0, sticky='NSEW')
        liquidhome.grid( column=2, row=1, sticky='NSEW')
        self._build_liquid_home_panel(liquidhome)

    def _build_current_home_panel(self, parent):
        parent.columnconfigure(0, minsize=120, weight=1)
        parent.columnconfigure(2, minsize=60,  weight=1)
        parent.columnconfigure(4, minsize=60,  weight=2)
        for r in range(0, 9, 2):
            parent.rowconfigure(r, minsize=52, weight=1)

        ttk.Separator(parent, orient=tk.VERTICAL).grid(  column=1, row=0, rowspan=10, sticky='NS')
        ttk.Separator(parent, orient=tk.VERTICAL).grid(  column=3, row=0, rowspan=10, sticky='NS')
        ttk.Separator(parent, orient=tk.HORIZONTAL).grid(column=0, row=1, columnspan=8, sticky='EW')
        ttk.Separator(parent, orient=tk.HORIZONTAL).grid(column=0, row=3, columnspan=8, sticky='EW')
        ttk.Separator(parent, orient=tk.HORIZONTAL).grid(column=0, row=5, columnspan=8, sticky='EW')
        ttk.Separator(parent, orient=tk.HORIZONTAL).grid(column=0, row=7, columnspan=8, sticky='EW')

        f = ("Times", 14)
        tk.Label(parent, text='Set Point mA',   bg='white', font=f).grid(column=0, row=2)
        tk.Label(parent, text='Supply mA',      bg='white', font=f).grid(column=0, row=4)
        tk.Label(parent, text='Supply Voltage', bg='white', font=f).grid(column=0, row=6)
        tk.Label(parent, text='Plasma Voltage', bg='white', font=f).grid(column=0, row=8)
        tk.Label(parent, text='Channel 1',      bg='white', font=f).grid(column=2, row=0)
        tk.Label(parent, text='Channel 2',      bg='white', font=f).grid(column=4, row=0)

        self.ch1_set_home_lbl    = tk.Label(parent, text='0', bg='white', font=f)
        self.ch2_set_home_lbl    = tk.Label(parent, text='0', bg='white', font=f)
        self.masensor_1_home_lbl = tk.Label(parent, text='0', bg='white', font=f)
        self.masensor_2_home_lbl = tk.Label(parent, text='0', bg='white', font=f)
        self.kvsensor_1_home_lbl = tk.Label(parent, text='0', bg='white', font=f)
        self.kvsensor_2_home_lbl = tk.Label(parent, text='0', bg='white', font=f)
        self.plasmaw_1_home_lbl  = tk.Label(parent, text='0', bg='white', font=f)
        self.plasmaw_2_home_lbl  = tk.Label(parent, text='0', bg='white', font=f)

        self.ch1_set_home_lbl.grid(  column=2, row=2)
        self.ch2_set_home_lbl.grid(  column=4, row=2)
        self.masensor_1_home_lbl.grid(column=2, row=4)
        self.masensor_2_home_lbl.grid(column=4, row=4)
        self.kvsensor_1_home_lbl.grid(column=2, row=6)
        self.kvsensor_2_home_lbl.grid(column=4, row=6)
        self.plasmaw_1_home_lbl.grid( column=2, row=8)
        self.plasmaw_2_home_lbl.grid( column=4, row=8)

    def _build_gas_home_panel(self, parent):
        parent.columnconfigure(0, minsize=230)
        for r in range(0, 7, 2):
            parent.rowconfigure(r, minsize=65)

        f = ("Times", 18)
        tk.Label(parent, text='Setpoint (mL/min)', bg='white', font=f).grid(column=0, row=0)
        ttk.Separator(parent, orient=tk.HORIZONTAL).grid(column=0, row=1, columnspan=3, sticky='EW')
        self.gassetphome_lbl = tk.Label(parent, text='0', bg='white', font=("Times", 18))
        self.gassetphome_lbl.grid(column=0, row=2)
        tk.Label(parent, text='Actual (ml/min)', bg='white', font=f).grid(column=0, row=4)
        ttk.Separator(parent, orient=tk.HORIZONTAL).grid(column=0, row=5, columnspan=3, sticky='EW')
        self.gas_sensorhome_lbl = tk.Label(parent, text='0', bg='white', font=("Times", 15))
        self.gas_sensorhome_lbl.grid(column=0, row=6)

    def _build_liquid_home_panel(self, parent):
        parent.columnconfigure(0, minsize=125)
        parent.columnconfigure(2, minsize=125)
        for r in range(0, 7, 2):
            parent.rowconfigure(r, minsize=65)

        f = ("Times", 17)
        tk.Label(parent, text='μL/min', bg='white', font=f).grid(column=0, row=0)
        tk.Label(parent, text='ID(mm)', bg='white', font=f).grid(column=2, row=0)
        ttk.Separator(parent, orient=tk.VERTICAL).grid(  column=1, row=0, rowspan=3, sticky='NS')
        ttk.Separator(parent, orient=tk.HORIZONTAL).grid(column=0, row=1, columnspan=3, sticky='EW')

        self.liquidlblhome_lbl      = tk.Label(parent, text='0', bg='white', font=f)
        self.diameterhome_value_lbl = tk.Label(parent, text='0', bg='white', font=f)
        self.liquidlblhome_lbl.grid(     column=0, row=2)
        self.diameterhome_value_lbl.grid(column=2, row=2)

        tk.Label(parent, text='Dispensed Volume', bg='white', font=f).grid(column=0, row=4, columnspan=3)
        ttk.Separator(parent, orient=tk.HORIZONTAL).grid(column=0, row=5, columnspan=3, sticky='EW')

        vol_frame = tk.Frame(parent, bg='white')
        vol_frame.columnconfigure(0, minsize=115)
        vol_frame.columnconfigure(1, minsize=20)
        vol_frame.columnconfigure(2, minsize=115)
        self.liquid_sensorhome_lbl = tk.Label(vol_frame, text='0', bg='white', font=f)
        self.volume_sensorhome_lbl = tk.Label(vol_frame, text='0', bg='white', font=f)
        tk.Label(vol_frame, text='of', bg='white', font=f).grid(column=1, row=0)
        self.liquid_sensorhome_lbl.grid(column=0, row=0)
        self.volume_sensorhome_lbl.grid(column=2, row=0)
        vol_frame.grid(column=0, row=6, columnspan=3)

    # -----------------------------------------------------------------------
    # CURRENT tab
    # -----------------------------------------------------------------------
    def _build_current_tab(self):
        content = ttk.Frame(self.nb)
        self.nb.add(content, text=' Current ')

        content.columnconfigure(0, minsize=600, weight=1)
        content.columnconfigure(1, minsize=200)
        content.rowconfigure(1, minsize=45)
        content.rowconfigure(2, minsize=280, weight=1)
        content.rowconfigure(3, minsize=45)

        # Header
        nameframe = tk.Frame(content, borderwidth=5, relief="ridge",
                             width=600, bg='white')
        tk.Label(nameframe, text="Current", justify=tk.CENTER,
                 bg='white', font=("Times", 30)).pack()
        nameframe.grid(column=0, row=1, sticky='NSEW')

        # Data display grid
        df = tk.Frame(content, borderwidth=5, relief="ridge",
                      width=600, height=250, bg='white')
        df.columnconfigure(0, minsize=200, weight=1)
        df.columnconfigure(2, minsize=200, weight=1)
        df.columnconfigure(4, minsize=200, weight=2)
        for r in range(0, 9, 2):
            df.rowconfigure(r, minsize=50, weight=1)

        ttk.Separator(df, orient=tk.VERTICAL).grid(  column=1, row=0, rowspan=10, sticky='NS')
        ttk.Separator(df, orient=tk.VERTICAL).grid(  column=3, row=0, rowspan=10, sticky='NS')
        ttk.Separator(df, orient=tk.HORIZONTAL).grid(column=0, row=1, columnspan=8, sticky='EW')
        ttk.Separator(df, orient=tk.HORIZONTAL).grid(column=0, row=3, columnspan=8, sticky='EW')
        ttk.Separator(df, orient=tk.HORIZONTAL).grid(column=0, row=5, columnspan=8, sticky='EW')
        ttk.Separator(df, orient=tk.HORIZONTAL).grid(column=0, row=7, columnspan=8, sticky='EW')

        f = ("Times", 20)
        tk.Label(df, text='Set Point mA',   bg='white', font=f).grid(column=0, row=2)
        tk.Label(df, text='Supply mA',      bg='white', font=f).grid(column=0, row=4)
        tk.Label(df, text='Supply Voltage', bg='white', font=f).grid(column=0, row=6)
        tk.Label(df, text='Plasma Voltage', bg='white', font=f).grid(column=0, row=8)
        tk.Label(df, text='Channel 1',      bg='white', font=f).grid(column=2, row=0)
        tk.Label(df, text='Channel 2',      bg='white', font=f).grid(column=4, row=0)

        self.ch1_set_lbl  = tk.Label(df, text='0', bg='white', font=f)
        self.ch2_set_lbl  = tk.Label(df, text='0', bg='white', font=f)
        self.masensor_1_lbl = tk.Label(df, text='0', bg='white', font=f)
        self.masensor_2_lbl = tk.Label(df, text='0', bg='white', font=f)
        self.kvsensor_1_lbl = tk.Label(df, text='0', bg='white', font=f)
        self.kvsensor_2_lbl = tk.Label(df, text='0', bg='white', font=f)
        self.plasmaw_1_lbl  = tk.Label(df, text='0', bg='white', font=f)
        self.plasmaw_2_lbl  = tk.Label(df, text='0', bg='white', font=f)

        self.ch1_set_lbl.grid(  column=2, row=2)
        self.ch2_set_lbl.grid(  column=4, row=2)
        self.masensor_1_lbl.grid(column=2, row=4)
        self.masensor_2_lbl.grid(column=4, row=4)
        self.kvsensor_1_lbl.grid(column=2, row=6)
        self.kvsensor_2_lbl.grid(column=4, row=6)
        self.plasmaw_1_lbl.grid( column=2, row=8)
        self.plasmaw_2_lbl.grid( column=4, row=8)
        df.grid(column=0, row=2, sticky='NSEW')

        # Control buttons
        frame1 = tk.Frame(content)
        frame1.grid(column=0, row=3)

        self.p_on_btn = tk.Button(frame1, text="ON",  width=7, height=2,
                                  relief="raised", bd=3, command=self._psupply_on,
                                  bg='green', activebackground='green', font=("Times", 23))
        self.p_off_btn = tk.Button(frame1, text="OFF", width=7, height=2,
                                   relief="sunken", bd=3, command=self._psupply_off,
                                   bg='red', activebackground='red', font=("Times", 23))
        igniter_btn = tk.Button(frame1, text="Ignite", width=7, height=2,
                                relief="raised", bd=3, command=self._igniter_sequence,
                                bg='orange', activebackground='orange', font=("Times", 23))

        self.p_on_btn.grid( column=0, row=3)
        self.p_off_btn.grid(column=1, row=3)
        igniter_btn.grid(   column=2, row=3)
        self.p_off_btn.focus()

        # Channel radio buttons
        frame2 = tk.Frame(frame1)
        frame2.grid(column=3, row=3)
        self.channel_var = tk.StringVar(value='both')
        rf = ('Times', 16)
        tk.Radiobutton(frame2, text='Channel 1', variable=self.channel_var, value='ch1',
                       command=self._channel_changed, font=rf).grid(column=0, row=0)
        tk.Radiobutton(frame2, text='Channel 2', variable=self.channel_var, value='ch2',
                       command=self._channel_changed, font=rf).grid(column=0, row=1)
        tk.Radiobutton(frame2, text='Both',      variable=self.channel_var, value='both',
                       command=self._channel_changed, font=rf).grid(column=0, row=2)

        # Current slider
        self.current_sl = tk.Scale(content, orient=tk.VERTICAL, length=290,
                                   from_=60, to=0, width=80, resolution=1,
                                   showvalue=True, bigincrement=15)
        self.current_sl.bind("<ButtonRelease-1>", lambda e: self._set_current())

        up_btn   = tk.Button(content, text="+", relief="raised", bd=3,
                             command=lambda: self._increment(self.current_sl, 1, self._set_current),
                             font=("Times", 30))
        down_btn = tk.Button(content, text="-", relief="raised", bd=3,
                             command=lambda: self._decrement(self.current_sl, 1, self._set_current),
                             font=("Times", 30))

        up_btn.grid(  column=1, row=1, sticky='NSEW')
        down_btn.grid(column=1, row=3, sticky='NSEW')
        self.current_sl.grid(column=1, row=2)

    # -----------------------------------------------------------------------
    # GAS FLOW tab
    # -----------------------------------------------------------------------
    def _build_gas_tab(self):
        gcontent = ttk.Frame(self.nb)
        self.nb.add(gcontent, text=' Gas Flow ')

        gcontent.columnconfigure(0, minsize=600)
        gcontent.columnconfigure(1, minsize=200)
        gcontent.rowconfigure(1, minsize=45)
        gcontent.rowconfigure(2, minsize=290)
        gcontent.rowconfigure(3, minsize=45)

        ml_var = tk.StringVar()

        # Header
        gnameframe = tk.Frame(gcontent, borderwidth=5, relief="ridge", width=600, bg='white')
        tk.Label(gnameframe, text="Gas Flow", justify=tk.CENTER,
                 bg='white', font=("Times", 30)).pack()
        gnameframe.grid(column=0, row=1, sticky='NSEW')

        # Data frame
        gdf = tk.Frame(gcontent, borderwidth=5, relief="ridge",
                       width=600, height=290, bg='white')
        gdf.columnconfigure(0, minsize=300)
        gdf.columnconfigure(2, minsize=300)
        for r in range(0, 7, 2):
            gdf.rowconfigure(r, minsize=70)

        f = ("Times", 30)
        tk.Label(gdf, text='Setpoint (mL min)', bg='white', font=f).grid(column=0, row=0, columnspan=3)
        ttk.Separator(gdf, orient=tk.HORIZONTAL).grid(column=0, row=1, columnspan=3, sticky='EW')
        gaslbl = tk.Label(gdf, textvariable=ml_var, bg='white', font=f)
        gaslbl.grid(column=0, row=2, columnspan=3)
        tk.Label(gdf, text='Status', bg='white', font=f).grid(column=0, row=4, columnspan=3)
        ttk.Separator(gdf, orient=tk.HORIZONTAL).grid(column=0, row=5, columnspan=3, sticky='EW')
        self.gas_sensor_lbl = tk.Label(gdf, text='0', bg='white', font=("Times", 20))
        self.gas_sensor_lbl.grid(column=0, row=6, columnspan=3)
        gdf.grid(column=0, row=2, sticky='NSEW')

        # Slider
        self.gas_sl = tk.Scale(gcontent, orient=tk.VERTICAL, length=290,
                               from_=1000, to=10, width=80,
                               variable=ml_var, resolution=10)
        self.gas_sl.bind("<ButtonRelease-1>", self._set_gas_flow)

        gup_btn   = tk.Button(gcontent, text="+", relief="raised", bd=3,
                              command=lambda: self._increment(self.gas_sl, 10, self._set_gas_flow),
                              font=("Times", 30))
        gdown_btn = tk.Button(gcontent, text="-", relief="raised", bd=3,
                              command=lambda: self._decrement(self.gas_sl, 10, self._set_gas_flow),
                              font=("Times", 30))

        gup_btn.grid(  column=1, row=1, sticky='NSEW')
        gdown_btn.grid(column=1, row=3, sticky='NSEW')
        self.gas_sl.grid(column=1, row=2)

        # ON/OFF buttons
        frame2 = tk.Frame(gcontent)
        self.gas_on_btn  = tk.Button(frame2, text="ON",  width=8, relief="raised", bd=3,
                                     command=self._gas_on,
                                     bg='green', activebackground='green', font=("Times", 30))
        self.gas_off_btn = tk.Button(frame2, text="OFF", width=8, relief="sunken", bd=3,
                                     command=self._gas_off,
                                     bg='red', activebackground='red', font=("Times", 30))
        frame2.grid(column=0, row=3)
        self.gas_on_btn.grid( column=0, row=3)
        self.gas_off_btn.grid(column=1, row=3)
        self.gas_off_btn.focus()

    # -----------------------------------------------------------------------
    # LIQUID FLOW tab
    # -----------------------------------------------------------------------
    def _build_liquid_tab(self):
        lcontent = ttk.Frame(self.nb)
        self.nb.add(lcontent, text='Liquid Flow')

        lcontent.columnconfigure(0, minsize=300)
        lcontent.columnconfigure(1, minsize=300)
        lcontent.columnconfigure(2, minsize=200)
        lcontent.rowconfigure(1, minsize=45)
        lcontent.rowconfigure(2, minsize=290)
        lcontent.rowconfigure(3, minsize=45)

        ul_var = tk.StringVar()

        # Header
        lnameframe = tk.Frame(lcontent, borderwidth=5, relief="ridge", width=600, bg='white')
        tk.Label(lnameframe, text="Liquid Flow", justify=tk.CENTER,
                 bg='white', font=("Times", 30)).pack()
        lnameframe.grid(column=0, row=1, columnspan=2, sticky='NSEW')

        # Data frame
        ldf = tk.Frame(lcontent, borderwidth=5, relief="ridge",
                       width=600, height=290, bg='white')
        ldf.columnconfigure(0, minsize=297)
        ldf.columnconfigure(1, minsize=6)
        ldf.columnconfigure(2, minsize=297)
        for r in range(0, 7, 2):
            ldf.rowconfigure(r, minsize=70)

        f = ("Times", 30)
        tk.Label(ldf, text='μL/min',          bg='white', font=f).grid(column=0, row=0)
        tk.Label(ldf, text='Syringe ID(mm)',   bg='white', font=f).grid(column=2, row=0)
        ttk.Separator(ldf, orient=tk.HORIZONTAL).grid(column=0, row=1, columnspan=3, sticky='EW')
        ttk.Separator(ldf, orient=tk.VERTICAL).grid(  column=1, row=0, rowspan=3, sticky='NS')

        liquidlbl = tk.Label(ldf, textvariable=ul_var, bg='white', font=f)
        liquidlbl.grid(column=0, row=2)

        self.syringe_diameter_lbl = tk.Label(ldf, text='0', bg='white', font=f)
        self.syringe_diameter_lbl.grid(column=2, row=2)

        tk.Label(ldf, text='Dispensed Volume(μL)', bg='white', font=f).grid(column=0, row=4, columnspan=3)
        ttk.Separator(ldf, orient=tk.HORIZONTAL).grid(column=0, row=5, columnspan=3, sticky='EW')

        vol_frame = tk.Frame(ldf, bg='white')
        vol_frame.columnconfigure(0, minsize=280)
        vol_frame.columnconfigure(1, minsize=40)
        vol_frame.columnconfigure(2, minsize=280)
        self.liquid_sensor_lbl = tk.Label(vol_frame, text='0', bg='white', font=f)
        self.liquid_volume_lbl = tk.Label(vol_frame, text='0', bg='white', font=f)
        tk.Label(vol_frame, text=' of ', bg='white', font=f).grid(column=1, row=0)
        self.liquid_sensor_lbl.grid(column=0, row=0)
        self.liquid_volume_lbl.grid( column=2, row=0)
        vol_frame.grid(column=0, row=6, columnspan=3)

        ttk.Separator(ldf, orient=tk.HORIZONTAL).grid(column=0, row=1, columnspan=3, sticky='EW')
        ttk.Separator(ldf, orient=tk.HORIZONTAL).grid(column=0, row=5, columnspan=3, sticky='EW')
        ldf.grid(column=0, row=2, columnspan=2, sticky='NSEW')

        # Slider
        self.liquid_sl = tk.Scale(lcontent, orient=tk.VERTICAL, length=290,
                                  from_=250, to=1, width=80,
                                  variable=ul_var, resolution=1)
        self.liquid_sl.bind("<ButtonRelease-1>", self._set_liquid_flow)

        lup_btn   = tk.Button(lcontent, text="+", relief="raised", bd=3,
                              command=lambda: self._increment(self.liquid_sl, 1, self._set_liquid_flow),
                              font=("Times", 30))
        ldown_btn = tk.Button(lcontent, text="-", relief="raised", bd=3,
                              command=lambda: self._decrement(self.liquid_sl, 1, self._set_liquid_flow),
                              font=("Times", 30))
        lup_btn.grid(  column=2, row=1, sticky='NSEW')
        ldown_btn.grid(column=2, row=3, sticky='NSEW')
        self.liquid_sl.grid(column=2, row=2)

        # Start / Pause / Stop buttons
        frame = tk.Frame(lcontent)
        self.lstart_btn = tk.Button(frame, text="Start", width=8,
                                    command=self._pump_start,
                                    relief="raised", bd=3,
                                    bg='green', activebackground='green', font=("Times", 30))
        self.lpause_btn = tk.Button(frame, text="Pause", width=8,
                                    command=self._pump_pause,
                                    bg='orange', relief="raised", bd=3,
                                    activebackground='orange', font=("Times", 30))
        self.lstop_btn  = tk.Button(frame, text="Stop",  width=8,
                                    command=self._pump_stop,
                                    bg='red', relief="sunken", bd=3,
                                    activebackground='red', font=("Times", 30))
        frame.grid(column=0, row=3, columnspan=2, sticky='NSEW')
        self.lstart_btn.grid(column=0, row=3)
        self.lpause_btn.grid(column=1, row=3)
        self.lstop_btn.grid( column=2, row=3)
        self.lstop_btn.focus()

    # -----------------------------------------------------------------------
    # SETTINGS tab
    # -----------------------------------------------------------------------
    def _build_settings_tab(self):
        settings = ttk.Frame(self.nb)
        self.nb.add(settings, text=' Settings ')

        settings.columnconfigure(0, minsize=120)
        settings.columnconfigure(1, minsize=250)
        settings.columnconfigure(2, minsize=40)
        settings.columnconfigure(3, minsize=200)
        settings.rowconfigure(0, minsize=40)

        # --- Syringe pump frame ---
        syringe_frame = ttk.Frame(settings, width=250, height=340)
        syringe_frame.grid(column=1, row=0, sticky='NSEW')

        # Syringe ID
        self.syringe_id_var = tk.StringVar()
        sid_text = tk.Label(text="Syringe ID(mm)", font=('Times', 20))
        sid_box  = ttk.Labelframe(syringe_frame, labelwidget=sid_text,
                                  borderwidth=3, relief="ridge")
        tk.Entry(sid_box, textvariable=self.syringe_id_var,
                 width=5, state='readonly', font=("Times", 20)).pack()
        tk.Button(sid_box, text="     Set ID     ", relief="raised", bd=3,
                  command=self._ask_syringe_id, font=("Times", 20)).pack()
        sid_box.grid(column=0, row=1, sticky='NSEW')

        # Syringe Volume
        self.syringe_volume_var = tk.StringVar()
        svol_text = tk.Label(text="Syringe Volume(ml)", font=('Times', 20))
        svol_box  = ttk.Labelframe(syringe_frame, labelwidget=svol_text,
                                   borderwidth=3, relief="ridge")
        tk.Entry(svol_box, textvariable=self.syringe_volume_var,
                 width=5, state='readonly', font=("Times", 20)).pack()
        tk.Button(svol_box, text="Set Volume", relief="raised", bd=3, width=10,
                  command=self._ask_syringe_volume, font=("Times", 20)).pack()
        svol_box.grid(column=0, row=2, sticky='NSEW')

        # Igniter Voltage
        self.igniter_voltage_var = tk.StringVar()
        iv_text = tk.Label(text="Igniter Voltage", font=('Times', 20))
        iv_box  = ttk.Labelframe(syringe_frame, labelwidget=iv_text,
                                 borderwidth=3, relief="ridge")
        tk.Entry(iv_box, textvariable=self.igniter_voltage_var,
                 width=5, state='readonly', font=("Times", 25)).pack()
        tk.Button(iv_box, text="Set Voltage", relief="raised", bd=3, width=10,
                  command=self._ask_igniter_voltage, font=("Times", 20)).pack()
        iv_box.grid(column=0, row=3, sticky='NSEW')

        # --- Cal gas frame ---
        gas_frame = ttk.Frame(settings, width=180, height=340)
        gas_frame.grid(column=3, row=0)

        gasframe = tk.Frame(gas_frame, borderwidth=5, relief="ridge",
                            width=180, height=40, bg="white")
        gasbox   = ttk.Frame(gas_frame, borderwidth=5, relief="ridge",
                             width=180, height=300)

        tk.Label(gasframe, text="Calibration Gas", justify=tk.CENTER,
                 bg="white", font=("Times", 20)).pack()

        calgas = ('Air', 'Argon', 'Carbon Dioxide', 'Nitrogen',
                  'Oxygen', 'Nitrous Oxide', 'Hydrogen', 'Helium')
        cnames = tk.StringVar(value=calgas)
        self.cal_gas_list = tk.Listbox(gasbox, listvariable=cnames,
                                       height=8, width=18,
                                       selectbackground='grey70',
                                       exportselection=False,
                                       font=("Times", 20))
        for i in range(0, 8, 2):
            self.cal_gas_list.itemconfigure(i, background='light blue')

        gasframe.grid(column=0, row=0, sticky='NESW')
        gasbox.grid(  column=0, row=1)
        self.cal_gas_list.grid(column=0, row=0)

        tk.Button(gas_frame, text="Save Cal Gas", relief="raised", bd=3, width=10,
                  command=self._save_settings, font=("Times", 20)).grid(column=0, row=4)

    # -----------------------------------------------------------------------
    # SHUTDOWN tab
    # -----------------------------------------------------------------------
    def _build_shutdown_tab(self):
        shutdown = ttk.Frame(self.nb)
        self.nb.add(shutdown, text=' Shutdown ')

        shutdown.columnconfigure(0, minsize=300)
        shutdown.columnconfigure(1, minsize=80)
        shutdown.rowconfigure(0, minsize=100)
        shutdown.rowconfigure(2, minsize=40)

        tk.Button(shutdown, text="Shutdown", relief="raised", bd=3, width=10,
                  command=self._shutdown_system, font=("Times", 25)).grid(column=1, row=1)
        tk.Button(shutdown, text="Exit",     relief="raised", bd=3,
                  command=self._exit_program, font=("Times", 15)).grid(column=1, row=3)
