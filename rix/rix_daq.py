# Set up the lcls2 daq stuff
import logging

from psdaq.control.control import DaqControl
from psdaq.control.DaqScan import DaqScan
from types import SimpleNamespace


logger = logging.getLogger(__name__)

_control = DaqControl(
    host='drp-neh-ctl001',
    platform=2,
    timeout=1000,
    )

_instr = _control.getInstrument()
if _instr is None:
    err = 'Failed to connect to LCLS-II DAQ'
    logger.error(err)

_state = _control.getState()
if _state == 'error':
    err = 'Daq is in error state'
    logger.error(err)

# Construct the args that DaqScan is looking for
args = SimpleNamespace(
    v=True,             # Verbosity
    B='DAQ:NEH',        # PV Base
    detname='scan',     # Detector name
    scantype='scan',    # scan type
    g=36,               # Bit mask of readout groups
    c=120,              # Events per step
    p=2,                # Platform
    x=0,                # Master XPM
    )

daq = DaqScan(_control, daqState=_state, args=args)

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
