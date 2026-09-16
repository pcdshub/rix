import bluesky.plans as bp
from pcdsdevices.beam_stats import BeamEnergyRequest, BeamEnergyRequestNoWait
from pcdsdevices.pseudopos import SyncAxis
from pcdsdevices.device import ObjectComponent as OCpt
from ophyd.device import FormattedComponent as FCpt
from ophyd.device import Component as Cpt
from ophyd.signal import EpicsSignal, EpicsSignalRO
from pcdsdevices.device import Device
from pcdsdevices.interface import BaseInterface
# from tmo.tmo_utils import log_positions as _log_positions

try:
    from rix.db import at2k2, at1k2
except ModuleNotFoundError:
    pass

import numpy as np

import time
import logging
logger = logging.getLogger(__name__)


hf_w = BeamEnergyRequest('RIX',name='hf_w',atol=0.05,skip_small_moves=False,pv_index=1)
hf_2w = BeamEnergyRequest('RIX',name='hf_2w',atol=0.05,skip_small_moves=False,pv_index=2)

hf_w_status = BeamEnergyRequest('RIX',name='hf_w',pv_index=1,acr_status_suffix='AO801')
hf_2w_status = BeamEnergyRequest('RIX',name='hf_2w',pv_index=2,acr_status_suffix='AO802')

class BeamEnergyRequestCheck(BeamEnergyRequestNoWait):
    tab_component_names = True
    tab_whitelist = ['pvname']
    
    target = FCpt(
        EpicsSignal,
        'SIOC:SYS0:ML07:{acr_target_suffix}',
        kind='normal',
        add_prefix=('suffix', 'write_pv', 'acr_target_suffix'),
        doc=(
            'Current target postions used to check if motor is ready to move.'
        )
    )
    
    done_moving = FCpt(
        EpicsSignal,
        'SIOC:SYS0:ML07:{acr_move_status_suffix}',
        kind='normal',
        add_prefix=('suffix', 'write_pv', 'acr_status_suffix'),
        doc=(
            'PV that is 0 while the motors are moving and 1 when ACR is '
            'ready for a new request. ACR can pick which of these PVs '
            'to use to report status.'
        )
    )
    
#    def _setup_move(self, position):
#        if abs(self.position-self.target.get()) > 0.1:
#            logger.debug('Motor has not reached target and a new move was issued')
#            while abs(self.position-self.target.get()) > 0.1:
#                time.sleep(0.1)
#        super()._setup_move(position)    
#        return
    
    def _check_move(self, position):
        if abs(position - self.target.get()) > 0.1:
            logger.debug('Last accepted (%s), is not updated to requested %s.' % (self.target.get(), position))
            if self.acr_move_status_suffix is None:
                logger.debug('No move status PV specified, checking target position')
                while abs(position - self.target.get()) > 0.1:
                    self.setpoint.put(position)
                    time.sleep(0.1)
                logger.debug('Setpoint set to %s' % position)
            else:
                logger.debug('Monitoring move status to wait for previous move to complete, current status:%s' % self.done_moving.get())
                while not self.done_moving.get():
                    time.sleep(0.05)
                logger.debug('Previous move complete moving to %s' % position)
                self.setpoint.put(position)
#        w_NoCheck = Cpt(BeamEnergyRequest, 'RIX', atol=0.1, skip_small_moves=False, pv_index=1, kind='omitted')
    def move(self, position, **kwargs):
        initial_setpoint = self.setpoint.get()
        logger.debug('current setpoint: %s, requested position: %s, last accepted position: %s, done moving: %s'
                     % (initial_setpoint, position, self.target.get(), self.done_moving.get()))
        result = super().move(position, **kwargs)
        if abs(initial_setpoint - position) > 0.1:
            logger.debug('waiting for move to start')
            while self.done_moving.get(): 
                time.sleep(0.01)
        self._check_move(position)
        return result
    
    @property
    def pvname(self):
        pv_dict = {
                 'setpoint': self.setpoint.pvname,
                      'ref': self.ref.pvname,
            'last accepted': self.target.pvname,
                   'status': self.done_moving.pvname
            
            }
        # _log_positions(pv_dict, log=False)
        
    
    def __init__(self, acr_target_suffix=None, acr_move_status_suffix=None, *args, **kwargs):
        self.acr_target_suffix = acr_target_suffix
        self.acr_move_status_suffix = acr_move_status_suffix
        super().__init__(*args, atol=0.1, skip_small_moves=False, **kwargs)

hf_w_check = BeamEnergyRequestCheck( prefix='RIX', name='hf_w', pv_index=1, acr_target_suffix='AO821', acr_move_status_suffix='AO801')
hf_2w_check = BeamEnergyRequestCheck( prefix='RIX', name='hf_2w', pv_index=2, acr_target_suffix='AO823', acr_move_status_suffix='AO802')
    
class HF_W2W(SyncAxis):
    hf_w = OCpt(hf_w_check)
    hf_2w = OCpt(hf_2w_check)
    tab_component_names = True
    scales = {'hf_w': 0.5, 'hf_2w':1}
    warn_deadband = 1E-2
    fix_sync_keep_still = 'hf_2w'
    sync_limits = (350, 2E3)

hf_w2w = HF_W2W('', name='hf_w2w')

class HF_W3W(SyncAxis):
    hf_w = OCpt(hf_w_check)
    hf_2w = OCpt(hf_2w_check)
    tab_component_names = True
    scales = {'hf_w': (1/3),'hf_2w':1}
    warn_deadband = 1E-2
    fix_sync_keep_still = 'hf_2w'
    sync_limits = (350, 2E3)

hf_w3w = HF_W3W('', name='hf_w3w')

class HF(BaseInterface, Device):
    """
    Photon Energy control PVs for RIX. 
    Attributes:
        w: Control of set1 PVs: RIX:USER:MCC:EPHOTK:SET1
        w2: Control of set2 PVs: RIX:USER:MCC:EPHOTK:SET2
        w2w: Combined mover for w/2w operation. The setpoint is controlled by set2 PV (RIX:USER:MCC:EPHOTK:SET2), set 1 PV is moved by half the requested amount.
        w_status: set1 PV control with movement readback from SIOC:SYS0:ML07:AO801
        w2_status: set2 PV control with movement readback from SIOC:SYS0:ML07:AO802
    """
    tab_component_names = True
       
    w = Cpt(BeamEnergyRequestCheck, prefix='RIX', pv_index=1, acr_target_suffix='AO821', acr_move_status_suffix='AO801')
#    w = Cpt(BeamEnergyRequest, 'RIX', atol=0.1, skip_small_moves=False, pv_index=1)
    w2 = Cpt(BeamEnergyRequestCheck, prefix='RIX', pv_index=2, acr_target_suffix='AO823', acr_move_status_suffix='AO802')
#    w2 = Cpt(BeamEnergyRequest, 'RIX', atol=0.1, skip_small_moves=False, pv_index=2)
    w2w = Cpt(HF_W2W, '')
    w_status = Cpt(BeamEnergyRequest, 'RIX', pv_index=1, acr_status_suffix='AO801')
    w2_status = Cpt(BeamEnergyRequest, 'RIX', pv_index=2, acr_status_suffix='AO802')
    w_NoCheck = Cpt(BeamEnergyRequest, 'RIX', atol=0.1, skip_small_moves=False, pv_index=1, kind='omitted')
    w2_NoCheck = Cpt(BeamEnergyRequest, 'RIX', atol=0.1, skip_small_moves=False, pv_index=2, kind='omitted')     
hf = HF(name='hf')

"""
class HF2(BaseInterface, Device):
    tab_component_names = True
       
    w = Cpt(BeamEnergyRequest, 'RIX', atol=0, skip_small_moves=False, pv_index=1)
    w2 = Cpt(BeamEnergyRequest, 'RIX', atol=0, skip_small_moves=False, pv_index=2)
    w2w = Cpt(SyncAxis, 
              w=Cpt(BeamEnergyRequest, 'RIX', atol=0, skip_small_moves=False, pv_index=1), 
              w2=Cpt(BeamEnergyRequest, 'RIX', atol=0, skip_small_moves=False, pv_index=2), 
              fix_sync_keep_still = 'w2', scales = {'w': 0.5}, 
              tab_component_names = True, warn_deadband = 1E-2, sync_limits = (350, 2E3))
    w_status = Cpt(BeamEnergyRequest, 'RIX', pv_index=1, acr_status_suffix='AO801')
    w2_status = Cpt(BeamEnergyRequest, 'RIX', pv_index=2, acr_status_suffix='AO802')
    
#    def __init__(self, prefix='', name='hf', **kwargs):
#        super().__init__(prefix=prefix, name=name, **kwargs)
#        self.w2w.w = self.w
#        self.w2w.w2 = self.w2
hf2 = HF2(name='hf2')
"""


#def pump_probe_scan(detectors, *args, snake_axes, per_step, md, ev_motor=hf.w, ev_start, ev_stop, ev_num, blade_num, filter_num):
 #   yield from bp.grid_scan(detectors, ev_motor, ev_start, ev_stop, ev_num, getattr(at2k2, f'blade_0{blade_num}').state, 1, filter_num + 2, 2, *args, snake_axes, per_step, md)


def pump_probe_scan(detectors, ev_start,
                    ev_stop,
                    ev_num,
                    filter_num,
                    ev_motor=hf_w,
                    blade_num=3,
                    snake_axes=True,
                    ref_per_step = True,
                    attenuator = 'at2k2'):
    #blade_motor = at2k2.blade_03
    if attenuator =='at2k2':
        blade_motor = getattr(at2k2, f'blade_0{blade_num}')
    elif attenuator =='at1k2':
        blade_motor = getattr(at1k2, f'blade_0{blade_num}')
    #blade velocity being None seems to mess things up sometimes?
    if hasattr(blade_motor.state, 'state_velo'):
        blade_motor.state.state_velo.kind = 'omitted'
    state_positions = [int(1), int(filter_num + 1)]
    ev_positions = list(np.linspace(ev_start,ev_stop,ev_num))
    if ref_per_step:
        # Take filter in filter out at each energy position
        yield from bp.list_grid_scan(detectors,
                                     ev_motor, ev_positions,
                                     blade_motor.state, state_positions,
                                     snake_axes)
    else:
        # Take filter in energy scan then filter out energy scan
        yield from bp.list_grid_scan(detectors,
                                     blade_motor.state, state_positions,
                                     ev_motor, ev_positions,  
                                     snake_axes)
