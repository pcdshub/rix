from pcdsdevices.device import ObjectComponent as OCpt
from pcdsdevices.lxe import Lcls2LaserTiming
from pcdsdevices.epics_motor import SmarAct
from pcdsdevices.pseudopos import SyncAxis, delay_instance_factory

from IPython import get_ipython


las_wp1 = SmarAct('LM2K2:INJ_MP1_ATT1_WP1', name='las_wp1')
las_wp2 = SmarAct('LM2K2:INJ_MP1_ATT1_WP2', name='las_wp2')

qrix_txt = delay_instance_factory('LM1K2:COM_MP2_DLY1', motor_class=SmarAct,
                                  egu='s', n_bounces=16, name='qrix_txt')
crix_txt = delay_instance_factory('LM2K2:COM_MP2_DLY1', motor_class=SmarAct,
                                  egu='s', n_bounces=16, name='crix_txt')

lxt_pvs = {2: 'LAS:LHN:LLG2:02', 3: 'LAS:LHN:LLG2:01'}
txts = {'qrix': qrix_txt, 'crix': crix_txt}

# defaults
global_instrument = 'qrix'

txt = txts[global_instrument]


def make_lxt_ttc(local_lxt, local_txt):
    print(local_lxt, local_txt)

    class LXTTTC(SyncAxis):
        lxt = OCpt(local_lxt)
        txt = OCpt(local_txt)
        tab_component_names = True
        scales = {'txt': 1}
        warn_deadband = 5e-14
        fix_sync_keep_still = 'lxt'
        sync_limits = (-10e-6, 10e-6)
    return LXTTTC('', name='lxt_ttc')


def update_lxt_ttc(update_global=True):
    global lxt, txt, lxt_ttc
    lxt_ttc = make_lxt_ttc(lxt, txt)
    if update_global:
        ip = get_ipython()
        if ip is not None:
            ip.user_global_ns['lxt_ttc'] = lxt_ttc
            ip.user_global_ns['a'].lxt_ttc = lxt_ttc
            ip.user_global_ns['m'].lxt_ttc = lxt_ttc
            ip.user_global_ns['m'].lxt_ttc_sync = lxt_ttc.sync
        

def set_lxt(bay: int):
    global lxt_pvs, lxt, global_instrument
    print(global_instrument)
    lxt = Lcls2LaserTiming(prefix=lxt_pvs[bay], name=f'bay{bay}_lxt', instrument=global_instrument)
    update_lxt_ttc(update_global=True)
    ip = get_ipython()
    if ip is not None:
        ip.user_global_ns['lxt'] = lxt
        ip.user_global_ns['a'].lxt = lxt
        ip.user_global_ns['m'].lxt = lxt
    return lxt
    

lxt_ttc = None
lxt = None
set_lxt(3)


def set_txt(instrument: str):
    instrument = instrument.lower()
    global txts, txt, global_instrument, lxt
    ip = get_ipython()
    ip.user_global_ns['txt'] = txts[instrument]
    ip.user_global_ns['a'].txt = txts[instrument]
    ip.user_global_ns['m'].txt = txts[instrument]
    ip.user_global_ns['m'].txt_delay = txts[instrument].delay
    ip.user_global_ns['m'].txt_motor = txts[instrument].motor
    txt = txts[instrument]
    global_instrument = instrument
    if lxt.name == 'bay2_lxt':
        set_lxt(2)
    elif lxt.name == 'bay3_lxt':
        set_lxt(3)


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
