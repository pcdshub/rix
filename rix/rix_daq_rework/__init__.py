import logging
from types import SimpleNamespace

from .DaqControl import DaqControl
from .BlueskyScan import BlueskyScan


logger = logging.getLogger(__name__)


def get_daq():
    # Construct the args that DaqScan is looking for
    args = SimpleNamespace(
        C='drp-neh-ctl001', # DRP host for control
        v=True,             # Verbosity
        B='DAQ:NEH',        # PV Base
        detname='scan',     # Detector name
        scantype='scan',    # scan type
        g=36,               # Bit mask of readout groups
        c=10,               # Events per step
        p=2,                # Platform
        x=0,                # Master XPM
        t=1000,             # Connection timeout
        )

    control = DaqControl(host=args.C, platform=args.p, timeout=args.t)

    instr = control.getInstrument()
    if instr is None:
        err = 'Failed to connect to LCLS-II DAQ'
        logger.error(err)

    state = control.getState()
    if state == 'error':
        err = 'Daq is in error state'
        logger.error(err)

    daq = BlueskyScan(control, daqState=state, args=args)

    # Hack over nabs for now to give us the lcls2 daq instead of lcls1
    def _get_daq():
        return daq

    import nabs.preprocessors
    nabs.preprocessors._get_daq = _get_daq

    # Disable the scan pvs, they are not set up for RIX
    try:
        from rix.db import scan_pvs
        scan_pvs.disable()
    except ImportError:
        pass # Not in full hutch python session

    return daq
