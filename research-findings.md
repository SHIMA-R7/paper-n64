# 紙データ記録の先行研究と今回の検証（2026-10-24）

## 結論

従来のランダムな全面セル試験は、PaperBackの復元方式を再現した試験ではない。
高密度で失敗したことを、そのままプリンターや紙の限界とみなせない。
まずPaperBack由来の疎なドット、局所同期、ECCによる復号確認を導入する。
ROMをA4両面へ収録できることは未実証である。

## 一次資料

1. Oleh Yuschuk, PaperBack公式説明とv1.10公式ソース。
   https://www.ollydbg.de/Paperbak/
   https://www.ollydbg.de/Paperbak/paperbak-1.10.src.zip
2. Yang et al., Robust and Fast Decoding of High-Capacity Color QR Codes for Mobile Applications.
   https://arxiv.org/html/1704.06447
3. Bulan and Sharma, Improved Color Barcodes via Expectation Maximization Style Interference Cancellation, ICASSP 2012.
   https://hajim.rochester.edu/ece/sites/gsharma/papers/Bulan_EMInterfCancelColBarcodesICASSP2012_0001509.pdf
4. Bulan and Sharma, High Capacity Color Barcodes: Per Channel Data Encoding via Orientation Modulation in Elliptical Dot Arrays, IEEE TIP 2011.
   https://hajim.rochester.edu/ece/sites/gsharma/papers/BulanColorBarcodesTIPMay2011.pdf
5. Fraunhofer / BSI, JAB Code公式実装・API資料。
   https://github.com/jabcode/jabcode
   https://jabcode.github.io/jabcode/ldpc_8c.html
   https://jabcode.github.io/jabcode/interleave_8c.html

## PaperBack公式ソースから確認した点

- Printer.cpp Drawblock: 32×32ドット。データ90 B、アドレス4 B、CRC2 B、RS検査32 B。
- Printer.cpp: ドットのピッチと幅は別。dotpercentにより同じピッチのまま幅を縮小する。白い隙間の導入が必ずしも記録セル数の減少を意味するわけではない。
- Printer.cpp: ブロックごとの格子、交互のXORマスク、回復用XORブロック、同一回復グループの分散配置。
- Decoder.cpp Recognizebits: 複数の隣接補正係数・閾値・向きを試し、RS訂正とCRCが一致した場合に採用。
- Decoder.cpp: ±1画素の9候補、異なる読取窓サイズ、8×8ドット単位の局所的な位置選択を実装。
- 公式説明はインクジェットでのノズル調整・双方向印刷OFF・最高品質・画像最適化OFFも案内する。

## 他の研究から使える点

- HiQ: 色クラスの統計モデル、上下左右の干渉、同期パターンを含む幾何補正。論文は別データで学習・評価を分ける。今回の単一スキャンでの評価はその再現ではない。
- Bulan: 物理的なCMY印刷層とRGB取得チャネルの干渉を扱う。RGB成分ごとの位置合わせは、物理的なCMYインク層の分離と同じではない。通常のRGBプリンタードライバーは黒生成等を行うため、CMY直接制御を仮定できない。
- Bulan 2011のドット方向変調は、主な実験が75/100 cells/inで、600 dpi以上のプリンターと1200 dpiスキャンを用いる。成果を400〜600 cells/inでの成功根拠に外挿してはいけない。
- JAB Code: 色見本、局所同期を備えた記録形式と、LDPC・インターリーブの公開実装が比較対象になる。今回の独自パターンをJAB Codeと呼んではいけない。

## 既存カラー画像での追加試験

スキャン: scan-color-v3-1200dpi-20261024-155331.bmp。
既存画像から抽出したRGB成分別位置補正後の値に、固定の隣接補正を適用。
初期色見本と未ラベルのセルから、ガウス混合EMによる判定と、光学濃度特徴の簡易線形分離を試した。
参照ペイロードは採点にのみ使用。論文のQDA-CMIや物理EM干渉分離の忠実な再実装ではない。

| 条件 | この試験のRGB k-means BER | RGBガウス混合EM BER | 光学濃度の簡易分離 BER |
|---|---:|---:|---:|
| 200 cells/in・4色 | 1.6418% | 0.2380% | 1.4008% |
| 200 cells/in・8色 | 8.2052% | 5.8573% | 4.8971% |
| 300 cells/in・4色 | 13.6902% | 14.2059% | 9.7046% |
| 300 cells/in・8色 | 42.9382% | 41.8132% | 43.4387% |

全体では完全復元なし。400 cells/inでも高い誤りが残る。
複数手法を比較した探索結果であり、最小BERの方法を選んだ後の性能保証ではない。
従来の数値との差には、k-means停止条件等の実装差も含まれる。
結果: research-color-model-results.json。再実行: research_color_models.py。

## 新しい物理試験 v4

- 同じデータを200/300 cells/in、ドット幅100%/70%で比較。
- 白黒・4色・8色を同一ページへ配置。
- 各層32×32ドット、RS(128,96)、CRC16、3データ+1 XOR回復ブロック。
- 独自実験形式であり、PaperBackとのファイル互換性はない。
- 印刷前96コードワードの読取り・RS・CRC検証、16バイト破損訂正、1ブロック消失からのXOR復元をソフトウェア上で確認。
- この時点では紙からのECC復元、折り目耐性、両面の裏写り耐性は未検証。
- 格子等の面積とECC、回復ブロックを含む実効容量で比較する。生セル容量を保存容量として扱わない。
