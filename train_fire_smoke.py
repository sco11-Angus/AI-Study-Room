from ultralytics import YOLO

if __name__ == "__main__":
    model = YOLO("yolov8n.pt")

    model.train(
        data="datasets/fire_smoke/data.yaml",
        epochs=50,
        imgsz=640,
        batch=8,
        project="runs/fire_smoke",
        name="yolov8n_fire_smoke",
        device=0,
    )