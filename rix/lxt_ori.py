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
