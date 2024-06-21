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


with safe_load('lxt, txt, lxt_ttc, las_wp1, las_wp2'):
    from rix.lxt import lxt, txt, lxt_ttc, las_wp1, las_wp2, shift_t0, get_timing


with safe_load('CAM Recorder'):
    from rix.cam_to_file import h5_img_collect, ppm_scan

#with safe_load('mono_vernier_scan'):
#    from rix.vernier_scan import (mono_vernier_scan, calc_mono_ev,
#                                  scan_devices as vernier_scan_devices,
#                                  setup_scan_devices as _setup_scan_devices)
#    _setup_scan_devices()

with safe_load('mono energy_scan'):
    from rix.energy_scan import (energy_fly_scan, energy_fly_scan_step,
                                 energy_fly_scan_nd, energy_fly_scan_nd_list,
                                 energy_fly_scan_nd_grid,
                                 energy_fly_scan_nd_grid_list,
                                 energy_step_scan, energy_step_scan_nd,
                                 energy_list_scan, energy_list_scan_nd,
                                 energy_step_scan_nd_grid, energy_list_scan_nd_grid,
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

with safe_load('table_formatters'):
    from bluesky.callbacks.core import LiveTable

    def set_table_format(fmt: str):
        LiveTable._FMT_MAP["number"] = fmt

    def set_table_format_scientific():
        set_table_format("g")

    def set_table_format_basic():
        set_table_format("f")

with safe_load('qrix arm motion'):
    from pcdsdevices.epics_motor import BeckhoffAxis
    qrix_sc_ssl_mms = BeckhoffAxis('QRIX:SC:SSL:MMS', name='qrix_sc_ssl_mms')
    qrix_sa_mms_2theta = BeckhoffAxis('QRIX:SA:MMS:2Theta', name='qrix_sa_mms_2theta')
    qrix_df_mms_y1 = BeckhoffAxis('QRIX:DF:MMS:Y1', name='qrix_df_mms_y1')
    qrix_df_mms_y2 = BeckhoffAxis('QRIX:DF:MMS:Y2', name='qrix_df_mms_y2')
    qrix_df_mms_y3 = BeckhoffAxis('QRIX:DF:MMS:Y3', name='qrix_df_mms_y3')
    qrix_diff_mms_x = BeckhoffAxis('QRIX:DIFF:MMS:X', name='qrix_diff_mms_x')
    qrix_diff_mms_y = BeckhoffAxis('QRIX:DIFF:MMS:Y', name='qrix_diff_mms_y')
    qrix_diff_mms_z = BeckhoffAxis('QRIX:DIFF:MMS:Z', name='qrix_diff_mms_z')
    qrix_diff_mms_theta = BeckhoffAxis('QRIX:DIFF:MMS:THETA', name='qrix_diff_mms_theta')
    qrix_diff_mms_2theta = BeckhoffAxis('QRIX:DIFF:MMS:2THETA', name='qrix_diff_mms_2theta')
    qrix_diff_mms_dety = BeckhoffAxis('QRIX:DIFF:MMS:DETY', name='qrix_diff_mms_dety')
    qrix_diff_mms_phi = BeckhoffAxis('QRIX:DIFF:MMS:PHI', name='qrix_diff_mms_phi')
    qrix_diff_mms_chi = BeckhoffAxis('QRIX:DIFF:MMS:CHI', name='qrix_diff_mms_chi')
    qrix_da_mms_y1 = BeckhoffAxis('QRIX:DA:MMS:Y1', name='qrix_da_mms_y1')
    qrix_da_mms_y2 = BeckhoffAxis('QRIX:DA:MMS:Y2', name='qrix_da_mms_y2')
    qrix_da_mms_z = BeckhoffAxis('QRIX:DA:MMS:Z', name='qrix_da_mms_z')
    qrix_dc_mms_x = BeckhoffAxis('QRIX:DC:MMS:X', name='qrix_dc_mms_x')
    qrix_dc_mms_ry = BeckhoffAxis('QRIX:DC:MMS:Ry', name='qrix_dc_mms_ry')
    qrix_dc_mms_z = BeckhoffAxis('QRIX:DC:MMS:Z', name='qrix_dc_mms_z')
    qrix_det_mms_rot = BeckhoffAxis('QRIX:DET:MMS:ROT', name='qrix_det_mms_rot')
    qrix_opt_mms_y1 = BeckhoffAxis('QRIX:OPT:MMS:Y1', name='qrix_opt_mms_y1')
    qrix_opt_mms_y2 = BeckhoffAxis('QRIX:OPT:MMS:Y2', name='qrix_opt_mms_y2')
    qrix_opt_mms_y3 = BeckhoffAxis('QRIX:OPT:MMS:Y3', name='qrix_opt_mms_y3')
    qrix_g_mms_rx = BeckhoffAxis('QRIX:G:MMS:Rx', name='qrix_g_mms_rx')
    qrix_pm_mms_rz = BeckhoffAxis('QRIX:PM:MMS:Rz', name='qrix_pm_mms_rz')
    qrix_g_mms_x = BeckhoffAxis('QRIX:G:MMS:X', name='qrix_g_mms_x')
    qrix_pm_mms_x1 = BeckhoffAxis('QRIX:PM:MMS:X1', name='qrix_pm_mms_x1')
    qrix_pm_mms_x2 = BeckhoffAxis('QRIX:PM:MMS:X2', name='qrix_pm_mms_x2')
    qrix_cryo_mms_x = BeckhoffAxis('QRIX:CRYO:MMS:X', name='qrix_cryo_mms_x')
    qrix_cryo_mms_y = BeckhoffAxis('QRIX:CRYO:MMS:Y', name='qrix_cryo_mms_y')
    qrix_cryo_mms_z = BeckhoffAxis('QRIX:CRYO:MMS:Z', name='qrix_cryo_mms_z')
    qrix_cryo_mms_rot = BeckhoffAxis('QRIX:CRYO:MMS:ROT', name='qrix_cryo_mms_rot')
    qrix_las_mms_vis = BeckhoffAxis('QRIX:LAS:MMS:VIS', name='qrix_las_mms_vis')
    qrix_diag_mms_h = BeckhoffAxis('QRIX:DIAG:MMS:H', name='qrix_diag_mms_h')
    qrix_diag_mms_v = BeckhoffAxis('QRIX:DIAG:MMS:V', name='qrix_diag_mms_v')
    qrix_sds_mms_x = BeckhoffAxis('QRIX:SDS:MMS:X', name='qrix_sds_mms_x')
    qrix_sds_mms_y = BeckhoffAxis('QRIX:SDS:MMS:Y', name='qrix_sds_mms_y')
    qrix_sds_mms_z = BeckhoffAxis('QRIX:SDS:MMS:Z', name='qrix_sds_mms_z')
    qrix_sds_mms_rot_v = BeckhoffAxis('QRIX:SDS:MMS:ROT_V', name='qrix_sds_mms_rot_v')
    qrix_sds_mms_rot_h = BeckhoffAxis('QRIX:SDS:MMS:ROT_H', name='qrix_sds_mms_rot_h')
    qrix_sds_mms_h = BeckhoffAxis('QRIX:SDS:MMS:H', name='qrix_sds_mms_h')


