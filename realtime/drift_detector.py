from river.drift import ADWIN
import numpy as np

class GasSensorDriftDetector:
    """
    Wraps the ADWIN algorithm (from the river package) to monitor the full 
    128-dimensional raw sensor feature vectors (16 sensors x 8 features) 
    from the UCI Gas Sensor array.
    """
    def __init__(self, sensor_id="GS-ARRAY-01", delta=0.002, num_features=128, drift_threshold_ratio=0.1):
        self.sensor_id = sensor_id
        self.num_features = num_features
        # Instantiate 128 individual ADWIN detectors (one per feature)
        self.adwins = [ADWIN(delta=delta) for _ in range(num_features)]
        self.total_drifts_detected = 0
        self.drift_threshold_ratio = drift_threshold_ratio
        
    def process_reading(self, feature_vector: np.ndarray, timestamp: str) -> dict | None:
        """
        Processes a new 128-dimensional feature vector.
        If a significant percentage of features exhibit drift simultaneously,
        it triggers a global sensor drift event.
        
        Args:
            feature_vector: numpy array of shape (128,)
            timestamp: string representing the time of the event
            
        Returns:
            A drift event dictionary if global drift is detected, else None.
        """
        if feature_vector.shape[0] != self.num_features:
            raise ValueError(f"Expected {self.num_features} features, got {feature_vector.shape[0]}")
            
        drifting_features_count = 0
        
        # Update each feature's ADWIN detector
        for i in range(self.num_features):
            self.adwins[i].update(feature_vector[i])
            if self.adwins[i].drift_detected:
                drifting_features_count += 1
                
        # Check if the proportion of drifting features exceeds the threshold
        if drifting_features_count / self.num_features >= self.drift_threshold_ratio:
            self.total_drifts_detected += 1
            return {
                "event_type": "sensor_drift",
                "sensor_id": self.sensor_id,
                "timestamp": timestamp,
                "severity": 0.85,
                "message": f"Global sensor drift detected on {self.sensor_id} ({drifting_features_count}/{self.num_features} features drifting). Accuracy may be reduced.",
                "drift_flag": True
            }
            
        return None

if __name__ == "__main__":
    # Test the drift detector with simulated 128-dim data stream
    detector = GasSensorDriftDetector("GS-TEST")
    
    # Simulate normal baseline (128 features with mean ~ 0.5)
    print("Feeding normal 128-dim data...")
    for i in range(150):
        val = np.random.normal(0.5, 0.05, 128)
        detector.process_reading(val, f"T{i}")
        
    # Simulate drift on 30 features (mean shifts to ~ 2.0)
    print("Injecting severe drift into a subset of features...")
    drift_caught = False
    for i in range(150, 400):
        val = np.random.normal(0.5, 0.05, 128)
        # Inject drift into the first 30 features
        val[:30] = np.random.normal(2.0, 0.2, 30)
        
        event = detector.process_reading(val, f"T{i}")
        if event and not drift_caught:
            print(f"Drift caught successfully at iteration {i}: {event}")
            drift_caught = True
            
    if not drift_caught:
        print("Warning: Drift not detected by ADWIN. (Ensure 'river' is installed).")
