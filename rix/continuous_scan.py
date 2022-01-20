import numpy as np
from nabs.plans import duration_scan
from toolz import partition


def continuous_scan(detectors, *args, num, duration, sawtooth=False):
    """
    Move motors through a start/stop/num set of points continuously.

    Parameters
    ----------
    detectors : readable or list of readable
        A list of the daq and any other detectors to read out.

    *args : groups of motor, start, stop
        For each motor you want to scan, you should pass in:
        the motor, the start position, and the end position
        for example, if I had two motors, I could pass in:
        continuous_scan([], mot1, 0, 10, mot2, 20, 25, num=10, duration=1000)

    num : int, required keyword
        Number of points for the scan

    duration : number, required keyword
        How long the scan should be in seconds.

    sawtooth : bool, optional
        If False, move through the points in order, then move directly back to
        the start point, then move again in order.
        If True, move through the points in order, then back through the points
        in reverse order, then move again in order, etc.
    """
    if isinstance(detectors, list):
        inner_args = [detectors]
    else:
        inner_args = [[detectors]]

    if len(args) % 3 != 0:
        raise ValueError('Must pass in sets of motor, stop, start!')

    for motor, start, stop in partition(3, args):
        inner_args.append(motor)
        points = list(np.linspace(start, stop, num))
        if sawtooth:
            points = points[:-1] + list(reversed(points))[:-1]
        inner_args.append(points)

    return (yield from duration_scan(*inner_args, duration=duration))
