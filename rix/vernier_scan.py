from types import SimpleNamespace
import threading
import time

import numpy as np

from bluesky import preprocessors as bpp, plan_stubs as bps
from nabs import plans as nbp
from ophyd import Device, Component as Cpt, EpicsSignal, EpicsSignalRO, Signal
from pcdsdevices.epics_motor import BeckhoffAxis
from pcdsdevices.sim import SlowMotor
#from rix.rix_daq_rework.DaqControl import DaqControl
from psdaq.control.DaqControl import DaqControl


class MonoVernierConfig(Device):
    low_ev = Cpt(EpicsSignal, 'RIX:VARS:FLOAT:01')
    high_ev = Cpt(EpicsSignal, 'RIX:VARS:FLOAT:02')
    low_urad = Cpt(EpicsSignal, 'RIX:VARS:FLOAT:03')
    high_urad = Cpt(EpicsSignal, 'RIX:VARS:FLOAT:04')

    ev_per_urad = 0
    ev_offset = 0
    urad_offset = 0

    def __init__(self,
        prefix='',
        name='rix_mono_vernier_scan_config',
        **kwargs):
        super().__init__(prefix, name=name, **kwargs)


    def recalc(self):
        self.ev_offset = self.low_ev.get()
        ev_diff = self.high_ev.get() - self.ev_offset
        self.urad_offset = self.low_urad.get()
        urad_diff = self.high_urad.get() - self.urad_offset
        try:
            self.ev_per_urad = ev_diff / urad_diff
        except ZeroDivisionError:
            self.ev_per_urad = 0

    def ev_to_urad(self, ev, recalc=True):
        if recalc:
            self.recalc()
        try:
            return (((ev - self.ev_offset) / self.ev_per_urad)
                    + self.urad_offset)
        except ZeroDivisionError:
            return 0

    def urad_to_ev(self, urad, recalc=True):
        if recalc:
            self.recalc()
        return (((urad - self.urad_offset) * self.ev_per_urad)
                + self.ev_offset)

class LocalConfig(MonoVernierConfig):
    low_ev = Cpt(Signal)
    high_ev = Cpt(Signal)
    low_urad = Cpt(Signal)
    high_urad = Cpt(Signal)


def interpolation_mono_vernier_duration_scan(
        mono_grating, energy_req, config, *,
        ev_bounds=None, urad_bounds=None, duration,
        num_steps=0, delay=0, record=True,
        ):
    """
    Move the mono between two urad points for some duration in seconds.

    As the mono moves, continually put the interpolated eV position to the
    energy_req signal.

    Starts from the point nearest to the current position.

    This plan is not safe to inspect because it uses an ophyd subscription
    with a standalone put. This could be fixed by including the ophyd
    subscription as a custom run engine message, or by refactoring to
    include the energy_req subscription as part of the mono grating's stage
    and unstage.

    The "record" argument is non-functional here, with the goal of giving us
    the same arguments as the daq version of the scan.
    """
    # Get the PV values at the start from the config
    config.recalc()

    # Interpolate to pick the bounds that were not given
    if ev_bounds is None and urad_bounds is None:
        raise ValueError('Either ev_bounds or urad_bounds must be provided')
    elif urad_bounds is None:
        urad_bounds = [config.ev_to_urad(ev, recalc=False) for ev in ev_bounds]

    if num_steps > 0:
        # Expand the urad_bounds to have extra steps between
        urad_bounds = np.linspace(urad_bounds[0], urad_bounds[1], num_steps + 2)
        # Add the middle steps in reverse order at the end
        urad_bounds = list(urad_bounds) + list(reversed(urad_bounds[1:-1]))
        # Find the nearest point to our current position
        start_point = mono_grating.position
        np_bounds = np.asarray(urad_bounds)
        idx = (np.abs(np_bounds - start_point)).argmin()
        # Shift the points to start the scan from right here
        urad_bounds = list(np.roll(np_bounds, -idx))

    # Set up some values for the vernier update
    setup_scan_devices()
    pre_mirror = scan_devices.pre_mirror_pos.get()

    def update_vernier(value, **kwargs):
        # This is the version that uses interpolation to update the vernier
        # energy_req.put(config.urad_to_ev(value, recalc=False))
        # This is the version that calculates using Alex Reid's calc
        energy_req.put(calc_mono_ev(grating=value, pre_mirror=pre_mirror))

    cbid = 0

    def sub_and_move():
        nonlocal cbid

        yield from bps.null()
        print('Moving to the start position')
        yield from bps.mv(mono_grating, urad_bounds[0])
        print('Starting Vernier putter')
        cbid = mono_grating.subscribe(update_vernier)
        mono_grating.settle_time = delay
        return (
            yield from nbp.duration_scan(
                [],
                mono_grating, urad_bounds,
                duration=duration
                )
            )

    def cleanup_sub():
        yield from bps.null()
        print('Cleaning up Vernier putter')
        mono_grating.unsubscribe(cbid)

    return (
        yield from bpp.finalize_wrapper(
            sub_and_move(),
            cleanup_sub(),
        )
    )


def daq_interpolation_mono_vernier_duration_scan(
    mono_grating, energy_req, config, *,
    ev_bounds=None, urad_bounds=None, duration,
    num_steps=0, delay=0, record=True,
):
    """
    Warning: this plan CANNOT be inspected!
    This should definitely be re-done to use a more bluesky-like
    interface so that we can inspect the plan!
    """

    daq_control = DaqControl(
        host='drp-neh-ctl001',
        platform=2,
        timeout=1000,
        )

    def daq_and_scan():
        yield from bps.null()
        state = daq_control.getState()
        if state != 'configured':
            raise RuntimeError(
                'DAQ must be in configured state to run vernier scan! '
                f'Currently in {state} state.'
                )
        print(f'Setting DAQ record to {record}')
        daq_control.setRecord(record)
        print('Starting the DAQ')
        daq_control.setState('running')

        return (yield from interpolation_mono_vernier_duration_scan(
            mono_grating, energy_req, config,
            ev_bounds=ev_bounds, urad_bounds=urad_bounds,
            duration=duration, num_steps=num_steps, delay=delay,
            )
        )

    def stop_daq():
        yield from bps.null()
        if daq_control.getState() in ('starting', 'paused', 'running'):
            print('Stopping the DAQ')
            daq_control.setState('configured')

    return (
        yield from bpp.finalize_wrapper(
            daq_and_scan(),
            stop_daq(),
        )
    )


scan_devices = SimpleNamespace()


def setup_scan_devices():
    if not scan_devices.__dict__:
        scan_devices.mono_grating = BeckhoffAxis('SP1K1:MONO:MMS:G_PI', name='mono_g_pi')
        #scan_devices.energy_req = EpicsSignal('RIX:USER:MCC:EPHOTK:VER', name='vernier_energy')
        #8:30PM 5/26/2021 Alberto says he's listening to EPHOTK not EPHOTK:VER
        scan_devices.energy_req = EpicsSignal('RIX:USER:MCC:EPHOTK:SET1', name='vernier_energy')
        scan_devices.config = MonoVernierConfig()
        scan_devices.acr_ephot_ref = EpicsSignal('RIX:USER:MCC:EPHOTK:REF1', name='acr_ref')
        scan_devices.energy_calc = EpicsSignalRO('SP1K1:MONO:CALC:ENERGY')
        scan_devices.pre_mirror_pos = EpicsSignalRO('SP1K1:MONO:MMS:M_PI.RBV')


def calc_mono_ev(grating=None, pre_mirror=None):
    setup_scan_devices()
    if grating is None:
        grating = scan_devices.mono_grating.position
    if pre_mirror is None:
        pre_mirror = scan_devices.pre_mirror_pos.get()

    # Calculation copied from Alex Reid's email with minimal edits

    # Constants:
    D = 5e4 # ruling density in lines per meter
    c = 299792458 # speed of light
    h = 6.62607015E-34 # Plank's const
    el = 1.602176634E-19 # elemental charge
    b = 0.03662 # beam from MR1K1 design value in radians
    ex = 0.1221413 # exit trajectory design value in radians

    # Inputs:
    # grating pitch remove offset and convert to rad
    g = (grating - 63358)/1e6
    # pre mirror pitch remove offset and convert to rad
    p = (pre_mirror - 90641)/1e6

    # Calculation
    alpha = np.pi/2 - g + 2*p - b
    beta = np.pi/2 + g - ex
    # Energy in eV
    return h*c*D/(el*(np.sin(alpha)-np.sin(beta)))

def calc_grating_pitch(energy=None, pre_mirror=None):
    setup_scan_devices()
    if energy is None:
        energy = scan_devices.energy_calc.get()
    if pre_mirror is None:
        pre_mirror = scan_devices.pre_mirror_pos.get()

    # Calculates grating pitch [urad] from energy [eV]

    # constants
    eVmm = 0.001239842 # Wavelenght[mm] = eVmm/Energy[eV]
    m = 1 # diffraction order
    D0 = 50.0 # 1/mm
    thetaM1 = 0.03662 # rad
    thetaES = 0.1221413 # rad
    offsetM2 = 90641.0e-6 # rad
    offsetG = 63358.0e-6 # rad

    pM2 = pre_mirror*1e-6 - offsetM2
    a0 = m*D0*eVmm/energy
    pG = pM2 - 0.5*thetaM1 + 0.5*thetaES  - np.arcsin(0.5*a0/np.cos(0.5*np.pi+pM2-0.5*thetaM1-0.5*thetaES))

    #Grating pitch in urad
    return (pG + offsetG)*1e6

class FixSlowMotor(SlowMotor):
    def _setup_move(self, position, status):
        if self.position is None:
            # Initialize position during __init__'s set call
            self._set_position(position)
            self._done_moving(success=True)
            return
        elif position == self.position:
            self._done_moving(success=True)
            return

        def update_thread(positioner, goal):
            positioner._moving = True
            while positioner.position != goal and not self._stop:
                if goal - positioner.position > 1:
                    positioner._set_position(positioner.position + 1)
                elif goal - positioner.position < -1:
                    positioner._set_position(positioner.position - 1)
                else:
                    positioner._set_position(goal)
                    positioner._done_moving(success=True)
                    return
                time.sleep(0.1)
            positioner._done_moving(success=False)
        self.stop()
        self._started_moving = True
        self._stop = False
        t = threading.Thread(target=update_thread,
                             args=(self, position))
        t.start()

    def stop(self, success=True):
        super().stop()


def mono_vernier_scan(
    *, ev_bounds=None, urad_bounds=None, duration, num_steps=0, delay=0,
    fake_mono=False, fake_vernier=False, fake_daq=False, record=True,
    ):
    """
    WARNING: this scan CANNOT be safely inspected! Only pass into RE!

    Parameters
    ----------
    ev_bounds: list of numbers, keyword-only
        Upper and lower bounds of the scan in ev.
        Provide either ev_bounds or urad_bounds, but not both.

    urad_bounds: list of numbers, keyword-only
        Upper and lower bounds of the scan in mono grating urad.
        Provide either ev_bounds or urad_bounds, but not both.

    duration: number, required keyword-only
        Duration of the scan in seconds.

    num_steps: integer, optional
        Number of evenly-spaced extra steps to include between the endpoints.
        These are places where the mono motor will stop before proceeding to
        the next point.

    delay: number, optional
        Amount of time to wait at each step in seconds.

    record: bool, optional
        Whether or not to record the data in the daq. Default is "True".
    """
    setup_scan_devices()
    if fake_mono:
        if urad_bounds is not None:
            start_pos = urad_bounds[0]
        else:
            start_pos = scan_devices.config.ev_to_urad(ev_bounds[0])
        mono_grating = FixSlowMotor(name='fake_mono', init_pos=start_pos-5)
    else:
        mono_grating = scan_devices.mono_grating
    if fake_vernier:
        vernier = Signal(name='fake_vernier')
        def loud_fake(value, **kwargs):
            print(f'Fake vernier set to {value}')
        vernier.subscribe(loud_fake)
    else:
        vernier = scan_devices.energy_req
    if fake_daq:
        inner_scan = interpolation_mono_vernier_duration_scan
    else:
        inner_scan = daq_interpolation_mono_vernier_duration_scan
    return (yield from inner_scan(
        mono_grating,
        vernier,
        scan_devices.config,
        ev_bounds=ev_bounds,
        urad_bounds=urad_bounds,
        duration=duration,
        num_steps=num_steps,
        delay=delay,
        record=record,
        )
    )
