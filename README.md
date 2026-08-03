# Robust Image Text Watermark

把 UTF-8 文字以**盲式 DCT 浮水印**藏進圖片；解碼時不需要原圖。設計目標是抵抗常見的 JPEG 重壓縮及 PNG/JPEG/WebP 互轉。

> 這是低容量、抗壓縮的浮水印，不是完全不可察覺或不可破解的加密系統。縮放、裁切、旋轉、截圖、強烈濾鏡及極低品質壓縮可能破壞資料。

## 安裝

需要 Python 3.10 或以上版本。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 使用

### 圖形介面

啟動本機介面：

```bash
python3 app.py
```

然後在瀏覽器開啟 `http://127.0.0.1:8080`。介面支援拖放圖片、嵌入／讀取文字、容量提示及進階強度設定。金鑰是選用項目；關閉「使用金鑰」後，嵌入與讀取都會使用空白金鑰。

### 指令列

嵌入文字：

```bash
python3 robust_steg.py embed input.png marked.png \
  --text "要隱藏的文字" --key "your-secret-key"
```

取回文字：

```bash
python3 robust_steg.py extract marked.png --key "your-secret-key"
```

從文字檔嵌入，並直接輸出 JPEG：

```bash
python3 robust_steg.py embed input.jpg marked.jpg \
  --text-file message.txt --key "your-secret-key" --quality 95
```

查看圖片容量：

```bash
python3 robust_steg.py capacity input.png --redundancy 3
```

## 抗壓縮設定

- `--strength`（預設 `56`）：越高越耐壓縮，但影像失真也會增加。嵌入與取回必須使用相同值。
- `--redundancy`（預設 `3`）：可選 1–15 的奇數。越高越耐損壞，但容量越低；此值已寫入浮水印，取回時不用提供。
- 要面對 JPEG quality 約 65–75 的壓縮時，建議 `--strength 64 --redundancy 5`。
- 輸出 JPEG/WebP 時，`--quality` 控制第一次存檔品質，預設 95。

同一個 `--key` 會決定資料散佈位置。金鑰錯誤時無法取回資料，但這不是經過安全審核的加密；如有保密需要，請先用成熟的加密工具加密文字。

## 原理與限制

程式在 YCbCr 的亮度通道上，以每個 8×8 區塊的兩對中頻 DCT 係數差進行量化索引調變（QIM）。資料先經 rate-1/2 卷積碼，再分散並重複寫入；解碼以軟判決 Viterbi 還原，最後用 CRC-32 驗證內容。

能抵抗的操作（程度取決於圖片內容與設定）：

- PNG、JPEG、WebP 之間保持原尺寸的格式轉換
- 中等 JPEG/WebP 有損重壓縮
- 輕微色彩或亮度變化

不能保證抵抗：

- 改變尺寸、裁切、旋轉、透視變形
- 社交平台未知的縮圖/銳化處理
- JPEG 極低 quality、強降噪或模糊
- 刻意移除浮水印的攻擊

## 測試

```bash
python3 -m unittest discover -s tests -v
```
