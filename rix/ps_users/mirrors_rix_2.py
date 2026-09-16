#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
###############################################################################
RIX Mirror Check Code
Run mirror check by first running:
mirrors = init_mirrors()

then run a given scan with:
mirrors[name].run_test()

Modified DJH April 29 2024

Classes:
--------
- MiscSignals(BaseInterface, Device):
    Represents miscellaneous signals used at soft-xray beamlines..
    - Attributes:
        * attenuator (EpicsSignalRO): Attenuator transmission for KFE
        * attenuator_SP (EpicsSignalRO): Attenuator setpoint for KFE
        * gmd_avg (EpicsSignalRO): GMD average pulse energy
        * gmd_per_pulse (EpicsSignalRO): GMD per pulse energy
        * xgmd_avg (EpicsSignalRO): XGMD average pulse energy
        * xgmd_per_pulse (EpicsSignalRO): XGMD per pulse energy
        * rate (EpicsSignalRO): Rate signal for KFE.
        * photon_energy (EpicsSignalRO): Photon energy signal for KFE.
        * bundle (list): list of PVs read during scans
    - Functions:
        * check_attenuator(tolerance (float)):
- Mirror:
    Class representing mirror configurations and related objects.
    - Attributes:
        * name (str): Name of the mirror configuration.
        * beamline (str): Name of the beamline associated with the mirror.
        * imager_before (PPM): PPM (Power/Position Monitor) before the mirror.
        * imager_after (PPM): PPM after the mirror.
        * transmissionPV (EpicsSignalRO): Transmission signal for the mirror.
        * kfe_signals (MiscSignals): GMDs, etc.
        * mirror_objs (list): List of KBOMirror objects associated with the mirror.
        * output path (str): hdf5 file save directory for scan data
    - Functions:
        * collect_data(signals, duration): read data from PVs and return average
        * collect_mirror_positions(): get all mirror motor positions
        * save_dict_to_hdf5(file,data,group): save collected data to hdf5
        * wait_for_beam(target_rate): pause script until beam rate returns
        * run_test(scan_duration,do_wait,max_drift): run transmission test

init_mirrors: function to return dictionary of RIX mirror objects
- mirrors (dict):
    A dictionary containing predefined mirror configurations.
    

###############################################################################
'''
import dataclasses
import numpy as np
from ophyd import Component as Cpt
from ophyd import Device
from ophyd.signal import EpicsSignalRO, EpicsSignal
from pcdsdevices.interface import BaseInterface
from pcdsdevices.pim import PPM
from pcdsdevices.mirror import KBOMirror
from archapp.interactive import EpicsArchive

import datetime
import logging
import os
import sys
import time
import elog
import h5py

from . import mirror_check_dir

@dataclasses.dataclass
class MiscSignals(BaseInterface, Device):
    
    def __init__(self):
        self.attenuator = EpicsSignalRO("AT1K0:GAS:TRANS_RBV")
        self.attenuator_SP = EpicsSignalRO("AT1K0:GAS:TRANS_REQ_RBV")
        self.gmd_avg = EpicsSignalRO("EM1K0:GMD:HPS:AvgPulseIntensity")
        self.gmd_per_pulse = EpicsSignalRO("EM1K0:GMD:HPS:milliJoulesPerPulse")
        self.xgmd_avg = EpicsSignalRO("EM2K0:XGMD:HPS:AvgPulseIntensity")
        self.xgmd_per_pulse= EpicsSignalRO("EM2K0:XGMD:HPS:milliJoulesPerPulse")
        self.rate = EpicsSignalRO("TPG:SYS0:1:DST04:RATE")
        self.photon_energy = EpicsSignalRO("SIOC:SYS0:ML00:AO628")
        
        self.bundle = [self.gmd_avg,
                       self.gmd_per_pulse,
                       self.xgmd_avg,
                       self.xgmd_per_pulse,
                       self.attenuator,
		       self.photon_energy]
    
    def check_attenuator(self, tolerance=0.2):
        """
        Check the attenuator transmission.

        Parameters:
        -----------
        tolerance : float, optional
            Tolerance level for transmission check (default: 0.2).

        Returns:
        --------
        Tuple[bool, float, float]
            A tuple containing a boolean indicating pass/fail, attenuator
            transmission, and tolerance.
        """
        attenuator_transmission = self.attenuator.get()
        attenuator_setpoint = self.attenuator_SP.get()
        if np.abs(attenuator_setpoint - attenuator_transmission)/attenuator_setpoint <= tolerance:
            return (True, attenuator_transmission, tolerance*attenuator_setpoint)
        else:
            return (False, attenuator_transmission, tolerance*attenuator_setpoint)


def collect_data(signals, duration: float):
    """
    Collect data from a list of signals for a specified duration.

    Parameters:
    -----------
    signals : List[Signal]
        List of signals to collect data from.
    duration : float
        Duration of data collection in seconds.

    Returns:
    --------
    Dict[str, List]
        A dictionary containing collected data for each signal.
    """
    def _get_data(value, timestamp, **kwargs):
        obj = kwargs["obj"]
        if isinstance(value, np.ndarray):
            data[obj.name].extend(value)
        else:
            data[obj.name].append(value)

    data = {}
    uid = {}

    for signal in signals:
        data[signal.name] = []
        uid[signal.name] = signal.subscribe(_get_data)

    time.sleep(duration)

    for signal in signals:
        signal.unsubscribe(uid[signal.name])
        data[f"{signal.name}_mean"] = np.mean(data[signal.name])

    return data

class MotorGroup:
    def __init__(self, name, motor_objs):
        self.name = name
        self.motor_objs = motor_objs
    def get_positions(self,t=None):
        """
        Collect and return positions of mirror motors.

        Parameters:
        -----------
        mirror_obj : KBOMirror
            The mirror object to extract motor positions from.

        Returns:
        --------
        Dict[str, float]
            A dictionary containing motor names and their respective positions.
        """
        motor_positions = {}
        if t is not None:
            if isinstance(t,str):
                t1=datetime.datetime.strptime(t.strip(),'%b/%d/%Y %H:%M:%S')
            else:
                t1=datetime.datetime(*t)
            arch = EpicsArchive()
            logging.info("Get motor positions for {}".format(t1.isoformat()))
        else:
            logging.info("Get current motor positions")
            
        for motor_obj in self.motor_objs:
            positions = {}
            if hasattr(motor_obj, "position"):
                if t is not None:
                    print([motor_obj.name])
                    try:
                        pvname = getattr(motor_obj.user_readback.pvname)
                        archived = arch.get(pvname,t1,t1)
                        positions[motor_obj.name] = archived[0][1]
                    except:
                        positions[motor_obj.name] = np.nan
                else:
                    positions[motor_obj.name] = getattr(motor_obj, "position")
                    
            for keys in list(motor_obj._signals):
                motor = getattr(motor_obj, keys)
                if hasattr(motor, "position"):
                    if t is not None:
                        print([motor.name])
                        try:
                            pvname = motor.user_readback.pvname
                            archived = arch.get(pvname,t1,t1)
                            positions[motor.name] = archived[0][1]
                        except:
                            positions[motor.name] = np.nan
                    else:
                        positions[motor.name] = getattr(motor, "position")
            motor_positions.update(positions)
        
        return motor_positions
    def calc_archive_delta(self,t,t2=None):
        mpos1 = self.get_positions(t)
        mpos2 = self.get_positions(t2)
        
        motor_positions_delta = {}
        for k in mpos1.keys():
            try:
                motor_positions_delta[k] = mpos2[k]-mpos1[k]
            except:
                motor_positions_delta[k] = np.nan
        return motor_positions_delta
class Mirror(MotorGroup):
    """
    Class representing mirror configurations and related objects.

    Parameters:
    -----------
    name : str : Name of the mirror configuration.
    beamline : str :  Name of the beamline associated with the mirror.
    imager_before : PPM : PPM (Power/Position Monitor) before the mirror.
    imager_after : PPM : PPM after the mirror.
    attenuator : EpicsSignalRO
        Attenuator signal for the mirror.
    gmd : GMD
        GMD associated with the mirror.
    xgmd : XGMD
        XGMD associated with the mirror.
    transmission : EpicsSignalRO
        Transmission signal for the mirror.
    mirror_objs : list
        List of KBOMirror objects associated with the mirror.
    output_path : str
        The path to save the collected data.
    """
    def __init__(self,
                name: str,
                beamline: str,
                imager_before: PPM,
                imager_after: PPM,
                transmissionPV: EpicsSignalRO,
                kfe_signals: MiscSignals,
                mirror_objs: [KBOMirror],
                output_path: str,
                ):
        self.name = name
        self.beamline = beamline
        self.imager_before = imager_before
        self.imager_after = imager_after
        self.transmissionPV = transmissionPV
        self.kfe_signals = kfe_signals
        self.motor_objs = mirror_objs
        self.output_path = output_path
    
    def save_dict_to_hdf5(self, file, data, group="/"):
        """
        Recursively save a dictionary to an HDF5 file.

        Parameters:
        -----------
        file : h5py.File
            The HDF5 file to save data to.
        data : Dict
            Data to be saved to the HDF5 file.
        group : str, optional
            The group in the HDF5 file to save data (default: "/").

        Returns:
        --------
        None

        """
        for key, item in data.items():
            if isinstance(item, dict):
                self.save_dict_to_hdf5(file, item, group + key + "/")
            else:
                file.create_dataset(group + key, data=item)

    def wait_for_beam(self, target_rate):
        current_rate = self.kfe_signals.rate.get()
        while current_rate < target_rate:
            logging.info("waiting 10 more seconds for beam rate to go back to {} Hz (Last Check {} Hz) ...".format(target_rate, current_rate))
            time.sleep(10) 
            current_rate = self.kfe_signals.rate.get()
                    
    def run_test(self, scan_duration = 60.0, do_wait=True, drift_max = 0.05):
        """
        Start the mirror transmission check process.

        The process involves multiple steps, including checking attenuator
        transmission, collecting data, calculating deviation and transmission,
        and saving data to an HDF5 file, posting results to the electronic
        logbook, and saving the result to PV.


        scan_duration : float, optional
            The duration of each scan in seconds (default: 60.0).
        do_wait : bool
            Flag to wait for beam rate to return
        drift_max : float
            Maximum fractional GMD power drift to allow without aborting scan

        Returns:
        --------
        None
        """
        timestamp = time.time()
        dt = datetime.datetime.now().strftime("%Y-%m-%d--%H-%M-%S")

        operating_rate = self.kfe_signals.rate.get()
        logging.info(f"Operating rate: {operating_rate} Hz")
        before_init_target = self.imager_before.target.state.enum_strs[self.imager_before.target.state.get()]
        after_init_target = self.imager_after.target.state.enum_strs[self.imager_after.target.state.get()]
        
        
        signals_before = [*self.kfe_signals.bundle,
            self.imager_before.power_meter.raw_voltage_buffer,
            self.imager_before.power_meter.calibrated_mj]
        
        signals_after = [*self.kfe_signals.bundle,
            self.imager_after.power_meter.raw_voltage_buffer,
            self.imager_after.power_meter.calibrated_mj]
        
        logging.info("step #1: check attenuator transmission")
        status, attenuator_transmission, tolerance = self.kfe_signals.check_attenuator()
        if status is False:
            logging.fatal(
                "check stopped: attenuator transmission {} exceeds tolerance {}".format(
                    attenuator_transmission, tolerance
                )
            )

        logging.info("step #2: get and save mirror motors positions")
        mirror_positions = self.get_positions()

        logging.info("step #3: put power meter before mirror in")
        self.imager_before.target("POWERMETER")
        
        time.sleep(10)
        if do_wait: self.wait_for_beam(operating_rate)
        time.sleep(30)
        
        logging.info(f"step #4: collect data from imager before mirror for {scan_duration} seconds")
        data_before = collect_data(signals_before, scan_duration)

        logging.info("step #5: move power meter before out, power meter after in")
        self.imager_before.target("OUT")
        self.imager_after.target("POWERMETER")
        
        time.sleep(10)
        if do_wait: self.wait_for_beam(operating_rate)
        time.sleep(30)
        
        logging.info(f"step #6: collect data from imager after mirror for {scan_duration} seconds")
        data_after = collect_data(signals_after, scan_duration)

        logging.info("step #7: return imagers to initial condition")
        self.imager_before.target(before_init_target)
        self.imager_after.target(after_init_target)
        
        logging.info("step #8: calculate GMD drift and mirror transmission")
        #print(data_before.keys())
        photon_energy = data_before["SIOC:SYS0:ML00:AO628"]
        
        gmd_avg_before = data_before["EM1K0:GMD:HPS:milliJoulesPerPulse_mean"]    # noqa: E501
        gmd_avg_after = data_after["EM1K0:GMD:HPS:milliJoulesPerPulse_mean"]      # noqa: E501
        ppm_before = data_before[
            #f"{self.imager_before.name}_power_meter_raw_voltage_buffer_mean" 
            f"{self.imager_before.name}_power_meter_calibrated_mj_mean" # noqa: E501
        ]
        ppm_after = data_after[
            #f"{self.imager_after.name}_power_meter_raw_voltage_buffer_mean"  
            f"{self.imager_after.name}_power_meter_calibrated_mj_mean" # noqa: E501
        ]

        drift = 2*(gmd_avg_after - gmd_avg_before)/(gmd_avg_after + gmd_avg_before)
        transmission = (ppm_after/ppm_before)*(gmd_avg_before/gmd_avg_after)
        
        logging.info("GMD Before = {}".format(gmd_avg_before))
        logging.info("GMD After = {}".format(gmd_avg_after))
        logging.info("PPM Before = {}".format(ppm_before))
        logging.info("PPM After = {}".format(ppm_after))
        logging.info("transmission = {}".format(transmission))
        logging.info("power drift = {}".format(drift))
        logging.info("transmission = {}".format(transmission))

        if np.abs(drift) > drift_max:
            logging.fatal(f"beam power drift {drift} is larger than {drift_max}")
            sys.exit()


        data = {
            "datetime": dt,
            "timestamp": timestamp,
            "mirror_name": self.name,
            "mirror_positions": mirror_positions,
            "imager_before_mirror": self.imager_before.name,
            "imager_after_mirror": self.imager_after.name,
            "imager_before_mirror_data": data_before,
            "imager_after_mirror_data": data_after,
            "drift": drift,
            "transmission": transmission,
        }

        logging.info("step #9: store data into .h5 file")
        filepath = "{}/scans/{}".format(self.output_path, self.name)
        os.makedirs(filepath, exist_ok=True)
        hdf5_file_path = "{}/{}_{}.h5".format(
            filepath, self.name, data["datetime"]
        )
        with h5py.File(hdf5_file_path, "w") as hdf5_file:
            self.save_dict_to_hdf5(hdf5_file, data)

        logging.info("Data saved to {} successfully.".format(hdf5_file_path))

        logging.info("step #10: post scan results to elog")
        elog_obj = elog.HutchELog.from_registry()
        elog_obj.post(
            "{} transmission: {:.2f}. Photon Energy: {:.1f}. scan data path: {}".format(
                self.name, transmission, photon_energy[0], hdf5_file_path
            ),
            title="Mirror check",
            tags=[self.name],
        )

        logging.info("step #11: save result to PV")
        try:
            self.transmissionPV.put(transmission)
        except:
            logging.error("Failed to write to PV: {}".format(self.transmissionPV.name))
        return data


from rix.db import im2k0, im1k1, im2k1, im1k2, im2k2, im3k2, im4k2, im5k2, im6k2 # RIX imagers
from rix.db import mr1k1_bend, sp1k1_mono, mr1k2_switch, mr2k2_flat, mr3k2_kbh, mr4k2_kbv # RIX mirrors


def init_mirrors():
    '''
    Initialize RIX mirror objects for mirror transmission checks
    Returns list of mirror objects
    '''
    output_path = mirror_check_dir
    kfe_signals = MiscSignals()
    
    mirror_names = ["MR1K1", "SP1K1", "MR1K2", "MR2K2", "MR3K2", "MR4K2", "HUTCH","TEST"]
    pre_imagers  = [im2k0, im1k1, im2k1, im1k2, im2k2, im3k2, im1k2, im5k2]
    post_imagers = [im1k1, im2k1, im1k2, im2k2, im3k2, im4k2, im4k2, im6k2]
    mirror_objects = [[mr1k1_bend],
                      [sp1k1_mono],
                      [mr1k2_switch],
                      [mr2k2_flat],
                      [mr3k2_kbh],
                      [mr4k2_kbv],
                      [mr2k2_flat, mr3k2_kbh, mr4k2_kbv],
                      [mr4k2_kbv]]
    
    mirrors = {}
    
    for i in range(len(mirror_names)):
        mirrors[mirror_names[i]] = Mirror(mirror_names[i],
                                     "RIX",
                                     pre_imagers[i],
                                     post_imagers[i],
                                     EpicsSignal("RIX:{:}:Transmission".format(mirror_names[i])),
                                     kfe_signals,
                                     mirror_objects[i],
                                     output_path)
    return mirrors


def baselinePPMs(scan_duration = 60.0):
    '''
    Acquires background data on PPM power meters for baselining.
    Writes acquired background to offset PVs

    Parameters
    ----------
    scan_duration : float, optional
        Time (seconds) to acquire data. The default is 60.0.

    Returns
    -------
    None.

    '''
    imagers = [im1k1, im2k1, im1k2, im2k2, im3k2, im4k2, im5k2, im6k2]
    ppm_scalef = [1, 1, 1, 1, 1, 1, 1, 1]
    ppm_calmj = [.0624, .0625, .0513, .0670, .0503, .0584, .0574, -.0719]
    signals = []
    for i in imagers:
        signals.append(i.power_meter.raw_voltage_buffer)
        signals.append(i.power_meter.calibrated_mj)
    logging.info(f"Reading PPMs for {scan_duration} seconds")
    data = collect_data(signals, scan_duration)
    
    n=0
    for i in imagers:
        
        ppm_rawV= data[
            f"{i.name}_power_meter_raw_voltage_buffer_mean" 
        ]
        ppm_cal = data[
            f"{i.name}_power_meter_calibrated_mj_mean" # noqa: E501
        ]
        
        logging.info(f"{i.name} raw voltage: {ppm_rawV}")
        logging.info(f"{i.name} calibrated: {ppm_cal}")
        
        BLPV = EpicsSignal(i.name.upper()+":PPM:SPM:CALIB:OFFSET")
        scalePV = EpicsSignal(i.name.upper()+":PPM:SPM:CALIB:RATIO")
        calmjPV = EpicsSignal(i.name.upper()+":PPM:SPM:CALIB:MJ_RATIO")
        try:
            BLPV.put(-1*ppm_rawV)
            logging.info("Wrote {} to PV: {}".format(-1*ppm_rawV,BLPV.name))
        except:
            logging.error("Failed to write to PV: {}".format(BLPV.name))
        
        try:
            scalePV.put(ppm_scalef[n])
            logging.info("Wrote {} to PV: {}".format(ppm_scalef[n],scalePV.name))
        except:
            logging.error("Failed to write to PV: {}".format(scalePV.name))
        
        try:
            calmjPV.put(ppm_calmj[n])
            logging.info("Wrote {} to PV: {}".format(ppm_calmj[n],calmjPV.name))
        except:
            logging.error("Failed to write to PV: {}".format(calmjPV.name))
        n += 1
