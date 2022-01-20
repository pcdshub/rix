from hutch_python.utils import safe_load
import numpy as np
import sys
from epics import caget, caput, cainfo


with safe_load('LCLS-II daq step_value'):
    from ophyd.sim import SynAxis
    from rix.rix_daq_rework.ControlDef import ControlDef

    step_value = SynAxis(name=ControlDef.STEP_VALUE)


with safe_load('FS14 lxt, txt, lxt_ttc, las_wp1, las_wp2'):
    from rix.lxt import lxt, txt, lxt_ttc, las_wp1, las_wp2


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
    vernier_energy = EpicsSignal('RIX:USER:MCC:EPHOTK:SET1', name='vernier_energy')


with safe_load('laser lens motors'):
    from pcdsdevices.epics_motor import SmarAct
    lm2k2_ejx_mp1_ls1_lm3 = SmarAct('LM2K2:EJX_MP1_LS1_LM3', name='lm2k2_ejx_mp1_ls1_lm3')
    lm2k2_ejx_mp1_ls1_lm2 = SmarAct('LM2K2:EJX_MP1_LS1_LM2', name='lm2k2_ejx_mp1_ls1_lm2')
    lm2k2_inj_mp1_att1_wp1 = SmarAct('LM2K2:INJ_MP1_ATT1_WP1', name='lm2k2_inj_mp1_att1_wp1')
    lm2k2_inj_mp1_att1_wp2 = SmarAct('LM2K2:INJ_MP1_ATT1_WP2', name='lm2k2_inj_mp1_att1_wp2')
    lm2k2_ejx_mp1_s41 = SmarAct('LM2K2:EJX_MP1_S41:M1', name='lm2k2_ejx_mp1_s41')


with safe_load('continous scan'):
    from rix.continuous_scan import continuous_scan
