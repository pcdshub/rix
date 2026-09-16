from ophyd.signal import EpicsSignal
import numpy as np
import time
from configparser import ConfigParser

from . import path_calib_dir as path_calib

# mono calibration constants
mono_calib_file = path_calib + '/Mono_calib_constants.txt'

config = ConfigParser()
with open(mono_calib_file) as stream:
    config.read_string('[section]\n' + stream.read())
D0_LRG = float(config['section']['D0_LRG'])
D0_LEG = float(config['section']['D0_LEG'])
D0_MEG = float(config['section']['D0_MEG'])
D0_HEG = float(config['section']['D0_HEG'])
thetaM1 = float(config['section']['thetaM1'])
thetaES = float(config['section']['thetaES'])
offsetM2 = float(config['section']['offsetM2'])
offsetG_LRG = float(config['section']['offsetG_LRG'])
offsetG_LEG = float(config['section']['offsetG_LEG'])
offsetG_MEG = float(config['section']['offsetG_MEG'])
offsetG_HEG = float(config['section']['offsetG_HEG'])
X_LRG = float(config['section']['X_LRG'])
X_LEG = float(config['section']['X_LEG'])
X_MEG = float(config['section']['X_MEG'])
X_HEG = float(config['section']['X_HEG'])
W_G = float(config['section']['W_G'])

# diffraction order of the monochromator
dif_order = 1 #this is globally used for all the functions

def get_grating():
    PV_horG = 'SP1K1:MONO:MMS:G_H'
    try:
        temppv = EpicsSignal(PV_horG+'.RBV')
        horG = temppv.get()
        #print('Grating horizontal RBV {0:8.2f} um'.format(horG))
    except:
        print('Failed to read PV: ' + PV_horG+'.RBV')

    if (horG>(X_LRG-W_G/2)) & (horG<(X_LRG+W_G/2)):
        stateG = 'LRG'
    elif (horG>(X_LEG-W_G/2)) & (horG<(X_LEG+W_G/2)):
        stateG = 'LEG'
    elif (horG>(X_MEG-W_G/2)) & (horG<(X_MEG+W_G/2)):
        stateG = 'MEG'
    elif (horG>(X_HEG-W_G/2)) & (horG<(X_HEG+W_G/2)):
        stateG = 'HEG'
    else:
        stateG = 'None'
    return stateG


def calc_pitch(*args):
    '''
    Calculates the grating pitch and Cff for given photon energy and pre-mirror pitch.
    Based on Alex Reid calculator.
    Arguments:  args[0] (required) - photon energy (eV)
                args[1] (optional) - pre-mirror pitch (urad)
                If only photon energy is provided then current pre-mirror pitch is used.
    Returns:    grating pitch (urad) and Cff
    Examples:   calc_pitch(400) - calculates grating pitch corresponding to 400 eV at the current pre-mirror pitch
                calc_pitch(500, 144650) - calculates grating pitch for 500 eV and 144650 urad pre-mirror pitch
    '''

    if len(args)==1:
        E = args[0]
        PV_pitchM2 = 'SP1K1:MONO:MMS:M_PI'
        try:
            temppv = EpicsSignal(PV_pitchM2+'.RBV')
            pitchM2 = temppv.get()
            #print('Pre-mirror pitch RBV {0:8.2f} urad'.format(pitchM2))
        except:
            print('Failed to read PV: ' + PV_pitchM2+'.RBV')
    elif len(args)==2:
        E = args[0]
        pitchM2 = args[1]
    else:
        raise Exception('One or two arguments needed.')

    stateG = get_grating()
    if stateG=='LRG':
        D0 = D0_LRG
        offsetG = offsetG_LRG
    elif stateG=='LEG':
        D0 = D0_LEG
        offsetG = offsetG_LEG
    elif stateG=='MEG':
        D0 = D0_MEG
        offsetG = offsetG_MEG
    elif stateG=='HEG':
        D0 = D0_HEG
        offsetG = offsetG_HEG
    else:
        raise Exception('Horizontal position is off grating.')


    # constants
    eVmm = 0.001239842 # Wavelenght[mm] = eVmm/Energy[eV]
    #m = 1 # diffraction order

    pM2 = pitchM2*1e-6 - offsetM2
    a0 = dif_order*D0*eVmm/E
    pG = pM2 - 0.5*thetaM1 + 0.5*thetaES  - np.arcsin(0.5*a0/np.cos(0.5*np.pi+pM2-0.5*thetaM1-0.5*thetaES))
    alpha = np.pi/2 - pG + 2*pM2 - thetaM1
    beta = -np.pi/2 - pG + thetaES
    Cff = np.cos(beta)/np.cos(alpha)

    # grating pitch in urad
    pitchG = (pG + offsetG)*1e6

    #print('Calculated grating pitch {0:8.2f} urad, Cff {1:3.2f}'.format(pitchG, Cff))
    return pitchG, Cff

def calc_pitchCff(E, Cff):
    '''
    Calculates the grating and pre-mirror pitch for given photon energy and Cff value.
    Based on Alex Reid calculator.
    Arguments:  E (required) - photon energy (eV)
                Cff (required) - Cff value
    Returns:    grating and pre-mirror pitch (urad)
    Example:    calc_pitchCff(400, 1.2) - calculates grating and pre-mirror pitch for 400 eV and Cff 1.2
    '''

    stateG = get_grating()
    if stateG=='LRG':
        D0 = D0_LRG
        offsetG = offsetG_LRG
    elif stateG=='LEG':
        D0 = D0_LEG
        offsetG = offsetG_LEG
    elif stateG=='MEG':
        D0 = D0_MEG
        offsetG = offsetG_MEG
    elif stateG=='HEG':
        D0 = D0_HEG
        offsetG = offsetG_HEG
    else:
        raise Exception('Horizontal position is off grating.')

    # constants
    eVmm = 0.001239842 # Wavelenght[mm] = eVmm/Energy[eV]
    #m = 2 # diffraction order

    a0 = dif_order*D0*eVmm/E
    beta = -np.arccos(np.sqrt((-a0**2*Cff**2*(1+Cff**2) + 2*a0*Cff**2*np.sqrt(a0**2*Cff**2+Cff**4-2*Cff**2+1))/(Cff**4 - 2*Cff**2 + 1)))
    alpha = np.arcsin(a0 - np.sin(beta))
    pG = -beta - np.pi/2 + thetaES
    pM2 = 0.5*(alpha - np.pi/2 + pG + thetaM1)

    #
    pitchM2 = (pM2 + offsetM2)*1e6
    pitchG = (pG + offsetG)*1e6

    #print('Calculated pre-mirror pitch {0:8.2f} urad'.format(pitchM2))
    #print('Calculated grating pitch {0:8.2f} urad'.format(pitchG))
    return pitchG, pitchM2

def calc_E(*args):
    '''
    Calculates photon energy and Cff for given grating and pre-mirror pitch.
    Based on Alex Reid calculator.
    Arguments:  args[0] (optional) - grating pitch (urad)
                args[1] (optional) - pre-mirror pitch (urad)
                If grating or pre-mirror pitch are not provided then current values are used.
    Returns:    photon energy (eV) and Cff
    Examples:   calc_E() - calculates grating and pre-mirror pitch at current position, should be same as SP1K1:MONO:CALC:ENERGY
                calc_E(153650) - calculates photon energy for 153650 urad grating pitch and current pre-mirror pitch
                calc_E(153650, 140800) - calculates photon energy for 153650 urad grating pitch and 144650 urad pre-mirror pitch
    '''

    PV_pitchG = 'SP1K1:MONO:MMS:G_PI'
    PV_pitchM2 = 'SP1K1:MONO:MMS:M_PI'
    if len(args)==0:
        try:
            temppv = EpicsSignal(PV_pitchG+'.RBV')
            pitchG = temppv.get()
            temppv = EpicsSignal(PV_pitchG)
            pitchG_target = temppv.get()
            #print('Grating pitch RBV {0:8.2f} urad, target {1:8.2f} urad'.format(pitchG, pitchG_target))
        except:
            print('Failed to read PV: ' + PV_pitchG)
        try:
            temppv = EpicsSignal(PV_pitchM2+'.RBV')
            pitchM2 = temppv.get()
            temppv = EpicsSignal(PV_pitchM2)
            pitchM2_target = temppv.get()
            #print('Pre-mirror pitch RBV {0:8.2f} urad, target {1:8.2f} urad'.format(pitchM2, pitchM2_target))
        except:
            print('Failed to read PV: ' + PV_pitchM2)
    elif len(args)==1:
        pitchG = args[0]
        try:
            temppv = EpicsSignal(PV_pitchM2+'.RBV')
            pitchM2_rbv = temppv.get()
            temppv = EpicsSignal(PV_pitchM2)
            pitchM2 = temppv.get()
            #print('Pre-mirror pitch RBV {0:8.2f} urad, target {1:8.2f} urad'.format(pitchM2, pitchM2_target))
        except:
            print('Failed to read PV: ' + PV_pitchM2)
    elif len(args)==2:
        pitchG = args[0]
        pitchM2 = args[1]
    else:
        raise Exception('Too many arguments.')

    stateG = get_grating()
    if stateG=='LRG':
        D0 = D0_LRG
        offsetG = offsetG_LRG
    elif stateG=='LEG':
        D0 = D0_LEG
        offsetG = offsetG_LEG
    elif stateG=='MEG':
        D0 = D0_MEG
        offsetG = offsetG_MEG
    elif stateG=='HEG':
        D0 = D0_HEG
        offsetG = offsetG_HEG
    else:
        raise Exception('Horizontal position is off grating.')

    # constants
    eVmm = 0.001239842 # Wavelenght[mm] = eVmm/Energy[eV]
    #m = 1 # diffraction order

    pG = pitchG*1e-6 - offsetG
    pM2 = pitchM2*1e-6 - offsetM2
    alpha = np.pi/2 - pG + 2*pM2 - thetaM1
    beta = -np.pi/2 - pG + thetaES
    E = dif_order*D0*eVmm/(np.sin(alpha) + np.sin(beta))
    Cff = np.cos(beta)/np.cos(alpha)

    #print('Calculated photon energy {0:6.2f} eV, Cff {1:3.2f}'.format(E, Cff))
    return E, Cff

def calc_BW(*args):
    '''
    Calculates mono bandwidth (eV).
    Arguments:  args[0] (optional) - exit slit gap (um)
                args[1] (optional) - grating pitch (urad)
                args[2] (optional) - pre-mirror pitch (urad)
                If slit or grating or pre-mirror pitch are not provided then current values are used.
    Returns:    mono bandwidth (eV)
    Examples:   calc_BW() - calculates monochromator bandwidth at the current slit and mono settings
                calc_BW(0.1) - calculates monochromator bandwidth for 0.1 mm slit at the current mono setting
                calc_BW(0.1, 153650, 140800) - calculates monochromator bandwidth for 0.1 mm slit and 153650 urad grating pitch and 144650 urad pre-mirror pitch
    '''

    PV_pitchG = 'SP1K1:MONO:MMS:G_PI'
    PV_pitchM2 = 'SP1K1:MONO:MMS:M_PI'
    PV_slit = 'SL1K2:EXIT:MMS:GAP'
    if len(args)==0:
        try:
            temppv = EpicsSignal(PV_slit+'.RBV')
            slit = temppv.get()
            print('Exit slit gap is {0:8.2f} um'.format(slit))
        except:
            print('Failed to read PV: ' + PV_slit+'.RBV')
        try:
            temppv = EpicsSignal(PV_pitchG+'.RBV')
            pitchG = temppv.get()
            print('Grating pitch is {0:8.2f} urad'.format(pitchG))
        except:
            print('Failed to read PV: ' + PV_pitchG+'.RBV')
        try:
            temppv = EpicsSignal(PV_pitchM2+'.RBV')
            pitchM2 = temppv.get()
            print('Pre-mirror pitch is {0:8.2f} urad'.format(pitchM2))
        except:
            print('Failed to read PV: ' + PV_pitchM2 + '.RBV')
    elif len(args)==1:
        slit = args[0]
        try:
            temppv = EpicsSignal(PV_pitchG+'.RBV')
            pitchG = temppv.get()
            print('Grating pitch is {0:8.2f} urad'.format(pitchG))
        except:
            print('Failed to read PV: ' + PV_pitchG+'.RBV')
        try:
            temppv = EpicsSignal(PV_pitchM2+'.RBV')
            pitchM2 = temppv.get()
            print('Pre-mirror pitch is {0:8.2f} urad'.format(pitchM2))
        except:
            print('Failed to read PV: ' + PV_pitchM2 + '.RBV')
    elif len(args)==2:
        slit = args[0]
        pitchG = args[1]
        try:
            temppv = EpicsSignal(PV_pitchM2+'.RBV')
            pitchM2 = temppv.get()
            print('Pre-mirror pitch is {0:8.2f} urad'.format(pitchM2))
        except:
            print('Failed to read PV: ' + PV_pitchM2 + '.RBV')
    elif len(args)==3:
        slit = args[0]
        pitchG = args[1]
        pitchM2 = args[2]
    else:
        raise Exception('Too many arguments.')

    stateG = get_grating()
    if stateG=='LRG':
        D0 = D0_LRG
        offsetG = offsetG_LRG
    elif stateG=='LEG':
        D0 = D0_LEG
        offsetG = offsetG_LEG
    elif stateG=='MEG':
        D0 = D0_MEG
        offsetG = offsetG_MEG
    elif stateG=='HEG':
        D0 = D0_HEG
        offsetG = offsetG_HEG
    else:
        raise Exception('Horizontal position is off grating.')

    # constants
    eVmm = 0.001239842 # Wavelenght[mm] = eVmm/Energy[eV]
    #m = 1 # diffraction order
    R = 20.0e3 # mm, exit slit distance


    pG = pitchG*1e-6 - offsetG
    pM2 = pitchM2*1e-6 - offsetM2
    alpha = np.pi/2 - pG + 2*pM2 - thetaM1
    beta = -np.pi/2 - pG + thetaES
    
    #E = m*D0*eVmm/(np.sin(alpha) + np.sin(beta))
    #Cff = np.cos(beta)/np.cos(alpha)
    ang_disp = dif_order*D0*eVmm*np.cos(beta)/(np.sin(alpha) + np.sin(beta))**2 # angular dispersion
    lin_disp = ang_disp/R # linear dispersion
    BW = (slit/1000)*lin_disp
    
    #print('Calculated photon energy is {0:6.2f} eV, Cff is {1:3.2f}'.format(E, Cff))
    #print('Angular dispersion is {0:6.2f} eV/rad'.format(ang_disp))
    #print('Linear dispersion is {0:6.2f} eV/mm'.format(lin_disp))
    #print('Bandwidth is {0:6.2f} eV'.format(BW))
    return BW

def calc_grating_velocity_eV(*args):
    '''
    Calculates mono bandwidth (eV).
    Arguments:  args[0] (optional) - grating velocity in urad (urad/sec)
                args[1] (optional) - grating pitch (urad)
                args[2] (optional) - pre-mirror pitch (urad)
                If velocity or grating or pre-mirror pitch are not provided then current values are used.
    Returns:    grating velocity (eV/sec)
    Examples:   calc_grating_velocity_eV() - calculates monochromator velocity at the current mono settings
    '''

    PV_pitchG = 'SP1K1:MONO:MMS:G_PI'
    PV_pitchM2 = 'SP1K1:MONO:MMS:M_PI'
    PV_velocity = 'SL1K2:EXIT:MMS:G_PI.VELO'
    if len(args)==0:
        try:
            temppv = EpicsSignal(PV_velocity+'.RBV')
            velocity = temppv.get()
            print('Velocity is {0:8.2f} urad/sec'.format(velocity))
        except:
            print('Failed to read PV: ' + PV_velocity+'.RBV')
        try:
            temppv = EpicsSignal(PV_pitchG+'.RBV')
            pitchG = temppv.get()
            print('Grating pitch is {0:8.2f} urad'.format(pitchG))
        except:
            print('Failed to read PV: ' + PV_pitchG+'.RBV')
        try:
            temppv = EpicsSignal(PV_pitchM2+'.RBV')
            pitchM2 = temppv.get()
            print('Pre-mirror pitch is {0:8.2f} urad'.format(pitchM2))
        except:
            print('Failed to read PV: ' + PV_pitchM2 + '.RBV')
    elif len(args)==1:
        velocity = args[0]
        try:
            temppv = EpicsSignal(PV_pitchG+'.RBV')
            pitchG = temppv.get()
            print('Grating pitch is {0:8.2f} urad'.format(pitchG))
        except:
            print('Failed to read PV: ' + PV_pitchG+'.RBV')
        try:
            temppv = EpicsSignal(PV_pitchM2+'.RBV')
            pitchM2 = temppv.get()
            print('Pre-mirror pitch is {0:8.2f} urad'.format(pitchM2))
        except:
            print('Failed to read PV: ' + PV_pitchM2 + '.RBV')
    elif len(args)==2:
        velocity = args[0]
        pitchG = args[1]
        try:
            temppv = EpicsSignal(PV_pitchM2+'.RBV')
            pitchM2 = temppv.get()
            print('Pre-mirror pitch is {0:8.2f} urad'.format(pitchM2))
        except:
            print('Failed to read PV: ' + PV_pitchM2 + '.RBV')
    elif len(args)==3:
        velocity = args[0]
        pitchG = args[1]
        pitchM2 = args[2]
    else:
        raise Exception('Too many arguments.')

    stateG = get_grating()
    if stateG=='LRG':
        D0 = D0_LRG
        offsetG = offsetG_LRG
    elif stateG=='LEG':
        D0 = D0_LEG
        offsetG = offsetG_LEG
    elif stateG=='MEG':
        D0 = D0_MEG
        offsetG = offsetG_MEG
    elif stateG=='HEG':
        D0 = D0_HEG
        offsetG = offsetG_HEG
    else:
        raise Exception('Horizontal position is off grating.')

    # constants
    eVmm = 0.001239842 # Wavelenght[mm] = eVmm/Energy[eV]
    #m = 1 # diffraction order
    #R = 20.0e3 # mm, exit slit distance


    pG = pitchG*1e-6 - offsetG
    pM2 = pitchM2*1e-6 - offsetM2
    alpha = np.pi/2 - pG + 2*pM2 - thetaM1
    beta = -np.pi/2 - pG + thetaES
    
    E = dif_order*D0*eVmm/(np.sin(alpha) + np.sin(beta))
    Cff = np.cos(beta)/np.cos(alpha)
    ang_disp = dif_order*D0*eVmm*np.cos(beta)/(np.sin(alpha) + np.sin(beta))**2 # angular dispersion
    velocity_eV = ang_disp*velocity*1e-6
    
    print('Calculated photon energy is {0:6.2f} eV, Cff is {1:3.2f}'.format(E, Cff))
    print('Angular dispersion is {0:6.2f} eV/urad'.format(ang_disp*1e-6))
    print('Velocity is {0:6.2f} eV/sec'.format(velocity_eV))
    return velocity_eV

def calc_slit(*args):
    '''
    Calculates exit slit gap (um).
    Arguments:  args[0] (required) - bandwidth (eV)
                args[1] (optional) - grating pitch (urad)
                args[2] (optional) - pre-mirror pitch (urad)
                If grating or pre-mirror pitch are not provided then current values are used.
    Returns:    gap (um)
    Examples:   calc_slit(0.1) - calculates exit slit gap for 0.1 eV bandwidth at the current mono setting
                calc_slit(0.1, 153650, 140800) - calculates exit slit gap for 0.1 eV bandwidth for 153650 urad grating pitch and 144650 urad pre-mirror pitch
    '''

    PV_pitchG = 'SP1K1:MONO:MMS:G_PI'
    PV_pitchM2 = 'SP1K1:MONO:MMS:M_PI'
    if len(args)==1:
        BW = args[0]
        try:
            temppv = EpicsSignal(PV_pitchG+'.RBV')
            pitchG = temppv.get()
            print('Grating pitch is {0:8.2f} urad'.format(pitchG))
        except:
            print('Failed to read PV: ' + PV_pitchG+'.RBV')
        try:
            temppv = EpicsSignal(PV_pitchM2+'.RBV')
            pitchM2 = temppv.get()
            print('Pre-mirror pitch is {0:8.2f} urad'.format(pitchM2))
        except:
            print('Failed to read PV: ' + PV_pitchM2 + '.RBV')
    elif len(args)==2:
        BW = args[0]
        pitchG = args[1]
        try:
            temppv = EpicsSignal(PV_pitchM2+'.RBV')
            pitchM2 = temppv.get()
            print('Pre-mirror pitch is {0:8.2f} urad'.format(pitchM2))
        except:
            print('Failed to read PV: ' + PV_pitchM2 + '.RBV')
    elif len(args)==3:
        BW = args[0]
        pitchG = args[1]
        pitchM2 = args[2]
    else:
        raise Exception('One, two or three arguments required.')

    stateG = get_grating()
    if stateG=='LRG':
        D0 = D0_LRG
        offsetG = offsetG_LRG
    elif stateG=='LEG':
        D0 = D0_LEG
        offsetG = offsetG_LEG
    elif stateG=='MEG':
        D0 = D0_MEG
        offsetG = offsetG_MEG
    elif stateG=='HEG':
        D0 = D0_HEG
        offsetG = offsetG_HEG
    else:
        raise Exception('Horizontal position is off grating.')

    # constants
    eVmm = 0.001239842 # Wavelenght[mm] = eVmm/Energy[eV]
    #m = 2 # diffraction order
    R = 20.0e3 # mm, exit slit distance


    pG = pitchG*1e-6 - offsetG
    pM2 = pitchM2*1e-6 - offsetM2
    alpha = np.pi/2 - pG + 2*pM2 - thetaM1
    beta = -np.pi/2 - pG + thetaES
    
    #E = m*D0*eVmm/(np.sin(alpha) + np.sin(beta))
    #Cff = np.cos(beta)/np.cos(alpha)
    ang_disp = dif_order*D0*eVmm*np.cos(beta)/(np.sin(alpha) + np.sin(beta))**2 # angular dispersion
    lin_disp = ang_disp/R # linear dispersion
    slit = BW/lin_disp
    
    #print('Calculated photon energy is {0:6.2f} eV, Cff is {1:3.2f}'.format(E, Cff))
    #print('Angular dispersion is {0:6.2f} eV/rad'.format(ang_disp))
    #print('Linear dispersion is {0:6.2f} eV/mm'.format(lin_disp))
    #print('Exit slit gap {0:6.2f} eV'.format(BW))
    return slit*1000

def calc_slitE(*args):
    '''
    Calculates exit slit gap (um).
    Arguments:  args[0] (required) - bandwidth (eV)
                args[1] (required) - photon energy (eV)
                args[2] (required) - Cff value
    Returns:   gap (um)
    Examples:  calc_slitE(0.1, 400, 1.2) - calculates exit slit gap for 0.1 eV bandwidth at 400 eV and 1.2 Cff
    '''

    BW = args[0]
    E = args[1]
    Cff = args[2]

    pitchG, pitchM2 = calc_pitchCff(E, Cff)
    slit = calc_slit(BW, pitchG, pitchM2)

    return slit

def get_E():
    '''
    Reports current photon energy and Cff for based on current grating and pre-mirror pitch target and RBV.
    Reports mono bandwidth based on the exit slit gap.
    Reports the FEL set energy.
    Arguments: none
    Returns:   none
    '''

    PV_pitchG = 'SP1K1:MONO:MMS:G_PI'
    PV_pitchM2 = 'SP1K1:MONO:MMS:M_PI'
    PV_slit = 'SL1K2:EXIT:MMS:GAP'
    PV_SET1 = 'RIX:USER:MCC:EPHOTK:SET1'

    try:
        temppv = EpicsSignal(PV_pitchG+'.RBV')
        pitchG = temppv.get()
    except:
        print('Failed to read PV: ' + PV_pitchG+'.RBV')
    try:
        temppv = EpicsSignal(PV_pitchG)
        pitchG_target = temppv.get()
    except:
        print('Failed to read PV: ' + PV_pitchG)
    try:
        temppv = EpicsSignal(PV_pitchM2+'.RBV')
        pitchM2 = temppv.get()
    except:
        print('Failed to read PV: ' + PV_pitchM2+'.RBV')
    try:
        temppv = EpicsSignal(PV_pitchM2)
        pitchM2_target = temppv.get()
    except:
        print('Failed to read PV: ' + PV_pitchM2)
    try:
        temppv = EpicsSignal(PV_slit+'.RBV')
        slit = temppv.get()
    except:
        print('Failed to read PV: ' + PV_slit+'.RBV')
    try:
        temppv = EpicsSignal(PV_slit)
        slit_target = temppv.get()
    except:
        print('Failed to read PV: ' + PV_slit)

    try:
        temppv = EpicsSignal(PV_SET1)
        E_FEL = temppv.get()
    except:
        print('Failed to read PV: ' + PV_SET1)

    print('Grating pitch RBV {0:8.2f} urad, target {1:8.2f} urad'.format(pitchG, pitchG_target))
    print('Pre-mirror pitch RBV {0:8.2f} urad, target {1:8.2f} urad'.format(pitchM2, pitchM2_target))
    print('Exit slit gap RBV {0:3.2f} um, target {1:3.2f} um'.format(slit, slit_target))

    # RBV
    E, Cff = calc_E(pitchG, pitchM2)
    BW = calc_BW(slit, pitchG, pitchM2)

    # target
    E_target, Cff_target = calc_E(pitchG_target, pitchM2_target)
    BW_target = calc_BW(slit_target, pitchG_target, pitchM2_target)

    print('Target mono energy {0:6.2f} eV (BW {1:3.2f} eV), Cff {2:3.2f}'.format(E_target, BW_target, Cff_target))
    print('RBV mono energy {0:6.2f} eV (BW {1:3.2f} eV), Cff {2:3.2f}'.format(E, BW, Cff))
    print('FEL set energy {0:6.2f} eV'.format(E_FEL))

    return

def move_E(*args):
    '''
    Moves the mono and Vernier/undulator to specified energy.
    Arguments:  args[0] (required) - photon energy (eV)
                args[1] (optional) - pre-mirror pitch (urad)
    If pre-mirror pitch is not given, then pre-mirror target PV value is used.
    Returns:    None
    Examples:   move_E(500)
                move_E(400, 140800)
    '''

    PV_pitchG = 'SP1K1:MONO:MMS:G_PI'
    PV_pitchM2 = 'SP1K1:MONO:MMS:M_PI'
    PV_SET1 = 'RIX:USER:MCC:EPHOTK:SET1'

    if len(args)==1:
        E = args[0]
        try:
            temppv = EpicsSignal(PV_pitchM2)
            pitchM2 = temppv.get()
        except:
            print('Failed to read PV: ' + PV_pitchM2)
    elif len(args)==2:
        E = args[0]
        pitchM2 = args[1]
    else:
        raise Exception('One or two arguments needed.')

    pitchG, Cff = calc_pitch(E, pitchM2)

    # report current energy
    #get_E()

    #
    print('Will do following moves:')
    print(' Grating pitch to {0:8.2f} urad, pre-mirror pitch to {1:8.2f} urad'.format(pitchG, pitchM2))
    print(' FEL photon energy to {0:6.2f} eV'.format(E))

    # command grating pitch, pre-mirror and FEL energy moves
    try:
        temppv = EpicsSignal(PV_pitchG)
        tempval = temppv.put(pitchG)
    except:
        print('Failed to write PV: ' + PV_pitchG)
    try:
        temppv = EpicsSignal(PV_pitchM2)
        tempval = temppv.put(pitchM2)
    except:
        print('Failed to write PV: ' + PV_pitchM2)
    try:
        temppv = EpicsSignal(PV_SET1)
        tempval = temppv.put(E)
    except:
        print('Failed to write PV: ' + PV_SET1)

    return

def move_E_Cff(*args):
    '''
    Moves the mono and Vernier/undulator to specified energy.
    Arguments:  args[0] (required) - photon energy (eV)
                args[1] (required) - Cff
    Returns:    None
    Examples:   move_E(400, 1.2)
                move_E(700, 1.13)
    '''

    if len(args)==2:
        E = args[0]
        Cff = args[1]
        pitchG, pitchM2 = calc_pitchCff(E, Cff)
    else:
        raise Exception('Two arguments needed.')

    PV_pitchG = 'SP1K1:MONO:MMS:G_PI'
    PV_pitchM2 = 'SP1K1:MONO:MMS:M_PI'
    PV_SET1 = 'RIX:USER:MCC:EPHOTK:SET1'

    # report current energy
    #get_E()
    
    #
    print('Will do following moves:')
    print(' Grating pitch to {0:8.2f} urad, pre-mirror pitch to {1:8.2f} urad'.format(pitchG, pitchM2))
    print(' FEL photon energy to {0:6.2f} eV'.format(E))

    try:
        temppv = EpicsSignal(PV_pitchG)
        tempval = temppv.put(pitchG)
    except:
        print('Failed to write PV: ' + PV_pitchG)

    try:
        temppv = EpicsSignal(PV_pitchM2)
        tempval = temppv.put(pitchM2)
    except:
        print('Failed to write PV: ' + PV_pitchM2)
    try:
        temppv = EpicsSignal(PV_SET1)
        tempval = temppv.put(E)
    except:
        print('Failed to write PV: ' + PV_SET1)

    return


def get_M1(*args):
    '''
    Calculates MR1K1 benders current focus position.
    Focus position is calculated based on the MR1K1 benders calibration.
    Arguments: None
    Returns: None
    '''

    # MR1K1 benders PVs
    PV_us = 'MR1K1:BEND:MMS:US'
    PV_ds = 'MR1K1:BEND:MMS:DS'
    # bender table for MR1K1
    qMR1, usMR1, dsMR1 = np.loadtxt(path_calib+'MR1K1.txt', unpack=True)

    try:
        temppv = EpicsSignal(PV_us+'.RBV')
        us = temppv.get()
        print('Upstream bender at {0:4.2f} mm'.format(us))
    except:
        print('Failed to read PV: ' + PV_us)
    try:
        temppv = EpicsSignal(PV_ds+'.RBV')
        ds = temppv.get()
        print('Downstream bender at {0:4.2f} mm'.format(ds))
    except:
        print('Failed to read PV: ' + PV_ds)

    q1 = np.interp(us, usMR1, qMR1, left=-1, right=-1)
    q2 = np.interp(ds, dsMR1, qMR1, left=-1, right=-1)
    if q1<0 or q2<0:
        raise Exception('Bender value is out of range.')
    q0 = 0.5*(q1 + q2)
    print('Current MR1K1 focus at {0:4.2f} m'.format(q0))
    return

def move_M1(*args):
    '''
    Moves MR1K1 benders current a specified position.
    Focus position is calculated based on the MR1K1 benders calibration.
    Arguments: args[0] (required) - focus position (m)
    Returns: None
    Examples:   move_M1(26.5) - move focus 26.5 m downstream, zeroth order on the exit slit
                move_M1(11) - move focus 11 m downstream, first order on the exit slit

    '''

    # MR1K1 benders PVs
    PV_us = 'MR1K1:BEND:MMS:US'
    PV_ds = 'MR1K1:BEND:MMS:DS'
    # bender table for MR1K1
    qMR1, usMR1, dsMR1 = np.loadtxt(path_calib+'MR1K1.txt', unpack=True)

    if len(args)==1:
        q = args[0]
    else:
        raise Exception('One argument needed.')

    us = np.interp(q, qMR1, usMR1, left=-1, right=-1)
    ds = np.interp(q, qMR1, dsMR1, left=-1, right=-1)
    
    if us<0:
        raise Exception('Bender value is out of range.')
    if ds<0:
        raise Exception('Bender value is out of range.')
    
    print('Will do following moves:')
    print(' M1 US bender to {0:4.3f} mm and DS bender to {1:4.3f} mm'.format(us, ds))

    try:
        temppv = EpicsSignal(PV_us)
        tempval = temppv.put(us)
    except:
        print('Failed to write PV: ' + PV_us)

    try:
        temppv = EpicsSignal(PV_ds)
        tempval = temppv.put(ds)
    except:
        print('Failed to write PV: ' + PV_ds)

    return


def calc_M1_range(*args):
    '''
    Calculates MR1K1 benders positions for a given focus range.
    Focus position is calculated based on the MR1K1 benders calibration.
    Arguments:  args[0] (required) - lower focus range limit (m)
                args[1] (optional) - upper focus range limit (m)
                args[2] (optional) - focus position with respect to calculate the range (m)
                If one or two arguments is provided then benders range is calculated from current position.
                If only one argument is provided then range is symmetric with respect to the current position.
    Returns: None
    Examples:   calc_bender(1) - calculates benders range corresponding to [-1,+1] m from the current focus position
                calc_bender(1,2,20)  - calculates benders range corresponding to focus range [20 - 1, 20 + 2] m

    '''

    # MR1K1 benders PVs
    PV_us = 'MR1K1:BEND:MMS:US'
    PV_ds = 'MR1K1:BEND:MMS:DS'
    # bender table for MR1K1
    qMR1, usMR1, dsMR1 = np.loadtxt(path_calib+'MR1K1.txt', unpack=True)

    if len(args)==0:
        raise Exception('One, two or three arguments needed.')
    elif len(args)==1 or len(args)==2:
        try:
            temppv = EpicsSignal(PV_us+'.RBV')
            us = temppv.get()
            print('Upstream bender at {0:4.2f} mm'.format(us))
        except:
            print('Failed to read PV: ' + PV_us)
        try:
            temppv = EpicsSignal(PV_ds+'.RBV')
            ds = temppv.get()
            print('Downstream bender at {0:4.2f} mm'.format(ds))
        except:
            print('Failed to read PV: ' + PV_ds)

        q1 = np.interp(us, usMR1, qMR1, left=-1, right=-1)
        q2 = np.interp(ds, dsMR1, qMR1, left=-1, right=-1)
        if q1<0 or q2<0:
            raise Exception('Bender value is out of range.')
        q0 = 0.5*(q1 + q2)
        print('Current MR1K1 focus at {0:4.2f} m'.format(q0))

        low = args[0]
        if len(args)==1:
            up = args[0]
        else:
            up = args[1]
    elif len(args)==3:
        low = args[0]
        up = args[1]
        q0 = args[2]
    else:
        raise Exception('One, two or three arguments needed.')


    us_low = np.interp(q0-low, qMR1, usMR1, left=-1, right=-1)
    us_up = np.interp(q0+up, qMR1, usMR1, left=-1, right=-1)
    ds_low = np.interp(q0-low, qMR1, dsMR1, left=-1, right=-1)
    ds_up = np.interp(q0+up, qMR1, dsMR1, left=-1, right=-1)

    if us_low<0:
        raise Exception('Upstream bender lower value is out of range.')
    if us_up<0:
        raise Exception('Upstream bender upper value is out of range.')
    if ds_low<0:
        raise Exception('Downstream bender lower value is out of range.')
    if ds_up<0:
        raise Exception('Downstream bender upper value is out of range.')

    print(' US bender range {0:5.3f}, {1:5.3f} mm'.format(us_low, us_up))
    print(' DS bender range {0:5.3f}, {1:5.3f} mm'.format(ds_low, ds_up))
    return

def get_KB0():
    '''
    Return current focus position from KB optics.
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

    print(' Hor. focus at {0:4.3f} m ({1:4.3f} m) from MR3K2'.format(hor0, hor1))
    print(' Ver. focus at {0:4.3f} m ({1:4.3f} m) from MR4K2'.format(ver0, ver1))
    return hor0, ver0

def setKScanningPVs(E=None):
    '''
    Sets the K scanning PVs to current Mono energy
    '''
    if E is None:
        E,cff = calc_E()
    
    print(f"Setting {E:.2f} eV as reference energy for K Scanning. Type 'y' to continue")
    answer = input()
    if answer.lower() not in ["y","yes"]:
        print('Reference change aborted')
        return
    
    EpicsSignal('RIX:USER:MCC:EPHOTK:REF1').put(E)
    EpicsSignal('RIX:USER:MCC:EPHOTK:SET1').put(E)

    reference = EpicsSignal('RIX:USER:MCC:EPHOTK:REF1').get()
    setpoint = EpicsSignal('RIX:USER:MCC:EPHOTK:SET1').get()
    print(f"Reference RIX:USER:MCC:EPHOTK:REF1 set to {reference:.2f} eV.")
    print(f"Set point RIX:USER:MCC:EPHOTK:SET1 set to {setpoint:.2f} eV.")
    return


def checkFIMsOff(showPrint=False):
    '''
    Check the power status of every FIM MCP Channel, returns True if all off

    Parameters
    ----------
    showPrint : Boolean, optional
        Print which channels are not powered off. The default is False.

    Returns
    -------
    bool
        DESCRIPTION.

    '''
    flag=False
    for i in range(10):
        if EpicsSignal(f'MR3K2:FIM:SHV:M0:C{i}:isOn').get():
            if showPrint: print(f'MR3K2:C{i} ramping')
            flag=True
        if EpicsSignal(f'MR4K2:FIM:SHV:M1:C{i}:isOn').get():
            if showPrint: print(f'MR4K2:C{i} ramping')
            flag=True
            
    if not flag:
        if showPrint: print('All FIMs powered off')
        return True
    else:
        return False

def turnOffFIMs():
    '''
    Power off all FIM MCPs.
    '''
    for i in range(10):
        EpicsSignal(f'MR3K2:FIM:SHV:M0:C{i}:Control:setOn').put(0)
        EpicsSignal(f'MR4K2:FIM:SHV:M1:C{i}:Control:setOn').put(0)
    
    while True:
        time.sleep(3)
        if checkFIMsOff(True): break
    return
        
def turnOnFIMs(grating):
    '''
    Power on FIM MCPs to correct voltage setting.
    
    grating = 'LRG': voltages optimized for low resolution grating
            = 'MEG': voltages optimized for high resolution grating
    '''
    
    if grating not in ['LRG','MEG']:
        print('Select either LRG or MEG grating')
        return
    
    if not checkFIMsOff():
        print('FIMs are already on, cycling:')
        turnOffFIMs()
    
    #End IN, End Mesh, Middle IN, Middle Mesh, End OUT, Middle OUT, UpEnd Anode, UpMid Anode, DwnMid Anode, DwnEndANode
    voltages_MR3K2 = {'LRG':[-1750, -1750, -1750, -1750, -300, -300, 0, 0, 0, 0],
                      'MEG':[100, 100, 100, 100, 1100, 1100, 1400, 1400, 1400, 1400]}
    voltages_MR4K2 = {'LRG':[-1800, -1800, -1750, -1750, -300, -300, 0, 0, 0, 0],
                      'MEG':[100, 100, 100, 100, 1100, 1100, 1400, 1400, 1400, 1400]}
    
    
    for i in range(10):
        EpicsSignal(f'MR3K2:FIM:SHV:M0:C{i}:VoltageSet').put(voltages_MR3K2[grating][i])
        EpicsSignal(f'MR4K2:FIM:SHV:M1:C{i}:VoltageSet').put(voltages_MR4K2[grating][i])
        EpicsSignal(f'MR3K2:FIM:SHV:M0:C{i}:Control:setOn').put(1)
        EpicsSignal(f'MR4K2:FIM:SHV:M1:C{i}:Control:setOn').put(1)
    time.sleep(1)
    
    flag=False
    for i in range(10):
        if not EpicsSignal(f'MR3K2:FIM:SHV:M0:C{i}:isOn').get():
            print(f'MR3K2:C{i} failed to turn on')
            flag=True
        if not EpicsSignal(f'MR4K2:FIM:SHV:M1:C{i}:isOn').get():
            print(f'MR4K2:C{i} failed to turn on')
            flag=True
            
    if not flag:
        print('All FIMs powered on')
        
    return
        

