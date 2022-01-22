from __future__ import annotations

import logging
import threading
import time
from functools import partial
from types import SimpleNamespace
from typing import Any, Callable, Generator, Iterable, Optional, Union

import numpy as np
from bluesky import plan_stubs as bps
from bluesky import plans as bp
from bluesky import preprocessors as bpp
from bluesky.utils import Msg
from nabs import plans as nbp
from ophyd import EpicsSignalRO, Signal
from ophyd.ophydobj import OphydObject
from ophyd.status import Status
from pcdsdevices.beam_stats import BeamEnergyRequest
from pcdsdevices.epics_motor import BeckhoffAxis
from pcdsdevices.sim import FastMotor, SlowMotor
from psdaq.control.DaqControl import DaqControl

from rix.chemrixs import calc_pitch

logger = logging.getLogger(__name__)
PlanType = Generator[Msg, Any, Any]


# 1D Scans (move back and forth for duration seconds)

def energy_scan(
    *,
    ev_bounds: Optional[list[float]] = None,
    urad_bounds: Optional[list[float]] = None,
    duration: float,
    grating_speed: float = 0.5,
    record: bool = True,
    fake_grating: bool = False,
    fake_pre_mirror: bool = False,
    fake_acr: bool = False,
    fake_daq: bool = False,
    fake_all: bool = False,
) -> PlanType:
    """
    Fly scan of the grating mono coordinated with an ACR energy request.

    The energy request may be a vernier move or it may be an undulator move.
    The energy request will track the the grating movement.

    The various "fake" arguments run test scans without the associated
    real hardware:
    - fake_grating: do not move the mono grating pitch
    - fake_pre_mirror: do not each the real pre mirror PV for the calcs
    - fake_acr: do not ask acr to change the energy, instead print it
    - fake_daq: do not run the daq
    - fake_all: do everything fake!

    This is a thin wrapper around energy_scan_step, simplifying the arguments
    for the case where we want to do a fly scan.

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

    grating_speed: number, optional
        Speed of the grating in urad/sec. This will be applied before
        starting the scan.

    record: bool, optional
        Whether or not to record the data in the daq. Default is "True".
    """
    return (
        yield from (
            energy_scan_step(
                ev_bounds=ev_bounds,
                urad_bounds=urad_bounds,
                duration=duration,
                grating_speed=grating_speed,
                num_steps=0,
                delay=0,
                record=record,
                fake_grating=fake_grating,
                fake_pre_mirror=fake_pre_mirror,
                fake_acr=fake_acr,
                fake_daq=fake_daq,
                fake_all=fake_all,
            )
        )
    )


def energy_scan_step(
    *,
    ev_bounds: Optional[list[float]] = None,
    urad_bounds: Optional[list[float]] = None,
    duration: float,
    grating_speed: float = 20.0,
    num_steps: int = 0,
    delay: float = 0.0,
    record: bool = True,
    fake_grating: bool = False,
    fake_pre_mirror: bool = False,
    fake_acr: bool = False,
    fake_daq: bool = False,
    fake_all: bool = False,
) -> PlanType:
    """
    Step scan of the grating mono coordinated with an ACR energy request.

    The energy request may be a vernier move or it may be an undulator move.
    The energy request will track the the grating movement.

    The various "fake" arguments run test scans without the associated
    real hardware.

    This is a thin wrapper around mono_energy_duration_scan, serving to
    automatically select the correct hardware objects.

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

    grating_speed: number, optional
        Speed of the grating in urad/sec. This will be applied before
        starting the scan.

    record: bool, optional
        Whether or not to record the data in the daq. Default is "True".
    """
    if fake_all:
        fake_grating = True
        fake_pre_mirror = True
        fake_acr = True
        fake_daq = True

    mono_grating, sim_kw = get_scan_hw(
        ev_bounds=ev_bounds,
        urad_bounds=urad_bounds,
        fake_grating=fake_grating,
        fake_pre_mirror=fake_pre_mirror,
        fake_acr=fake_acr,
    )

    plan = mono_energy_duration_scan(
        mono_grating,
        ev_bounds=ev_bounds,
        urad_bounds=urad_bounds,
        duration=duration,
        num_steps=num_steps,
        delay=delay,
        grating_speed=grating_speed,
        **sim_kw
    )
    if not fake_daq:
        plan = daq_helper_wrapper(
            plan,
            record=record,
        )
    return (yield from plan)


def mono_energy_duration_scan(
    mono_grating: BeckhoffAxis,
    *,
    ev_bounds: Optional[list[float]] = None,
    urad_bounds: Optional[list[float]] = None,
    duration: float,
    grating_speed: float = 0.5,
    num_steps: int = 0,
    delay: float = 0.0,
    **kwargs,
) -> PlanType:
    """
    Move the mono between two urad points for some duration in seconds.

    As the mono moves, continually put the interpolated eV position to the
    energy_req signal.

    Starts from the point nearest to the current position.

    **kwargs are passed through to energy_request_wrapper to instantiate the
    EnergyRequestHandler. The defaults should be sufficient, but this is
    useful for simulation and testing.

    This is separate from the titular "energy_scan" to make it easier to test.
    """
    urad_bounds = calculate_bounds(
        ev_bounds=ev_bounds,
        urad_bounds=urad_bounds,
        **kwargs
    )

    if num_steps > 0:
        # Expand the urad_bounds to have extra steps between
        urad_bounds = np.linspace(
            urad_bounds[0], urad_bounds[1], num_steps + 2
        )
        # Add the middle steps in reverse order at the end
        urad_bounds = list(urad_bounds) + list(reversed(urad_bounds[1:-1]))
        # Find the nearest point to our current position
        start_point = mono_grating.position
        np_bounds = np.asarray(urad_bounds)
        idx = (np.abs(np_bounds - start_point)).argmin()
        # Shift the points to start the scan from right here
        urad_bounds = list(np.roll(np_bounds, -idx))

    yield from energy_scan_setup(
        mono_grating=mono_grating,
        urad_bounds=urad_bounds,
        grating_speed=grating_speed,
        delay=delay,
    )

    return (
        yield from energy_request_wrapper(
            nbp.duration_scan(
                [],
                mono_grating,
                urad_bounds,
                duration=duration,
            ),
            **kwargs,
        )
    )


# ND scans (scan a motor or n motors, do 1 energy sweep at each step)

def energy_scan_nd(
    *args,
    num: Optional[int] = None,
    ev_bounds: Optional[list[float]] = None,
    urad_bounds: Optional[list[float]] = None,
    grating_speed: float = 0.5,
    record: bool = True,
    fake_grating: bool = False,
    fake_pre_mirror: bool = False,
    fake_acr: bool = False,
    fake_daq: bool = False,
    fake_all: bool = False,
) -> PlanType:
    """
    A multi-dimensional start, stop, number of points energy scan.

    This will start the daq and execute a scan where at every step
    we do one back-and-forth sweep of the mono energy, synchronized
    with energy changes from ACR.

    *args should be triplets of (motor, start, stop)
    Where we move every motor through its trajectory at the same time.
    num is the number of steps and must be provided, either as the
    final positional argument or explicitly as the kwarg.

    The rest of the arguments are used as in the standard energy_scan.
    """
    yield from _generic_nd_scan(
        specific_plan=partial(
            bp.scan,
            [],
            *args,
            num=num,
        ),
        ev_bounds=ev_bounds,
        urad_bounds=urad_bounds,
        grating_speed=grating_speed,
        record=record,
        fake_grating=fake_grating,
        fake_pre_mirror=fake_pre_mirror,
        fake_acr=fake_acr,
        fake_daq=fake_daq,
        fake_all=fake_all,
    )


def energy_scan_nd_relative(
    *args,
    num: Optional[int] = None,
    ev_bounds: Optional[list[float]] = None,
    urad_bounds: Optional[list[float]] = None,
    grating_speed: float = 0.5,
    record: bool = True,
    fake_grating: bool = False,
    fake_pre_mirror: bool = False,
    fake_acr: bool = False,
    fake_daq: bool = False,
    fake_all: bool = False,
) -> PlanType:
    """
    A multi-dimensional start, stop, number of points energy relative scan.

    This is often also called a "dscan".

    This will start the daq and execute a scan where at every step
    we do one back-and-forth sweep of the mono energy, synchronized
    with energy changes from ACR.

    *args should be triplets of (motor, relative_start, relative_stop)
    Where we move every motor through its trajectory at the same time.
    Here, "relative" means relative to the initial position of the motor,
    e.g. 0 is "where we started" and 10 is "10 greater than where we started."
    num is the number of steps and must be provided, either as the
    final positional argument or explicitly as the kwarg.

    The rest of the arguments are used as in the standard energy_scan.
    """
    yield from _generic_nd_scan(
        specific_plan=partial(
            bp.relative_scan,
            [],
            *args,
            num=num,
        ),
        ev_bounds=ev_bounds,
        urad_bounds=urad_bounds,
        grating_speed=grating_speed,
        record=record,
        fake_grating=fake_grating,
        fake_pre_mirror=fake_pre_mirror,
        fake_acr=fake_acr,
        fake_daq=fake_daq,
        fake_all=fake_all,
    )


def energy_scan_nd_list(
    *args,
    ev_bounds: Optional[list[float]] = None,
    urad_bounds: Optional[list[float]] = None,
    grating_speed: float = 0.5,
    record: bool = True,
    fake_grating: bool = False,
    fake_pre_mirror: bool = False,
    fake_acr: bool = False,
    fake_daq: bool = False,
    fake_all: bool = False,
) -> PlanType:
    """
    A multi-dimensional list of points energy scan.

    This will start the daq and execute a scan where at every step
    we do one back-and-forth sweep of the mono energy, synchronized
    with energy changes from ACR.

    *args should be pairs of (motor, list)
    Where we move every motor through its trajectory at the same time.

    The rest of the arguments are used as in the standard energy_scan.
    """
    yield from _generic_nd_scan(
        specific_plan=partial(
            bp.list_scan,
            [],
            *args,
        ),
        ev_bounds=ev_bounds,
        urad_bounds=urad_bounds,
        grating_speed=grating_speed,
        record=record,
        fake_grating=fake_grating,
        fake_pre_mirror=fake_pre_mirror,
        fake_acr=fake_acr,
        fake_daq=fake_daq,
        fake_all=fake_all,
    )


def energy_scan_nd_grid(
    *args,
    snake_axes: Optional[bool] = None,
    ev_bounds: Optional[list[float]] = None,
    urad_bounds: Optional[list[float]] = None,
    grating_speed: float = 0.5,
    record: bool = True,
    fake_grating: bool = False,
    fake_pre_mirror: bool = False,
    fake_acr: bool = False,
    fake_daq: bool = False,
    fake_all: bool = False,
) -> PlanType:
    """
    A multi-dimensional grid of start, stop, num points energy scan.

    This will start the daq and execute a scan where at every step
    we do one back-and-forth sweep of the mono energy, synchronized
    with energy changes from ACR.

    *args should be quads of (motor, start, stop, num),
    where we move the motors through an ND mesh of these points.
    The first motor is the slowest (the outer loop).
    If snake_axes is True, then we'll move back and forth through each
    motor's trajectory rather than resetting to the first position and
    always moving forward through the trajectory.

    The rest of the arguments are used as in the standard energy_scan.
    """
    yield from _generic_nd_scan(
        specific_plan=partial(
            bp.grid_scan,
            [],
            *args,
            snake_axes=snake_axes,
        ),
        ev_bounds=ev_bounds,
        urad_bounds=urad_bounds,
        grating_speed=grating_speed,
        record=record,
        fake_grating=fake_grating,
        fake_pre_mirror=fake_pre_mirror,
        fake_acr=fake_acr,
        fake_daq=fake_daq,
        fake_all=fake_all,
    )


def energy_scan_nd_grid_list(
    *args,
    snake_axes: Optional[bool] = None,
    ev_bounds: Optional[list[float]] = None,
    urad_bounds: Optional[list[float]] = None,
    grating_speed: float = 0.5,
    record: bool = True,
    fake_grating: bool = False,
    fake_pre_mirror: bool = False,
    fake_acr: bool = False,
    fake_daq: bool = False,
    fake_all: bool = False,
) -> PlanType:
    """
    A multi-dimensional grid of lists of points energy scan.

    This will start the daq and execute a scan where at every step
    we do one back-and-forth sweep of the mono energy, synchronized
    with energy changes from ACR.

    *args should be pairs of (motor, list),
    where we move the motors through an ND mesh of these points.
    The first motor is the slowest (the outer loop).
    If snake_axes is True, then we'll move back and forth through each
    motor's trajectory rather than resetting to the first position and
    always moving forward through the trajectory.

    The rest of the arguments are used as in the standard energy_scan.
    """
    yield from _generic_nd_scan(
        specific_plan=partial(
            bp.list_grid_scan,
            [],
            *args,
            snake_axes=snake_axes,
        ),
        ev_bounds=ev_bounds,
        urad_bounds=urad_bounds,
        grating_speed=grating_speed,
        record=record,
        fake_grating=fake_grating,
        fake_pre_mirror=fake_pre_mirror,
        fake_acr=fake_acr,
        fake_daq=fake_daq,
        fake_all=fake_all,
    )


def _generic_nd_scan(
    specific_plan: PlanType,
    ev_bounds: Optional[list[float]] = None,
    urad_bounds: Optional[list[float]] = None,
    grating_speed: float = 0.5,
    record: bool = True,
    fake_grating: bool = False,
    fake_pre_mirror: bool = False,
    fake_acr: bool = False,
    fake_daq: bool = False,
    fake_all: bool = False,
) -> PlanType:
    """
    Generic plan composer for the multi-dimensional energy scans.

    This handles everything except for the specifics of the
    multi-motor trajectory.

    It expects "specific_plan" to be a partially-argumented plan
    that only needs an additional "per_step" kwarg to complete it.

    This plan does the common setup/teardown for all of these
    multi-dimensional plans, as well as making sure that we do
    one full sweep of the energy range at each scan step by using
    _energy_per_step.
    """
    if fake_all:
        fake_grating = True
        fake_pre_mirror = True
        fake_acr = True
        fake_daq = True

    mono_grating, sim_kw = get_scan_hw(
        ev_bounds=ev_bounds,
        urad_bounds=urad_bounds,
        fake_grating=fake_grating,
        fake_pre_mirror=fake_pre_mirror,
        fake_acr=fake_acr,
    )

    urad_bounds = calculate_bounds(
        ev_bounds=ev_bounds,
        urad_bounds=urad_bounds,
        **sim_kw
    )

    inner = energy_request_wrapper(
        specific_plan(
            per_step=_energy_per_step(
                mono_grating=mono_grating,
                urad_bounds=urad_bounds,
            )
        ),
        **sim_kw
    )

    if not fake_daq:
        inner = daq_helper_wrapper(
            inner,
            record=record,
        )

    # Yields are where the scan runs
    # Do these all last so we can check all args before any motion
    yield from energy_scan_setup(
        mono_grating=mono_grating,
        urad_bounds=urad_bounds,
        grating_speed=grating_speed,
        delay=0,
    )

    return (yield from inner)


def _energy_per_step(
    *,
    mono_grating: BeckhoffAxis,
    urad_bounds: list[float, float],
) -> Callable[[Iterable, dict, dict], PlanType]:
    """
    A per_step hook for including an energy scan inside of another scan.

    We will move the grating from end-to-end at every step of the
    containing scan.

    Bluesky plans often include a "per_step" argument, which is used to
    redefine what exactly we do at each step.

    This lets us do an entire energy_scan at each step of another scan.

    For example, we could use this to step through one or more motor
    positions, and at each position do a fly scan through the
    energy range.
    """
    def inner(detectors, step, pos_cache):
        """
        detectors: a list of readables from the outer plan
        step: dict of all the motor moves from this step
        pos_cache: dict of all motors to their last-set positions
        """
        # Standard building block: move all the motors, read everything
        # This makes the scan position appear in the text table
        # And potentially also in a plot
        yield from bps.one_nd_step(detectors, step, pos_cache)
        # Variations on the normal full scan:
        # - We only need to set up once, don't do that every step
        # - We want to go end-to-end once, not for a duration
        # - We don't need to do any reads at the ends
        yield from bps.mv(mono_grating, urad_bounds[1])
        yield from bps.mv(mono_grating, urad_bounds[0])
    return inner


def calculate_bounds(
    ev_bounds: Optional[list[float]] = None,
    urad_bounds: Optional[list[float]] = None,
    **kwargs
) -> list[float]:
    """
    Get the urad_bounds if the user supplied ev_bounds.
    """
    if ev_bounds is None and urad_bounds is None:
        raise ValueError('Either ev_bounds or urad_bounds must be provided')
    # Calculate what urad should be if ev was given
    elif urad_bounds is None:
        if 'pre_mirror_pos' in kwargs:
            pos = kwargs['pre_mirror_pos'].get()
            urad_bounds = [calc_pitch(ev, pos)[0] for ev in ev_bounds]
        else:
            urad_bounds = [calc_pitch(ev)[0] for ev in ev_bounds]
    return urad_bounds


def get_scan_hw(
    urad_bounds: Optional[list[float]] = None,
    ev_bounds: Optional[list[float]] = None,
    fake_grating: bool = False,
    fake_pre_mirror: bool = False,
    fake_acr: bool = False,
) -> tuple[BeckhoffAxis, dict]:
    """
    Helper function for picking the hardware and kwargs.

    This is to centralize the selection of real/fake hardware
    as it is needed in multiple places.
    """
    # Modifiers for sim/test/fake scans
    sim_kw = {}
    if fake_grating:
        # Initialize a fake grating motor
        if urad_bounds is not None:
            start_pos = urad_bounds[0]
        elif fake_pre_mirror:
            start_pos = calc_pitch(ev_bounds[0], 143253)[0]
        else:
            start_pos = calc_pitch(ev_bounds[0])[0]
        mono_grating = FixSlowMotor(name='fake_mono', init_pos=start_pos-5)
        sim_kw['grating_pos'] = mono_grating
    else:
        # Create the mono grating object if first time
        setup_scan_devices()
        mono_grating = scan_devices.mono_grating
    if fake_pre_mirror:
        sim_kw['pre_mirror_pos'] = Signal(
            name='fake_pre_mirror_pos',
            value=143253,  # live value on the day I made this
        )
    if fake_acr:
        request = FastMotor(name='fake_request')
        last_print = 0
        loud_lock = threading.Lock()

        def loud_fake(value, **kwargs):
            nonlocal last_print
            with loud_lock:
                now = time.monotonic()
                if now - last_print > 1:
                    print(f'Fake request for {value} eV')
                    last_print = now

        request.subscribe(loud_fake)
        sim_kw['request_pos'] = request
    return mono_grating, sim_kw


def energy_scan_setup(
    mono_grating: BeckhoffAxis,
    *,
    urad_bounds: list[float],
    grating_speed: float = 0.5,
    delay: float = 0.0,
) -> PlanType:
    """
    Re-usable setup steps before the main scan
    """
    # Separate from the main scan with empty null plan
    # Prevents the prints/logs from coming early
    yield from bps.null()
    # Set the settings, bluesky-style
    logger.info('Setting grating speed: %s', grating_speed)
    yield from bps.abs_set(mono_grating.velocity, grating_speed, wait=True)
    logger.info('Setting step delay to %s', delay)
    yield from bps.abs_set(SettleProxy(mono_grating), delay)
    logger.info('Moving to the start position: %s', urad_bounds[0])
    yield from bps.mv(mono_grating, urad_bounds[0])


class EnergyRequestHandler:
    """
    Utility class for requesting energy changes during a scan.

    After calling "start_requests", this will send energy requests to ACR
    every time the grating pitch moves. This will continue until a call to
    "stop_requests".

    It is up to ACR to determine how to handle these requests, with
    some coordinated agreement between the operators and the instrument.

    This could also be used outside of a scan.
    """
    def __init__(
        self,
        grating_pos: Union[str, OphydObject] = "SP1K1:MONO:MMS:G_PI.RBV",
        pre_mirror_pos: Union[str, Signal] = "SP1K1:MONO:MMS:M_PI.RBV",
        request_pos: Optional[Signal] = None,
        **kwargs,
    ):
        """
        Note: kwargs can be used to adjust the move tolerance
        (default atol=5 => only ask for a move if eV change >5)
        """
        if isinstance(grating_pos, OphydObject):
            self.grating_sig = grating_pos
        elif isinstance(grating_pos, str):
            self.grating_sig = EpicsSignalRO(grating_pos)
        else:
            raise TypeError(f"Invalid grating_pos={grating_pos}")
        if isinstance(pre_mirror_pos, Signal):
            self.pre_mirror_sig = pre_mirror_pos
        elif isinstance(pre_mirror_pos, str):
            self.pre_mirror_sig = EpicsSignalRO(pre_mirror_pos)
        else:
            raise TypeError(f"Invalid pre_mirror_pos={pre_mirror_pos}")
        if request_pos is None:
            self.request = BeamEnergyRequest(
                "RIX",
                name="energy_request",
                **kwargs,
            )
        else:
            self.request = request_pos
        self.cbid = None
        self.parent = None

    def start_requests(self) -> None:
        """
        Schedule an energy request every time the grating moves.
        """
        logger.info("Starting Energy Requester")
        self.stop_requests()
        self.cbid = self.grating_sig.subscribe(self.update_energy)

    def stop_requests(self) -> None:
        """
        End the previous energy request handling.
        """
        if self.cbid is not None:
            logger.info("Stopping Energy Requester")
            self.grating_sig.unsubscribe(self.cbid)
            self.cbid = None

    def update_energy(self, value: float, **kwargs) -> None:
        """
        Automatically called to send a beam request when the mirror moves.
        """
        calc = calc_mono_ev(
            grating=value,
            pre_mirror=self.pre_mirror_sig.get(),
        )
        self.request.move(calc, wait=False)

    def stage(self) -> list[EnergyRequestHandler]:
        """
        During a scan, this starts up the energy request callback.

        Signature and return value mandated by bluesky.
        """
        self.start_requests()
        return [self]

    def unstage(self) -> list[EnergyRequestHandler]:
        """
        During a scan, this stops the energy request callback.

        Signature and return value mandated by bluesky.
        """
        self.stop_requests()
        return [self]


# Utility for including the EnergyRequestHandler in a plan
def energy_request_wrapper(plan: PlanType, **kwargs) -> PlanType:
    request_handler = EnergyRequestHandler(**kwargs)
    return (yield from bpp.stage_wrapper(plan, [request_handler]))


class DaqHelper:
    """
    Basic object to start/stop the DAQ in the fly scan
    """
    def __init__(
        self,
        host: str = 'drp-neh-ctl001',
        platform: int = 2,
        timeout: int = 1000,
        record: Optional[bool] = None,
    ):
        self.control = DaqControl(
            host=host,
            platform=platform,
            timeout=timeout
        )
        self.record = record
        self.parent = None

    def stage(self) -> list[DaqHelper]:
        """
        Daq operations at the start of the scan.

        Checks if OK to start, sets recording state, starts DAQ.
        Signature and return value mandated by bluesky.
        """
        state = self.control.getState()
        if state != 'configured':
            raise RuntimeError(
                'DAQ must be in configured state to run energy scan! '
                f'Currently in {state} state.'
            )
        if self.record is not None:
            logger.info(f'Setting DAQ record to {self.record}')
            self.control.setRecord(self.record)
        logger.info('Starting the DAQ')
        self.control.setState('running')
        return [self]

    def unstage(self) -> list[DaqHelper]:
        """
        Daq operations at the end of the scan.

        Ends the run if applicable.
        Signature and return value mandated by bluesky.
        """
        if self.control.getState() in ('starting', 'paused', 'running'):
            logger.info('Stopping the DAQ')
            self.control.setState('configured')
        return [self]


# Utility for including the DaqHelper in a plan
def daq_helper_wrapper(plan: PlanType, **kwargs) -> PlanType:
    daq_helper = DaqHelper(**kwargs)
    return (yield from bpp.stage_wrapper(plan, [daq_helper]))


scan_devices = SimpleNamespace()


class SettleProxy:
    """
    Quick wrapper to change the settle_time during a scan.
    """
    def __init__(self, obj):
        self.obj = obj
        self.parent = None

    def set(self, value, **kwargs):
        self.obj.settle_time = value
        status = Status()
        status.set_finished()
        return status

    def read(self):
        return {
            'settle_proxy': {
                'value': self.obj.settle_time,
                'timestamp': time.time(),
            }
        }


def setup_scan_devices():
    if not scan_devices.__dict__:
        scan_devices.mono_grating = BeckhoffAxis(
            'SP1K1:MONO:MMS:G_PI',
            name='mono_g_pi',
        )
        scan_devices.pre_mirror_pos = EpicsSignalRO('SP1K1:MONO:MMS:M_PI.RBV')


def calc_mono_ev(grating=None, pre_mirror=None):
    setup_scan_devices()
    if grating is None:
        grating = scan_devices.mono_grating.position
    if pre_mirror is None:
        pre_mirror = scan_devices.pre_mirror_pos.get()

    # Calculation copied from Alex Reid's email with minimal edits

    # Constants:
    D = 5e4  # ruling density in lines per meter
    c = 299792458  # speed of light
    h = 6.62607015E-34  # Plank's const
    el = 1.602176634E-19  # elemental charge
    b = 0.03662  # beam from MR1K1 design value in radians
    ex = 0.1221413  # exit trajectory design value in radians

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
    eVmm = 0.001239842  # Wavelenght[mm] = eVmm/Energy[eV]
    m = 1  # diffraction order
    D0 = 50.0  # 1/mm
    thetaM1 = 0.03662  # rad
    thetaES = 0.1221413  # rad
    offsetM2 = 90641.0e-6  # rad
    offsetG = 63358.0e-6  # rad

    pM2 = pre_mirror*1e-6 - offsetM2
    a0 = m*D0*eVmm/energy
    pG = (
        pM2 - 0.5*thetaM1 + 0.5*thetaES
        - np.arcsin(0.5*a0/np.cos(0.5*np.pi+pM2-0.5*thetaM1-0.5*thetaES))
    )

    # Grating pitch in urad
    return (pG + offsetG)*1e6


class FixSlowMotor(SlowMotor):
    velocity = Signal(name='fake_velo')

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
