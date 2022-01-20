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

# Simulation tools
from ophyd.positioner import SoftPositioner
from ophyd.sim import motor1, motor2, det1
import bluesky.plan_stubs as bps

logger = logging.getLogger(__name__)

PPMS = [
    'im1k1',
    'im2k1',
    'im1k2'
]

PPM_EXT = ':PPM:SPM:VOLT_BUFFER_RBV'

CAMS = [
    'im1k1',
    'im2k1',
    'im1k2',
    'mono-04',
    'sl1k2'
]

EPICSARCH = [
    'EM2K0:XGMD:HPS:KeithleySum',
    'IM2K4:PPM:SPM:VOLT_RBV',
    'IM3K4:PPM:SPM:VOLT_RBV',
    'IM4K4:PPM:SPM:VOLT_RBV',
    'IM5K4:PPM:SPM:VOLT_RBV',
    'MR1K4:SOMS:MMS:XUP.RBV',
    'MR1K4:SOMS:MMS:YUP.RBV',
    'MR1K4:SOMS:MMS:PITCH.RBV',
    'MR2K4:KBO:MMS:X.RBV'
]

GMD = 'EM1K0:GMD:HPS:AvgPulseIntensity'
XGMD = 'EM2K0:XGMD:HPS:AvgPulseIntensity'

PGMD = 'EM1K0:GMD:HPS:milliJoulesPerPulse'
PXGMD = 'EM2K0:XGMD:HPS:milliJoulesPerPulse'

PPM_PATH = '/cds/home/opr/rixopr/experiments/x43518/ppm_data/'
CAM_PATH = '/cds/home/opr/rixopr/experiments/x43518/cam_data/'
SCAN_PATH = '/cds/home/opr/rixopr/experiments/x43518/scan_data/'

class PPMRecorder:
    _data = []
    _gmd_data = []
    _xgmd_data = []
    _ppm = 'im2k4'
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
        #self.gmd_data.append(caget(GMD))
        #self.xgmd_data.append(caget(XGMD))

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

        if not self.path:
            self.path = f'/cds/data/iocData/ioc-kfe-mono-gige04/'    ##iocData location for MONO-04 camera 
            #self.path = f'/reg/d/iocData/ioc-{self.camera.name}-gige/'
        
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

class CamTools:
    _camera = camviewer.im1k0
    _cam_type = 'opal'
    _path = CAM_PATH
    _images = []
    _timestamps = []
    _cb_uid = None
    _num_images = 10
    _state = 'idle'

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
    def height(self):
        if self.camera:
            return self.camera.image2.height.get()
        else:
            return None

    @property
    def width(self):
        if self.camera:
            return self.camera.image2.width.get()
        else:
            return None

    @property
    def file_path(self):
        return self._path

    @file_path.setter
    def file_path(self, path):
        # We'll have to validate or make path
        self._path = path

    @property
    def timestamps(self):
        return self._timestamps

    @property
    def images(self):
        return self._images

    @property
    def num_images(self):
        return self._num_images

    @num_images.setter
    def num_images(self, num):
        try:
            self._num_images = int(num)
        except:
            logger.warning('number of images must be castable as int')

    @staticmethod
    def camera_names():
        return CAMS

    def clear_data(self):
        self._images = []
        self._timestamps = []

    def collect(self, n_img):
        """General collection method.  If n_img specified, set
        property as well"""
        if not self.num_images:
            if n_img:
                self.num_images = n_img
            else:
                logger.warning('You need to specify number of images to collect')

        if self.images:
            logger.info('Leftover image data, clearing')
            self._images = []
            self._timestamps = []

        if not self.camera:
            logger.warning('You have not specified a camera')        
            return

        #if self.camera.cam.acquire.get() is not 1:
        #    logger.info('Camera has no rate, starting acquisition')
        #    self.camera.cam.acquire.put(1)

        cam_model = self.camera.cam.model.get()
        # TODO: Make dir with explicit cam model
        if 'opal' in cam_model:
            self._cam_type = 'opal'
        else:
            self._cam_type = 'gige'
        
        logger.info(f'Starting data collection for {self.camera.name}')
        #self._cb_uid = self.camera.image2.array_data.subscribe(self._data_cb)
        self._get_data()

    def _get_data(self):
        delay = 0.1
        while len(self.images) < self.num_images:
            img = self.camera.image2.array_data.get()
            ts = self.camera.image2.array_data.timestamp
            if len(self.images) == 0:
                self.images.append(np.reshape(img, (self.height, self.width)))
                self.timestamps.append(ts)
            if not np.array_equal(self.images[-1], img):
                print('getting image: ', len(self.images))
                self.images.append(np.reshape(img, (self.height, self.width)))
                self.timestamps.append(ts)
                print('delay ', time.time() - ts)
                time.sleep(delay)
            else:
                time.sleep(0.01)   
        logger.info('done collecting image data ')     

    def _data_cb(self, **kwargs):
        """Area detector cbs does not know thyself"""
        obj = kwargs.get('obj')
        arr = obj.value
        ts = obj.timestamp
        self.images.append(np.reshape(arr, (self.height, self.width)))
        self.timestamps.append(ts)
        logger.info('received image: ', len(self.images), time.time() - ts)
        if len(self.images) >= self.num_images:
            logger.info('We have collected all our images, stopping collection')
            self.camera.image2.array_data.unsubscribe(self._cb_uid)

    def plot(self):
        """Let people look at collected images"""
        if not self.images:
            info.warning('You do not have any images collected')

        num_images = len(self.images)
        img_sum = self.images[0]
        if num_images is 1:
            plt.imshow(img_sum)
        else:
            for img in self.images[1:]:
                img_sum += img
            plt.imshow(img_sum / num_images)

    def save(self):
        file_name = f'{self.camera.name}-{int(time.time())}.h5'
        location = ''.join([self._path, self._cam_type, '/', file_name])
        hf = h5py.File(location, 'w')
        hf.create_dataset('image_data', data=self.images)
        hf.create_dataset('timestamps', data=self.timestamps)
        hf.close()
        logger.info(f'wrote all image data to {location}')
        return location
#class SimPlans:


class SimEvrScan:
    _motor = motor1
    _evr = SoftPositioner(name='EVR:TDES')
    _RE = RunEngine({})
    _scan_id = None
    
    @property
    def scan_id(self):
        return self._scan_id

    @scan_id.setter
    def scan_id(self, uid):
        self._scan_id = uid

    def start(self, evr_start, evr_stop, evr_steps, motor_start, motor_stop, motor_steps):
        """Set TDES, then scan the x motor"""
        return grid_scan([det1],
                         self._evr, evr_start, evr_stop, evr_steps,
                         self._motor, motor_start, motor_stop, motor_steps)

class BYKIKS(Device):
    abort_enable = Cpt(EpicsSignal, 'IOC:IN20:EV01:BYKIKS_ABTACT')
    abort_every_n = Cpt(EpicsSignal, 'IOC:IN20:EV01:BYKIKS_ABTPRD')
    burst_mode_enable = Cpt(EpicsSignalRO, 'IOC:BSY0:MP01:REQBYKIKSBRST')
    shots_to_burst = Cpt(EpicsSignal, 'PATT:SYS0:1:BYKIKSCNTMAX')
    request_burst =  Cpt(EpicsSignal, 'PATT:SYS0:1:BYKIKSCTRL')

class User:
    _cam_tools = CamTools()    
#    _sim_cs = SimEvrScan()
    _bykiks = BYKIKS('', name='bykiks', read_attrs=['burst_mode_enable'])

    @property
    def bykiks(self):
        return self._bykiks

    @staticmethod
    def ppm_scan(ppm='im2k4', time=60, downsample=100, plot=True, save=True):
        """General PPM Recorder Scan with basic steps that Phil uses

        Parameters:
        ----------
        ppm: str (default: 'im2k4')
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

    @staticmethod
    def h5_img_collect(camera, images=10, path=None, file_name=None):
        """This method is to simplify a call to camviewer hdf51 plugin.
        Capture number of images and save as hdf5 file to path and file_name
        Parameters:
        ----------
        camera: camviewer camera object
            Example is ('im2k4').  The motor you'd like to scan

        images: int (default: 10)
            Number of images to collect and save in hdf5 file

        path: str (default: None)
            If you don't specify the path, will try to create
            based on /reg/d/iocData/ioc-<cam>-gige/.  
            This only works for im2k4-5k4 for now

        file_name: str (default: None)
            If not specified, we will create in form of <cam>-<int(epoch time)>
        """
        c = CamH5()
        c.camera = camera
        c.images = images
        c.path = path
        c.file_name = file_name
        c.collect()

    def ascan(self, motor, start, end, nsteps, nEvents, record=None, use_l3t=False):
        self.cleanup_RE()
        currPos = motor.wm()
        daq.configure(nEvents, record=record, controls=[motor], use_l3t=use_l3t)
        try:
            RE(scan([daq], motor, start, end, nsteps))
        except Exception:
            logger.debug('RE Exit', exc_info=True)
        finally:
            self.cleanup_RE()
        motor.mv(currPos)

    def abs_scan(self, mot, start, stop, steps):
        """This simply moves a devices from absolute start
        to stop with number of steps
        Parameters:
        ----------
        dev: pcdsdevice EpicsMotor like object
            Example is (mr3k4_kbo.x).  The motor you'd like to scan

        start: float/int
            Starting position for motor scan. The amount of time you would like to record for in seconds

        stop: float/int
            The amount you would like to downsample.  Averages points

        steps: int
            Number of steps
        """
        RE(scan([], mot, start, stop, steps))      

    #def rel_scan(self, mot, low, high, steps):
        """This is a relative scan from current position
        Parameters:
        ----------
        dev: pcdsdevice EpicsMotor like object
            Example is (mr3k4_kbo.x).  The motor you'd like to scan

        low: float/int
            Amount below current position you'd like to move

        high: float/int
            Amount above current position you'd like to move

        steps: int
            Number of steps
        """          
        #RE(rel_scan([], mot, low, high, steps))

    @property
    def cam_tools(self):
        return self._cam_tools

    def scanner(self, mov_pv, start, stop, steps, tol, cam, images=10, rbck_ext='.RBV'):
        """General scanner for now because we want to take images"""
        steps = np.linspace(start, stop, steps)
        times = []
        image_files = []
        self.cam_tools.camera = cam
        try:
            pv_obj = PV(mov_pv)
            pv_rbck = PV(mov_pv + rbck_ext)
        except:
            logger.warning('Unable to connect to {mov_pv}')
        df = pd.DataFrame()
        for step in steps:
            pv_obj.put(step)
            while abs(pv_rbck.get() - step) > tol:
                time.sleep(0.1)
            logger.info(f'Stepper reached {step}, collecting data')
            times.append(time.time())
            self.cam_tools.num_images = images
            self.cam_tools.collect(images)
            f = self.cam_tools.save()
            image_files.append(f)
            df = df.append(pd.DataFrame([caget_many(EPICSARCH)], columns=EPICSARCH), ignore_index=True)
        df = df.assign(times=times)
        df = df.assign(image_files=image_files)
        file_name = f'{mov_pv}-{int(time.time())}.h5'
        location = SCAN_PATH + file_name
        df.to_hdf(location, key='metadata')
        logger.info(f'wrote all data to {location}')
    
    @staticmethod
    def scan_motor_img(motor, start, stop, steps, camera, images=10):
        """Method to scan a motor and save images and epics data at each position
        Parameters:
        ----------
        motor: pcdsdevice EpicsMotor like object
            Example is (mr3k4_kbo.x).  The motor you'd like to scan in x

        start: float
            Absolute x motor starting position

        stop: float
            Absolute x motor ending position

        steps: int
            Number of steps for the x scan

        camera: str
            Camera name in lower case format (i.e. 'im2k4')

        images: int
            Number of images to collect at each motor position
        """
        df = pd.DataFrame()
        motor_vals = np.linspace(start, stop, steps)
        c = CamH5()
        c.camera = camera
        c.images = images
        image_files = []
        times = []
        logger.info(f'Scanning {motor.name} over {motor_vals}')
        for val in motor_vals:
            motor.mv(val, wait=True)
            filename = c.collect()
            image_files.append(filename)
            times.append(time.time())
            logger.info(f'Collected camera images and saved to {filename}')
            df = df.append(pd.DataFrame([caget_many(EPICSARCH)], columns=EPICSARCH), ignore_index=True)
        df = df.assign(times=times)
        df = df.assign(image_files=image_files)
        file_name = f'{motor.name}-{int(time.time())}.h5'
        location = ''.join([SCAN_PATH, file_name])
        df.to_hdf(location, key='metadata')
        logger.info(f'wrote all data to {location}')

    @staticmethod
    def imprint_scan(x_motor, x_start, x_stop, x_steps, y_motor, y_start, y_stop, y_steps):
        """Moves motors in a grid and fires one pulse from bykiks at each position,
        y is slow parameter, x is fast.  So it starts at x_start, y_start, then scans
        through x, then makes a step in y and continues.  You must call ACR for SXR burst mode

        Parameters:
        ----------
        x_motor: pcdsdevice EpicsMotor like object
            Example is (mr3k4_kbo.x).  The motor you'd like to scan in x

        x_start: float
            Absolute x motor starting position

        x_stop: float
            Absolute x motor ending position

        x_steps: int
            Number of steps for the x scan

        y_motor: pcdsdevice EpicsMotor like object
            Example is (mr3k4_kbo.y).  The motor you'd like to scan in y

        y_start: float
            Absolute y motor starting position

        y_stop: float
            Absolute y motor ending position

        y_steps: int
            Number of steps for the y scan
        """
        initial_x_pos = x_motor.user_setpoint.get()
        initial_y_pos = y_motor.user_setpoint.get()
        bykiks = BYKIKS('', name='bykiks', read_attrs=['burst_mode_enable'])
        if not bykiks.burst_mode_enable.get():
            logger.warning('Burst Mode not enabled, call ACR.  Exiting')
            #return
        bykiks.shots_to_burst.put(1)
        x_vals = np.linspace(x_start, x_stop, x_steps)
        y_vals = np.linspace(y_start, y_stop, y_steps)
        for y_val in y_vals:
            y_motor.mv(y_val, wait=True)
            for x_val in x_vals:
                x_motor.mv(x_val, wait=True)
                logger.info('Bursting BYKIKS single shot')
                bykiks.request_burst.put(1)
                time.sleep(0.1)  # Consider how to do with callbacks

        logger.info('Restoring initial positions')
        x_motor.mv(initial_x_pos, wait=True)
        y_motor.mv(initial_y_pos, wait=True)
        logger.info('Motors Restored, finished with scan')
