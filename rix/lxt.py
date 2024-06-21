from pcdsdevices.device import ObjectComponent as OCpt
from pcdsdevices.lxe import LaserTiming, TimeToolDelay
from pcdsdevices.lxe import Lcls2LaserTiming
from pcdsdevices.epics_motor import SmarAct
from pcdsdevices.pseudopos import SyncAxis, delay_instance_factory
import pandas as pd


##lxt = LaserTiming('LAS:FS11', name='lxt')
#lxt = LaserTiming('LAS:FS14', name='lxt')
lxt = Lcls2LaserTiming('LAS:LHN:LLG2:01', name='lxt') #this is for lcls2
txt = delay_instance_factory('LM2K2:COM_MP2_DLY1', motor_class=SmarAct,
                             egu='s', n_bounces=16, name='txt')

las_wp1 = SmarAct('LM2K2:INJ_MP1_ATT1_WP1', name='las_wp1')
las_wp2 = SmarAct('LM2K2:INJ_MP1_ATT1_WP2', name='las_wp2')

class LXTTTC(SyncAxis):
    lxt = OCpt(lxt)
    txt = OCpt(txt)
    tab_component_names = True
    scales = {'txt': 1}
    warn_deadband = 5e-14
    fix_sync_keep_still = 'lxt'
    sync_limits = (-10e-6, 10e-6)

lxt_ttc = LXTTTC('', name='lxt_ttc')

def shift_t0(shift):
        """
        this function zeros lxt_ttc and shifts lxt by the amount passed (in seconds). 
        """
        lxt_ttc.mv(0)
        lxt.mvr(shift)
        lxt_ttc.set_current_position(0)
        txt_position = txt.get()[2][0]
        msg = "moved lxt offset by " + str(shift*1E12) + "ps to compensate for drift. Current position of txt for lxt_ttc=0: " + str(txt_position)
        elog.post(msg, tags='fs_timing')
        return txt_position

def get_timing(log=False, msg=None, **kwargs):
    """
    Get current positions of laser timing variables.
    log - boolean to log the positions in the elog 
    msg - optional argument to append a message to the elog with the KB positions 
    """
    curr_positions= {
            "lxt pos [ps]":lxt.wm()*1e12,
            "txt pos [ps]":txt.wm()*1e12,
        "lxt_ttc pos [ps]":lxt_ttc.wm()*1e12,
         "lxt offset [ns]":lxt.get()[3]*1e9,
    "lxt total delay [ns]":(lxt.get()[3] - lxt.get()[0]) * 1e9,
     "txt user stage [mm]":txt.get()[2][0],
    }
    kwargs['tags'] = kwargs.get('tags', ' ') + ' fs_timing'
    _log_positions(curr_positions, log, msg=msg, **kwargs)
