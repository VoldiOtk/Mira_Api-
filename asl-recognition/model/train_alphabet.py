import os
import json
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader

# Modifier le sys.path si besoin
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model import HandSignModel

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'knowledge', 'asl_data_hands')

def train():
    actions_file = os.path.join(DATA_PATH, 'actions_hands.json')
    if not os.path.exists(actions_file):
        print("[ERR] actions_hands.json introuvable. Avez-vous exécuté process_alphabet.py ?")
        return

    with open(actions_file, 'r', encoding='utf-8') as f:
        ACTIONS = json.load(f)
        
    print(f"[INFO] Classes cibles ({len(ACTIONS)}) : {ACTIONS}")
    
    label_map = {label: num for num, label in enumerate(ACTIONS)}

    X_all = []
    y_all = []

    for action in ACTIONS:
        class_file = os.path.join(DATA_PATH, f"{action}.npy")
        if not os.path.exists(class_file):
            print(f"  [WARN] Fichier manquant pour '{action}'.npy, on ignore.")
            continue
            
        data = np.load(class_file)
        if len(data) == 0:
            continue
            
        X_all.append(data)
        # Créer les labels associés
        y_all.extend([label_map[action]] * len(data))
        print(f"  [OK] [{action}] : {len(data)} images chargées.")
        
    if not X_all:
        print("[ERR] Aucune donnée d'entrainement trouvée !")
        return

    X = np.vstack(X_all)
    y = np.array(y_all)
    
    print(f"\n[INFO] Dataset final: {X.shape[0]} images, {len(ACTIONS)} classes")
    print(f"   Input shape: {X.shape}")

    # Mélanger et charger dans PyTorch
    X_tensor = torch.tensor(X, dtype=torch.float32)
    y_tensor = torch.tensor(y, dtype=torch.long)

    # Création du Dataset et DataLoader
    dataset = TensorDataset(X_tensor, y_tensor)
    
    # Division train/validation 80/20 pour voir s'il overfitte pas ? 
    # Pour faire simple, on entraîne sur tout mais on mélange bien
    dataloader = DataLoader(dataset, batch_size=32, shuffle=True)

    # Initialisation
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"\n[INFO] Device: {device}")
    model = HandSignModel(input_size=1662, num_classes=len(ACTIONS)).to(device)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

    # Entrainement (Les réseaux denses apprennent bcp plus vite qu'un LSTM)
    num_epochs = 50
    print(f"\n[RUN] Démarrage de l'entraînement Hands ({num_epochs} epochs)...")
    
    for epoch in range(num_epochs):
        model.train()
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

        if (epoch + 1) % 5 == 0:
            acc = 100.0 * correct / total if total > 0 else 0
            print(f"  Epoch {epoch+1}/{num_epochs} — Loss: {loss_val/len(dataloader):.4f} — Accuracy: {acc:.1f}%")

    # Sauvegarde du nouveau modèle spécifique aux mains
    model_path = os.path.join(os.path.dirname(__file__), 'model_hands.pth')
    torch.save(model.state_dict(), model_path)
    
    # Sauvegarde des métadonnées
    meta_path = os.path.join(os.path.dirname(__file__), 'model_hands_meta.json')
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump({'actions': ACTIONS, 'num_classes': len(ACTIONS), 'input_size': 1662}, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] Modèle statique sauvegardé: {model_path}")
    print(f"[OK] Métadonnées: {meta_path}")

if __name__ == "__main__":
    train()
