from hutch_python.utils import safe_load
import numpy as np
import sys
from epics import caget, caput, cainfo


with safe_load('Configure Run Engine'):
    # Always move to start
    from rix.db import RE
    from bluesky.preprocessors import reset_positions_wrapper as _rpm
    try:
        RE.preprocessors.remove(_rpm)
    except ValueError:
        # Already gone
        pass
    #RE.preprocessors.append(_rpm)
    # To enable 'rpm' per scan try %RE(rpm(my_scan(some_args)))
 

with safe_load('LCLS-II daq step_value'):
    from ophyd.sim import SynAxis
    from psdaq.control.ControlDef import ControlDef

    step_value = SynAxis(name=ControlDef.STEP_VALUE)


with safe_load('FS14 lxt, txt, lxt_ttc, las_wp1, las_wp2'):
    from rix.lxt import lxt, txt, lxt_ttc, las_wp1, las_wp2


with safe_load('CAM Recorder'):
    from rix.cam_to_file import h5_img_collect, ppm_scan

#with safe_load('mono_vernier_scan'):
#    from rix.vernier_scan import (mono_vernier_scan, calc_mono_ev,
#                                  scan_devices as vernier_scan_devices,
#                                  setup_scan_devices as _setup_scan_devices)
#    _setup_scan_devices()

with safe_load('mono energy_scan'):
    from rix.energy_scan import (energy_scan, energy_scan_step,
                                 energy_scan_nd, energy_scan_nd_list,
                                 energy_scan_nd_grid,
                                 energy_scan_nd_grid_list,
                                 energy_grating_step_scan,
                                 energy_grating_list_scan,
                                 setup_scan_devices as _setup_scan_devices)
    _setup_scan_devices()


with safe_load('aliases'):
    from rix.db import mr1k1_bend
    mr1k1_bend_us = mr1k1_bend.bender_us
    mr1k1_bend_ds = mr1k1_bend.bender_ds


with safe_load('mono energy scan devices'):
    from ophyd.signal import EpicsSignal
    from pcdsdevices.epics_motor import BeckhoffAxis
    mono_g_pi = BeckhoffAxis('SP1K1:MONO:MMS:G_PI', name='mono_g_pi')
    energy_request = EpicsSignal(
        'RIX:USER:MCC:EPHOTK:SET1',
        name='energy_request',
    )
    vernier_energy = energy_request


with safe_load('laser lens motors'):
    from pcdsdevices.epics_motor import SmarAct
    lm2k2_ejx_mp1_ls1_lm3 = SmarAct('LM2K2:EJX_MP1_LS1_LM3', name='lm2k2_ejx_mp1_ls1_lm3')
    lm2k2_ejx_mp1_ls1_lm2 = SmarAct('LM2K2:EJX_MP1_LS1_LM2', name='lm2k2_ejx_mp1_ls1_lm2')
    lm2k2_inj_mp1_att1_wp1 = SmarAct('LM2K2:INJ_MP1_ATT1_WP1', name='lm2k2_inj_mp1_att1_wp1')
    lm2k2_inj_mp1_att1_wp2 = SmarAct('LM2K2:INJ_MP1_ATT1_WP2', name='lm2k2_inj_mp1_att1_wp2')
    lm2k2_ejx_mp1_s41 = SmarAct('LM2K2:EJX_MP1_S41:M1', name='lm2k2_ejx_mp1_s41')


with safe_load('continous scan'):
    from rix.continuous_scan import continuous_scan

with safe_load('rix beamline script utilities'):
    from rix.rix_utilities import *

with safe_load('chemrixs script utilities'):
    from rix.chemrixs_utilities import *

with safe_load('qrixs script utilities'):
    from rix.qrixs_utilities import *

