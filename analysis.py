"""
Author: Antlampas
CC BY-SA 4.0
https://creativecommons.org/licenses/by-sa/4.0/
"""

import cv2
import numpy
import pandas
import time
import base64
import json
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
        self.config               = config
        self.referenceSpectraPath = self.config['reference_spectra_path']
        self.toleranceNm          = self.config['tolerance_nm']
        self.referenceSpectra     = None

    def onStart(self):
        """
        Method called when the module starts.
        Loads the reference data and registers with the EventManager.
        """
        self.sendMessage("EventManager", "Register")
        try:
            self.referenceSpectra = pandas.read_csv(self.referenceSpectraPath)
            self.referenceSpectra.set_index('wavelength',inplace=True)
            self.log("INFO", f"Reference spectra loaded successfully from {self.referenceSpectraPath}.")
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

        if msgType == "Analyze":
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
            if imageB64:
                # Decode the image from Base64
                imgBytes = base64.b64decode(imageB64)
                imgNp = numpy.frombuffer(imgBytes,dtype=numpy.uint8)
                imageData = cv2.imdecode(imgNp,cv2.IMREAD_COLOR)

                # Start analysis in a separate thread to avoid blocking
                analysisThread = Thread(target=self.performAnalysis,args=(imageData,))
                analysisThread.start()
            else:
                self.sendMessage("All","AnalysisError",{"message": "'Analyze' command received without image data."})
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
            intensityProfile = self.extractSpectrogramProfile(imageData)
            
            # Phase 2: Valley Detection (Points of maximum absorbance)
            peaksIndices = self.detectAbsorbanceValleys(intensityProfile)
            
            # Phase 3: Comparison with reference spectra
            results = self.compareWithReferences(peaksIndices,intensityProfile)

            # Phase 4: Sending results
            self.sendAnalysisResults(results)

        except Exception as e:
            self.sendMessage("All","AnalysisError",{"error": str(e)})

    def extractSpectrogramProfile(self,imageData):
        """
        Extracts and pre-processes the 1D intensity profile from a 2D image.
        
        Args:
            imageData (numpy.ndarray): The pixel matrix of the color image.
            
        Returns:
            numpy.ndarray: The 1D intensity profile.
        """
        # Defining a Region of Interest (ROI) centered on the image
        height,width,_ = imageData.shape
        roiHeight = 20 # Example: a central band of 20 pixels
        yStart = int(height / 2) - int(roiHeight / 2)
        yEnd = yStart + roiHeight
        roi = imageData

        # Converting the ROI to grayscale for intensity analysis
        roiGray = cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY)
        
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
        # To detect valleys with find_peaks,we invert the signal.
        # Maximum absorption corresponds to the minimum intensity.
        invertedProfile = numpy.max(intensityProfile) - intensityProfile

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
            for _,row in self.referenceSpectra.iterrows():
                refWavelength = row['wavelength']
                
                if numpy.isclose(estimatedWavelengthNm,refWavelength,atol=self.toleranceNm):
                    substance = row['substance']
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
