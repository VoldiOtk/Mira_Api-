import os
import json
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader
from model import ASLLstmModel

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'knowledge', 'asl_data')
SEQUENCE_LENGTH = 30

def train():
    # 1. Charger dynamiquement la liste des actions
    actions_file = os.path.join(DATA_PATH, 'actions.json')
    if not os.path.exists(actions_file):
        print("[ERR] Erreur: actions.json introuvable. Lancez d'abord:")
        print("   python model/process_wlasl.py")
        return

    with open(actions_file, 'r', encoding='utf-8') as f:
        ACTIONS = json.load(f)
    
    print(f"[INFO] Actions détectées ({len(ACTIONS)}): {ACTIONS}")
    label_map = {label: num for num, label in enumerate(ACTIONS)}

    # 2. Charger les données (toutes les séquences trouvées par action)
    sequences, labels = [], []

    for action in ACTIONS:
        action_dir = os.path.join(DATA_PATH, action)
        if not os.path.isdir(action_dir):
            print(f"[WARN] Dossier manquant pour '{action}', skip.")
            continue

        seq_folders = sorted([d for d in os.listdir(action_dir) if os.path.isdir(os.path.join(action_dir, d))])
        loaded = 0

        for seq_name in seq_folders:
            window = []
            valid = True
            for frame_num in range(SEQUENCE_LENGTH):
                npy_path = os.path.join(action_dir, seq_name, f"{frame_num}.npy")
                if os.path.exists(npy_path):
                    res = np.load(npy_path)
                    window.append(res)
                else:
                    valid = False
                    break

            if valid and len(window) == SEQUENCE_LENGTH:
                sequences.append(window)
                labels.append(label_map[action])
                loaded += 1

        print(f"  [OK] [{action.upper()}] {loaded} séquences chargées")

    if len(sequences) == 0:
        print("[ERR] Aucune donnée trouvée ! Vérifiez que process_wlasl.py a bien tourné.")
        return

    X = np.array(sequences)
    y = np.array(labels)
    print(f"\n[INFO] Dataset: {X.shape[0]} séquences, {len(ACTIONS)} classes")
    print(f"   Input shape: {X.shape}")

    X_tensor = torch.tensor(X, dtype=torch.float32)
    y_tensor = torch.tensor(y, dtype=torch.long)

    dataset = TensorDataset(X_tensor, y_tensor)
    dataloader = DataLoader(dataset, batch_size=8, shuffle=True)

    # 3. Initialiser le Modèle
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"\n[INFO] Device: {device}")
    model = ASLLstmModel(input_size=1662, num_classes=len(ACTIONS)).to(device)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

    # 4. Entraînement
    num_epochs = 150
    print(f"\n[RUN] Démarrage de l'entraînement ({num_epochs} epochs)...")
    for epoch in range(num_epochs):
        loss_val = 0
        correct = 0
        total = 0
        for batch_X, batch_y in dataloader:
            batch_X, batch_y = batch_X.to(device), batch_y.to(device)
            optimizer.zero_grad()
            outputs = model(batch_X)
            loss = criterion(outputs, batch_y)
            loss.backward()
            optimizer.step()
            loss_val += loss.item()

            _, predicted = torch.max(outputs, 1)
            total += batch_y.size(0)
            correct += (predicted == batch_y).sum().item()

        if (epoch + 1) % 10 == 0:
            acc = 100.0 * correct / total if total > 0 else 0
            print(f"  Epoch {epoch+1}/{num_epochs} — Loss: {loss_val/len(dataloader):.4f} — Accuracy: {acc:.1f}%")

    # 5. Sauvegarde
    model_path = os.path.join(os.path.dirname(__file__), 'model.pth')
    torch.save(model.state_dict(), model_path)
    
    # Sauvegarder aussi les métadonnées du modèle
    meta_path = os.path.join(os.path.dirname(__file__), 'model_meta.json')
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump({'actions': ACTIONS, 'num_classes': len(ACTIONS), 'input_size': 1662}, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] Modèle sauvegardé: {model_path}")
    print(f"[OK] Métadonnées: {meta_path}")
    print(f"\n[NEXT] Prochaine étape: python -m uvicorn backend.app:app")


if __name__ == "__main__":
    train()
