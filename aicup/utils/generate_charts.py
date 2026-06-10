import json
import matplotlib.pyplot as plt
import numpy as np
from collections import Counter

# Set style for professional look
plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Arial', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

# Colors matching presentation theme
PRIMARY = '#182B49'      # Deep slate blue
SECONDARY = '#228B73'    # Emerald green
ACCENT = '#E09924'       # Amber gold
MUTED = '#6C757D'        # Muted gray
LIGHT_GRAY = '#F8F9FA'

# 1. Generate Task Label Distribution Plot
print("Loading dataset and counting labels...")
with open("aicup/vpesg4k_train_1000.json", "r", encoding="utf-8") as f:
    data = json.load(f)

fields = ["promise_status", "verification_timeline", "evidence_status", "evidence_quality"]
field_titles = {
    "promise_status": "1. 承諾狀態 (promise_status)",
    "verification_timeline": "2. 驗證時程 (verification_timeline)",
    "evidence_status": "3. 證據狀態 (evidence_status)",
    "evidence_quality": "4. 證據品質 (evidence_quality)"
}

fig, axes = plt.subplots(2, 2, figsize=(12, 10))
axes = axes.flatten()

for idx, field in enumerate(fields):
    counts = Counter([item[field] for item in data])
    # Order labels nicely
    if field == "promise_status":
        ordered_labels = ["Yes", "No"]
    elif field == "verification_timeline":
        ordered_labels = ["already", "within_2_years", "between_2_and_5_years", "more_than_5_years", "N/A"]
    elif field == "evidence_status":
        ordered_labels = ["Yes", "No", "N/A"]
    else:
        ordered_labels = ["Clear", "Not Clear", "Misleading", "N/A"]
        
    y_vals = [counts.get(lbl, 0) for lbl in ordered_labels]
    
    # Highlight the majority class and highlight minority in accent
    max_val = max(y_vals)
    bar_colors = [SECONDARY if val == max_val else (ACCENT if val < 50 else PRIMARY) for val in y_vals]
    
    ax = axes[idx]
    bars = ax.bar(ordered_labels, y_vals, color=bar_colors, alpha=0.9, edgecolor='none', width=0.6)
    
    # Add values on top of bars
    for bar in bars:
        height = bar.get_height()
        ax.annotate(f'{height}',
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3),  # 3 points vertical offset
                    textcoords="offset points",
                    ha='center', va='bottom', fontsize=10, fontweight='bold', color=PRIMARY)
                    
    ax.set_title(field_titles[field], fontsize=13, fontweight='bold', color=PRIMARY, pad=10)
    ax.set_ylim(0, 1000)
    ax.grid(axis='y', linestyle='--', alpha=0.3)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.tick_params(colors=PRIMARY)
    
plt.suptitle("ESG 驗證資料集 — 四大任務標籤分布不均分析 (N = 1000)", fontsize=16, fontweight='bold', color=PRIMARY, y=0.98)
plt.tight_layout()
plt.savefig("aicup/esg_label_distribution.png", dpi=150)
print("Saved aicup/esg_label_distribution.png")

# 2. Generate Model Comparison Plot
print("Generating model comparison chart...")
models = [
    "1. Baseline\n(BERT-base)", 
    "2. Proposed\n(RoBERTa-base)", 
    "3. Optimized\n(本機最優集成)", 
    "4. Optimized Large\n(雲端大模型集成)"
]
scores = [0.56067, 0.59016, 0.59794, 0.76801]

fig2, ax2 = plt.subplots(figsize=(9, 6))
bars2 = ax2.bar(models, scores, color=[PRIMARY, PRIMARY, ACCENT, SECONDARY], width=0.5, alpha=0.9)

# Add value label on top of bars
for bar in bars2:
    height = bar.get_height()
    ax2.annotate(f'{height:.5f}',
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 4),
                textcoords="offset points",
                ha='center', va='bottom', fontsize=11, fontweight='bold', color=PRIMARY)

# Highlight percentage gains
gain_large = ((0.76801 - 0.56067) / 0.56067) * 100
gain_local = ((0.59794 - 0.56067) / 0.56067) * 100
ax2.annotate(f"本機提升: +{gain_local:.2f}%", xy=(2, 0.61), xytext=(2, 0.65),
            arrowprops=dict(facecolor=ACCENT, shrink=0.05, width=1, headwidth=6),
            ha='center', fontsize=10, fontweight='bold', color=ACCENT)
ax2.annotate(f"極致提升: +{gain_large:.2f}%", xy=(3, 0.78), xytext=(3, 0.82),
            arrowprops=dict(facecolor=SECONDARY, shrink=0.05, width=1, headwidth=6),
            ha='center', fontsize=10, fontweight='bold', color=SECONDARY)

ax2.set_title("ESG 承諾與佐證證據驗證 — 模型加權 Macro F1 得分對比", fontsize=14, fontweight='bold', color=PRIMARY, pad=15)
ax2.set_ylabel("加權 Macro F1 得分 (Weighted F1)", fontsize=11, color=PRIMARY)
ax2.set_ylim(0, 0.9)
ax2.grid(axis='y', linestyle='--', alpha=0.3)
ax2.spines['top'].set_visible(False)
ax2.spines['right'].set_visible(False)
ax2.tick_params(colors=PRIMARY)

plt.tight_layout()
plt.savefig("aicup/model_comparison.png", dpi=150)
print("Saved aicup/model_comparison.png")
