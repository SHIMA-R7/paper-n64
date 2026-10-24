# Optar / HCCB / Bulan・Sharmaから取り込む候補

調査日: 2026-10-24。公開一次資料と公開実装を確認。以下の「適用案」は本プロジェクトへの判断であり、実機での改善をまだ示したものではない。

## 現在との差分

v8は16色、200セル/in、1200dpiカラースキャン。各区画は96×64データセルと16×64校正セル、小マーカーの格子間隔は15.24×10.16mm。区画四隅からの射影変換、区画全体の移動・伸縮補正、QDAと隣接色補正、RS＋アドレス＋CRCで確定したデータからの再学習を使用する。RSへの入力は色の第1候補と、消失位置の順位に使う信頼度である。

## 1. Optar: 細密な同期格子と局所補間

公開実装の `resync_cross`、`sync_crosses`、`bit_coord` は、24セル間隔の十字を相関で探索し、サブピクセルで再調整する。検出済みの近隣十字から次の位置を予測し、隣接4点の座標・閾値を双線形補間する。200セル/inなら参照点間隔は約3.05mm。

適用案は、既存の確定済みデータセルを追加の参照点として、区画内部を24セル程度の小領域に分けて位置を推定し、連続した変位場で読み直すこと。次の印刷形式では校正・同期セルを内部にも分散する。現在の右端の校正帯を再配分し、容量低下を測ってから採用する。

白黒Golayへの置換は優先しない。局所障害を符号語へ分散する考え方は、現在も内側シャッフルと外側の空間分散で一部取り入れている。作者の折り紙実験はレーザー印刷の一例で、インクジェットの強い揉みシワを保証しない。

資料: [公式説明](https://ronja.twibright.com/optar/)、[設定](https://raw.githubusercontent.com/colindean/optar/master/optar.h)、[復号実装](https://raw.githubusercontent.com/colindean/optar/master/unoptar.c)、[符号化実装](https://raw.githubusercontent.com/colindean/optar/master/optar.c)。GitHub版は公式コードを引き継ぐ公開版。

## 2. Microsoft HCCB: 局所サンプリングと復号器からのフィードバック

Parikh・Janckeの論文は行と各記号の位置を推定し、色ごとの信頼度を保持する。復号結果を使い、失敗したときに別の位置推定法へ段階的に進む。対象実験は主に4色HCCBとカメラ画像であり、現在の16色スキャナー方式そのものの実証ではない。

今回に使うのは、区画内部の行・小領域ごとの位置調整と、複数の色候補を保持する仕組み。三角形に変更するだけで容量が増えるとは判断しない。確定ブロックを使う現在の再学習とも方向が合う。

資料: [Localization and Segmentation of A 2D High Capacity Color Barcode, WACV 2008](https://deviparikh.com/publications/ParikhJancke_WACV_2008_barcodes_update.pdf)、[Microsoft Research HCCB](https://www.microsoft.com/en-us/research/project/high-capacity-color-barcodes-hccb/)。

## 3. Bulan・Sharma: 尤度を残した復号と色干渉の物理モデル

2011年方式はCMY各層の楕円ドットの向きを変えて情報を載せる。周期から全体同期を求め、局所位置を追従し、尤度を利用する誤り訂正を行う。主な条件は75〜100セル/in、1200dpiスキャン。ドライバーによる再ハーフトーン化でドット形が崩れる問題も記載されている。BrotherのRGB印刷経路でCMY層や微小楕円が保たれるか未確認のため、直ちに全面置換はしない。

取り込みやすいのは、QDAの全16色スコアを残し、少数の低信頼セルで第2・第3候補も試すこと。これは論文の畳み込み符号復号器をそのまま使う意味ではなく、現在のRS＋CRCに候補列挙を追加する適用案である。計算量を制限し、最終的な紙上ハッシュで全体を検証する。

2012/2013年の方式はRGBを紙白に対する光学濃度へ変換し、CMYとRGB間の干渉を物理モデルで近似する。紙白をW、観測値をSとすると、各成分は d=-log10(S/W)。既知色パイロットやEMによるモデル推定を使う。既存の任意16色方式へそのまま3層分離を適用できるわけではないが、光学濃度空間でのQDAと現行RGB-QDAの比較は可能。紙白・クリッピング・ゼロ値の処理を固定し、訓練に使わない確定セルで評価する。

資料: [High Capacity Color Barcodes: Per Channel Data Encoding via Orientation Modulation in Elliptical Dot Arrays, TIP 2011](https://hajim.rochester.edu/ece/sites/gsharma/papers/BulanColorBarcodesTIPMay2011.pdf)、[ICASSP 2012](https://hajim.rochester.edu/ece/sites/gsharma/papers/Bulan_EMInterfCancelColBarcodesICASSP2012_0001509.pdf)、[Blasinski・Bulan・Sharma, Per-Colorant-Channel Color Barcodes for Mobile Applications: An Interference Cancellation Framework, TIP 2013](https://hajim.rochester.edu/ece/sites/gsharma/papers/HenrykColorMobileBarcodesTIP0413.pdf)。

## 優先順位と評価

1. 既存スキャンで局所変位補正を試す。確定ブロック数、回収バイト数、最終ハッシュで判断する。
2. 全色スコアから限定した候補列挙を行う。現在の信頼度順消失指定と同じ画像・同じ計算時間で比較する。
3. RGB／光学濃度空間の比較。未使用の検証セルと未回収ブロックで効果を測る。
4. 新しい印刷で分散校正格子を比較する。シワ耐性と実効容量を両方計測する。
5. CMY独立層・楕円向き変調は小さい試験パターンから始める。

公開研究の密度やレーザープリンターでの結果を、このBrother普通紙環境の容量保証に転用しない。現段階で使える根拠が強いのは、細密な位置合わせ、色候補の保持、色干渉のモデル化である。

## 調査中に行った実機スキャンへの適用

揉みシワを付けた実物のスキャンでは、区画単位の移動・伸縮だけでは全体訂正後も348バイトが不足した。局所同期という考え方を参考に、CRC確定データから区画内部の3次多項式変位場を推定する `warp_smw_v8.py` を追加した。区画143が19/24ブロックから24/24ブロックに改善し、外側RSで残りを補完してROMの524,288バイトが原本と完全一致した。Optarの十字格子方式をそのまま実装した結果ではなく、局所幾何補正が有効だった1事例である。詳しくは `smw-v8-crumpled-success.md`。
