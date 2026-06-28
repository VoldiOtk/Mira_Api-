import os
import json
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader, random_split
from model import ASLLstmModel

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "knowledge", "asl_data")
SEQUENCE_LENGTH = 30
NUM_EPOCHS = int(os.getenv("TRAIN_EPOCHS", "80"))
BATCH_SIZE = int(os.getenv("TRAIN_BATCH_SIZE", "16"))
LEARNING_RATE = float(os.getenv("TRAIN_LR", "0.0005"))
VAL_SPLIT = float(os.getenv("TRAIN_VAL_SPLIT", "0.1"))


def train():
    actions_file = os.path.join(DATA_PATH, "actions.json")
    if not os.path.exists(actions_file):
        print("[ERR] actions.json introuvable. Lancez d'abord:")
        print("   set WLASL_NSLT=nslt_2000.json")
        print("   set WLASL_USE_ALL_CLASSES=1")
        print("   python model/process_wlasl.py")
        return

    with open(actions_file, "r", encoding="utf-8") as f:
        ACTIONS = json.load(f)

    print(f"[INFO] {len(ACTIONS)} classes ASL")
    label_map = {label: num for num, label in enumerate(ACTIONS)}

    sequences, labels = [], []

    for action in ACTIONS:
        action_dir = os.path.join(DATA_PATH, action)
        if not os.path.isdir(action_dir):
            print(f"[WARN] Dossier manquant: '{action}'")
            continue

        seq_folders = sorted(
            d for d in os.listdir(action_dir) if os.path.isdir(os.path.join(action_dir, d))
        )
        loaded = 0

        for seq_name in seq_folders:
            window = []
            valid = True
            for frame_num in range(SEQUENCE_LENGTH):
                npy_path = os.path.join(action_dir, seq_name, f"{frame_num}.npy")
                if os.path.exists(npy_path):
                    window.append(np.load(npy_path))
                else:
                    valid = False
                    break

            if valid and len(window) == SEQUENCE_LENGTH:
                sequences.append(window)
                labels.append(label_map[action])
                loaded += 1

        if loaded:
            print(f"  [OK] {action}: {loaded} sequences")

    if not sequences:
        print("[ERR] Aucune donnee. Verifiez process_wlasl.py.")
        return

    X = np.array(sequences, dtype=np.float32)
    y = np.array(labels, dtype=np.int64)
    print(f"\n[INFO] Dataset: {X.shape[0]} sequences, {len(ACTIONS)} classes")

    X_tensor = torch.tensor(X, dtype=torch.float32)
    y_tensor = torch.tensor(y, dtype=torch.long)

    full_dataset = TensorDataset(X_tensor, y_tensor)
    val_size = max(1, int(len(full_dataset) * VAL_SPLIT)) if len(full_dataset) > 20 else 0
    train_size = len(full_dataset) - val_size

    if val_size > 0:
        train_ds, val_ds = random_split(
            full_dataset,
            [train_size, val_size],
            generator=torch.Generator().manual_seed(42),
        )
    else:
        train_ds, val_ds = full_dataset, None

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    pin = device.type == "cuda"
    train_loader = DataLoader(
        train_ds,
        batch_size=BATCH_SIZE,
        shuffle=True,
        pin_memory=pin,
    )
    val_loader = (
        DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False, pin_memory=pin)
        if val_ds
        else None
    )

    print(f"[INFO] Device: {device} | batch={BATCH_SIZE} | epochs={NUM_EPOCHS}")

    model = ASLLstmModel(input_size=1662, num_classes=len(ACTIONS)).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="max", factor=0.5, patience=8
    )

    best_acc = 0.0
    model_dir = os.path.dirname(__file__)
    model_path = os.path.join(model_dir, "model.pth")
    meta_path = os.path.join(model_dir, "model_meta.json")

    print(f"\n[RUN] Entrainement ({NUM_EPOCHS} epochs)...")

    for epoch in range(NUM_EPOCHS):
        model.train()
        loss_sum = 0.0
        correct = 0
        total = 0

        for batch_X, batch_y in train_loader:
            batch_X, batch_y = batch_X.to(device), batch_y.to(device)
            optimizer.zero_grad()
            outputs = model(batch_X)
            loss = criterion(outputs, batch_y)
            loss.backward()
            optimizer.step()
            loss_sum += loss.item()
            _, predicted = torch.max(outputs, 1)
            total += batch_y.size(0)
            correct += (predicted == batch_y).sum().item()

        train_acc = 100.0 * correct / total if total else 0.0
        val_acc = 0.0

        if val_loader:
            model.eval()
            v_correct = 0
            v_total = 0
            with torch.no_grad():
                for batch_X, batch_y in val_loader:
                    batch_X, batch_y = batch_X.to(device), batch_y.to(device)
                    outputs = model(batch_X)
                    _, predicted = torch.max(outputs, 1)
                    v_total += batch_y.size(0)
                    v_correct += (predicted == batch_y).sum().item()
            val_acc = 100.0 * v_correct / v_total if v_total else 0.0
            scheduler.step(val_acc)

            if val_acc > best_acc:
                best_acc = val_acc
                torch.save(model.state_dict(), model_path)
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "actions": ACTIONS,
                            "num_classes": len(ACTIONS),
                            "input_size": 1662,
                            "val_accuracy": round(val_acc, 2),
                        },
                        f,
                        ensure_ascii=False,
                        indent=2,
                    )

        if (epoch + 1) % 5 == 0 or epoch == 0:
            msg = f"  Epoch {epoch+1}/{NUM_EPOCHS} — loss {loss_sum/len(train_loader):.4f} — train {train_acc:.1f}%"
            if val_loader:
                msg += f" — val {val_acc:.1f}% (best {best_acc:.1f}%)"
            print(msg)

    if best_acc == 0.0:
        torch.save(model.state_dict(), model_path)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(
                {"actions": ACTIONS, "num_classes": len(ACTIONS), "input_size": 1662},
                f,
                ensure_ascii=False,
                indent=2,
            )

    print(f"\n[OK] Modele: {model_path}")
    print(f"[OK] Meta: {meta_path} ({len(ACTIONS)} classes)")
    if best_acc:
        print(f"[OK] Meilleure precision validation: {best_acc:.1f}%")
    print("\n[NEXT] python -m uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000")


if __name__ == "__main__":
    train()
