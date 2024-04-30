import logging
import h5py
import pandas as pd
import time
from epics import caget, caget_many, PV
import matplotlib.pyplot as plt
import numpy as np
from threading import Thread
from rix.db import camviewer, RE
from pcdsdevices.areadetector import plugins
from pcdsdevices.slits import PowerSlits
from pcdsdevices.pim import PPM
from ophyd import EpicsSignalRO, EpicsSignal, Device
from ophyd import Component as Cpt
from bluesky.plans import scan, rel_scan, grid_scan, list_scan
from bluesky.plan_stubs import mv
from bluesky import RunEngine
from bluesky.callbacks.best_effort import BestEffortCallback

logger = logging.getLogger(__name__)

GMD = 'EM1K0:GMD:HPS:AvgPulseIntensity'
XGMD = 'EM2K0:XGMD:HPS:AvgPulseIntensity'

PGMD = 'EM1K0:GMD:HPS:milliJoulesPerPulse'
PXGMD = 'EM2K0:XGMD:HPS:milliJoulesPerPulse'

PPM_EXT = ':PPM:SPM:VOLT_BUFFER_RBV'
PPM_PATH='/cds/home/opr/rixopr/experiments/ppm_data/'

class CamH5:
    _camera = None
    _collecting = False
    _writing = False
    _path = None
    _file_name = None
    _images = 10

    @property
    def camera(self):
        return self._camera

    @camera.setter
    def camera(self, camera):
        try:
            self._camera = getattr(camviewer, camera)
        except AttributeError as e:
            logger.warning(f'{camera} is not a valid camera: {e}')

    @property
    def path(self):
        return self._path

    @path.setter
    def path(self, path):
        self._path = path

    @property
    def file_name(self):
        return self._file_name

    @file_name.setter
    def file_name(self, file_name):
        self._file_name = file_name

    @property
    def collecting(self):
        return self._collecting

    @collecting.setter
    def collecting(self, collecting):
        self._collecting = collecting

    @property
    def writing(self):
        return self._writing

    @writing.setter
    def writing(self, writing):
        self._writing = writing

    @property
    def images(self):
        return self._images

    @images.setter
    def images(self, images):
        self._images = images

    def collect(self):
        """Collect images and save using hdf51 plugin
        Returns file name
        """
        if not self.camera:
            logger.warning('You have not specified a camera, exiting')
            return

        if 'opal' in self.camera.cam.model.get():
            cam_type = 'opal'
        else:
            cam_type = 'gige'

        if not self.path:
            self.path = f'/reg/d/iocData/ioc-{self.camera.name}-{cam_type}/'
      
        # Check path
        self.camera.hdf51.file_path.put(self.path)
        if not self.camera.hdf51.file_path_exists.get():
            logger.warning(f'{self.path} does not exist, stopping')
            return

        if not self.file_name:
            self.file_name = f'{self.camera.name}-{int(time.time())}'

        self.camera.hdf51.file_name.put(self.file_name)
        # Put all the standard settings
        self.camera.hdf51.file_template.put('%s%s_%03d.h5')
        self.camera.hdf51.num_capture.put(self.images)
        self.camera.hdf51.auto_save.put(True)
        self.camera.hdf51.file_write_mode.put('Capture')
        self.camera.hdf51.enable.put('Enabled')
        self.camera.hdf51.capture.put('Capture')
        collect_uid = self.camera.hdf51.capture.subscribe(self._collecting_cb)
        write_uid = self.camera.hdf51.write_file.subscribe(self._writing_cb)
        logger.info('Starting HDF5 image collection')

        # Wait for initial callback, I know there's a better way
        time.sleep(0.1)
        self.collecting = True
        self.writing = True
        while self.collecting:
            num_captured = self.camera.hdf51.num_captured.get()
            if num_captured >= self.images:
                break
            time.sleep(0.1)
            logger.info(f'Collected {self.camera.hdf51.num_captured.get()} images')

        self.camera.hdf51.capture.unsubscribe(collect_uid)
        logger.info('finished collecting, writing file')
        while self.writing:
            time.sleep(0.1)

        self.camera.hdf51.write_file.unsubscribe(write_uid)
        logger.info(f'wrote all data to {self.path}{self.file_name}')
        self.camera.hdf51.enable.put('Disabled')
        return f'{self.path}{self.file_name}'

    def _writing_cb(self, value, **kwargs):
        """Get a callback when writing changes"""
        self.writing = value

    def _collecting_cb(self, value, **kwargs):
        """Get a callback for collecting changes"""
        self.collecting = value

def h5_img_collect(camera, images=10, path=None, file_name=None):
    """This method is to simplify a call to camviewer hdf51 plugin.
    Capture number of images and save as hdf5 file to path and file_name
    Parameters:
    ----------
    camera: camviewer camera object
       Example is ('im1k2').  The motor you'd like to scan

    images: int (default: 10)
        Number of images to collect and save in hdf5 file

    path: str (default: None)
        If you don't specify the path, will try to create
        based on /reg/d/iocData/ioc-<cam>-gige/.  
        This only works for im1k2-6k2 for now

    file_name: str (default: None)
        If not specified, we will create in form of <cam>-<int(epoch time)>
    """
    c = CamH5()
    c.camera = camera
    c.images = images
    c.path = path
    c.file_name = file_name
    c.collect()

class PPMRecorder:
    _data = []
    _gmd_data = []
    _xgmd_data = []
    _ppm = 'im1k2'
    _collection_time = 60

    @staticmethod
    def ppms():
        return PPMS

    @property
    def ppm(self):
        """Name of ppm"""
        return self._ppm

    @ppm.setter
    def ppm(self, ppm):
        self._ppm = ppm

    @property
    def collection_time(self):
        """Time for collection"""
        return self._collection_time

    @collection_time.setter
    def collection_time(self, ct):
        try:
            self._collection_time = float(ct)
        except:
            logger.warning('collection time must be number')

    @property
    def data(self):
        return self._data

    @property
    def gmd_data(self):
        return self._gmd_data

    @property
    def xgmd_data(self):
        return self._xgmd_data

    def clear_data(self):
        self._data = []
        self._gmd_data = []
        self._xgmd_data = []

    def collect(self):
        if self.data:
            logger.info('Found leftover data, clearing')
            self.clear_data()

        logger.info(f'Starting PPM scan for {self.ppm}')
        ppm_obj = EpicsSignalRO(self.ppm.upper()+PPM_EXT)
        #print('getting ', ppm_obj.get())
        ppm_obj.wait_for_connection(timeout=1.0)
        uid = ppm_obj.subscribe(self.data_cb)
        time.sleep(self.collection_time)  # Threading?
        logger.info('Done collecting PPM data')
        ppm_obj.unsubscribe(uid)

    def data_cb(self, value, **kwargs):
        """Collect all the data"""
        self.data.extend(value)
        self.gmd_data.append(caget(GMD))
        self.xgmd_data.append(caget(XGMD))

    def downsample(self, downsample=100, ave=True):
        """General method for downsampling in even intervals, could be faster"""
        if not self.data:
            logger.warning('Trying to downsample empty dataset')
            return
        logger.info(f'Downsampling data by a factor of {downsample}')
        if ave:
            segments = range(int(len(self.data) / downsample))
            self._data = [np.mean(self.data[i*downsample:(i+1)*downsample]) for i in segments]
        else:
            self._data = self.data[::downsample]

    def plot(self):
        plt.title(f'time plot of {self.ppm}')
        plt.plot(self.data)

    def save_hdf5(self, file_name=None):
        if not file_name:
            file_name = f'{self.ppm}-{int(time.time())}.h5'
        location = ''.join([PPM_PATH, file_name])
        hf = h5py.File(location, 'w')
        hf.create_dataset('ppm_data', data=self.data)
        hf.create_dataset('gmd_data', data=self._gmd_data)
        hf.create_dataset('xgmd_data', data=self._xgmd_data)
        hf.close()
        logger.info(f'wrote all data to {location}')

def ppm_scan(ppm='im1k2', time=60, downsample=100, plot=True, save=True):
    """General PPM Recorder Scan with basic steps that Phil uses

    Parameters:
    ----------
    ppm: str (default: 'im1k2')
        The root name of the PPM you'd like to record for

    time: int (default: 60)
        The amount of time you would like to record for in seconds

    downsample: int (default: 100)
        The amount you would like to downsample.  Averages points
        in between

    plot: bool (default: True)
        If you'd like to have show a plot of the PPM data

    save: bool (default: True)
        If you'd like to save the data to default location
    """
    recorder = PPMRecorder()
    recorder.ppm = ppm
    recorder.collection_time = time
    recorder.collect()
    if plot:
        recorder.plot()

    if downsample > 1:
        recorder.downsample(downsample=downsample)

    if save:
        recorder.save_hdf5()

