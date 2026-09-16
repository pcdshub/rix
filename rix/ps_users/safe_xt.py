#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jun  3 17:01:31 2024

@author: rixopr
"""
import numpy as np
import elog
import json
#from lxtgui import * #Breaking the mono energy reader IoC somehow
from prettytable import PrettyTable

from . import data_path

t0_file = str(data_path / "laser_t0.json")


class safe_xt:
    '''
    safe_xt is a wrapper for txt,lxt,lxt_ttc motions.
    Saves user set time zeros
    Tracks the absolute position of stages and prevents large accidental motions with the mv command
    '''
    def __init__(self,stage,slxt=None,stxt=None):
        self.stage = stage
        self.threshold = 1e-3
        self.precision = 15
        self.isttc = hasattr(stage,'txt')
        self.slxt = slxt
        self.stxt = stxt
        #update for new user offset handling
        if self.isttc:
            self.t0 = 0
        else:
            self.t0 = -1*self.stage.user_offset.get()
        #Load t0 from file
        '''
        try:
            with open(t0_file,'r') as f:
                t0_dict = json.load(f)
                self.t0 = t0_dict[self.stage.name]
        except:
            print('Failed to load saved t0 from file: ' + t0_file)
            self.t0 = 0
        '''
        self.position()
        if not self.isttc:
            self.stage.set_current_position(self.position(False))
        
    def round(self,var):
        return np.round(var,self.precision)
        
    def getoffset(self):
        try:
            stage_offset = self.stage.user_offset.get()
        except:
            stage_offset = 0
        return stage_offset
    
    def getstagepos(self):
        '''
        Returns current absolute stage position regardless of type (txt, lxt, lxt_ttc)
        -------
        '''
        
        try:
            return self.stage.position[0]-self.getoffset()
        except:
            return self.stage.position-self.getoffset()
        
    def position(self,disp=True):
        '''
        Updates raw and zeroed delay positions, returns zeroed position
        Parameters
        ----------
        disp : boolean, optional
            Print the current positions. The default is True.

        Returns
        -------
        pos : float
            Current zeroed delay positions.

        '''
        self.pos = self.getstagepos()+self.getoffset()#-self.t0
        self.posraw = self.getstagepos()
        if disp: 
        
            t2 = PrettyTable(['Stage','Zeroed (s)','Raw (s)'])
            t2.add_row([self.stage.name,self.round(self.pos),self.round(self.posraw)])
            if self.isttc:
                self.slxt.position(False)
                self.stxt.position(False)
                t2.add_row(['lxt',self.round(self.slxt.pos),self.round(self.slxt.posraw)])
                t2.add_row(['txt',self.round(self.stxt.pos),self.round(self.stxt.posraw)])
                
                
            print(t2)
        
        return self.pos
        
    def set_current_position(self,t=0):
        '''
        Set the current delay to given time t. Updates t0 position.
        Posts t0 to elog
        Parameters
        ----------
        t : float, optional
            Delay time to set current delay to. The default is 0.

        Returns
        -------
        None.

        '''
        self.position(False)
        self.pos = t
        self.t0 = self.getstagepos() - t
        self.stage.set_current_position(t)
        #self.mv(t)
        print('Setting raw delay {:} to {:} (t0 = {:})'.format(self.round(self.posraw),t,self.round(self.t0)))
        try:
            elog_obj = elog.HutchELog.from_registry()
            elog_obj.post(
                "New {:} t0: {:}".format(self.stage.name,self.round(self.t0)),
                tags=[self.stage.name, 't0'],
            )
        except:
            print('Failed to post to elog')
            
        '''
        #Save new t0 to file
        try:
            with open(t0_file,'r+') as f:
                t0_dict = json.load(f)
                t0_dict[self.stage.name] = self.t0
                
                f.seek(0)
                json.dump(t0_dict,f)
                f.truncate()
        except:
            print('Failed to save t0 to file: ' + t0_file)
        '''
    def mv(self,t):
        '''
        Move time delay to given time.
        Checks that the motion doesn't exceed given thresholds.
        Reports raw stage positions.
        Parameters
        ----------
        t : float
            Delay time to move to in (seconds).

        Returns
        -------
        None.

        '''
        #update position
        self.position(False)
        
        #check txt stage if lxt_ttc. Record lxt and txt raw start positions
        if self.isttc:
            if (np.abs(t-self.stage.txt.position[0]) > self.stxt.threshold):
                print("txt move from {:} to {:} exceeds {:} threshold. Type 'y' to continue".format(self.stage.txt.position[0],t,self.stxt.threshold))
                answer = input()
                if answer.lower() not in ["y","yes"]:
                    print('Move aborted')
                    return
            self.stxt.position(False)
            self.slxt.position(False)
            lasttxtposraw = self.stxt.posraw
            lastlxtposraw = self.slxt.posraw
                
        #check if move is outside of threshold         
        if np.abs(t-self.pos) > self.threshold:
            print("Move from {:} to {:} exceeds {:} threshold. Type 'y' to continue".format(self.pos,t,self.threshold))
            answer = input()
            if answer.lower() not in ["y","yes"]:
                print('Move aborted')
                return
        
        #update positions and move
        lastposraw = self.posraw 
        lastpos = self.pos
        self.pos = t
        self.posraw = t-self.getoffset()#+self.t0
        self.stage.mv(t)
        
        #display raw stage positions, and lxt txt positions for lxt_ttc
        
        #print('(Raw positions: {:} to {:})'.format(self.round(lastposraw),self.round(self.posraw)))
        if self.isttc:
            
            t2 = PrettyTable(['Position','Zeroed (s)','Raw LXT (s)','Raw TXT (s)'])
            
            t2.add_row(['Start',self.round(lastpos),self.round(lastlxtposraw), self.round(lasttxtposraw)])
            #t2.add_row(['End',self.round(t),self.round(self.round(self.slxt.t0+t)), self.round(self.stxt.t0+t)])
            t2.add_row(['End',self.round(t),self.round(self.round(t-self.slxt.getoffset())), self.round(t-self.stxt.getoffset())])
            print(t2)
            '''
            print('(LXT raw: Moving lxt from {:} to {:})'.format(self.round(lastlxtposraw),self.round(self.slxt.t0+t)))
            print('TXT: Moving txt from {:} to {:}'.format(self.stage.txt.position[0],t))
            print('(TXT raw: Moving txt from {:} to {:})'.format(self.round(lasttxtposraw),self.round(self.stxt.t0+t)))
            '''
        else:
            t2 = PrettyTable([self.stage.name,'Zeroed (s)','Raw (s)'])
            
            t2.add_row(['Start',self.round(lastpos),self.round(lastposraw)])
            t2.add_row(['End',self.round(t),self.round(self.posraw)])
            print(t2)
        
    def mvr(self,dt):
        
        '''
        Move time delay from current position by given relative time delta.
        Checks that the motion doesn't exceed given thresholds.
        Reports raw stage positions.
        Parameters
        ----------
        dt : float
            Delay time delta to move (seconds).

        Returns
        -------
        None.

        '''
        
        self.position(False)
        self.mv(self.pos+dt)
        
