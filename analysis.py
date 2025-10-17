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
import os
from scipy.signal import find_peaks
from threading    import Thread, Lock
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
        self._newSubstanceLock     = Lock()
        self._newSubstanceState    = None
        self._referenceLock        = Lock()

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
                for rowNumber,row in enumerate(reader,start=1):
                    if not row:
                        continue

                    rawSpectrum = row.get("spectrum_values") or row.get("spectrum")
                    if not rawSpectrum:
                        # Fallback for legacy files containing single peak data.
                        wavelengthRaw = row.get("wavelength")
                        if wavelengthRaw is not None:
                            self.log(
                                "WARNING",
                                f"Legacy reference entry detected at line {rowNumber}; skipping because full spectrum data is required."
                            )
                        continue

                    spectrumArray = self._parse_reference_spectrum(rawSpectrum)
                    if spectrumArray is None or spectrumArray.size == 0:
                        self.log("WARNING",f"Reference entry at line {rowNumber} discarded: spectrum data is empty or invalid.")
                        continue

                    spectra.append({
                        "substance"            : row.get("substance","Unknown"),
                        "ion_state"            : row.get("ion_state",""),
                        "source"               : row.get("source",""),
                        "captured_at"          : row.get("captured_at",""),
                        "pixel_to_nm_factor"   : self._safe_float(row.get("pixel_to_nm_factor"),default=self.config.get("pixel_to_nm_factor")),
                        "pixel_to_nm_offset"   : self._safe_float(row.get("pixel_to_nm_offset"),default=self.config.get("pixel_to_nm_offset")),
                        "spectrum"             : spectrumArray
                    })

                self.referenceSpectra = spectra
                if not spectra:
                    self.log(
                        "WARNING",
                        f"Reference spectra file '{self.referenceSpectraPath}' is empty. Analysis will run without reference matches until data is added."
                    )
                else:
                    self.log(
                        "INFO",
                        f"Reference spectra loaded successfully from {self.referenceSpectraPath} ({len(self.referenceSpectra)} entries)."
                    )
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

        if msgType == "PictureTaken":
            self._handleNewSubstanceCapture(payload)
            return
        elif msgType == "Calibrate":
            self.calibrate()
            return
        elif msgType == "AddSubstance":
            self.sendMessage("All","RequestName")
            self.log("INFO","Requesting new substance name.")
            return
        elif msgType == "NewSubstanceName":
            substanceName = payload.get("name") or payload.get("substance")
            try:
                self.newSubstance(substanceName)
            except Exception as exc:
                self.log("ERROR",f"Failed to start new substance acquisition: {exc}")
                self.sendMessage(
                    "All",
                    "NewReferenceCapture",
                    {
                        "status": "error",
                        "substance": (substanceName or "").strip(),
                        "message": str(exc)
                    }
                )
            return
        elif msgType == "Analyze":
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

    def _handleNewSubstanceCapture(self,payload):
        """
        Processes a captured image when registering a new substance reference.
        """
        if not payload:
            return

        with self._newSubstanceLock:
            state = self._newSubstanceState
            if state is None:
                return
            if state.get("status") == "processing":
                self.log("WARNING","Ignoring additional camera frame while new substance processing is ongoing.")
                return
            self._newSubstanceState["status"] = "processing"
            substanceName = state.get("substance")

        try:
            imageB64 = payload.get("image")
            if not imageB64:
                raise ValueError("Camera response did not include image data.")

            imageBytes = base64.b64decode(imageB64)
            imageNp = numpy.frombuffer(imageBytes,dtype=numpy.uint8)
            imageData = cv2.imdecode(imageNp,cv2.IMREAD_COLOR)
            if imageData is None:
                raise ValueError("Failed to decode image data for new substance acquisition.")

            intensityProfile = numpy.asarray(self.extractSpectrogramProfile(imageData),dtype=numpy.float32)
            if intensityProfile.size == 0:
                raise ValueError("Extracted intensity profile is empty.")

            baseProfile = self._get_resampled_base_profile(intensityProfile.size)
            diffProfile = baseProfile - intensityProfile
            if diffProfile.size == 0:
                raise ValueError("Difference profile is empty.")

            peakIdx = int(numpy.argmax(diffProfile))
            peakValue = float(diffProfile[peakIdx])

            pixelToNmFactor = self.config.get("pixel_to_nm_factor",0.5)
            pixelOffset = self.config.get("pixel_to_nm_offset",400.0)
            wavelengthNm = peakIdx * pixelToNmFactor + pixelOffset

            metadata = {
                "substance": substanceName,
                "ion_state": self.config.get("default_ion_state",""),
                "source": self.config.get("reference_source","Raspiscope"),
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
                "pixel_to_nm_factor": pixelToNmFactor,
                "pixel_to_nm_offset": pixelOffset
            }

            self._store_reference_spectrum(diffProfile,metadata)

            self.sendMessage(
                "All",
                "NewReferenceCapture",
                {
                    "status": "completed",
                    "substance": substanceName,
                    "wavelength_nm": float(wavelengthNm),
                    "intensity": peakValue
                }
            )
            self.log("INFO",f"New reference '{substanceName}' stored at {wavelengthNm:.2f} nm (intensity delta {peakValue:.3f}).")
        except Exception as exc:
            self.log("ERROR",f"Failed to register new substance '{substanceName}': {exc}")
            self.sendMessage("All","NewReferenceCapture",{"status": "error","substance": substanceName,"message": str(exc)})
        finally:
            with self._newSubstanceLock:
                self._newSubstanceState = None

    def newSubstance(self,substanceName):
        """
        Requests a new camera capture and stores the main absorption peak
        for the provided substance in the reference spectra database.
        """
        if self.calibrationInProgress:
            raise RuntimeError("Cannot register new substances while calibration is in progress.")

        substance = (substanceName or "").strip()
        if not substance:
            raise ValueError("Substance name must be provided.")

        if self.baseIntensityProfile is None:
            raise RuntimeError("Base intensity profile not available. Run calibration first.")

        with self._newSubstanceLock:
            if self._newSubstanceState is not None:
                raise RuntimeError("Another new substance acquisition is already in progress.")
            self._newSubstanceState = {
                "substance": substance,
                "status": "waiting_image",
                "created_at": time.time()
            }

        self.log("INFO",f"Requesting camera capture for new substance '{substance}'.")
        self.sendMessage("Camera","Take")
        self.sendMessage("All","NewReferenceCapture",{"status": "requested","substance": substance})

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
            
            # Phase 2: Baseline removal and valley detection (points of maximum absorbance)
            peaksIndices,processedProfile = self.detectAbsorbanceValleys(
                intensityProfile,
                processedProfile=self._compute_processed_profile(intensityProfile)
            )
            
            # Phase 3: Comparison with reference spectra
            results = self.compareWithReferences(processedProfile,intensityProfile,peaksIndices)

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

        manualRect = (15,550,310,10)
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

    def _parse_reference_spectrum(self,rawSpectrum):
        """
        Converts a serialized spectrum payload into a numpy array.
        """
        if rawSpectrum is None:
            return None

        spectrumArray = None
        try:
            loaded = json.loads(rawSpectrum)
            if isinstance(loaded,list):
                spectrumArray = numpy.asarray([float(item) for item in loaded],dtype=numpy.float32)
        except (json.JSONDecodeError,TypeError,ValueError):
            spectrumArray = None

        if spectrumArray is None:
            values = []
            for token in str(rawSpectrum).replace(";", " ").split():
                try:
                    values.append(float(token))
                except (TypeError,ValueError):
                    continue
            if values:
                spectrumArray = numpy.asarray(values,dtype=numpy.float32)

        return spectrumArray

    @staticmethod
    def _safe_float(value,default=None):
        """
        Attempts to convert a value to float, returning default on failure.
        """
        if value is None:
            return default
        if isinstance(value,(int,float)):
            return float(value)
        valueStr = str(value).strip()
        if valueStr == "":
            return default
        try:
            return float(valueStr)
        except ValueError:
            return default

    def _get_resampled_base_profile(self,targetLength):
        """
        Returns the base intensity profile, resampled to the desired length if necessary.
        """
        if self.baseIntensityProfile is None:
            raise RuntimeError("Base intensity profile is not available.")

        baseArray = numpy.asarray(self.baseIntensityProfile,dtype=numpy.float32)
        if baseArray.size == 0:
            raise RuntimeError("Base intensity profile is empty.")

        if baseArray.size == targetLength:
            return baseArray

        xBase = numpy.linspace(0.0,1.0,num=baseArray.size,endpoint=True)
        xTarget = numpy.linspace(0.0,1.0,num=targetLength,endpoint=True)
        return numpy.interp(xTarget,xBase,baseArray)

    def _compute_processed_profile(self,intensityProfile):
        """
        Returns the spectrum with the base intensity profile removed when available.
        """
        profile = numpy.asarray(intensityProfile,dtype=numpy.float32)
        if profile.size == 0:
            return profile

        if self.baseIntensityProfile is None:
            return profile

        try:
            baseArray = numpy.asarray(self.baseIntensityProfile,dtype=numpy.float32)
        except Exception as exc:
            self.log("WARNING",f"Failed to convert base intensity profile: {exc}")
            return profile

        if baseArray.size == 0:
            return profile

        if baseArray.size != profile.size:
            x_base = numpy.linspace(0.0,1.0,num=baseArray.size,endpoint=True)
            x_target = numpy.linspace(0.0,1.0,num=profile.size,endpoint=True)
            try:
                baseResampled = numpy.interp(x_target,x_base,baseArray)
            except Exception as exc:
                self.log("WARNING",f"Failed to resample base intensity profile: {exc}")
                return profile
        else:
            baseResampled = baseArray

        return baseResampled - profile

    @staticmethod
    def _resample_spectrum(spectrum,target_length):
        """
        Resamples a spectrum to a new length while preserving shape.
        """
        spectrumArray = numpy.asarray(spectrum,dtype=numpy.float32)
        if spectrumArray.size == 0 or target_length <= 0:
            return numpy.asarray([],dtype=numpy.float32)

        if spectrumArray.size == target_length:
            return spectrumArray

        if spectrumArray.size == 1:
            return numpy.full((target_length,),spectrumArray[0],dtype=numpy.float32)

        x_source = numpy.linspace(0.0,1.0,num=spectrumArray.size,endpoint=True)
        x_target = numpy.linspace(0.0,1.0,num=int(target_length),endpoint=True)
        return numpy.interp(x_target,x_source,spectrumArray)

    def detectAbsorbanceValleys(self,intensityProfile,processedProfile=None):
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
            return numpy.asarray([],dtype=int),profile

        if processedProfile is not None:
            workingProfile = numpy.asarray(processedProfile,dtype=numpy.float32)
            if workingProfile.size != profile.size:
                workingProfile = self._compute_processed_profile(profile)
        else:
            workingProfile = self._compute_processed_profile(profile)

        if numpy.allclose(workingProfile.max(),workingProfile.min()):
            self.log("WARNING","Working profile is nearly flat after baseline subtraction; no valleys detected.")
            return numpy.asarray([],dtype=int),workingProfile

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
        
        return peaksIndices,workingProfile

    def _store_reference_spectrum(self,spectrum,metadata):
        """
        Appends a full spectrum entry to the reference spectra CSV and updates the in-memory cache.
        """
        fieldnames = [
            "substance",
            "ion_state",
            "source",
            "captured_at",
            "pixel_to_nm_factor",
            "pixel_to_nm_offset",
            "spectrum_length",
            "spectrum_values"
        ]
        filePath = self.referenceSpectraPath
        directory = os.path.dirname(filePath)
        if directory:
            os.makedirs(directory,exist_ok=True)

        with self._referenceLock:
            try:
                needsHeader = not os.path.exists(filePath) or os.path.getsize(filePath) == 0
            except OSError:
                needsHeader = True

            appendNewline = False
            if not needsHeader:
                try:
                    with open(filePath,"rb") as existingFile:
                        existingFile.seek(0,os.SEEK_END)
                        if existingFile.tell() > 0:
                            existingFile.seek(-1,os.SEEK_END)
                            lastByte = existingFile.read(1)
                            appendNewline = lastByte not in (b"\n",b"\r")
                except OSError:
                    appendNewline = False

            serializedSpectrum = json.dumps([float(value) for value in numpy.asarray(spectrum,dtype=numpy.float32)])
            entry = {
                "substance": metadata.get("substance","Unknown"),
                "ion_state": metadata.get("ion_state",""),
                "source": metadata.get("source",""),
                "captured_at": metadata.get("captured_at",""),
                "pixel_to_nm_factor": "" if metadata.get("pixel_to_nm_factor") is None else f"{float(metadata['pixel_to_nm_factor']):.6f}",
                "pixel_to_nm_offset": "" if metadata.get("pixel_to_nm_offset") is None else f"{float(metadata['pixel_to_nm_offset']):.6f}",
                "spectrum_length": str(int(len(spectrum))),
                "spectrum_values": serializedSpectrum
            }

            with open(filePath,"a",newline='') as csvFile:
                if appendNewline:
                    csvFile.write("\n")
                writer = csv.DictWriter(csvFile,fieldnames=fieldnames)
                if needsHeader:
                    writer.writeheader()
                writer.writerow(entry)

            spectrumArray = numpy.asarray(spectrum,dtype=numpy.float32)
            if self.referenceSpectra is None:
                self.referenceSpectra = []
            self.referenceSpectra.append({
                "substance"          : entry["substance"],
                "ion_state"          : entry["ion_state"],
                "source"             : entry["source"],
                "captured_at"        : entry["captured_at"],
                "pixel_to_nm_factor" : self._safe_float(entry["pixel_to_nm_factor"],default=self.config.get("pixel_to_nm_factor")),
                "pixel_to_nm_offset" : self._safe_float(entry["pixel_to_nm_offset"],default=self.config.get("pixel_to_nm_offset")),
                "spectrum"           : spectrumArray
            })

    def compareWithReferences(self,processedProfile,intensityProfile,peaksIndices):
        """
        Compares detected peaks with the reference spectra and compiles the results.
        
        Args:
            processedProfile (numpy.ndarray): The baseline-corrected spectrum.
            intensityProfile (numpy.ndarray): The raw 1D intensity profile.
            peaksIndices (numpy.ndarray): The indices of the detected peaks.
            
        Returns:
            dict: A dictionary containing the analysis results.
        """
        if self.referenceSpectra is None:
            raise RuntimeError("Reference data not loaded. Cannot perform comparison.")

        processedArray = numpy.asarray(processedProfile,dtype=numpy.float32)
        rawArray = numpy.asarray(intensityProfile,dtype=numpy.float32)

        results = {
            "detected_peaks"        : [],
            "raw_spectrogram"       : rawArray.tolist(),
            "processed_spectrogram" : processedArray.tolist(),
            "reference_matches"     : []
        }

        pixelToNmFactor = self.config.get("pixel_to_nm_factor",0.5)
        pixelOffset = self.config.get("pixel_to_nm_offset",400.0)

        for peakIdx in peaksIndices:
            idx = int(peakIdx)
            estimatedWavelengthNm = idx * pixelToNmFactor + pixelOffset
            detected = {
                "pixel_index": idx,
                "wavelength_nm": float(estimatedWavelengthNm)
            }
            if 0 <= idx < rawArray.size:
                detected["raw_intensity"] = float(rawArray[idx])
            if 0 <= idx < processedArray.size:
                detected["processed_intensity"] = float(processedArray[idx])
            results["detected_peaks"].append(detected)

        matches = []

        for reference in self.referenceSpectra:
            refSpectrum = reference.get("spectrum")
            if refSpectrum is None or len(refSpectrum) == 0:
                continue

            alignedRef = self._resample_spectrum(refSpectrum,processedArray.size)
            if alignedRef.size == 0 or processedArray.size == 0:
                continue

            diff = processedArray - alignedRef
            rmse = float(numpy.sqrt(numpy.mean(numpy.square(diff))))

            numerator = float(numpy.dot(processedArray,alignedRef))
            denom = float(numpy.linalg.norm(processedArray) * numpy.linalg.norm(alignedRef))
            similarity = 0.0 if denom == 0.0 else numerator / denom

            matches.append({
                "substance": reference.get("substance","Unknown"),
                "ion_state": reference.get("ion_state",""),
                "source": reference.get("source",""),
                "captured_at": reference.get("captured_at",""),
                "rmse": rmse,
                "similarity": similarity
            })

        matches.sort(key=lambda item: (-item["similarity"],item["rmse"]))
        results["reference_matches"] = matches
        results["identified_substances"] = [match["substance"] for match in matches[:3]]

        return results

    def sendAnalysisResults(self,results):
        """
        Sends the final analysis results message.
        
        Args:
            results (dict): The dictionary of analysis results.
        """
        payload = {
            "identified_substances": results.get("identified_substances", []),
            "spectrogram_data": results.get("raw_spectrogram", []),
            "processed_spectrogram": results.get("processed_spectrogram", []),
            "reference_matches": results.get("reference_matches", []),
            "details": results
        }
        self.sendMessage("All","AnalysisComplete",payload)
        self.log("INFO","Analysis complete and results sent.")
