from ophyd import Component as Cpt, EpicsMotor
from pcdsdevices.pseudopos import SyncAxis
import numpy as np

class QRIXS_H_Positioner(SyncAxis):
    """
    Synchronized horizontal positioner for QRIXS diagnostic and MCS motors.
    Geometry:
    - DIAG motor stands at 45° angle
    - MCS2 motor stands at 45° to DIAG (compensates the movement)
    - Both motors work together to achieve pure horizontal displacement
    When moving in the horizontal direction (sync axis):
    - DIAG motor needs to move by distance / cos(45°) = distance * sqrt(2)
    - MCS2 motor needs to move in opposite direction to compensate
    All units are in mm.
    """
    h = Cpt(EpicsMotor, 'QRIXS:DIAG:MMS:H', kind='normal')
    thz_h = Cpt(EpicsMotor, 'QRIX:MCS2:01:THZ_H', kind='normal')
    # Scale factors for 45° geometry
    # sqrt(2) ≈ 1.414 for the projection
    scales = {
        'h': np.sqrt(2),      # DIAG motor: moves sqrt(2) times the sync distance
        'thz_h': -np.sqrt(2)  # MCS2 motor: compensates (negative direction)
    }
    # Auto-determine offsets based on current positions
    offset_mode = SyncAxisOffsetMode.AUTO_FIXED
    # Keep DIAG motor still when re-synchronizing
    fix_sync_keep_still = 'h'
"""
# Create instance
qrixs_h = QRIXS_H_Positioner('', name='qrixs_h')

# Wait until connected
qrixs_h.wait_for_connection()

# Move 1 mm horizontally
# DIAG moves by +1.414 mm
# MCS2 moves by -1.414 mm (compensates)
qrixs_h.sync.move(1.0)
"""
