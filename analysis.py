"""
Author: Antlampas
CC BY-SA 4.0
https://creativecommons.org/licenses/by-sa/4.0/
"""

import cv2
import numpy
import csv
import time
import base64
import json
import math
from scipy.signal import find_peaks
from threading    import Thread
from module       import Module

class Analysis(Module):
    """
    Class for spectrogram analysis.
    Inherits from the base Module class.
    """
    def __init__(self,config,networkConfig,systemConfig):
        super().__init__("Analysis",networkConfig,systemConfig)
        self.config                = config
        self.networkConfig         = networkConfig
        self.systemConfig          = systemConfig
        self.referenceSpectraPath  = self.config['reference_spectra_path']
        self.toleranceNm           = self.config['tolerance_nm']
        self.referenceSpectra      = None
        self.baseIntensityProfile  = self.config.get("base_intensity_profile")
        self.calibrationInProgress = False
        self._config_path          = self.systemConfig.get("config_path","config.json")

    def onStart(self):
        """
        Method called when the module starts.
        Loads the reference data and registers with the EventManager.
        """
        self.sendMessage("EventManager", "Register")
        try:
            with open(self.referenceSpectraPath,newline='') as csvfile:
                reader = csv.DictReader(csvfile)
                spectra = []
                for row in reader:
                    if not row:
                        continue
                    wavelengthRaw = row.get('wavelength')
                    if wavelengthRaw is None:
                        continue
                    try:
                        wavelength = float(wavelengthRaw)
                    except (TypeError,ValueError):
                        continue
                    spectra.append((wavelength,dict(row)))

                if not spectra:
                    raise ValueError("No valid reference data rows found.")

                self.referenceSpectra = sorted(spectra,key=lambda item: item[0])
                self.log("INFO", f"Reference spectra loaded successfully from {self.referenceSpectraPath} ({len(self.referenceSpectra)} entries).")
        except FileNotFoundError:
            self.log("ERROR", f"Reference file not found at {self.referenceSpectraPath}. Analysis module will not work correctly.")
        except Exception as e:
            self.log("ERROR", f"Failed to load reference spectra from {self.referenceSpectraPath}. Error: {e}")

    def handleMessage(self,message):
        """
        Handles incoming messages.
        """
        msgType = message.get("Message",{}).get("type")
        payload = message.get("Message",{}).get("payload",{})

        if msgType == "Calibrate":
            self.calibrate()
            return

        if msgType == "Analyze":
            if not self.calibrationInProgress:
                self.sendMessage("All","AnalysisRequested",{"status": "received"})
                if self.referenceSpectra is None:
                    self.sendMessage("All",
                                     "AnalysisError",
                                     {
                                        "message": "Cannot analyze: reference data not loaded."
                                     }
                                    )
                    return

            imageB64 = payload.get("image")
            if not imageB64:
                errorMsg = "'Analyze' command received without image data."
                self.sendMessage("All","AnalysisError",{"message": errorMsg})
                if self.calibrationInProgress:
                    self._calibrationFailed(errorMsg)
                return

            # Decode the image from Base64
            imgBytes = base64.b64decode(imageB64)
            imgNp = numpy.frombuffer(imgBytes,dtype=numpy.uint8)
            imageData = cv2.imdecode(imgNp,cv2.IMREAD_COLOR)

            if imageData is None:
                errorMsg = "Failed to decode image data for analysis."
                self.sendMessage("All","AnalysisError",{"message": errorMsg})
                if self.calibrationInProgress:
                    self._calibrationFailed(errorMsg)
                return

            # Start the appropriate processing in a separate thread to avoid blocking
            if self.calibrationInProgress:
                worker = Thread(target=self._performCalibration,args=(imageData,))
            else:
                worker = Thread(target=self.performAnalysis,args=(imageData,))
            worker.start()

    def calibrate(self):
        """
        Initiates the base spectrum calibration by requesting an image from the camera.
        """
        if self.calibrationInProgress:
            self.log("WARNING","Calibration request ignored: already in progress.")
            return

        self.calibrationInProgress = True
        self.sendMessage("All","AnalysisCalibration",{"status": "started"})
        self.log("INFO","Starting base spectrum calibration: requesting image from camera.")

        try:
            self.sendMessage("Camera","Analyze")
        except Exception as exc:
            self._calibrationFailed(f"Failed to request calibration image: {exc}")

    def _performCalibration(self,imageData):
        """
        Processes the calibration image, stores the baseline intensity profile,
        and persists it to the configuration file.
        """
        try:
            intensityProfile = self.extractSpectrogramProfile(imageData)
            if intensityProfile is None or len(intensityProfile) == 0:
                raise ValueError("Extracted calibration intensity profile is empty.")

            baseProfile = [float(value) for value in numpy.asarray(intensityProfile).tolist()]
            self.baseIntensityProfile = baseProfile
            self.config["base_intensity_profile"] = baseProfile
            self._persist_base_profile(baseProfile)

            self.sendMessage("All","AnalysisCalibration",{"status": "completed"})
            self.log("INFO","Base spectrum calibration completed successfully.")
        except Exception as exc:
            self._calibrationFailed(str(exc))
        finally:
            self.calibrationInProgress = False

    def _persist_base_profile(self,baseProfile):
        """
        Persists the base intensity profile to the JSON configuration file.
        """
        try:
            with open(self._config_path,"r",encoding="utf-8") as cfgFile:
                data = json.load(cfgFile)

            modulesCfg = data.setdefault("modules",{})
            analysisCfg = modulesCfg.setdefault("analysis",{})
            analysisCfg["base_intensity_profile"] = baseProfile

            with open(self._config_path,"w",encoding="utf-8") as cfgFile:
                json.dump(data,cfgFile,indent=2)
        except FileNotFoundError as exc:
            raise RuntimeError(f"Configuration file '{self._config_path}' not found.") from exc
        except Exception as exc:
            raise RuntimeError(f"Failed to persist base profile to '{self._config_path}': {exc}") from exc

    def _calibrationFailed(self,message):
        """
        Handles calibration failures by logging and notifying other modules.
        """
        self.calibrationInProgress = False
        self.sendMessage("All","AnalysisCalibration",{"status": "error","message": message})
        self.log("ERROR",f"Calibration failed: {message}")

    def performAnalysis(self,imageData):
        """
        Performs a complete analysis of a spectroscopic absorption image
        by orchestrating the four phases of the analysis pipeline.
        
        Args:
            imageData (numpy.ndarray): The pixel matrix of the color image.
        """
        self.log("INFO","Starting absorption spectrogram analysis...")
        
        try:
            # Phase 1: Data Extraction and Pre-processing
            intensityProfile = numpy.asarray(self.extractSpectrogramProfile(imageData),dtype=numpy.float32)
            if intensityProfile.size == 0:
                raise ValueError("Empty intensity profile extracted from image.")
            
            # Phase 2: Valley Detection (Points of maximum absorbance)
            peaksIndices = self.detectAbsorbanceValleys(intensityProfile)
            
            # Phase 3: Comparison with reference spectra
            results = self.compareWithReferences(peaksIndices,intensityProfile)

            # Phase 4: Sending results
            self.sendAnalysisResults(results)

        except Exception as e:
            self.log("ERROR",{"error": str(e)})
            self.sendMessage("All","AnalysisError",{"error": str(e)})

    def extractSpectrogramProfile(self,imageData):
        """
        Extracts and pre-processes the 1D intensity profile from a 2D image.
        
        Args:
            imageData (numpy.ndarray): The pixel matrix of the color image.
            
        Returns:
            numpy.ndarray: The 1D intensity profile.
        """
        height,width = imageData.shape[:2]

        manualRect = (110,720,300,10)
        x,y,w,h = manualRect
        xStart = max(0,int(x))
        yStart = max(0,int(y))
        xEnd = min(width,xStart + int(w))
        yEnd = min(height,yStart + int(h))
        if xEnd <= xStart or yEnd <= yStart:
            raise ValueError("Configured manual ROI is invalid for the current image dimensions.")

        self.log("INFO",f"Using manual ROI: x={xStart}, y={yStart}, width={xEnd - xStart}, height={yEnd - yStart}.")
        roi = imageData[yStart:yEnd,xStart:xEnd]

        roiGray = cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY)

        def encode_image_to_base64(image):
            success, buffer = cv2.imencode(".jpg", image)
            if not success:
                raise RuntimeError("Failed to encode ROI image.")
            return base64.b64encode(buffer).decode("utf-8")
            
        try:
            roi_b64 = encode_image_to_base64(roi)
            self.sendMessage("GUI","PictureTaken",{"image": roi_b64})
            self.log("INFO","ROI extracted and sent to GUI.")
        except Exception as exc:
            self.log("WARNING",f"Failed to send ROI to GUI: {exc}")
        
        # Calculating the 1D intensity profile by averaging along the rows
        intensityProfile = numpy.mean(roiGray,axis=0)
        
        return intensityProfile

    def detectAbsorbanceValleys(self,intensityProfile):
        """
        Detects valleys in the intensity profile by inverting the signal
        and finding peaks.
        
        Args:
            intensityProfile (numpy.ndarray): The 1D intensity profile.
            
        Returns:
            numpy.ndarray: The indices of the detected peaks (original valleys).
        """
        profile = numpy.asarray(intensityProfile,dtype=numpy.float32)
        if profile.size == 0:
            return numpy.asarray([],dtype=int)

        workingProfile = numpy.copy(profile)
        if self.baseIntensityProfile is not None:
            try:
                baseArray = numpy.asarray(self.baseIntensityProfile,dtype=numpy.float32)
            except Exception as exc:
                self.log("WARNING",f"Failed to convert base intensity profile: {exc}")
                baseArray = None

            if baseArray is not None and baseArray.size > 0:
                if baseArray.size != workingProfile.size:
                    x_base = numpy.linspace(0.0,1.0,num=baseArray.size,endpoint=True)
                    x_target = numpy.linspace(0.0,1.0,num=workingProfile.size,endpoint=True)
                    try:
                        baseResampled = numpy.interp(x_target,x_base,baseArray)
                    except Exception as exc:
                        self.log("WARNING",f"Failed to resample base intensity profile: {exc}")
                        baseResampled = None
                else:
                    baseResampled = baseArray

                if baseResampled is not None and baseResampled.size == workingProfile.size:
                    workingProfile = workingProfile - baseResampled
                else:
                    self.log("WARNING","Base intensity profile not used due to shape mismatch.")

        if numpy.allclose(workingProfile.max(),workingProfile.min()):
            self.log("WARNING","Working profile is nearly flat after baseline subtraction; no valleys detected.")
            return numpy.asarray([],dtype=int)

        # To detect valleys with find_peaks,we invert the signal.
        # Maximum absorption corresponds to the minimum intensity.
        invertedProfile = numpy.max(workingProfile) - workingProfile

        # Finds peaks in the inverted profile,which correspond to the original valleys.
        # The parameters are crucial for filtering noise.
        peaksIndices,_ = find_peaks(
            invertedProfile,
            height=numpy.mean(invertedProfile) + numpy.std(invertedProfile) / 2,# Dynamic threshold
            distance=5 # Minimum distance between peaks (in pixels)
        )
        
        return peaksIndices

    def compareWithReferences(self,peaksIndices,intensityProfile):
        """
        Compares detected peaks with the reference spectra and compiles the results.
        
        Args:
            peaksIndices (numpy.ndarray): The indices of the detected peaks.
            intensityProfile (numpy.ndarray): The 1D intensity profile.
            
        Returns:
            dict: A dictionary containing the analysis results.
        """
        if self.referenceSpectra is None:
            raise RuntimeError("Reference data not loaded. Cannot perform comparison.")

        results = {
            "detected_peaks"   : [],
            "spectrogram_data" : intensityProfile.tolist()
        }
        
        identifiedSubstances = set()

        for peakIdx in peaksIndices:
            # Example: pixel to wavelength conversion (assuming linear calibration)
            pixelToNmFactor = 0.5 # nm per pixel,to be calibrated
            estimatedWavelengthNm = peakIdx * pixelToNmFactor + 400 # Example offset
            
            # Comparison with reference data using numpy.isclose for tolerance
            for refWavelength,rowData in self.referenceSpectra:
                if numpy.isclose(estimatedWavelengthNm,refWavelength,atol=self.toleranceNm):
                    substance = rowData.get('substance',"Unknown")
                    if substance not in identifiedSubstances:
                        self.log("INFO",f"Substance '{substance}' identified! Wavelength: {estimatedWavelengthNm:.2f} nm.")
                        identifiedSubstances.add(substance)

                    results["detected_peaks"].append({
                        "pixel_index": int(peakIdx),
                        "wavelength_nm": float(estimatedWavelengthNm),
                        "intensity": float(intensityProfile[peakIdx]),
                        "match": {
                            "substance": substance,
                            "reference_nm": float(refWavelength),
                            "delta_nm": abs(estimatedWavelengthNm - refWavelength)
                        }
                    })
                    break # A peak corresponds to only one reference substance

        results["identified_substances"] = list(identifiedSubstances)
        
        return results

    def sendAnalysisResults(self,results):
        """
        Sends the final analysis results message.
        
        Args:
            results (dict): The dictionary of analysis results.
        """
        payload = {
            "identified_substances": results.get("identified_substances", []),
            "spectrogram_data": results.get("spectrogram_data", []),
            "details": results
        }
        self.sendMessage("All","AnalysisComplete",payload)
        self.log("INFO","Analysis complete and results sent.")
