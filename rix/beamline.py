from hutch_python.utils import safe_load


with safe_load('LCLS-II get_daq'):
    #def get_daq():
    #    from rix.rix_daq import daq
    #    return daq
    from rix.rix_daq_rework import get_daq


with safe_load('LCLS-II daq step_value'):
    from ophyd.sim import SynAxis
    from rix.rix_daq_rework.ControlDef import ControlDef

    step_value = SynAxis(name=ControlDef.STEP_VALUE)


with safe_load('mono_vernier_scan'):
    from rix.vernier_scan import (mono_vernier_scan, calc_mono_ev,
                                  scan_devices as vernier_scan_devices,
                                  setup_scan_devices as _setup_scan_devices)
    _setup_scan_devices()


with safe_load('aliases'):
    from rix.db import mr1k1_bend
    mr1k1_bend_us = mr1k1_bend.bender_us
    mr1k1_bend_ds = mr1k1_bend.bender_ds

with safe_load('mono energy scan'):
    from ophyd.signal import EpicsSignal
    from pcdsdevices.epics_motor import BeckhoffAxis
    mono_g_pi = BeckhoffAxis('SP1K1:MONO:MMS:G_PI', name='mono_g_pi')
    vernier_energy = EpicsSignal('RIX:USER:MCC:EPHOTK', name='vernier_energy')
   
