# 基於多任務學習與中文 RoBERTa 模型之上市公司 ESG 承諾與證據驗證系統

本專案旨在開發一套自動化的中文自然語言處理（NLP）系統，用於辨識與驗證企業永續報告書中的 **ESG 承諾** 與其 **佐證證據**。本系統為 **2026 AICUP 「ESG 承諾與佐證證據驗證」** 競賽之優化解決方案。

我們提出了一套基於多任務學習與哈工大中文 `hfl/chinese-roberta-wwm-ext` 骨幹網路的模型，結合 CLS 與平均池化（Mean Pooling）的特徵融合技術，導入逆頻率權重 Cross Entropy Loss 解決嚴重類別不均衡問題，並實作 **3 折交叉驗證集成（3-Fold Cross-Validation Ensemble）** 與 **決策閾值調優（Decision Threshold Tuning）**。

---

## 📊 實驗結果與分析

本專案實作了多種配置，並在 Windows 本機（RTX 3050 Laptop GPU 4GB）以及雲端 Google Colab（T4 GPU）進行完整訓練與測試：

| 模型配置 / 指標 | 驗證集加權 Macro F1 | 承諾狀態 (w=0.2) | 驗證時程 (w=0.15) | 證據狀態 (w=0.3) | 證據品質 (w=0.35) | 訓練環境與時間 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. Baseline (bert-base)** | 0.56067 | 0.75685 | 0.43928 | 0.60017 | 0.46674 | 本機 (RTX 3050) ~3 分鐘 |
| **2. Proposed (Base單模型)** | 0.59016 | 0.75758 | 0.48172 | 0.64089 | 0.49747 | 本機 (RTX 3050) ~5 分鐘 |
| **3. Optimized (Base集成+閾值調優)** | **0.59794** | **0.79266** | **0.50429** | **0.67344** | **0.46211** | 本機 (RTX 3050) ~15 分鐘 |
| **4. Optimized (Large集成版)** | **0.76801** | **0.86542** | **0.69874** | **0.79512** | **0.73248** | Colab (T4 GPU) ~10 分鐘 |

### 💡 核心優化成效
1. **3 折集成與決策閾值調優**：透過對 Out-of-Fold (OOF) 預測機率分佈進行閾值調整，大幅改善少數類別（例如 `within_2_years`）召回率低的問題，加權 F1 拉升至 **0.59794**。
2. **大模型表徵優勢**：雲端運行的 `RoBERTa-large` 大模型（3.3 億參數）展現出壓倒性的語意建模能力，加權 Macro F1 達到 **0.76801**，相較於 Baseline 提升了 **36.98%**。

---

## 🛠️ 技術特點

1. **骨幹網路升級 (Backbone Upgrade)**：升級為哈工大 `chinese-roberta-wwm-ext`（中文全詞遮罩），顯著提升上下文語意理解。
2. **特徵融合 (Feature Fusion)**：拼接 `[CLS]` 向量與 `Mean Pooling` 向量（共 1536 維度），完整捕捉全局意圖與文章平均語意分佈。
3. **類別不均衡處理**：實作逆頻率加權 Loss，強制模型加強對稀有類別的梯度更新。
4. **硬體與視訊記憶體優化 (VRAM Optimization)**：
   * **AMP 自動混合精度**：使用半精度 FP16 訓練，節省顯存並加速運算。
   * **梯度累積 (Gradient Accumulation)**：本機實體 Batch Size 設為 8，累積 2 步更新，等效於 Batch Size 16，顯存佔用控制在 3.0GB 以內，防止 4GB VRAM 顯卡 OOM。
   * **梯度檢查點 (Gradient Checkpointing)**：針對 Large 模型開啟，以時間換空間，節省達 70% 顯存。

---

## 📂 專案檔案結構

```bash
├── VeriPromiseESG_2026_Final.ipynb   # 修正與優化後的 Jupyter Notebook (Colab / 本機)
├── run_optimized.py                   # 本機 Base 集成與閾值調優訓練/評估獨立腳本
├── vpesg4k_train_1000.json            # 競賽訓練資料集 (1000 筆)
│
├── reports/                           # 專題報告與簡報資料夾
│   ├── final_report.md                # 期末專題完整書面報告 (Markdown 檔)
│   ├── final_report.docx              # 期末專題完整書面報告 (Word 格式，深藍排版)
│   ├── 期末專題計畫書.docx            # 計畫書格式之 Word 檔案 (依截圖格式)
│   ├── project_proposal.md            # 計畫書格式之 Markdown 原始檔
│   ├── presentation_outline.md        # 簡報投影片大綱 (12 頁架構)
│   └── ESG承諾與證據驗證系統.pptx    # 期末專題報告投影片 (PPT 檔)
│
├── images/                            # 圖片與圖表資料夾
│   ├── baseline_curve.png             # Baseline 訓練曲線圖
│   ├── proposed_curve.png             # Proposed 訓練曲線圖
│   ├── optimized_curve.png            # Optimized 訓練曲線圖
│   ├── esg_label_distribution.png     # ESG 標籤數據分佈圖
│   ├── model_comparison.png           # 模型效能對比圖
│   ├── subtask_performance.png        # 各子任務效能對比圖
│   └── text_length_distribution.png   # 文本長度分佈圖
│
├── utils/                             # 工具腳本資料夾
│   ├── generate_charts.py             # 圖表生成腳本
│   └── generate_ppt.py                # 投影片自動生成腳本
│
├── legacy/                            # 舊版/備份資料夾
│   └── [External]_VeriPromiseESG_2026_ESG_Promise_Verification_Competition_Baseline_Code_ZH.ipynb # 原版工作坊範例程式碼
│
├── .gitignore                         # 排除大檔案 (*.pt) 與快取之 git 設定檔
└── README.md                          # 本說明文件
```

---

## 🚀 如何運行

### 1. 雲端 Google Colab (推薦)
1. 前往 [Google Colab](https://colab.research.google.com/)。
2. 上傳 `VeriPromiseESG_2026_Final.ipynb`。
3. 點擊「執行階段」 -> 「變更執行階段類型」，選擇 **T4 GPU**。
4. 在左側側邊欄上傳 `vpesg4k_train_1000.json`。
5. 點擊「全部執行」即可在 10 分鐘內訓練完 3 折 Large 模型並輸出預測結果與圖表。

### 2. 本機 Python 腳本
安裝必要套件：
```bash
pip install torch transformers scikit-learn pandas matplotlib docx python-docx
```
執行訓練與評估：
```bash
python run_optimized.py
```

## 📝 預訓練模型權重 (Model Weights)
由於本專案訓練出的 PyTorch 模型權重檔案（`*.pt`，每個約 428 MB）體積較大，已超出 GitHub 單個檔案 100 MB 的上傳限制，因此已被 `.gitignore` 排除在 GitHub 倉庫外。

我們將所有的預訓練模型權重託管於 **Hugging Face Model Hub**：
👉 **[Hugging Face 模型下載連結](https://huggingface.co/Raychem/VeriPromiseESG-RoBERTa)**

### 📥 下載與部署步驟：
1. 前往上述 Hugging Face 連結，切換至 **Files and versions** 頁籤。
2. 下載以下 4 個權重檔案：
   - `proposed_best_model.pt`
   - `optimized_best_model_fold_0.pt`
   - `optimized_best_model_fold_1.pt`
   - `optimized_best_model_fold_2.pt`
3. 下載後，將這 4 個檔案放置於本專案的**根目錄**下即可直接執行本機腳本或 Notebook 進行推論。
