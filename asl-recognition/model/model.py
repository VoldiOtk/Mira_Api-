import torch
import torch.nn as nn

class ASLLstmModel(nn.Module):
    def __init__(self, input_size=1662, hidden_size=64, num_layers=3, num_classes=5):
        super(ASLLstmModel, self).__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True)
        self.fc1 = nn.Linear(hidden_size, 32)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(32, num_classes)

    def forward(self, x):
        # x est de shape (batch_size, sequence_length, input_size)
        out, _ = self.lstm(x)
        # On ne prend que la sortie du dernier pas de temps seq_len
        out = out[:, -1, :] 
        out = self.fc1(out)
        out = self.relu(out)
        out = self.fc2(out)
        return out

class HandSignModel(nn.Module):
    def __init__(self, input_size=1662, num_classes=29):
        super(HandSignModel, self).__init__()
        # Un réseau de neurones statique (Dense/MLP) car on a qu'une seule frame
        self.fc1 = nn.Linear(input_size, 256)
        self.relu1 = nn.ReLU()
        self.drop1 = nn.Dropout(0.3)
        self.fc2 = nn.Linear(256, 128)
        self.relu2 = nn.ReLU()
        self.drop2 = nn.Dropout(0.3)
        self.fc3 = nn.Linear(128, num_classes)

    def forward(self, x):
        # x est de shape (batch_size, input_size)
        out = self.fc1(x)
        out = self.relu1(out)
        out = self.drop1(out)
        out = self.fc2(out)
        out = self.relu2(out)
        out = self.drop2(out)
        out = self.fc3(out)
        return out
