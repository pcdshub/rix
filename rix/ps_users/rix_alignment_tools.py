#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jun  5 15:49:25 2024

@author: rixopr
"""


import h5py
import numpy as np

from ophyd.signal import EpicsSignal
import os
import datetime
from prettytable import PrettyTable

from . import trajectory_data_dir


def find_newest_file(directory, search_string, reftime=None):
    '''
    Function that searches given directory for files with names that match a given search string.
    By default it returns the newest file, but can return file which most closely matches a given reference time
    
    Parameters:
        directory (str): Directory to search
        search_string (str): File name part to search directory for
        reftime: Can except either a datestamp in the format %b/%d/%Y %H:%M:%S (normal elog timestamp string)
            or a list of integers in format [YYYY, MM, DD, hh, mm, ss]
            Default=None uses current datetime instead
    Returns:
        newest_file (str): name of file closest to reftime
    '''
    
    # Initialize variables to store the name and the modification time of the newest file
    newest_file = None
    newest_time = None
    if reftime is None:
        reftime = datetime.datetime.now()
    else:
        if isinstance(reftime,str):
            reftime=datetime.datetime.strptime(reftime.strip(),'%b/%d/%Y %H:%M:%S')
        else:
            reftime=datetime.datetime(*reftime)
    
    # Iterate over all files in the given directory
    for filename in os.listdir(directory):
        # Check if the filename contains the search string
        if search_string in filename:
            # Get the full path of the file
            filepath = os.path.join(directory, filename)
            # Get the modification time of the file
            file_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(filepath))
            # Compare and store the newest file
            if newest_time is None or abs(file_mtime-reftime) < newest_time:
                newest_time = abs(file_mtime-reftime) 
                newest_file = filename
    return newest_file


        
def loadCentroid(filename):
    '''
    Reads given hdf5 file from Matt Seaberg's PPM_screen. Returns the center of the
    2D Gaussian fit in the x and y axes.'
    Parameters
    ----------
    filename : str
        Filepath and name to hdf5 file

    Returns
    -------
    (cx,cy): centers of the 2D Gaussian fit from PPM_screen.

    '''
    with h5py.File(filename, 'r') as f:
        cxs = f['cx'][:]
        cys = f['cy'][:]
        
        '''
        Filtering based on some goodness of fit metric from PPM_screen...
        Weird behavior and doesn't work very well
        '''
        #shotmsk = f['centroid_is_valid'][:]==1
        #print(cxs)
        #print(shotmsk)
        #cxs_msk = cxs[shotmsk]
        #cys_msk = cys[shotmsk]
        
        #Look at last 10 images, same as PPM_screen default
        cx = np.nanmean(cxs[-10:])
        cy = np.nanmean(cys[-10:])
        
    return(cx,cy)

def calc_align_2K0(reftime=None,refpos=[550,-750]):
    '''
    Calculate recommended ACR undulator pointing adjustments relative to
    current position on IM2K0.
    
    By default uses most recent PPM_screen hdf5 files.
    
    Can reference older hdf5 files by supplying timestamps for the file in
    elog format, e.g. 'Jun/20/2024 20:29:38', which returns the file saved
    closest to that timestamp.

    Parameters
    ----------
    reftime : str, optional
        Timestamp for IM2K0 file. The default is None.
    refpos : [float,float], optional
        Reference golden trajectory coordinates for IM2K0

    Returns
    -------
    None.
    '''
    trajectories_dir = trajectory_data_dir
    
    #
    h5im2file=find_newest_file(trajectories_dir,'IM2K0',reftime)
    print('Loaded IM2K0 data from ' + h5im2file)
    im2cx,im2cy=loadCentroid(os.path.join(trajectories_dir,h5im2file))
    
    near_dx = (im2cx-refpos[0])
    near_dy = (im2cy-refpos[1])
    
    res_x = near_dx/-3
    res_y = near_dy/-3
    
    
    t1 = PrettyTable(['Imager','X_0 (um)','dX (um)','Y_0 (um)','dY (um)'])
    t1.add_row(['IM2K0',im2cx,near_dx,im2cy,near_dy])
    t1.float_format = '.1'
    t1.align = "r"
    print(t1)
    
    print('Suggested ACR Motions:')
    t2 = PrettyTable(['Motion','Delta (um)'])
    t2.add_row(['X',res_x])
    t2.add_row(['Y',res_y])
    t2.float_format = '.1'
    t2.align = "r"
    print(t2)
    
    
def calc_align_56(reftime=None,reftime2=None):
    '''
    Calculate pitch adjustments for mirrors MR1K2 through MR4K2 to align to
    the golden trajectory on IM5K2 and IM6K2. Uses saved PPM_screen hdf5 files.
    
    By default uses most recent PPM_screen hdf5 files.
    
    Can reference older hdf5 files by supplying timestamps for the file in
    elog format, e.g. 'Jun/20/2024 20:29:38', which returns the file saved
    closest to that timestamp.
    
    If only one timestamp is provided, uses the same timestamp for IM5K2 and IM6K2

    Parameters
    ----------
    reftime : str, optional
        Timestamp for IM5K2 file. The default is None.
    reftime2 : str, optional
        Timestamp for IM6K2 file. The default is None.

    Returns
    -------
    None.

    '''
    trajectories_dir = trajectory_data_dir
    if reftime is not None and reftime2 is None:
        reftime2 = reftime
    
    
    '''
    Response matrices: each element is how far in um the beam moved on a given
    imager for a 1 urad motion.
    Colummns: mirrors, rows: imagers.
    '''
    R_x = np.array([[-28,12],[24,24]]) #MR1K2, MR3K2
    R_y = np.array([[-9.3,-10.5],[-13,-25]]) #MR2K2, MR4K2
    
    #Get PPM_screen reference position
    ref_im5cx = EpicsSignal('IM5K2:PPM:CAM:X_RTCL_CTR').get()
    ref_im5cy = EpicsSignal('IM5K2:PPM:CAM:Y_RTCL_CTR').get()
    ref_im6cx = EpicsSignal('IM6K2:PPM:CAM:X_RTCL_CTR').get()
    ref_im6cy = EpicsSignal('IM6K2:PPM:CAM:Y_RTCL_CTR').get()
    
    #Get centroids from hdf5 files
    h5im5file=find_newest_file(trajectories_dir,'IM5K2',reftime)
    h5im6file=find_newest_file(trajectories_dir,'IM6K2',reftime2)
    print('Loaded IM5K2 data from ' + h5im5file)
    print('Loaded IM6K2 data from ' + h5im6file)
    im5cx,im5cy=loadCentroid(os.path.join(trajectories_dir,h5im5file))
    im6cx,im6cy=loadCentroid(os.path.join(trajectories_dir,h5im6file))

    #Calculate position deltas
    near_dx = (im5cx-ref_im5cx)
    near_dy = (im5cy-ref_im5cy)
    far_dx  = (im6cx-ref_im6cx)
    far_dy  = (im6cy-ref_im6cy)
    dx = np.transpose(np.array([[near_dx,far_dx]]))
    dy = np.transpose(np.array([[near_dy,far_dy]]))
    
    #Calculate angular deviations
    dtheta_x = -1*np.linalg.solve(R_x,dx)
    dtheta_y = -1*np.linalg.solve(R_y,dy)
    
    #Calculate new mirror positions
    MR1K2_pi = EpicsSignal('MR1K2:SWITCH:MMS:PITCH.RBV').get()+dtheta_x[0][0]
    MR2K2_pi = EpicsSignal('MR2K2:FLAT:MMS:PITCH.RBV').get()+dtheta_y[0][0]
    MR3K2_pi = EpicsSignal('MR3K2:KBH:MMS:PITCH.RBV').get()+dtheta_x[1][0]
    MR4K2_pi = EpicsSignal('MR4K2:KBV:MMS:PITCH.RBV').get()+dtheta_y[1][0]
    
    #Print results
    t1 = PrettyTable(['Imager','X_0 (um)','dX (um)','Y_0 (um)','dY (um)'])
    t1.add_row(['IM5K2',im5cx,near_dx,im5cy,near_dy])
    t1.add_row(['IM6K2',im6cx,far_dx,im6cy,far_dy])
    t1.float_format = '.1'
    t1.align = "r"
    print(t1)
    print('Suggested Mirror Motions:')
    t2 = PrettyTable(['Mirror','dTheta (urad)','New Pitch (urad)'])
    t2.add_row(['MR1K2',dtheta_x[0][0],MR1K2_pi])
    t2.add_row(['MR2K2',dtheta_y[0][0],MR2K2_pi])
    t2.add_row(['MR3K2',dtheta_x[1][0],MR3K2_pi])
    t2.add_row(['MR4K2',dtheta_y[1][0],MR4K2_pi])
    t2.float_format = '.1'
    t2.align = "r"
    print(t2)
    print('(Note: New Pitch based on current mirror positions)')


def calc_align_45(reftime=None,reftime2=None):
    '''
    Calculate pitch adjustments for mirrors MR1K2 through MR4K2 to align to
    the golden trajectory on IM4K2 and IM5K2. Uses saved PPM_screen hdf5 files.
    
    By default uses most recent PPM_screen hdf5 files.
    
    Can reference older hdf5 files by supplying timestamps for the file in
    elog format, e.g. 'Jun/20/2024 20:29:38', which returns the file saved
    closest to that timestamp.
    
    If only one timestamp is provided, uses the same timestamp for IM4K2 and IM5K2

    Parameters
    ----------
    reftime : str, optional
        Timestamp for IM4K2 file. The default is None.
    reftime2 : str, optional
        Timestamp for IM5K2 file. The default is None.

    Returns
    -------
    None.

    '''
    trajectories_dir = trajectory_data_dir
    if reftime is not None and reftime2 is None:
        reftime2 = reftime
    
    
    '''
    Response matrices: each element is how far in um the beam moved on a given
    imager for a 1 urad motion.
    Colummns: mirrors, rows: imagers.
    '''
    R_x = np.array([[-36.5,4.5],[33,12]]) #MR1K2, MR3K2
    R_y = np.array([[-5.3,-1.4],[-2.4,-10.5]]) #MR2K2, MR4K2
    
    #Get PPM_screen reference position
    ref_im4cx = EpicsSignal('IM4K2:PPM:CAM:X_RTCL_CTR').get()
    ref_im4cy = EpicsSignal('IM4K2:PPM:CAM:Y_RTCL_CTR').get()
    ref_im5cx = EpicsSignal('IM5K2:PPM:CAM:X_RTCL_CTR').get()
    ref_im5cy = EpicsSignal('IM5K2:PPM:CAM:Y_RTCL_CTR').get()
    
    #Get centroids from hdf5 files
    h5im4file=find_newest_file(trajectories_dir,'IM4K2',reftime)
    h5im5file=find_newest_file(trajectories_dir,'IM5K2',reftime2)
    print('Loaded IM4K2 data from ' + h5im4file)
    print('Loaded IM5K2 data from ' + h5im5file)
    im4cx,im4cy=loadCentroid(os.path.join(trajectories_dir,h5im4file))
    im5cx,im5cy=loadCentroid(os.path.join(trajectories_dir,h5im5file))

    #Calculate position deltas
    near_dx = (im4cx-ref_im4cx)
    near_dy = (im4cy-ref_im4cy)
    far_dx  = (im5cx-ref_im5cx)
    far_dy  = (im5cy-ref_im5cy)
    dx = np.transpose(np.array([[near_dx,far_dx]]))
    dy = np.transpose(np.array([[near_dy,far_dy]]))
    
    #Calculate angular deviations
    dtheta_x = -1*np.linalg.solve(R_x,dx)
    dtheta_y = -1*np.linalg.solve(R_y,dy)
    
    #Calculate new mirror positions
    MR1K2_pi = EpicsSignal('MR1K2:SWITCH:MMS:PITCH.RBV').get()+dtheta_x[0][0]
    MR2K2_pi = EpicsSignal('MR2K2:FLAT:MMS:PITCH.RBV').get()+dtheta_y[0][0]
    MR3K2_pi = EpicsSignal('MR3K2:KBH:MMS:PITCH.RBV').get()+dtheta_x[1][0]
    MR4K2_pi = EpicsSignal('MR4K2:KBV:MMS:PITCH.RBV').get()+dtheta_y[1][0]
    
    #Print results
    t1 = PrettyTable(['Imager','X_0 (um)','dX (um)','Y_0 (um)','dY (um)'])
    t1.add_row(['IM4K2',im4cx,near_dx,im4cy,near_dy])
    t1.add_row(['IM5K2',im5cx,far_dx,im5cy,far_dy])
    t1.float_format = '.1'
    t1.align = "r"
    print(t1)
    print('Suggested Mirror Motions:')
    t2 = PrettyTable(['Mirror','dTheta (urad)','New Pitch (urad)'])
    t2.add_row(['MR1K2',dtheta_x[0][0],MR1K2_pi])
    t2.add_row(['MR2K2',dtheta_y[0][0],MR2K2_pi])
    t2.add_row(['MR3K2',dtheta_x[1][0],MR3K2_pi])
    t2.add_row(['MR4K2',dtheta_y[1][0],MR4K2_pi])
    t2.float_format = '.1'
    t2.align = "r"
    print(t2)
    print('(Note: New Pitch based on current mirror positions)')



def calc_align_S1(reftime=None):
    '''
    Calculate pitch adjustments for MR1K1 and SP1K1_g to align to
    the golden trajectory on IM1K1 and the exit slit. Uses saved PPM_screen hdf5 files.
    ****Assumes beam is already aligned onto exit slit.****
    
    By default uses most recent PPM_screen hdf5 files.
    
    Can reference older hdf5 files by supplying timestamps for the file in
    elog format, e.g. 'Jun/20/2024 20:29:38', which returns the file saved
    closest to that timestamp.

    Parameters
    ----------
    reftime : str, optional
        Timestamp for IM1K2 file. The default is None.

    Returns
    -------
    None.

    '''
    trajectories_dir = trajectory_data_dir
    
    '''
    Response matrices: each element is how far in um the beam moved on a given
    imager for a 1 urad motion.
    Colummns: mirrors, rows: imagers.
    '''
    R_y = np.array([[-15,-8],[120,75]]) #MR1K1, SP1K1_g
    
    #Get PPM_screen reference position
    ref_im1cy = EpicsSignal('IM1K2:PPM:CAM:Y_RTCL_CTR').get()
    
    #Get centroids from hdf5 files
    h5im1file=find_newest_file(trajectories_dir,'IM1K2',reftime)
    print('Loaded IM1K2 data from ' + h5im1file)
    im1cx,im1cy=loadCentroid(os.path.join(trajectories_dir,h5im1file))

    #Calculate position deltas
    far_dy = (im1cy-ref_im1cy)
    near_dy = 0
    dy = np.transpose(np.array([[near_dy,far_dy]]))
    
    #Calculate angular deviations
    dtheta_y = -1*np.linalg.solve(R_y,dy)
    
    #Calculate new mirror positions
    MR1K1_pi = EpicsSignal('MR1K1:BEND:MMS:PITCH.RBV').get()+dtheta_y[0][0]
    SP1K1_g_pi = EpicsSignal('SP1K1:MONO:MMS:G_PI.RBV').get()+dtheta_y[1][0]
    
    #Print results
    t1 = PrettyTable(['Imager','Y_0 (um)','dY (um)'])
    t1.add_row(['IM1K2',im1cy,far_dy])
    t1.float_format = '.1'
    t1.align = "r"
    print(t1)
    print('Suggested Mirror Motions:')
    t2 = PrettyTable(['Mirror','dTheta (urad)','New Pitch (urad)'])
    t2.add_row(['MR1K1',dtheta_y[0][0],MR1K1_pi])
    t2.add_row(['SP1K1_g_pi',dtheta_y[1][0],SP1K1_g_pi])
    t2.float_format = '.1'
    t2.align = "r"
    print(t2)
    print('(Note: New Pitch based on current mirror positions)')
