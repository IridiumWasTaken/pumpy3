import serial
import logging
import re
import threading
from time import sleep

def remove_crud(string):
    """Return string without useless information.
     Return string with trailing zeros after a decimal place, trailing
     decimal points, and leading and trailing spaces removed.
     """
    if "." in string:
        string = string.rstrip('0')

    string = string.lstrip('0 ')
    string = string.rstrip(' .')

    return string

def convert_units(val, fromUnit, toUnit):
    """ Convert flowrate units. Possible volume values: ml, ul, pl; possible time values: hor, min, sec
    :param fromUnit: unit to convert from
    :param toUnit: unit to convert to
    :type fromUnit: str
    :type toUnit: str
    :return: float
    """
    time_factor_from = 1
    time_factor_to = 1
    vol_factor_to = 1
    vol_factor_from = 1

    if fromUnit[-3:] == "sec":
        time_factor_from = 60
    elif fromUnit == "hor": # does it really return hor?
        time_factor_from = 1/60
    else:
        pass

    if toUnit[-3:] == "sec":
        time_factor_to = 1/60
    elif toUnit[-3:] == "hor":
        time_factor_to = 60
    else:
        pass

    if fromUnit[:2] == "ml":
        vol_factor_from = 1000
    elif fromUnit[:2] == "nl":
        vol_factor_from = 1/1000
    elif fromUnit[:2] == "pl":
        vol_factor_from = 1/1e6
    else:
        pass

    if toUnit[:2] == "ml":
        vol_factor_to = 1/1000
    elif toUnit[:2] == "nl":
        vol_factor_to = 1000
    elif toUnit[:2] == "pl":
        vol_factor_to = 1e6
    else:
        pass

    return val * time_factor_from * time_factor_to * vol_factor_from * vol_factor_to

def convert_str_units(abbr):
    """ Convert string units from serial units m, u, p and s, m, h to full strings.
    :param abbr: abbreviated unit
    :type abbr: str
    :return: str
    """
    first_part = abbr[0] + "l"
    if abbr[2] == "s":
        second_part = "sec"
    elif abbr[2] == "m":
        second_part = "min"
    elif abbr[2] == "h":
        second_part = "hor" # is that true?
    else:
        raise ValueError("Unknown unit")
    
    resp = first_part + "/" + second_part
    return resp

class Chain(serial.Serial):
    """Create Chain object.
    Harvard syringe pumps are daisy chained together in a 'pump chain'
    off a single serial port. A pump address is set on each pump. You
    must first create a chain to which you then add Pump objects.
    Chain is a subclass of serial.Serial. Chain creates a serial.Serial
    instance with the required parameters, flushes input and output
    buffers (found during testing that this fixes a lot of problems) and
    logs creation of the Chain. Adapted from pumpy on github.
    """
    def __init__(self, port, baudrate=115200):
        """
        :param port: Port of pump at PC
        :type port: str
        """
        serial.Serial.__init__(self, port=port, stopbits=serial.STOPBITS_TWO, parity=serial.PARITY_NONE, bytesize=serial.EIGHTBITS, xonxoff= False, baudrate = baudrate, timeout=2)
        self.flushOutput()
        self.flushInput()
        logging.info('Chain created on %s',port)

class Pump:
    """Create Pump object for Harvard Pump.
    Argument:
        Chain: pump chain
    Optional arguments:
        address: pump address. Default is 0.
        name: used in logging. Default is Ultra.
    """
    def __init__(self, chain, address=0, name='Ultra'):
        self.name = name
        self.serialcon = chain
        self.address = '{0:02.0f}'.format(address)
        self.diameter = None
        self.flowrate = None
        self.targetvolume = None
        self.state = None

        """Query model and version number of firmware to check pump is
        OK. Responds with a load of stuff, but the last three characters
        are XXY, where XX is the address and Y is pump status. :, > or <
        when stopped, running forwards, or running backwards. Confirm
        that the address is correct. This acts as a check to see that
        the pump is connected and working."""
        try:
            self.write('ver')
            resp = self.read(17)

            if int(resp[0:2]) != int(self.address):
                raise PumpError('No response from pump at address %s' %
                                self.address)
            
            if resp[2] == ':':
                self.state = 'idle'
            elif resp[2] == '>':
                self.state = 'infusing'
            elif resp[2] == '<':
                self.state = 'withdrawing'
            else:
                raise PumpError('%s: Unknown state encountered' % self.name)

        except PumpError:
            self.serialcon.close()
            raise

        logging.info('%s: created at address %s on %s', self.name,
                      self.address, self.serialcon.port)

    def __repr__(self):
        string = ''
        for attr in self.__dict__:
            string += '%s: %s\n' % (attr,self.__dict__[attr]) 
        return string

    def write(self, command):
        """ Write serial command to pump. 
        :param command: command to write
        :type command: str
        """
        self.serialcon.write((self.address + command + '\r').encode())

    def read(self, bytes=5):
        """ Read serial stream from pump. 
        :param bytes: number of bytes to read
        :type bytes: int
        :return: str
        """
        response = self.serialcon.read(bytes)

        if len(response) == 0:
            pass
            # raise PumpError('%s: no response to command' % self.name)
        else:
            response = response.decode()
            response = response.replace('\n', '')
            return response

    def setdiameter(self, diameter):
        """Set syringe diameter (millimetres).
        Pump syringe diameter range is 0.1-35 mm. Note that the pump
        ignores precision greater than 2 decimal places. If more d.p.
        are specificed the diameter will be truncated.
        :param diameter: syringe diameter
        :type diameter: float
        """
        if self.state == 'idle':
            if diameter > 35 or diameter < 0.1:
                raise PumpError('%s: diameter %s mm is out of range' % 
                                (self.name, diameter))

            str_diameter = "%2.2f" % diameter

            # Send command   
            self.write('diameter ' + str_diameter)
            resp = self.read(80).splitlines()
            last_line = resp[-1]

            # Pump replies with address and status (:, < or >)        
            if (last_line[2] == ':' or last_line[2] == '<' or last_line[2] == '>'):
                # check if diameter has been set correctlry
                self.write('diameter')
                resp = self.read(45)
                returned_diameter = remove_crud(resp[3:9])
                
                # Check diameter was set accurately
                if float(returned_diameter) != diameter:
                    logging.error('%s: set diameter (%s mm) does not match diameter'
                                ' returned by pump (%s mm)', self.name, diameter,
                                returned_diameter)
                elif float(returned_diameter) == diameter:
                    self.diameter = float(returned_diameter)
                    logging.info('%s: diameter set to %s mm', self.name,
                                self.diameter)
            else:
                raise PumpError('%s: unknown response to setdiameter' % self.name)
        else:
            print("Please wait until pump is idle.\n")

    def setwithdrawrate(self, flowrate, unit):
        """Set withdraw rate.
        The pump will tell you if the specified flow rate is out of
        range. This depends on the syringe diameter. See Pump manual.
        :param flowrate: withdrawing flowrate
        :type flowrate: float
        :param unit: unit of flowrate. can be [m,u,p]/[h,m,s]
        :type unit: str 
        """
        if self.state == 'idle':
            self.write('wrate ' + str(flowrate) + ' ' + unit)
            resp = self.read(7)
            
            if (resp[2] == ':' or resp[2] == '<' or resp[2] == '>'):
                # Flow rate was sent, check it was set correctly
                self.write('wrate')
                resp = self.read(150).splitlines()[0]

                if 'Argument error' in resp:
                    raise PumpError('%s: flow rate (%s %s) is out of range' %
                            (self.name, flowrate, unit))

                idx1 = resp.find(str(flowrate)[0])
                idx2 = resp.find("l/")
                returned_flowrate = remove_crud(resp[idx1:idx2-1])
                returned_unit = resp[idx2-1:idx2+5]
                returned_flowrate = convert_units(float(returned_flowrate), returned_unit, convert_str_units(unit))

                if returned_flowrate != flowrate:
                    logging.error('%s: set flowrate (%s %s) does not match'
                                'flowrate returned by pump (%s %s)',
                                self.name, flowrate, unit, returned_flowrate, unit)
                elif returned_flowrate == flowrate:
                    self.flowrate = returned_flowrate
                    logging.info('%s: flow rate set to %s uL/min', self.name,
                                self.flowrate)
            else:
                raise PumpError('%s: unknown response' % self.name)
        else:
            print("Please wait until pump is idle.\n")

    def setinfusionrate(self, flowrate, unit):
        """Set infusion rate.
        The pump will tell you if the specified flow rate is out of
        range. This depends on the syringe diameter. See Pump manual.
        :param flowrate: withdrawing flowrate
        :type flowrate: float
        :param unit: unit of flowrate. can be [m,u,p]/[h,m,s]
        :type unit: str 
        """
        if self.state == "idle":
            self.write('irate ' + str(flowrate) + ' ' + unit)
            resp = self.read(17)
            
            if (":" in resp or "<" in resp or ">" in resp):
                # Flow rate was sent, check it was set correctly
                self.write('irate')
                resp = self.read(150)

                if 'error' in resp:
                    raise PumpError('%s: flow rate (%s %sl) is out of range' %
                            (self.name, flowrate, unit))

                matches = re.search(r"(\d+\.?\d*) ([mup][l])", resp)
                if matches is None:
                    raise PumpError("Syringe volume could not be found")
                else:
                    returned_flowrate = matches.group(1)
                    returned_unit = matches.group(2)

                returned_flowrate = convert_units(float(returned_flowrate), returned_unit, convert_str_units(unit))

                if returned_flowrate != flowrate:
                    logging.error('%s: set flowrate (%s %s) does not match'
                                'flowrate returned by pump (%s %s)',
                                self.name, flowrate, unit, returned_flowrate, unit)
                elif returned_flowrate == flowrate:
                    self.flowrate = returned_flowrate
                    logging.info('%s: flow rate set to %s uL/min', self.name,
                                self.flowrate)
            else:
                raise PumpError('%s: unknown response' % self.name)
        else:
            print("Please wait until pump is idle.\n")

    def infuse(self):
        """Start infusing pump."""
        if self.state == 'idle':
            self.write('irun')
            resp = self.read(55)

            if "Command error" in resp:
                error_msg = resp.splitlines()[1]
                raise PumpError('%s: %s', (self.name, error_msg))
            
            # pump doesn't respond to serial commands while infusing
            self.state = "infusing"
            threading.Thread(target=self.waituntilfinished)            
        else:
            print("Please wait until the pump is idle before infusing.\n")

    def waituntilfinished(self):
        """ Try to read pump state and return it. """
        while self.state == "infusing" or self.state == "withdrawing":
            try:
                resp = self.read(5)
                if 'T*' in resp:
                    self.state = "idle"
                    return "finished"
            except:
                pass
        
    def withdraw(self):
        """Start withdrawing pump."""
        if self.state == 'idle':
            self.write('wrun')
            resp = self.read(85)

            if "Command error" in resp:
                error_msg = resp.splitlines()[1]
                raise PumpError('%s: %s', (self.name, error_msg))
            
            # pump doesn't respond to serial commands while withdrawing
            self.state = "withdrawing"
            threading.Thread(target=self.waituntilfinished)
        else:
            print("Please wait until the pump is idle before withdrawing.\n")

    def settargetvolume(self, targetvolume, unit):
        """Set target volume.
        The pump will tell you if the specified target volume is out of
        range. This depends on the syringe. See Pump manual.
        :param targetvolume: target volume
        :type targetvolume: float
        :param unit: unit of targetvolume. Can be [m,u,p]
        :type unit: str 
        """
        if self.state == 'idle':
            self.write('tvolume ' + str(targetvolume) + ' ' + unit)
            resp = self.read(7)
            
            if True:
                # Target volume was sent, check it was set correctly
                self.write('tvolume')
                resp = self.read(150)

                if 'Target volume not set' in resp:
                    raise PumpError('%s: Target volume (%s %s) could not be set' %
                            (self.name, targetvolume, unit))

                matches = re.search(r"(\d+\.?\d*) ([mup][l])", resp)
                if matches is None:
                    raise PumpError("Syringe volume could not be found")
                else:
                    returned_targetvolume = matches.group(1)
                    returned_unit = matches.group(2)

                returned_targetvolume = convert_units(float(returned_targetvolume), returned_unit + "/min", convert_str_units(unit + "/min"))

                if returned_targetvolume != targetvolume:
                    logging.error('%s: set targetvolume (%s %s) does not match'
                                'targetvolume returned by pump (%s %s)',
                                self.name, targetvolume, unit, returned_targetvolume, unit)
                elif returned_targetvolume == targetvolume:
                    self.targetvolume = returned_targetvolume
                    logging.info('%s: target volume set to %s %s', self.name,
                                self.targetvolume, convert_str_units(unit + "/min")[:2])
            else:
                raise PumpError('%s: unknown response' % self.name)  
        else:
            print("Please wait until pump is idle.\n")

    def gettargetvolume(self):
        """Get target volume.
        :return: str
        """
        # Target volume was sent, check it was set correctly
        self.write('tvolume')
        resp = self.read(150)

        if 'Target volume not set' in resp:
            raise PumpError('%s: Target volume not be set' %
                        self.name)

        matches = re.search(r"(\d+\.?\d*) ([mup][l])", resp)
        if matches is None:
            raise PumpError("Target value could not be found")
        else:
            returned_targetvolume = matches.group(1)
            returned_unit = matches.group(2)
        
        rtn_str = returned_targetvolume + " " + returned_unit
        return rtn_str

    def setsyringevolume(self, vol, unit):
        """ Sets syringe volume.
        :param vol: volume of syringe
        :param unit: volume unit, can be [m, u, p]
        :type vol: float
        :type unit: str
        """
        if self.state == 'idle':
            self.write('svolume ' + str(vol) + ' ' + unit + 'l')
            resp = self.read(10)

            if (resp[-1] == ':' or resp[-1] == '<' or resp[-1] == '>'):
                # Volume was sent, check it was set correctly
                volume_str = self.getsyringevolume()
                returned_volume = volume_str[:-3]
                returned_unit = volume_str[-2:]
                returned_volume = convert_units(float(returned_volume), returned_unit + "/min", convert_str_units(unit + "/min"))

                if returned_volume != vol:
                    logging.error('%s: set syringe volume (%s %s) does not match'
                                'syringe volume returned by pump (%s %s)',
                                self.name, vol, unit, returned_volume, unit)
                elif returned_volume == vol:
                    self.syringevolume = returned_volume
                    logging.info('%s: syringe volume set to %s %s', self.name,
                                self.syringevolume, convert_str_units(unit + "/min")[:2])
            else:
                raise PumpError('%s: unknown response' % self.name) 
        else:
            print("Please wait until pump is idle.\n")  

    def getsyringevolume(self):
        """ Gets syringe volume. 
        :return: str
        """
        self.write('svolume')
        resp = self.read(60)
        
        matches = re.search(r"(\d+\.?\d*) ([mup][l])", resp)
        if matches is None:
            raise PumpError("Syringe volume could not be found")
        else:
            returned_volume = matches.group(1)
            returned_unit = matches.group(2)
        
        rtn_str = returned_volume + " " + returned_unit
        return rtn_str

    def stop(self):
        """Stop pump.
        To be used in an emergency as pump should stop if target is reached.
        """
        self.write('stop')
        resp = self.read(5)
        
        if resp[:3] != self.address + ":":
            raise PumpError('%s: unexpected response to stop' % self.name)
        else:
            logging.info('%s: stopped',self.name)
            self.state = "idle"

    def cvolume(self):
        """ Clears both withdrawn and infused volume """
        self.civolume()
        self.cwvolume()

    def civolume(self):
        """ Clears infused volume """
        self.write('civolume')
    
    def ctvolume(self):
        """ Clears target volume """
        self.write('ctvolume')

    def cwvolume(self):
        """" Clears withdrawn volume """
        self.write('cwvolume')

    def ivolume(self):
        """ Displays infused volume
        :return: str
        """
        self.write('ivolume')
        resp = self.read(55)

        matches = re.search(r"(\d+\.?\d*) ([mup][l])", resp)
        if matches is not None:
            return matches.group(1) + " " + matches.group(2)
        else:
            raise PumpError('%s: Unknown answer received' % self.name)

    def wvolume(self):
        """ Displays withdrawn volume
        :return: str
        """
        self.write('wvolume')
        resp = self.read(55)

        matches = re.search(r"(\d+\.?\d*) ([mup][l])", resp)
        if matches is not None:
            return matches.group(1) + " " + matches.group(2)
        else:
            raise PumpError('%s: Unknown answer received' % self.name)

class Pump2000(Pump):
    """ Create pump object for Harvard PhD 2000 pump. """

    def __init__(self, chain, address=00, name='PhD2000'):
        self.name = name
        self.serialcon = chain
        self.address = '{0:02.0f}'.format(address)
        self.diameter = None
        self.flowrate = None
        self.targetvolume = None
        self.state = None

        """Query model and version number of firmware to check pump is
        OK. Responds with a load of stuff, but the last three characters
        are XXY, where XX is the address and Y is pump status. :, > or <
        when stopped, running forwards, or running backwards. Confirm
        that the address is correct. This acts as a check to see that
        the pump is connected and working."""
        try:
            self.write('VER')
            resp = self.read(17)

            if 'PHD' not in resp:
                raise PumpError('No response from pump at address %s' %
                                self.address)
            
            if resp[-1] == ':':
                self.state = 'idle'
            elif resp[-1] == '>':
                self.state = 'infusing'
            elif resp[-1] == '<':
                self.state = 'withdrawing'
            elif resp[-1] == '*':
                self.state = 'stalled'
            else:
                raise PumpError('%s: Unknown state encountered' % self.name)

        except PumpError:
            self.serialcon.close()
            raise

        logging.info('%s: created at address %s on %s', self.name,
                      self.address, self.serialcon.port)

    def waituntilfinished(self):
        """ Try to read pump state and return it. """
        while self.state == "infusing" or self.state == "withdrawing":
            try:
                resp = self.read(5)
                if '*' in resp:
                    self.state = "idle"
                    return "finished"
            except:
                pass

    def run(self):
        self.write('RUN')
        resp = self.read(17)

        self._errorcheck(resp)

        self.state = 'infusing'

    def rev(self):
        self.write('REV')
        resp = self.read(17)

        self._errorcheck(resp)

        self.state = 'withdrawing'

    def infuse(self):
        self.run()
       
        if self.state == 'withdrawing':
            self.stop()
            self.rev()
    
    def withdraw(self):
        self.rev()

        if self.state == 'infusing':
            self.stop()
            self.run()

    def stop(self):
        self.write('STP')
        resp = self.read(17)

        self._errorcheck(resp)

        sleep(0.1)
        if self.state == 'infusing' or self.state == 'withdrawing':
            raise PumpError('%s: Pump could not be stopped.' % self.name)

    def _errorcheck(self, resp):
        if resp[-1] == ':':
            self.state = 'idle'
        elif resp[-1] == '>':
            self.state = 'infusing'
        elif resp[-1] == '<':
            self.state = 'withdrawing'
        elif resp[-1] == '*':
            self.state = 'stalled'
        else:
            raise PumpError('%s: Unknown state encountered' % self.name)

    def clear_accumulated_volume(self):
        self.write('CLV')
        resp = self.read(17)

        self._errorcheck(resp)

    def clear_target_volume(self):
        self.write('CLT')
        resp = self.read(17)

        self._errorcheck(resp)

    def set_rate(self, flowrate, units):
        flowrate_str = "%4.4f" %flowrate
        if units == 'm/m':
            write_str = 'MLM'
        elif units == 'u/m':
            write_str = 'ULM'
        elif units == 'm/h':
            write_str = 'MLH'
            self.rate_units = "ml/h"
        elif units == 'u/h':
            write_str = 'ULH'
        else:
            raise PumpError('%s: Unknown unit specified' % self.name)

        self.write(write_str + flowrate_str)
        resp = self.read(17)
        self._errorcheck(resp)

    def setdiameter(self, diameter):
        self.write('MMD' + str(diameter))
        resp = self.read(17)
        self._errorcheck(resp)

    def settargetvolume(self, volume):
        """ Set target volume in mL. """
        self.write('MLT' + str(volume))
        resp = self.read(17)
        self._errorcheck(resp)

    def getdiameter(self):
        self.write('DIA')
        resp = self.read(17)

        self._errorcheck(resp)
        matches = re.search(r"(\d+\.?\d*)", resp)
        if matches is not None:
            return matches.group(1) + " mm"
        else:
            raise PumpError('%s: Unknown answer received' % self.name)

    def getrate(self):
        self.write('RAT')
        resp = self.read(19)

        self._errorcheck(resp)
        matches = re.search(r"(\d+\.?\d*)", resp)
        if matches is not None:
            self.write('RNG')
            resp = self.read(17)
            self._errorcheck(resp)
            return matches.group(1) + " " + resp[:4]
        else:
            raise PumpError('%s: Unknown answer received' % self.name)
        
    def ivolume(self):
        self.write('VOL')
        resp = self.read(17)

        self._errorcheck(resp)
        matches = re.search(r"(\d+\.?\d*)", resp)
        if matches is not None:
            return matches.group(1) + " " + "ml"
        else:
            raise PumpError('%s: Unknown answer received' % self.name)
    
    def gettargetvolume(self):
        self.write('TAR')
        resp = self.read(17)

        self._errorcheck(resp)
        matches = re.search(r"(\d+\.?\d*)", resp)
        if matches is not None:
            return matches.group(1) + " " + "ml"
        else:
            raise PumpError('%s: Unknown answer received' % self.name)

class PumpError(Exception):
    pass