#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Oct  9 11:30:07 2025

@author: rixopr
"""


from ophyd.signal import EpicsSignal
import time

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
    voltages_MR3K2 = {'LRG':[-1590, -1600, -1580, -1590, -300, -300, 0, 0, 0, 0],
                      'MEG':[100, 100, 100, 100, 1100, 1100, 1400, 1400, 1400, 1400]}
    voltages_MR4K2 = {'LRG':[-1600, -1600, -1600, -1600, -300, -300, 0, 0, 0, 0],
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
        
