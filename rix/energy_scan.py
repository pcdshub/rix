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
from ophyd.device import Component as Cpt
from ophyd.ophydobj import OphydObject
from ophyd.pseudopos import (PseudoPositioner, PseudoSingle,
                             pseudo_position_argument, real_position_argument)
from ophyd.signal import EpicsSignal, EpicsSignalRO, Signal
from ophyd.status import Status
from pcdsdevices.epics_motor import BeckhoffAxis
from pcdsdevices.signal import AggregateSignal, _AggregateSignalState
from pcdsdevices.sim import SlowMotor
from psdaq.control.DaqControl import DaqControl
from toolz import partition

from rix.rix_utilities import calc_E, calc_pitch

logger = logging.getLogger(__name__)
PlanType = Generator[Msg, Any, Any]


# 1D Scans (move back and forth for duration seconds)

def energy_fly_scan(
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
            energy_fly_scan_step(
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


def energy_fly_scan_step(
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

    plan = energy_fly_duration_scan(
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


def energy_fly_duration_scan(
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

    original_speed = yield from energy_scan_setup(
        mono_grating=mono_grating,
        urad_bounds=urad_bounds,
        grating_speed=grating_speed,
        delay=delay,
    )

    return (
        yield from bpp.finalize_wrapper(
            energy_request_wrapper(
                nbp.duration_scan(
                    [],
                    mono_grating,
                    urad_bounds,
                    duration=duration,
                ),
                **kwargs,
            ),
            energy_scan_cleanup(
                mono_grating=mono_grating,
                original_speed=original_speed,
            )
        )
    )


# ND scans (scan a motor or n motors, do 1 energy sweep at each step)

def energy_fly_scan_nd(
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


def energy_fly_scan_nd_relative(
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


def energy_fly_scan_nd_list(
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


def energy_fly_scan_nd_grid(
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


def energy_fly_scan_nd_grid_list(
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
    original_speed = yield from energy_scan_setup(
        mono_grating=mono_grating,
        urad_bounds=urad_bounds,
        grating_speed=grating_speed,
        delay=0,
    )
    return (
        yield from bpp.finalize_wrapper(
            inner,
            energy_scan_cleanup(
                mono_grating=mono_grating,
                original_speed=original_speed,
            )
        )
    )


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
    use_pseudo: bool = False,
) -> tuple[BeckhoffAxis | GratingPitchEnergy, dict]:
    """
    Helper function for picking the hardware and kwargs.

    This is to centralize the selection of real/fake hardware
    as it is needed in multiple places.
    """
    # Modifiers for sim/test/fake scans
    sim_kw = {}
    mpi_default = GratingPitchEnergy._default_m_pi_pos
    if fake_grating:
        # Initialize a fake grating motor
        if urad_bounds is not None:
            start_pos = urad_bounds[0]
        elif fake_pre_mirror:
            start_pos = calc_pitch(ev_bounds[0], mpi_default)[0]
        else:
            start_pos = calc_pitch(ev_bounds[0])[0]
        if use_pseudo:
            if fake_pre_mirror:
                mono_grating = GPESim()
            else:
                mono_grating = GPESimGPI()
            mono_grating.g_pi.set_current_position(start_pos-5)
            sim_kw['grating_pos'] = mono_grating.g_pi
        else:
            mono_grating = FixSlowMotor(name='fake_mono', init_pos=start_pos-5)
            sim_kw['grating_pos'] = mono_grating
    else:
        # Create the mono grating object if first time
        setup_scan_devices()
        if use_pseudo:
            if fake_pre_mirror:
                mono_grating = GPESimMPI()
            else:
                mono_grating = scan_devices.energy_pseudo
        else:
            mono_grating = scan_devices.mono_grating
    if fake_pre_mirror:
        sim_kw['pre_mirror_pos'] = Signal(
            name='fake_pre_mirror_pos',
            value=mpi_default,
        )
    if fake_acr:
        request = Signal(name='fake_request')
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
    # Get the starting speed
    try:
        velo_read = yield from bps.read(mono_grating.velocity)
        velo = velo_read[mono_grating.velocity.name]['value']
        logger.info('Original speed is %s', velo)
    except TypeError:
        velo = None
        logger.info('Plan inspection, cannot get original speed')
    # Set the settings, bluesky-style
    logger.info('Setting step delay to %s', delay)
    yield from bps.abs_set(SettleProxy(mono_grating), delay)
    logger.info('Moving to the start position: %s', urad_bounds[0])
    yield from bps.mv(mono_grating, urad_bounds[0])
    logger.info('Setting grating speed: %s', grating_speed)
    yield from bps.abs_set(mono_grating.velocity, grating_speed, wait=True)
    return velo


def energy_scan_cleanup(
    mono_grating: BeckhoffAxis,
    original_speed: float,
) -> PlanType:
    """
    Re-usable cleanup steps after the main scan.
    """
    logger.info('Setting grating speed: %s', original_speed)
    yield from bps.abs_set(mono_grating.velocity, original_speed, wait=True)


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
            self.request = EpicsSignal(
                'RIX:USER:MCC:EPHOTK:SET1',
                name='energy_request',
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
        calc = calc_E(
            value,
            self.pre_mirror_sig.get(),
        )[0]
        self.request.put(calc, wait=False)

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

    def stop(self, *args, **kwargs):
        ...


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
        host: str = 'drp-srcf-cmp004',
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
        scan_devices.energy_pseudo = GratingPitchEnergy()


class FixSlowMotor(SlowMotor):
    velocity = Signal(name='fake_velo', value=20)
    user_readback = Signal(name='fake_pos', value=0)

    def _set_position(self, position):
        super()._set_position(position)
        self.user_readback.put(position)

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
            step_time = 0.1
            step_size = self.velocity.get() * step_time
            while positioner.position != goal and not self._stop:
                if goal - positioner.position > step_size:
                    positioner._set_position(positioner.position + step_size)
                elif goal - positioner.position < -step_size:
                    positioner._set_position(positioner.position - step_size)
                else:
                    positioner._set_position(goal)
                    positioner._done_moving(success=True)
                    return
                time.sleep(step_time)
            positioner._done_moving(success=False)
        self.stop()
        self._started_moving = True
        self._stop = False
        t = threading.Thread(
            target=update_thread,
            args=(self, position),
            daemon=True,
        )
        t.start()

    def stop(self, success=True):
        super().stop()


class PlotDisableHelper:
    """
    Helper class for making sure plots are disabled for the energy step scans.

    The plots for these scans are necessarily simple flat slopes are never
    particularly interesting.
    """
    parent = None

    def stage(self) -> list[PlotDisableHelper]:
        try:
            from hutch_python.db import bec  # type: ignore
            self.bec = bec
        except ImportError:
            self.enable_after = False
        else:
            if bec._plots_enabled:
                bec.disable_plots()
                self.enable_after = True
            else:
                self.enable_after = False
        return [self]

    def unstage(self) -> list[PlotDisableHelper]:
        if self.enable_after:
            self.bec.enable_plots()
        return [self]


class MonoEnergySignal(AggregateSignal):
    """
    Signal that reads back the mono energy for the LiveTable.
    """
    def __init__(self, *, g_pi_sig: Signal, m_pi_sig: Signal, **kwargs):
        super().__init__(**kwargs)
        self._g_pi_sig = g_pi_sig
        self._m_pi_sig = m_pi_sig
        self._signals[g_pi_sig] = _AggregateSignalState(signal=g_pi_sig)
        self._signals[m_pi_sig] = _AggregateSignalState(signal=m_pi_sig)

    def _calc_readback(self):
        return calc_E(
            self._signals[self._g_pi_sig].value,
            self._signals[self._m_pi_sig].value,
        )[0]


class GratingPitchEnergy(PseudoPositioner):
    """
    When you move this motor to an eV value, it moves g_pi appropriately.
    """
    g_pi = Cpt(BeckhoffAxis, "SP1K1:MONO:MMS:G_PI", kind="hinted")
    ev = Cpt(PseudoSingle, kind="hinted")
    m_pi = Cpt(EpicsSignalRO, "SP1K1:MONO:MMS:M_PI.RBV", kind="normal")

    _default_g_pi_pos = 150000
    _default_m_pi_pos = 158000

    def __init__(self):
        self.mirror_pos = self._default_m_pi_pos
        super().__init__("", name="mono")

    @m_pi.sub_value
    def _new_mirror_pos(self, value, **kwargs):
        self.mirror_pos = value

    @pseudo_position_argument
    def forward(self, pseudo_pos):
        return self.RealPosition(
            g_pi=calc_pitch(pseudo_pos.ev, self.mirror_pos)[0]
        )

    @real_position_argument
    def inverse(self, real_pos):
        return self.PseudoPosition(
            ev=calc_E(real_pos.g_pi, self.mirror_pos)[0]
        )


class GPESimGPI(GratingPitchEnergy):
    g_pi = Cpt(FixSlowMotor, "", kind="hinted")

    def __init__(self):
        super().__init__()
        self.g_pi.set_current_position(self._default_g_pi_pos)


class GPESimMPI(GratingPitchEnergy):
    m_pi = Cpt(Signal, kind="normal")

    def __init__(self):
        super().__init__()
        self.m_pi.put(self._default_m_pi_pos)


class GPESim(GPESimGPI, GPESimMPI):
    # Avoid an ophyd multi-inheritance edge case
    g_pi = GPESimGPI.g_pi
    m_pi = GPESimMPI.m_pi


def _step_scan_base(
    *,
    mono_grating: GratingPitchEnergy,
    sim_kw: dict[str, Any],
    inner_plan: PlanType,
    plan_args: list[Any],
    plan_kwargs: dict[str, Any],
    record: bool = True,
    motors: Optional[list[Any]] = None,
    fake_daq: bool = False,
    daq_cfg: dict[str, Any],
) -> PlanType:
    """
    Common setup for mono step scans.

    Parameters
    ----------
    mono_grating: Motor
        The mono grating motor we're using
    sim_kw: dict of str to any
        Any relevent sim_kw returns from get_scan_hw
    inner_plan: PlanType
        An unopened plan that will be called with
        dets, *plan_args, **plan_kwargs
    plan_args: list of Any
        The args for the inner plan, omitting detectors
    plan_kwargs: dict of str to any
        The kwargs for the inner plan.
    record: bool, optional
        Whether or not to record the data in the daq. Default is "True".
    motors: list of motors, optional
        Motors to tell the DAQ about during the config step
    fake_daq: bool, optional
        If True, don't use the daq at all.
    **daq_cfg: various, optional
        Any standard DAQ config keyword, such as events or duration.
    """
    if motors is None:
        motors = []
    if fake_daq:
        dets = []
    else:
        # Require a fully loaded DAQ object via hutch-python!
        from hutch_python.db import daq  # type: ignore
        dets = [daq]
        yield from bps.configure(
            daq,
            record=record,
            motors=motors,
            **daq_cfg,
        )
    yield from bps.null()
    logger.info(
        f"Starting mono step scan with m_pi at {mono_grating.m_pi.get()}"
    )
    return (
        yield from bpp.stage_wrapper(
            energy_request_wrapper(
                inner_plan(
                    dets,
                    *plan_args,
                    **plan_kwargs,
                ),
                **sim_kw,
            ),
            [PlotDisableHelper()]
        )
    )


def energy_step_scan(
    start_ev: float,
    stop_ev: float,
    num: int,
    *,
    record: bool = True,
    fake_grating: bool = False,
    fake_pre_mirror: bool = False,
    fake_acr: bool = False,
    fake_daq: bool = False,
    fake_all: bool = False,
    **daq_cfg,
) -> PlanType:
    """
    Basic step scan of the grating mono coordinated with an ACR energy request.

    This uses the default bp.scan behavior under-the-hood to facilitate
    basic step scans using the energy calculations.

    The energy request may be a vernier move or it may be an undulator move.
    The energy request will track the the grating movement.

    The various "fake" arguments run test scans without the associated
    real hardware:
    - fake_grating: do not move the mono grating pitch
    - fake_pre_mirror: do not each the real pre mirror PV for the calcs
    - fake_acr: do not ask acr to change the energy, instead print it
    - fake_daq: do not run the daq
    - fake_all: do everything fake!

    Parameters
    ----------
    start_ev: number
        The lower-bound of the eV to scan.
    stop_ev: number
        The upper-bound of the eV to scan.
    num: int
        The number of points to scan between start_ev and stop_ev,
        including the start and stop points.
    record: bool, optional
        Whether or not to record the data in the daq. Default is "True".
    **daq_cfg: various, optional
        Any standard DAQ config keyword, such as events or duration.
    """
    if fake_all:
        fake_grating = True
        fake_pre_mirror = True
        fake_acr = True
        fake_daq = True
    mono_grating, sim_kw = get_scan_hw(
        ev_bounds=[start_ev],
        fake_grating=fake_grating,
        fake_pre_mirror=fake_pre_mirror,
        fake_acr=fake_acr,
        use_pseudo=True,
    )

    return (
        yield from _step_scan_base(
            mono_grating=mono_grating,
            sim_kw=sim_kw,
            inner_plan=bp.scan,
            plan_args=[
                mono_grating,
                start_ev,
                stop_ev,
            ],
            plan_kwargs={
                "num": num,
            },
            record=record,
            motors=[mono_grating.g_pi, mono_grating.ev],
            fake_daq=fake_daq,
            daq_cfg=daq_cfg,
        )
    )


def energy_list_scan(
    ev_points: list[float],
    *,
    record: bool = True,
    fake_grating: bool = False,
    fake_pre_mirror: bool = False,
    fake_acr: bool = False,
    fake_daq: bool = False,
    fake_all: bool = False,
    **daq_cfg,
) -> PlanType:
    """
    Basic list scan of the grating mono coordinated with an ACR energy request.

    This uses the default bp.list_scan behavior under-the-hood to facilitate
    basic list scans using the energy calculations.

    The energy request may be a vernier move or it may be an undulator move.
    The energy request will track the the grating movement.

    The various "fake" arguments run test scans without the associated
    real hardware:
    - fake_grating: do not move the mono grating pitch
    - fake_pre_mirror: do not each the real pre mirror PV for the calcs
    - fake_acr: do not ask acr to change the energy, instead print it
    - fake_daq: do not run the daq
    - fake_all: do everything fake!

    Parameters
    ----------
    ev_points: list of numbers
        The mono energies in eV to visit
    record: bool, optional
        Whether or not to record the data in the daq. Default is "True".
    **daq_cfg: various, optional
        Any standard DAQ config keyword, such as events or duration.
    """
    if fake_all:
        fake_grating = True
        fake_pre_mirror = True
        fake_acr = True
        fake_daq = True
    mono_grating, sim_kw = get_scan_hw(
        ev_bounds=ev_points,
        fake_grating=fake_grating,
        fake_pre_mirror=fake_pre_mirror,
        fake_acr=fake_acr,
        use_pseudo=True,
    )

    return (
        yield from _step_scan_base(
            mono_grating=mono_grating,
            sim_kw=sim_kw,
            inner_plan=bp.list_scan,
            plan_args=[
                mono_grating,
                ev_points,
            ],
            plan_kwargs={},
            record=record,
            motors=[mono_grating.g_pi, mono_grating.ev],
            fake_daq=fake_daq,
            daq_cfg=daq_cfg,
        )
    )


def energy_step_scan_nd(
    start_ev: float,
    stop_ev: float,
    *args,
    num: Optional[int] = None,
    record: bool = True,
    fake_grating: bool = False,
    fake_pre_mirror: bool = False,
    fake_acr: bool = False,
    fake_daq: bool = False,
    fake_all: bool = False,
    **daq_cfg,
) -> PlanType:
    """
    A multidimensional start, stop, number of points energy step scan.

    This uses the underlying behavior from bp.scan for simultaneous
    1D trajectories across N motors.

    For the ND mesh/grid version of this scan, see energy_step_scan_nd_grid.

    We'll move the mono energy and each additional motor through the
    range of points with equivalent number of steps.

    The positional args should be
    (mono_energy_start, mono_energy_stop)
    followed by *args triplets of
    (motor, start, stop)
    with the number of points passed as as the last positional arg
    or as an explicit keyword arg

    The energy request may be a vernier move or it may be an undulator move.
    The energy request will track the the grating movement.

    The various "fake" arguments run test scans without the associated
    real hardware:
    - fake_grating: do not move the mono grating pitch
    - fake_pre_mirror: do not each the real pre mirror PV for the calcs
    - fake_acr: do not ask acr to change the energy, instead print it
    - fake_daq: do not run the daq
    - fake_all: do everything fake!

    Parameters
    ----------
    start_ev: number
        The lower-bound of the eV to scan.
    stop_ev: number
        The upper-bound of the eV to scan.
    *args: see above
        Additional motors to include in the step scan.
        These should be (motor, start, stop) triples.
    num: int
        The number of points to scan between start_ev and stop_ev,
        including the start and stop points.
    record: bool, optional
        Whether or not to record the data in the daq. Default is "True".
    **daq_cfg: various, optional
        Any standard DAQ config keyword, such as events or duration.
    """
    if fake_all:
        fake_grating = True
        fake_pre_mirror = True
        fake_acr = True
        fake_daq = True
    mono_grating, sim_kw = get_scan_hw(
        ev_bounds=[start_ev],
        fake_grating=fake_grating,
        fake_pre_mirror=fake_pre_mirror,
        fake_acr=fake_acr,
        use_pseudo=True,
    )
    other_motors = []
    for mot, _, _ in partition(3, args):
        other_motors.append(mot)

    return (
        yield from _step_scan_base(
            mono_grating=mono_grating,
            sim_kw=sim_kw,
            inner_plan=bp.scan,
            plan_args=[
                mono_grating,
                start_ev,
                stop_ev,
            ] + list(args),
            plan_kwargs={
                "num": num,
            },
            record=record,
            motors=[mono_grating.g_pi, mono_grating.ev] + other_motors,
            fake_daq=fake_daq,
            daq_cfg=daq_cfg,
        )
    )


def energy_list_scan_nd(
    ev_points: list[float],
    *args,
    record: bool = True,
    fake_grating: bool = False,
    fake_pre_mirror: bool = False,
    fake_acr: bool = False,
    fake_daq: bool = False,
    fake_all: bool = False,
    **daq_cfg,
) -> PlanType:
    """
    ND list scan of the grating mono coordinated with an ACR energy request.

    The positional args should be
    ev_points
    Followed by *args pairs of
    (motor, motor_points)

    This uses the default bp.list_scan behavior under-the-hood to facilitate
    nd list scans using the energy calculations.

    For the ND mesh/grid version of this scan, see energy_list_scan_nd_grid

    The energy request may be a vernier move or it may be an undulator move.
    The energy request will track the the grating movement.

    The various "fake" arguments run test scans without the associated
    real hardware:
    - fake_grating: do not move the mono grating pitch
    - fake_pre_mirror: do not each the real pre mirror PV for the calcs
    - fake_acr: do not ask acr to change the energy, instead print it
    - fake_daq: do not run the daq
    - fake_all: do everything fake!

    Parameters
    ----------
    ev_points: list of numbers
        The mono energies in eV to visit
    *args: see above
        Additional motors to include in the step scan.
        These should be (motor, point_list) pairs.
    record: bool, optional
        Whether or not to record the data in the daq. Default is "True".
    **daq_cfg: various, optional
        Any standard DAQ config keyword, such as events or duration.
    """
    if fake_all:
        fake_grating = True
        fake_pre_mirror = True
        fake_acr = True
        fake_daq = True
    mono_grating, sim_kw = get_scan_hw(
        ev_bounds=ev_points,
        fake_grating=fake_grating,
        fake_pre_mirror=fake_pre_mirror,
        fake_acr=fake_acr,
        use_pseudo=True,
    )
    other_motors = []
    for mot, _ in partition(2, args):
        other_motors.append(mot)

    return (
        yield from _step_scan_base(
            mono_grating=mono_grating,
            sim_kw=sim_kw,
            inner_plan=bp.list_scan,
            plan_args=[
                mono_grating,
                ev_points,
            ] + list(args),
            plan_kwargs={},
            record=record,
            motors=[mono_grating.g_pi, mono_grating.ev] + other_motors,
            fake_daq=fake_daq,
            daq_cfg=daq_cfg,
        )
    )


def energy_step_scan_nd_grid(
    start_ev: float,
    stop_ev: float,
    num_ev: int,
    *args,
    snake_axes: bool = False,
    record: bool = True,
    fake_grating: bool = False,
    fake_pre_mirror: bool = False,
    fake_acr: bool = False,
    fake_daq: bool = False,
    fake_all: bool = False,
    **daq_cfg,
) -> PlanType:
    """
    A multidimensional grid start, stop, number of points energy step scan.

    This uses the underlying behavior from bp.grid_scan for multidemensional
    mesh trajectories across N motors.

    We'll move the mono energy and each additional motor through the
    range of points with independent number of steps along each dimension.

    The mono will be the "slow" motor in the grid that moves the fewest number of times.
    The motors should be provided in order from slowest to fastest for maximum
    scan efficiency.

    For example, if we have the mono, motor2, and motor3:
    - The mono will move to each of its points once
    - For each mono step, motor2 will move to each point once
    - For each motor2 step, motor3 will move to each point once

    The positional args should be
    (mono_energy_start, mono_energy_stop, mono_number_of_points)
    followed by *args quadruplets of
    (motor, start, stop, num)

    The energy request may be a vernier move or it may be an undulator move.
    The energy request will track the the grating movement.
    
    The various "fake" arguments run test scans without the associated
    real hardware:
    - fake_grating: do not move the mono grating pitch
    - fake_pre_mirror: do not each the real pre mirror PV for the calcs
    - fake_acr: do not ask acr to change the energy, instead print it
    - fake_daq: do not run the daq
    - fake_all: do everything fake!

    Parameters
    ----------
    start_ev: number
        The lower-bound of the eV to scan.
    stop_ev: number
        The upper-bound of the eV to scan.
    num_ev: the number of points to include for the ev trajectory.
    *args: see above
        Additional motors to include in the step scan.
        These should be (motor, start, stop, num) quadruples.
    snake_axes: bool
        If True, scan up and down the secondary axes in both directions, repeating endpoints.
        If False (default), return all the way to the bottom of the scan ranges for
        each new grid step, scanning up in the same direction for each new mesh trajectory.
    record: bool, optional
        Whether or not to record the data in the daq. Default is "True".
    **daq_cfg: various, optional
        Any standard DAQ config keyword, such as events or duration.
    """
    if fake_all:
        fake_grating = True
        fake_pre_mirror = True
        fake_acr = True
        fake_daq = True
    mono_grating, sim_kw = get_scan_hw(
        ev_bounds=[start_ev],
        fake_grating=fake_grating,
        fake_pre_mirror=fake_pre_mirror,
        fake_acr=fake_acr,
        use_pseudo=True,
    )
    other_motors = []
    for mot, _, _, _ in partition(4, args):
        other_motors.append(mot)

    return (
        yield from _step_scan_base(
            mono_grating=mono_grating,
            sim_kw=sim_kw,
            inner_plan=bp.grid_scan,
            plan_args=[
                mono_grating,
                start_ev,
                stop_ev,
                num_ev,
            ] + list(args),
            plan_kwargs={
                "snake_axes": snake_axes,
            },
            record=record,
            motors=[mono_grating.g_pi, mono_grating.ev] + other_motors,
            fake_daq=fake_daq,
            daq_cfg=daq_cfg,
        )
    )


def energy_list_scan_nd_grid(
    ev_points: list[float],
    *args,
    snake_axes: bool = False,
    record: bool = True,
    fake_grating: bool = False,
    fake_pre_mirror: bool = False,
    fake_acr: bool = False,
    fake_daq: bool = False,
    fake_all: bool = False,
    **daq_cfg,
) -> PlanType:
    """
    ND list scan of the grating mono coordinated with an ACR energy request.

    The positional args should be
    ev_points
    Followed by *args pairs of
    (motor, motor_points)

    This uses the default bp.list_grid_scan behavior under-the-hood to facilitate
    nd list scans over a mesh using the energy calculations.

    The energy request may be a vernier move or it may be an undulator move.
    The energy request will track the the grating movement.

    The various "fake" arguments run test scans without the associated
    real hardware:
    - fake_grating: do not move the mono grating pitch
    - fake_pre_mirror: do not each the real pre mirror PV for the calcs
    - fake_acr: do not ask acr to change the energy, instead print it
    - fake_daq: do not run the daq
    - fake_all: do everything fake!

    Parameters
    ----------
    ev_points: list of numbers
        The mono energies in eV to visit
    *args: see above
        Additional motors to include in the step scan.
        These should be (motor, point_list) pairs.
    snake_axes: bool
        If True, scan up and down the secondary axes in both directions, repeating endpoints.
        If False (default), return all the way to the bottom of the scan ranges for
        each new grid step, scanning up in the same direction for each new mesh trajectory.
    record: bool, optional
        Whether or not to record the data in the daq. Default is "True".
    **daq_cfg: various, optional
        Any standard DAQ config keyword, such as events or duration.
    """
    if fake_all:
        fake_grating = True
        fake_pre_mirror = True
        fake_acr = True
        fake_daq = True
    mono_grating, sim_kw = get_scan_hw(
        ev_bounds=ev_points,
        fake_grating=fake_grating,
        fake_pre_mirror=fake_pre_mirror,
        fake_acr=fake_acr,
        use_pseudo=True,
    )
    other_motors = []
    for mot, _ in partition(2, args):
        other_motors.append(mot)

    return (
        yield from _step_scan_base(
            mono_grating=mono_grating,
            sim_kw=sim_kw,
            inner_plan=bp.list_grid_scan,
            plan_args=[
                mono_grating,
                ev_points,
            ] + list(args),
            plan_kwargs={
                "snake_axes": snake_axes,
            },
            record=record,
            motors=[mono_grating.g_pi, mono_grating.ev] + other_motors,
            fake_daq=fake_daq,
            daq_cfg=daq_cfg,
        )
    )