'''
Helper functions for ChemRIXS
11/15/2021

update 07/19/2022:
Reporting read-back values (RBV) of the Epics PVs and better handling of mono drifting

update 06/21/2023:
Moved the monochromator functions to rix_utilities.py

update 06/23/2023:
changes to recirculation scripts:
    - hard coded the duration variable to 24 hours
    - all arguments in seconds (including interval)
    - additional interlock check for valve 3 after valve 2 closes
update 08/23/2023
change to recirculator script DJH:
    make repeated checks to valve 3 interlock status. If trips during drain, restart cycle
update 12/14/2023
    make option to keep valve 2 open during draining (helps with interlocks in some situations)
update 08/31/2023:
Use new KBs tables.
update 09/27/2023:
Added VLS functions.
update 04/12/2024:
Added h5_img_average and h5_img_proj

update 10/07/2024:
Added nozzle EPS PV functions
'''

from ophyd.signal import EpicsSignal
import numpy as np
import time
import h5py
import matplotlib.pyplot as plt
from rix.db import crixs_rcc_vrc_1, crixs_rcc_vrc_2, crixs_rcc_vrc_3, crixs_rcc_vrc_4

from . import path_calib_dir

# path to the folder with KBs calibrations files
path_calib = path_calib_dir

def rcc_cycle(t1=20,t2=10,t3=5,t4=10,runclean=True):
    '''
    Cycles the RCC recirculator
    Arguments: t1 (optional) - time valve 2 is open (seconds), default 20 s
               t2 (optional) - time valve 3 is open (seconds), default 10 s
               t3 (optional) - time valve 1 is open before 4 is opened (seconds), default 5 s
               t4 (optional) - time valve 4 is open before 1&4 are closed (seconds), default 10 s
               runclean - True to keep valve 2 closed while valve 3 is open, False to keep valve 2 open while valve 3 open (helps with interlocks)
    Returns: None
    '''

    def prRed(skk): print("\033[91m {}\033[00m" .format(skk))
    def prGreen(skk): print("\033[92m {}\033[00m" .format(skk))

    #
    crixs_rcc_vrc_1.open_command.put(0)
    crixs_rcc_vrc_2.open_command.put(0)
    crixs_rcc_vrc_3.open_command.put(0)
    crixs_rcc_vrc_4.open_command.put(0)
    
    
    draining = True
    while draining:
        crixs_rcc_vrc_2.open_command.put(1)
        print('Opened valve 2, waiting {0} seconds'.format(t1))
        time.sleep(t1)
        # checking valve 3 interlock status
        valve3_ok = crixs_rcc_vrc_3.interlock_ok.get()
        if not valve3_ok:
            prRed('Valve 3 interlocked, waiting more...')
        while not valve3_ok:
            time.sleep(5)
            valve3_ok = crixs_rcc_vrc_3.interlock_ok.get()
        if valve3_ok:
            prGreen('Valve 3 interlock ok.')
        
        #running clean
        if runclean:
            crixs_rcc_vrc_2.open_command.put(0)
            print('Closed valve 2')
    
        crixs_rcc_vrc_3.open_command.put(1)
        print('Opened valve 3, waiting {0} seconds'.format(t2))
        # checking valve 3 interlock status
        
        #check valve 3 interlock status every second during t2 period. If trips, restart
        draining = False
        for t in range(t2):
            time.sleep(1)
            valve3_ok = crixs_rcc_vrc_3.interlock_ok.get()
            if not valve3_ok:
                prRed('VALVE 3 INTERLOCK TRIPPED: RESTARTING CYCLE')
                draining = True
                break
        
            
        crixs_rcc_vrc_3.open_command.put(0)
        print('Closed valve 3')
        
        #Running dirty
        if not runclean:
            crixs_rcc_vrc_2.open_command.put(0)
            print('Closed valve 2')
        

    #
    time.sleep(2)
    crixs_rcc_vrc_1.open_command.put(1)
    print('Opened valve 1, waiting {0} seconds'.format(t3))
    time.sleep(t3)
    crixs_rcc_vrc_4.open_command.put(1)
    print('Opened valve 4, waiting {0} seconds'.format(t4))
    time.sleep(t4)
    crixs_rcc_vrc_1.open_command.put(0)
    crixs_rcc_vrc_4.open_command.put(0)
    print('Closed valve 1 and 4')
    print('Cycle finished.')

def rcc_cycle_loop(interval=10,t1=20,t2=10,t3=5,t4=10,runclean=True):
    '''
    Loop for the RCC recirculator cycle
    Arguments: interval (optional) - interval between cycles (seconds), default 10 s
               t1 (optional) - time valve 2 is open (seconds), default 20 s
               t2 (optional) - time valve 3 is open (seconds), default 10 s
               t3 (optional) - time valve 1 is open before 4 is opened (seconds), default 5 s
               t4 (optional) - time valve 4 is open before 1&4 are closed (seconds), default 10 s
               runclean - True to keep valve 2 closed while valve 3 is open, False to keep valve 2 open while valve 3 open (helps with interlocks)
    Returns: None
    '''
    
    #duration = 24*60*60 # 24 hours

    #ncycle = duration/(interval+t1+t2+t3+t4+2.0)
    print('Recirculation loop started on ' + time.strftime('%d %b %Y %H:%M:%S', time.localtime()))
    #print('Will do {0:.0f} cycles ({1:.0f} hours).'.format(ncycle, duration/60/60))
    print('-')
    #for i in np.arange(ncycle):
    i = 0
    while True:
        print('Cycle {0:.0f}'.format(i+1))
        rcc_cycle(t1,t2,t3,t4,runclean)
        print('Waiting {0} sec, time is '.format(interval) + time.strftime('%H:%M:%S', time.localtime()))
        time.sleep(interval)
        i += 1
    print('Done!')

def set_nozzle_eps():
    '''
    Use current motor positions to set the EPS for minimum distance btw nozzle and catcher
    '''
    PV_nozzle_eps = 'RIX:CRIX:EPS:fNozzleCatcherOffset'
    PV_rcc_y = 'CRIX:RCC:MMS:Y.RBV'
    PV_sds_y = 'CRIX:SDS:MMS:Y.RBV'
    
    try:
        rcc_y = EpicsSignal(PV_rcc_y).get()
    except:
        print('Failed to read PV: ' + PV_rcc_y)
    
    try:
        sds_y = EpicsSignal(PV_sds_y).get()
    except:
        print('Failed to read PV: ' + PV_sds_y)
    
    try:
        temppv = EpicsSignal(PV_nozzle_eps)
        temppv.put(sds_y-rcc_y)
    except:
        print('Failed to write PV: ' + PV_nozzle_eps)
    
def clear_nozzle_eps():
    '''
    Remove minimum EPS distance for nozzle and catcher
    '''
    PV_nozzle_eps = 'RIX:CRIX:EPS:fNozzleCatcherOffset'
    try:
        temppv = EpicsSignal(PV_nozzle_eps)
        temppv.put(0)
    except:
        print('Failed to write PV: ' + PV_nozzle_eps)

def run_hplc_pid(hplc_num,pressureSP,cycles=10000,dt=5,pid=[.025,0.002,0]):
    
    '''
    PID to try and run HPLC at constant pressure (to help pump fluctuations)
    
    hplc_num: Number of pump to run (1 or 2)
    pressureSP: Pressure set point to try and maintain
    cycles: number of cycles to watch
    dt: wait time between cycles (seconds)
    pid: proportional, integral, derivative gain settings
    '''
    
    PV_flowrate = EpicsSignal(f'RIX:SDS:LC20:0{hplc_num}:FlowRate')
    PV_pressure = EpicsSignal(f'RIX:SDS:LC20:0{hplc_num}:Pressure')
    PV_flowrateSP = EpicsSignal(f'RIX:SDS:LC20:0{hplc_num}:SetFlowRate')
    PV_status = EpicsSignal(f'RIX:SDS:LC20:0{hplc_num}:Status')
    
    startQ = PV_flowrate.get()
    pumpstatus = PV_status.get()
    maxQ = 2*startQ
    minQ = 0.8*startQ
    
    Q = startQ
    newQ = startQ
    P_readings = np.zeros(cycles)
    P_errors = np.zeros(cycles)
    print(f'Starting HPLC Pressure PID on HPLC {hplc_num}. Will maintain at {pressureSP} PSI')
    for i in range(cycles):
        try:
            P = PV_pressure.get()
            Q = PV_flowrate.get()
            if (PV_status.get() != pumpstatus) | (Q != newQ):
                print('Pump status changed:: breaking PID control')
                break
            
            P_readings[i] = P
            P_errors[i] = (pressureSP-P)
            Pterm = pid[0]*P_errors[i]
            Iterm = pid[1]*np.sum(P_errors[:i+1])
            Dterm = pid[2]*(P_errors[i]-P_errors[i-1])
            newQ = np.round(max(min(startQ+Pterm+Iterm+Dterm,maxQ),minQ),1)
            PV_flowrateSP.put(newQ)
            
            if newQ != Q:
                print(f'Changed flowrate from {Q} to {newQ} mL/min')
            
            time.sleep(dt)
        except:
            print('PV READ ERROR')

def run_bk_pid(temperatureSP,cycles=20000,dt=15,pid=[.05,0,0]):
    
    '''
    PID to run BK Precision Power Supply to control RIX temperature
    
    temperatureSP: Temperature set point to maintain
    cycles: number of cycles to watch
    dt: wait time between cycles (seconds)
    pid: proportional, integral, derivative gain settings
    '''
    
    PV_currentOut = EpicsSignal('RIX:BKP:01:AVDD_CUR')
    PV_voltageOut = EpicsSignal('RIX:BKP:01:AVDD_VOLT')
    PV_voltageSP  = EpicsSignal('RIX:BKP:01:SET_V')
    
    PV_temp       = EpicsSignal('CRIXS:RCC:01:TEMP_RBV')
    
    PV_currentSet  = EpicsSignal('RIX:BKP:01:SETCURRENT_RAW_IN')
    PV_voltageSet  = EpicsSignal('RIX:BKP:01:SETVOLTAGE_RAW_IN')
    PV_max_current = EpicsSignal('RIX:BKP:01:MAX_I')
    PV_max_voltage = EpicsSignal('RIX:BKP:01:MAX_V')
    
    maxI = PV_max_current.get()
    minI = 0
    
    T_readings = np.zeros(cycles)
    T_errors = np.zeros(cycles)
    print('Starting BK Precision PID Loop')
    for i in range(cycles):
        try:
            T = PV_temp.get()
            if T > 1000:
                print("Bad Thermocouple Reading")
                time.sleep(dt)
                continue
            
            
            I = PV_currentOut.get()
            V = PV_voltageOut.get()
            #if V < 0.1:
            #V = PV_voltageSP.get()
            #Power = V*I
            #print(f"{Power:.2f} W Output")
            
            T_readings[i] = T
            T_errors[i] = (temperatureSP-T)
            Pterm = pid[0]*T_errors[i]
            Iterm = pid[1]*np.sum(T_errors[:i+1])
            Dterm = pid[2]*(T_errors[i]-T_errors[i-1])
            
            #print(I,V)
            #print(T_errors[i],Pterm,Iterm,Dterm)
            
            newPower = max(Pterm+Iterm+Dterm, 0)
            newI = np.round(min((newPower)**0.5, maxI),2)
            #print(newI)
            
            PV_currentSet.put(newI)
            
            if newI != np.round(I,2):
                print(f'Changed current from {I} to {newI} A')
            
            time.sleep(dt)
        except KeyboardInterrupt:
            print('\nBreaking Loop')
            return
        except Exception as e:
            print(f'Error: {e}')

def get_KB2():
    '''
    Displays current focus position from ChemRIXS IP.
    Focus position is calculated based on the KBs benders calibration.
    Arguments: None
    Returns: None
    '''
    
    PV_usH = 'MR3K2:KBH:MMS:BEND:US'
    PV_dsH = 'MR3K2:KBH:MMS:BEND:DS'
    PV_usV = 'MR4K2:KBV:MMS:BEND:US'
    PV_dsV = 'MR4K2:KBV:MMS:BEND:DS'

    # old bender tables for MR3K2 and MR4K2
    #qH, usH, dsH = np.loadtxt(path_calib+'MR3K2.txt', unpack=True)
    #qV, usV, dsV = np.loadtxt(path_calib+'MR4K2.txt', unpack=True)

    # new bender tables for MR3K2 and MR4K2 (29 Aug. 2023 from Lance Lee)
    # clear aperture 1 (CA1), center 200 mm
    pH, qH, thetaH, usH, dsH = np.loadtxt(path_calib+'MR3K2/mr3k2_focus_table_ca1.csv', delimiter=',', skiprows=1, unpack=True)
    pH, qV, thetaV, usV, dsV = np.loadtxt(path_calib+'MR4K2/mr4k2_focus_table_ca1.csv', delimiter=',', skiprows=1, unpack=True)

    # ChemRIXS distance from MR3K2 and MR4K2
    dH = 8.8
    dV = 7.3

    try:
        temppv = EpicsSignal(PV_usH+'.RBV')
        usH0 = temppv.get()
        temppv = EpicsSignal(PV_dsH+'.RBV')
        dsH0 = temppv.get()
        temppv = EpicsSignal(PV_usV+'.RBV')
        usV0 = temppv.get()
        temppv = EpicsSignal(PV_dsV+'.RBV')
        dsV0 = temppv.get()
    except:
        print('Failed to read PV')

    hor0 = np.interp(usH0, usH, qH, left=-1, right=-1)
    hor1 = np.interp(dsH0, dsH, qH, left=-1, right=-1)
    ver0 = np.interp(usV0, usV, qV, left=-1, right=-1)
    ver1 = np.interp(dsV0, dsV, qV, left=-1, right=-1)

    if hor0<0:
        raise Exception('Horizontal KB upstream bender value is out of range.')
    if hor1<0:
        raise Exception('Horizontal KB downstream bender value is out of range.')
    if ver0<0:
        raise Exception('Vertical KB upstream bender value out is of range.')
    if ver1<0:
        raise Exception('Vertical KB downstream bender value is out of range.')

    print(' Hor. focus at {0:4.3f} m ({1:4.3f} m) from ChemRIXS'.format(hor0-dH, hor1-dH))
    print(' Ver. focus at {0:4.3f} m ({1:4.3f} m) from ChemRIXS'.format(ver0-dV, ver1-dV))
    return


def move_KB2(*args):
    '''
    Moves current focus position to a specified distance from ChemRIXS IP.
    Focus position is calculated based on the KBs benders calibration.
    Arguments:  args[0] (required) - horizontal focus position (m)
                args[1] (optional) - vertical focus position (m)
                If only one argument is provided then hor. and ver. focus is moved to the same distance.
    Returns:    None
    Examples:   moveKBs(0) - moves hor. and ver. focus to ChemRIXS IP
                moveKBs(-1, 1) - moves hor. focus 1 m before and ver. focus 1 m after ChemRIXS IP
    '''

    PV_usH = 'MR3K2:KBH:MMS:BEND:US'
    PV_dsH = 'MR3K2:KBH:MMS:BEND:DS'
    PV_usV = 'MR4K2:KBV:MMS:BEND:US'
    PV_dsV = 'MR4K2:KBV:MMS:BEND:DS'

    # old bender tables for MR3K2 and MR4K2
    #qH, usH, dsH = np.loadtxt(path_calib+'MR3K2.txt', unpack=True)
    #qV, usV, dsV = np.loadtxt(path_calib+'MR4K2.txt', unpack=True)

    # new bender tables for MR3K2 and MR4K2 (29 Aug. 2023 from Lance Lee)
    # clear aperture 1 (CA1), center 200 mm
    pH, qH, thetaH, usH, dsH = np.loadtxt(path_calib+'MR3K2/mr3k2_focus_table_ca1.csv', delimiter=',', skiprows=1, unpack=True)
    pH, qV, thetaV, usV, dsV = np.loadtxt(path_calib+'MR4K2/mr4k2_focus_table_ca1.csv', delimiter=',', skiprows=1, unpack=True)

    # ChemRIXS distance from MR3K2 and MR4K2
    dH = 8.8
    dV = 7.3

    if len(args)==0:
        raise Exception('One or two arguments needed.')
    elif len(args)==1:
        hor = args[0]
        ver = args[0]
    elif len(args)==2:
        hor = args[0]
        ver = args[1]
    else:
        raise Exception('One or two arguments needed.')

    usH0 = np.interp(hor, qH-dH, usH, left=-1, right=-1)
    dsH0 = np.interp(hor, qH-dH, dsH, left=-1, right=-1)
    usV0 = np.interp(ver, qV-dV, usV, left=-1, right=-1)
    dsV0 = np.interp(ver, qV-dV, dsV, left=-1, right=-1)

    if usH0<0:
        raise Exception('Horizontal KB upstream bender value is out of range.')
    if dsH0<0:
        raise Exception('Horizontal KB downstream bender value is out of range.')
    if usV0<0:
        raise Exception('Vertical KB upstream bender value out is of range.')
    if dsV0<0:
        raise Exception('Vertical KB downstream bender value is out of range.')

    print('Will do following moves:')
    print(' Hor. KB US bender to {0:4.3f} mm and DS bender to {1:4.3f} mm'.format(usH0, dsH0))
    print(' Ver. KB US bender to {0:4.3f} mm and DS bender to {1:4.3f} mm'.format(usV0, dsV0))

    try:
        temppv = EpicsSignal(PV_usH)
        tempval = temppv.put(usH0)
    except:
        print('Failed to write PV: ' + PV_usH)

    try:
        temppv = EpicsSignal(PV_dsH)
        tempval = temppv.put(dsH0)
    except:
        print('Failed to write PV: ' + PV_dsH)

    try:
        temppv = EpicsSignal(PV_usV)
        tempval = temppv.put(usV0)
    except:
        print('Failed to write PV: ' + PV_usV)

    try:
        temppv = EpicsSignal(PV_dsV)
        tempval = temppv.put(dsV0)
    except:
        print('Failed to write PV: ' + PV_dsV)

    return

def calc_VLS(*args):
    '''
    Calculates the VLS spectrometer energy and resolution at the center of the detector.
    If not specified, current detector, mirror and grating angles are used.
    Arguments:  args[0] (optional) - source size (um), default is 20 um.
                args[1] (optional) - detector resolution (um), default is 24 um.
                args[2] (optional) - detector arm angle wrt. horizontal (deg). If not specified current RBV is used.
                args[3] (optional) - mirror pitch wrt. Horizontal (mrad). If not specified current RBV is used.
                args[4] (optional) - grating pitch wrt. Horizontal (mrad). If not specified current RBV is used.
    Returns:    None
    Examples:   calc_VLS() - calculates photon energy and resolution for current spectrometer setting..
                calc_VLS(10, 20, 2) - calculates photon energy for 2 deg detector arm position and resolution for 10 um source and 20 um detector resolution.
    Note: desiged incident angles for mirror and grating are 2.12 deg (37.0 mrad) and 1.45 deg (25.3 mrad), respectively.
    '''
    
    PV_pitchDET = 'CRIX:VLS:CAM:MMS:PITCH'
    PV_pitchM = 'CRIX:VLS:MMS:MP'
    PV_pitchG = 'CRIX:VLS:MMS:GP'

    w_source = 20
    det_res = 24.0 # um
    
    # get current spectrometer setting
    try:
        temppv = EpicsSignal(PV_pitchDET+'.RBV')
        det_pitch = temppv.get()
    except:
        print('Failed to read PV: ' + PV_pitchDET+'.RBV')
    try:
        temppv = EpicsSignal(PV_pitchM+'.RBV')
        pitchM_mm = temppv.get()
        # conversion to mrad
        pitchM = -0.7569*pitchM_mm**2 + 18.1*pitchM_mm + 27.667
    except:
        print('Failed to read PV: ' + PV_pitchM+'.RBV')
    try:
        temppv = EpicsSignal(PV_pitchG+'.RBV')
        pitchG_mm = temppv.get()
        # conversion to mrad
        pitchG = 0.334*pitchG_mm**2 - 16.25*pitchG_mm + 22.56
    except:
        print('Failed to read PV: ' + PV_pitchG+'.RBV')


    if len(args)==0:
        1
    elif len(args)==1:
        w_source = args[0]
    elif len(args)==2:
        w_source = args[0]
        det_res = args[1]
    elif len(args)==3:
        w_source = args[0]
        det_res = args[1]
        det_pitch = args[2]
    elif len(args)==4:
        w_source = args[0]
        det_res = args[1]
        det_pitch = args[2]
        pitchM = args[3]
    elif len(args)==5:
        w_source = args[0]
        det_res = args[1]
        det_pitch = args[2]
        pitchM = args[3]
        pitchG = args[4]
    else:
        raise Exception('Too many arguments (max. five).')

    # constants
    eVmm = 0.001239842 # Wavelenght[mm] = eVmm/Energy[eV]
    rM = 28200 # Mirror radius of curvature, mm
    rG = 9.9e99 # Grating radius of curvature (plane grating)
    #alphaM = (90-2.12)*np.pi/180.0 # Mirror angle of incidence (wrt. normal)
    #alpha = (90-1.485)*np.pi/180.0 # Grating angle of incidence (wrt. normal)
    dSM = 930.427 # distance Source-Mirror, mm
    dMG = 100.0 # distance Mirror-Grating, mm
    D0 = 1200 # central groove density, 1/mm
    D1 = 2.19 # 1/mm^2
    #D2 = 0.0 # 1/mm^3
    #D3 = 0.0 # 1/mm^4
    Dslope = 1e-6 # slope error, rad
    w_G = 90.0 # Grating width (dispersive dimension), mm

    # Mirror angle of incidence (wrt. mirror normal), rad
    alphaM = np.pi/2 - pitchM/1000
    # Grating angle of incidence (wrt. grating normal), rad
    alpha = np.pi/2 - (2*pitchM - pitchG)/1000
    # diffraction angle (wrt. grating normal), convention: alpha>0, beta<0
    beta = det_pitch*np.pi/180.0+(2*(np.pi/2-alphaM)-(np.pi/2-alpha)) - np.pi/2
    
    # photon energy
    E1 = 1.0*D0*eVmm/(np.sin(alpha) + np.sin(beta))
    E2 = 2.0*D0*eVmm/(np.sin(alpha) + np.sin(beta))

    #
    fM = 0.5*rM*np.cos(alphaM) # Mirror focal length
    di = 1.0/(1.0/fM-1.0/dSM) # Mirror image distance (lens equation)
    #dSG = dSM + dMG
    dSiG = dMG-di # Source-Grating distance for the imaginary source of the grating (negative, behind the Grating)
    dGD = (np.cos(beta))**2/(-np.cos(alpha)**2/dSiG+np.cos(alpha)/rG+np.cos(beta)/rG+1.0*D1*eVmm/E1) # Grating-Detector distance
    #dSD = dSM+dMG+dGD
    
    # linear dispersion at the detector per mm, eV/mm
    # assumes 90 deg detector angle
    disp1 = E1*np.cos(beta)/(1.0*D0*eVmm/E1*dGD)
    disp2 = E2*np.cos(beta)/(2.0*D0*eVmm/E2*dGD)

    # magnification
    magM = (dMG-dSiG)*np.cos(alphaM)/(dSM*np.cos(alphaM))
    magG = dGD*np.cos(alpha)/(dSiG*np.cos(beta))
    mag = magM*magG

    # broadening due to source size (det. at 90 deg)
    DE_s1 = np.abs(w_source*1e-3*mag*disp1)
    DE_s2 = np.abs(w_source*1e-3*mag*disp2)
    # broadening due to detector (det. at 90 deg)
    DE_d1 =det_res*1e-3*np.abs(disp1)
    DE_d2 =det_res*1e-3*np.abs(disp2)
    # broadening due to abberations
    DE_a = 0.0
    # slope error
    DE_slope1 = E1**2*(np.cos(alpha)+np.cos(beta))/np.abs(1.0*D0*eVmm)*Dslope
    DE_slope2 = E2**2*(np.cos(alpha)+np.cos(beta))/np.abs(2.0*D0*eVmm)*Dslope
    # broadening due to finite size of the grating
    DE_dif1 = E1/np.abs(1.0*w_G*D0)
    DE_dif2 = E2/np.abs(2.0*w_G*D0)
    # total resolution
    DE_tot1 = np.sqrt(DE_s1**2+DE_d1**2+DE_a**2+DE_slope1**2+DE_dif1**2)
    DE_tot2 = np.sqrt(DE_s2**2+DE_d2**2+DE_a**2+DE_slope2**2+DE_dif2**2)
    
    print(' Detector angle {0:3.2f} deg, mirror pitch {1:3.3f} mrad, grating pitch {2:5.2f} mrad.'.format(det_pitch, pitchM, pitchG))
    print(' Photon energy (1st order): {0:5.2f} eV, resolution {1:3.2f} eV'.format(E1, DE_tot1))
    #print(' Photon energy (2nd order): {0:5.2f} eV, resolution {1:3.2f} eV'.format(E2, DE_tot2))

    return 

def calc_VLS_detpos(*args):
    '''
    Calculates the VLS spectrometer detector arm angle for a given photon energy and dif. order
    Arguments:  args[0] (required) - photon energy (eV)
                args[1] (optional) - diffraction order, default is 1
                args[2] (optional) - mirror pitch wrt. Horizontal (mrad)
                args[3] (optional) - grating pitch wrt. Horizontal (mrad)
    Returns:    None
    Examples:   calc_VLS_detpos(500) - calculates detector position (deg) for 500 eV and 1st order diffraction
    Note: desiged incident angles for mirror and grating are 2.12 deg (37.0 mrad) and 1.45 deg (25.3 mrad), respectively.
    '''

    PV_pitchM = 'CRIX:VLS:MMS:MP'
    PV_pitchG = 'CRIX:VLS:MMS:GP'

    # get current mirror pitch and grating pitch
    try:
        temppv = EpicsSignal(PV_pitchM+'.RBV')
        pitchM_mm = temppv.get()
        # conversion to mrad
        pitchM = -0.7569*pitchM_mm**2 + 18.1*pitchM_mm + 27.667
    except:
        print('Failed to read PV: ' + PV_pitchM+'.RBV')
    try:
        temppv = EpicsSignal(PV_pitchG+'.RBV')
        pitchG_mm = temppv.get()
        # conversion to mrad
        pitchG = 0.334*pitchG_mm**2 - 16.25*pitchG_mm + 22.56
    except:
        print('Failed to read PV: ' + PV_pitchG+'.RBV')


    if len(args)==1:
        E = args[0]
        m_dif = 1
    elif len(args)==2:
        E = args[0]
        m_dif = args[1]
    elif len(args)==3:
        E = args[0]
        m_dif = args[1]
        pitchM = args[2]
    elif len(args)==4:
        E = args[0]
        m_dif = args[1]
        pitchM = args[2]
        pitchG = args[3]
    else:
        raise Exception('One to four arguments needed.')

    # constants
    eVmm = 0.001239842 # Wavelenght[mm] = eVmm/Energy[eV]
    #alphaM = (90-2.12)*np.pi/180.0 # Mirror angle of incidence (wrt. normal)
    #alpha = (90-1.485)*np.pi/180.0 # Grating angle of incidence (wrt. normal)
    D0 = 1200 # central groove density, 1/mm
    #D1 = 2.19 # 1/mm^2
    #D2 = 0.0 # 1/mm^3
    #D3 = 0.0 # 1/mm^4
    
    # Mirror angle of incidence (wrt. mirror normal), rad
    alphaM = np.pi/2 - pitchM/1000
    # Grating angle of incidence (wrt. grating normal), rad
    alpha = np.pi/2 - (2*pitchM - pitchG)/1000
    # diffraction angle (wrt. normal), convention: alpha>0, beta<0
    beta = np.arcsin(m_dif*D0*eVmm/E-np.sin(alpha))

    # detector pitch
    det_pitch = (beta + np.pi/2) - (2*(np.pi/2-alphaM)-(np.pi/2-alpha))
    det_pitch = det_pitch/np.pi*180.0
    
    print(' Detector angle for {0:3.1f} eV ({1}. order) is {2:4.4f} deg'.format(E, m_dif, det_pitch))

    return 

def calc_VLS_ZO(*args):
    '''
    Calculates the VLS spectrometer detector arm angle for zero order reflection for given mirror and grating pitch.
    Arguments:  args[0] (optional) - mirror pitch wrt. Horizontal (mrad)
                args[1] (optional) - grating pitch wrt. Horizontal (mrad)
    Returns:    None
    Examples:   calc_VLS_ZO() - calculates det. pitch (mrad/deg) for current mirror and grating pitch.
    '''
    
    #PV_pitchDET = 'CRIX:VLS:CAM:MMS:PITCH'
    PV_pitchM = 'CRIX:VLS:MMS:MP'
    PV_pitchG = 'CRIX:VLS:MMS:GP'

    if len(args)==0:
        try:
            temppv = EpicsSignal(PV_pitchM+'.RBV')
            pitchM_mm = temppv.get()
            # conversion to mrad
            pitchM = -0.7569*pitchM_mm**2 + 18.1*pitchM_mm + 27.667
        except:
            print('Failed to read PV: ' + PV_pitchM+'.RBV')
        try:
            temppv = EpicsSignal(PV_pitchG+'.RBV')
            pitchG_mm = temppv.get()
            # conversion to mrad
            pitchG = 0.334*pitchG_mm**2 - 16.25*pitchG_mm + 22.56
        except:
            print('Failed to read PV: ' + PV_pitchG+'.RBV')
    elif len(args)==2:
        pitchM = args[0]
        pitchG = args[1]
    else:
        raise Exception('Zero or two arguments needed.')
    
    # grating incident angle wrt. grating surface
    alpha = 2*pitchM - pitchG
    
    # detector pitch wrt. Horizontal
    det_pitch0 = 2*alpha - 2*pitchM

    print(' Mirror pitch is {0:3.3f} mrad ({1:3.2f} deg)'.format(pitchM, pitchM/np.pi*180/1000))
    print(' Grating pitch is {0:3.3f} mrad ({1:3.2f} deg)'.format(pitchG, pitchG/np.pi*180/1000))
    print(' Grating incident angle is {0:3.3f} mrad ({1:3.2f} deg)'.format(alpha, alpha/np.pi*180/1000))
    print(' Detector arm angle for ZO is {0:3.3f} mrad ({1:3.2f} deg)'.format(det_pitch0, det_pitch0/np.pi*180/1000))
    return 

def h5_img_average(file_name, roi=None):
    """Show an average image with h5_img_collect
    Parameters:
    ----------
    file_name: name of the hdf5 file name (with extension)
       Example is 'im1k2_001.h5'.
    roi: [x_min, x_max, y_min, y_max]
        Example: [1000, 1048, 0, 2048]
    """

    # load in the images
    file = h5py.File(file_name,'r')
    data = file['/entry/data/data'][:]
    #detector = file['/entry/instrument/detector']
    file.close()

    #print(np.shape(data))
    img = np.mean(data, axis=0)

    if roi==None:
        lenx,leny = np.shape(img)
        roi = [0, lenx, 0, leny]

    '''
    # save the integrated image
    h5_out = h5py.File(path+file_name+'.h5','w')
    h5_out.create_dataset('data', data=img)
    h5_out.close()
    print('Image saved to file '+path+file_name+'.h5')
    '''
    
    fig,ax0 = plt.subplots(1,1)

    ax0.imshow(img[roi[0]:roi[1], roi[2]:roi[3]])

    plt.show()

def h5_img_proj(file_name, roi=None, axis=0):
    """Show a projection of an average image ROI recorded with h5_img_collect
    ----------
    file_name: name of the hdf5 file name (with extension)
        Example is 'im1k2_001.h5'.
    roi: [x_min, x_max, y_min, y_max]
        Example: [1000, 1048, 0, 2048]
    axis: dimension of the projection, value 0 or 1 
    """

    # load in the images
    file = h5py.File(file_name,'r')
    data = file['/entry/data/data'][:]
    #detector = file['/entry/instrument/detector']
    file.close()

    #print(np.shape(data))
    img = np.mean(data, axis=0)

    if roi==None:
        lenx,leny = np.shape(img)
        roi = [0, lenx, 0, leny]

    proj = np.mean(img[roi[0]:roi[1], roi[2]:roi[3]], axis=axis)

    '''
    # save the integrated image
    h5_out = h5py.File(path+file_name+'.h5','w')
    h5_out.create_dataset('data', data=img)
    h5_out.close()
    print('Image saved to file '+path+file_name+'.h5')
    '''
    
    fig,ax0 = plt.subplots(1,1)

    ax0.plot(proj)

    plt.show()



