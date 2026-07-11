import os
import sys
from ultralytics import YOLO

def main():
    print("Starting YOLOv8-Pose model training demonstration...")
    print("We will use the built-in 'coco8-pose' dataset (a tiny 8-image pose dataset).")
    
    # Load the pretrained nano pose model
    print("Loading yolov8n-pose.pt base model...")
    model = YOLO('yolov8n-pose.pt')
    
    # Start training
    # We set workers=0 to avoid Windows multiprocessing issues.
    # We set epochs=3 for a quick, successful test run.
    print("Training started (3 epochs, workers=0)...")
    try:
        results = model.train(
            data='coco8-pose.yaml',
            epochs=3,
            imgsz=640,
            workers=0,
            project='yolo_train_runs',
            name='pose_model'
        )
        print("\nTraining completed successfully!")
        print(f"Trained weights are saved in: {os.path.abspath('yolo_train_runs/pose_model/weights/best.pt')}")
    except Exception as e:
        print(f"\nTraining failed with error: {e}", file=sys.stderr)

if __name__ == '__main__':
    main()
