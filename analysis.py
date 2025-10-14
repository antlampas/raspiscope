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

        gray = cv2.cvtColor(imageData,cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray,(5,5),0)
        clahe = cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8))
        enhanced = clahe.apply(blurred)

        bandRect = self._locate_spectrum_band(enhanced)

        if bandRect:
            x,y,w,h = bandRect
            padY = int(h * 0.1)
            padX = int(w * 0.05)
            yStart = max(0,y - padY)
            yEnd = min(height,y + h + padY)
            xStart = max(0,x - padX)
            xEnd = min(width,x + w + padX)
            roi = imageData[yStart:yEnd,xStart:xEnd]
        else:
            self.log("WARNING","Failed to detect spectrum band automatically, using centered fallback ROI.")
            roiHeight = max(20,int(height * 0.1))
            yStart = max(0,height // 2 - roiHeight // 2)
            yEnd = min(height,yStart + roiHeight)
            roi = imageData[yStart:yEnd,:]

        roiGray = cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY)

        def encode_image_to_base64(image):
            success, buffer = cv2.imencode(".jpg", image)
            if not success:
                raise RuntimeError("Failed to encode ROI image.")
            return base64.b64encode(buffer).decode("utf-8")

        time.sleep(5)
        try:
            roi_b64 = encode_image_to_base64(roi)
            self.sendMessage("GUI","PictureTaken",{"image": roi_b64})
            self.log("INFO","ROI extracted and sent to GUI.")
            time.sleep(5)
        except Exception as exc:
            self.log("WARNING",f"Failed to send ROI to GUI: {exc}")

        try:
            roi_gray_b64 = encode_image_to_base64(roiGray)
            self.sendMessage("GUI","PictureTaken",{"image": roi_gray_b64})
            self.log("INFO","ROI GREY extracted and sent to GUI.")
            time.sleep(5)
        except Exception as exc:
            self.log("WARNING",f"Failed to send ROI Gray to GUI: {exc}")
        
        # Calculating the 1D intensity profile by averaging along the rows
        intensityProfile = numpy.mean(roiGray,axis=0)
        
        return intensityProfile
        
    def _locate_spectrum_band(self,enhancedImage):
        """
        Locate the bounding rectangle of the spectral band by evaluating contours
        produced with orientation-aware morphology.
        """
        height,width = enhancedImage.shape[:2]
        edges = cv2.Canny(enhancedImage,50,150)
        kernels = [
            ("horizontal",cv2.getStructuringElement(cv2.MORPH_RECT,(31,5))),
            ("vertical",cv2.getStructuringElement(cv2.MORPH_RECT,(5,31))),
        ]
        minArea = max(0.002 * width * height,500.0)
        candidates = []

        for orientation,kernel in kernels:
            closed = cv2.morphologyEx(edges,cv2.MORPH_CLOSE,kernel,iterations=2)
            dilated = cv2.dilate(closed,kernel,iterations=1)
            contours = cv2.findContours(dilated,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            contours = contours[0] if len(contours) == 2 else contours[1]

            for cnt in contours:
                x,y,w,h = cv2.boundingRect(cnt)
                area = w * h
                if area < minArea or w <= 0 or h <= 0:
                    continue

                aspectRatio = w / float(max(h,1))
                ratioScore = self._aspect_ratio_score(aspectRatio,orientation)
                if ratioScore < 0.1:
                    continue

                roiEnhanced = enhancedImage[y:y+h,x:x+w]
                if roiEnhanced.size == 0:
                    continue

                intensity = float(numpy.mean(roiEnhanced))
                contrast = float(numpy.std(roiEnhanced))
                intensityScore = 0.5 + (intensity / 255.0)
                contrastScore = 0.5 + min(1.0,contrast / 64.0)
                compositeScore = area * ratioScore * intensityScore * contrastScore
                candidates.append((compositeScore,(x,y,w,h)))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0],reverse=True)
        return candidates[0][1]

    @staticmethod
    def _aspect_ratio_score(aspectRatio,orientation):
        """
        Score how well the aspect ratio fits the expected orientation.
        """
        aspectRatio = max(aspectRatio,1e-3)
        if orientation == "horizontal":
            target = 5.0
        else:
            target = 0.2
        return math.exp(-abs(math.log(aspectRatio / target)))

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
