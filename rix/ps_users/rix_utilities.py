'''
Helper functions for RIX beamline
06/21/2023

Attention!
Some functions here are used by energy scanning scripts and for calculating SP1K1:MONO:CALC PVs.
Changing the function names or API will break these.

update 10/07/2023:
Added functions to calculate mono bandwidth

update 11/15/2023:
Added function to move to MR1K1 focus
Mono calibration constants in a configuration file

update 04/25/2024:
Added high resolutions gratings to the mono calibration.
Function that checks which grating is selected.

update 05/07/2024:
Exit slit gap is in um now.

update 01/15/2025:
Functions moved to rix_calibration.py
'''

#Additional scripts to load with helper classes and functions
import sys
from .mirrors_rix_2 import * #Mirror check script classes and functions
from .safe_xt import * #safe_xt wrapper for lxt, txt, lxt_ttc
from .rix_alignment_tools import * #alignment tools
from .rix_calibration import * #functions that used to be here
#from .fim_controls import * #functions for powering on FIMs

