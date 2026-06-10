import os
import json
import urllib.request
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from transformers import AutoTokenizer, AutoModel, get_linear_schedule_with_warmup
from sklearn.model_selection import KFold
from sklearn.metrics import classification_report, f1_score
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from collections import Counter
import warnings
warnings.filterwarnings('ignore')

# ------------------------------------------------------------
# Configurations (Base Model Configuration - Extremely Fast!)
# ------------------------------------------------------------
MODEL_NAME = "hfl/chinese-roberta-wwm-ext"
MAX_LEN = 512
BATCH_SIZE = 8             # Increased to 8 since base model has small VRAM footprint
GRADIENT_ACCUMULATION = 1  # No gradient accumulation needed
EPOCHS = 8                 # Increased to 8 epochs for proper convergence
LR = 2e-5                  # Standard learning rate for base model
NUM_FOLDS = 3              # 3-Fold Cross-Validation Ensemble

EVAL_FIELDS = {
    "promise_status": ["Yes", "No"],
    "verification_timeline": ["already", "within_2_years", "between_2_and_5_years", "more_than_5_years", "N/A"],
    "evidence_status": ["Yes", "No", "N/A"],
    "evidence_quality": ["Clear", "Not Clear", "Misleading", "N/A"]
}

FIELD_WEIGHTS = {
    "promise_status": 0.2,
    "verification_timeline": 0.15,
    "evidence_status": 0.3,
    "evidence_quality": 0.35
}

label2id = {field: {label: i for i, label in enumerate(labels)} for field, labels in EVAL_FIELDS.items()}
id2label = {field: {i: label for i, label in enumerate(labels)} for field, labels in EVAL_FIELDS.items()}
num_labels = {field: len(labels) for field, labels in EVAL_FIELDS.items()}

# ------------------------------------------------------------
# Data Loading
# ------------------------------------------------------------
DATA_FILE = "vpesg4k_train_1000.json"
with open(DATA_FILE, "r", encoding="utf-8") as f:
    all_data = json.load(f)

all_data_np = np.array(all_data)

# ------------------------------------------------------------
# Dataset & Model
# ------------------------------------------------------------
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

class ESGDataset(Dataset):
    def __init__(self, data, tokenizer, label2id):
        self.data = data
        self.tokenizer = tokenizer
        self.label2id = label2id

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        sample = self.data[idx]
        text = sample['data']

        encoding = self.tokenizer(
            text,
            truncation=True,
            max_length=MAX_LEN,
            padding='max_length',
            return_tensors='pt'
        )

        input_ids = encoding['input_ids'].squeeze(0)
        attention_mask = encoding['attention_mask'].squeeze(0)

        labels = {}
        for field, mapping in self.label2id.items():
            label_text = sample[field]
            labels[field] = torch.tensor(mapping[label_text], dtype=torch.long)

        return {
            'input_ids': input_ids,
            'attention_mask': attention_mask,
            'labels': labels
        }

def collate_fn(batch):
    input_ids = torch.stack([item['input_ids'] for item in batch])
    attention_mask = torch.stack([item['attention_mask'] for item in batch])
    labels = {
        field: torch.stack([item['labels'][field] for item in batch])
        for field in EVAL_FIELDS
    }
    return {
        'input_ids': input_ids,
        'attention_mask': attention_mask,
        'labels': labels
    }

class MultiTaskRoberta(nn.Module):
    def __init__(self, num_labels_dict):
        super().__init__()
        self.roberta = AutoModel.from_pretrained(MODEL_NAME)
        hidden_size = self.roberta.config.hidden_size  # 768 for RoBERTa-base

        # MLP classifiers with Feature Fusion (CLS + Mean Pooling output has shape hidden_size * 2)
        self.classifiers = nn.ModuleDict({
            field: nn.Sequential(
                nn.Dropout(0.2),
                nn.Linear(hidden_size * 2, hidden_size),
                nn.GELU(),
                nn.Dropout(0.2),
                nn.Linear(hidden_size, n)
            )
            for field, n in num_labels_dict.items()
        })

    def forward(self, input_ids, attention_mask):
        outputs = self.roberta(input_ids=input_ids, attention_mask=attention_mask)
        cls_output = outputs.last_hidden_state[:, 0, :]

        # Mean Pooling
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(outputs.last_hidden_state.size()).float()
        sum_embeddings = torch.sum(outputs.last_hidden_state * input_mask_expanded, 1)
        sum_mask = input_mask_expanded.sum(1)
        sum_mask = torch.clamp(sum_mask, min=1e-9)
        mean_pooling = sum_embeddings / sum_mask

        # Feature Fusion
        combined = torch.cat((cls_output, mean_pooling), dim=1)

        logits = {
            field: clf(combined)
            for field, clf in self.classifiers.items()
        }
        return logits

# ------------------------------------------------------------
# Training Loop Functions
# ------------------------------------------------------------
def train_one_epoch(model, dataloader, optimizer, scheduler, device, criteria, scaler):
    model.train()
    total_loss = 0

    for step, batch in enumerate(dataloader):
        input_ids = batch["input_ids"].to(device)
        attention_mask = batch["attention_mask"].to(device)
        labels = batch["labels"]

        # AMP Mixed Precision
        with torch.cuda.amp.autocast():
            logits = model(input_ids, attention_mask)
            loss = 0
            for field in EVAL_FIELDS:
                task_loss = criteria[field](logits[field], labels[field].to(device))
                loss += FIELD_WEIGHTS[field] * task_loss

        optimizer.zero_grad()
        scaler.scale(loss).backward()
        scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        scaler.step(optimizer)
        scaler.update()
        scheduler.step()

        total_loss += loss.item()

    return total_loss / len(dataloader)

def predict_probabilities(model, dataloader, device):
    model.eval()
    probabilities = {field: [] for field in EVAL_FIELDS}

    with torch.no_grad():
        for batch in dataloader:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            logits = model(input_ids, attention_mask)

            for field in EVAL_FIELDS:
                probs = torch.softmax(logits[field], dim=-1).cpu().numpy()
                probabilities[field].append(probs)

    for field in EVAL_FIELDS:
        probabilities[field] = np.concatenate(probabilities[field], axis=0)

    return probabilities

# ------------------------------------------------------------
# 3-Fold Training and Cross Validation
# ------------------------------------------------------------
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {device}")

kf = KFold(n_splits=NUM_FOLDS, shuffle=True, random_state=42)

oof_probabilities = {field: np.zeros((len(all_data), len(labels))) for field, labels in EVAL_FIELDS.items()}
fold_scores = []

scaler = torch.cuda.amp.GradScaler()

for fold, (train_idx, val_idx) in enumerate(kf.split(all_data_np)):
    print(f"\n==================== Fold {fold + 1} / {NUM_FOLDS} ====================")
    
    fold_train_data = all_data_np[train_idx].tolist()
    fold_val_data = all_data_np[val_idx].tolist()
    
    # Compute weights
    criteria = {}
    for field, labels in EVAL_FIELDS.items():
        label_counts = Counter([item[field] for item in fold_train_data])
        total = len(fold_train_data)
        num_classes = len(labels)
        weights = []
        for label in labels:
            count = label_counts.get(label, 0)
            w = total / (num_classes * count) if count > 0 else 1.0
            weights.append(w)
        weights_tensor = torch.tensor(weights, dtype=torch.float).to(device)
        criteria[field] = nn.CrossEntropyLoss(weight=weights_tensor)
        
    train_dataset = ESGDataset(fold_train_data, tokenizer, label2id)
    val_dataset = ESGDataset(fold_val_data, tokenizer, label2id)
    
    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True, collate_fn=collate_fn)
    val_loader = DataLoader(val_dataset, batch_size=BATCH_SIZE, shuffle=False, collate_fn=collate_fn)
    
    model = MultiTaskRoberta(num_labels).to(device)
    
    # Optimizer setup
    no_decay = ["bias", "LayerNorm.weight"]
    optimizer_grouped_parameters = [
        {
            "params": [p for n, p in model.roberta.named_parameters() if not any(nd in n for nd in no_decay)],
            "weight_decay": 0.01,
            "lr": LR
        },
        {
            "params": [p for n, p in model.roberta.named_parameters() if any(nd in n for nd in no_decay)],
            "weight_decay": 0.0,
            "lr": LR
        },
        {
            "params": [p for n, p in model.classifiers.named_parameters() if not any(nd in n for nd in no_decay)],
            "weight_decay": 0.01,
            "lr": LR * 5
        },
        {
            "params": [p for n, p in model.classifiers.named_parameters() if any(nd in n for nd in no_decay)],
            "weight_decay": 0.0,
            "lr": LR * 5
        }
    ]
    optimizer = torch.optim.AdamW(optimizer_grouped_parameters)
    
    total_steps = len(train_loader) * EPOCHS
    warmup_steps = int(0.1 * total_steps)
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=warmup_steps,
        num_training_steps=total_steps
    )
    
    best_fold_score = 0.0
    best_fold_probs = None
    MODEL_SAVE_PATH = f"optimized_best_model_fold_{fold}.pt"
    
    for epoch in range(EPOCHS):
        avg_loss = train_one_epoch(model, train_loader, optimizer, scheduler, device, criteria, scaler)
        fold_val_probs = predict_probabilities(model, val_loader, device)
        
        pred_data = []
        for i in range(len(fold_val_data)):
            pred = {}
            for field in EVAL_FIELDS:
                pred_id = fold_val_probs[field][i].argmax()
                pred[field] = id2label[field][pred_id]
            pred_data.append(pred)
            
        weighted_score = 0.0
        for field, labels in EVAL_FIELDS.items():
            y_true = [item[field] for item in fold_val_data]
            y_pred = [item[field] for item in pred_data]
            macro_f1 = f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)
            weighted_score += macro_f1 * FIELD_WEIGHTS[field]
            
        print(f"Fold {fold+1} Epoch {epoch+1}/{EPOCHS} - Loss: {avg_loss:.4f} - Weighted F1: {weighted_score:.5f}")
        
        if weighted_score > best_fold_score:
            best_fold_score = weighted_score
            best_fold_probs = fold_val_probs
            torch.save(model.state_dict(), MODEL_SAVE_PATH)
            
    print(f"Fold {fold+1} Finished! Best Score: {best_fold_score:.5f}")
    fold_scores.append(best_fold_score)
    
    for field in EVAL_FIELDS:
        oof_probabilities[field][val_idx] = best_fold_probs[field]

print(f"\nAll Folds Finished! Average Fold Score (Before Tuning): {np.mean(fold_scores):.5f}")

# ------------------------------------------------------------
# Decision Threshold Tuning
# ------------------------------------------------------------
print("\n==================== Tuning Decision Thresholds ====================")
optimized_multipliers = {}
tuned_oof_predictions = []

for field, labels in EVAL_FIELDS.items():
    num_classes = len(labels)
    y_true = [item[field] for item in all_data]
    y_true_ids = np.array([labels.index(val) for val in y_true])
    probs = oof_probabilities[field]
    
    # Grid search for optimal multiplier for each class
    best_multipliers = np.ones(num_classes)
    best_f1 = f1_score(y_true_ids, probs.argmax(axis=-1), average="macro", zero_division=0)
    
    candidates = [0.1, 0.2, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0, 5.0, 8.0, 10.0]
    
    for c in range(num_classes):
        best_c_mult = 1.0
        for val in candidates:
            temp_mults = best_multipliers.copy()
            temp_mults[c] = val
            preds = (probs * temp_mults).argmax(axis=-1)
            score = f1_score(y_true_ids, preds, average="macro", zero_division=0)
            if score > best_f1:
                best_f1 = score
                best_c_mult = val
        best_multipliers[c] = best_c_mult
    
    optimized_multipliers[field] = best_multipliers.tolist()
    print(f"  {field} Optimized Multipliers: {best_multipliers} | Tuned Macro F1: {best_f1:.5f}")

# Generate final predictions using optimized thresholds
final_predictions = []
for i in range(len(all_data)):
    pred = {}
    for field in EVAL_FIELDS:
        probs = oof_probabilities[field][i]
        mults = np.array(optimized_multipliers[field])
        pred_id = (probs * mults).argmax()
        pred[field] = id2label[field][pred_id]
    final_predictions.append(pred)

final_results = {}
weighted_score = 0.0

for field, labels in EVAL_FIELDS.items():
    y_true = [item[field] for item in all_data]
    y_pred = [item[field] for item in final_predictions]
    
    macro_f1 = f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)
    micro_f1 = f1_score(y_true, y_pred, labels=labels, average="micro", zero_division=0)
    report = classification_report(y_true, y_pred, labels=labels, zero_division=0)
    
    weight = FIELD_WEIGHTS.get(field, 0)
    weighted_score += macro_f1 * weight
    
    final_results[field] = {
        "macro_f1": macro_f1,
        "micro_f1": micro_f1,
        "report": report,
        "weight": weight
    }

final_results["final_weighted_score"] = weighted_score

print(f"\n==================== Final Tuned Ensemble Evaluation ====================")
print(f"Final Weighted Score: {weighted_score:.5f}")
for field in EVAL_FIELDS:
    print(f"  {field}: Tuned Macro F1={final_results[field]['macro_f1']:.4f}")

# Save metrics
summary_metrics = {
    "final_weighted_score": weighted_score,
    "multipliers": optimized_multipliers
}
for field in EVAL_FIELDS:
    summary_metrics[field] = {
        "macro_f1": final_results[field]["macro_f1"],
        "micro_f1": final_results[field]["micro_f1"],
        "report": final_results[field]["report"]
    }

with open("optimized_metrics.json", "w", encoding="utf-8") as f:
    json.dump(summary_metrics, f, indent=2, ensure_ascii=False)

# Save final predictions
output_data = []
for orig, pred in zip(all_data, final_predictions):
    item = dict(orig)
    item.update(pred)
    output_data.append(item)

with open("prediction.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)
print("Saved optimized ensemble predictions to prediction.json")

# Generate and save comparison plot
fig, ax = plt.subplots(figsize=(10, 6))
fields = list(EVAL_FIELDS.keys())
macro_f1s = [final_results[f]["macro_f1"] for f in fields]
micro_f1s = [final_results[f]["micro_f1"] for f in fields]
x = range(len(fields))
width = 0.35

ax.bar([i - width/2 for i in x], macro_f1s, width, label='Tuned Macro F1', color='darkblue', alpha=0.8)
ax.bar([i + width/2 for i in x], micro_f1s, width, label='Tuned Micro F1', color='orange', alpha=0.8)
ax.set_xticks(x)
ax.set_xticklabels(fields)
ax.set_title(f"Optimized RoBERTa Ensemble F1 Scores (Tuned)\nFinal Weighted F1: {weighted_score:.5f}")
ax.legend()
ax.grid(True, alpha=0.3)
plt.savefig("optimized_curve.png", dpi=150)
print("Optimized plot saved as optimized_curve.png.")
