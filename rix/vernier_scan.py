from types import SimpleNamespace

from bluesky import preprocessors as bpp, plan_stubs as bps
from nabs import plans as nbp
from ophyd import Device, Component as Cpt, EpicsSignal, Signal
from pcdsdevices.epics_motor import BeckhoffAxis
from pcdsdevices.sim import SlowMotor
from rix.rix_daq_rework.DaqControl import DaqControl


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
        ev_bounds=None, urad_bounds=None, duration
        ):
    """
    Move the mono between two urad points for some duration in seconds.

    As the mono moves, continually put the interpolated eV position to the
    energy_req signal.

    This plan is not safe to inspect because it uses an ophyd subscription
    with a standalone put. This could be fixed by including the ophyd
    subscription as a custom run engine message, or by refactoring to
    include the energy_req subscription as part of the mono grating's stage
    and unstage.
    """
    # Get the PV values at the start from the config
    config.recalc()

    # Interpolate to pick the bounds that were not given
    if ev_bounds is None and urad_bounds is None:
        raise ValueError('Either ev_bounds or urad_bounds must be provided')
    elif urad_bounds is None:
        urad_bounds = [config.ev_to_urad(ev, recalc=False) for ev in ev_bounds]

    def update_vernier(value, **kwargs):
        energy_req.put(config.urad_to_ev(value, recalc=False))

    cbid = 0

    def sub_and_move():
        nonlocal cbid

        cbid = mono_grating.subscribe(update_vernier)
        return (
            yield from nbp.duration_scan(
                [],
                mono_grating, urad_bounds,
                duration=duration
                )
            )

    def cleanup_sub():
        yield from bps.null()
        mono_grating.unsubscribe(cbid)

    return (
        yield from bpp.finalize_wrapper(
            sub_and_move(),
            cleanup_sub(),
        )
    )


def daq_interpolation_mono_vernier_duration_scan(
        mono_grating, energy_req, config, *,
        ev_bounds=None, urad_bounds=None, duration
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
        print('Starting the DAQ')
        daq_control.setState('running')

        return (yield from interpolation_mono_vernier_duration_scan(
            mono_grating, energy_req, config,
            ev_bounds=ev_bounds, urad_bounds=urad_bounds,
            duration=duration,
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
        scan_devices.energy_req = EpicsSignal('RIX:USER:MCC:EPHOTK:VER', name='vernier_energy')
        scan_devices.config = MonoVernierConfig()


class FixSlowMotor(SlowMotor):
    def stop(self, success=True):
            super().stop()


def mono_vernier_scan(
    *, ev_bounds=None, urad_bounds=None, duration,
    fake_mono=False, fake_vernier=False, fake_daq=False,
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
    """
    setup_scan_devices()
    if fake_mono:
        mono_grating = FixSlowMotor(name='fake_mono')
    else:
        mono_grating = scan_devices.mono_grating
    if fake_vernier:
        vernier = Signal(name='fake_vernier')
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
        duration=duration
        )
    )
